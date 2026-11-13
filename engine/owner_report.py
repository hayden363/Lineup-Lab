"""Monthly owner report: a plain email to the app's owner with last month's numbers.

Recipient is the OWNER_REPORT_EMAIL environment variable. If it is not set nothing is
ever sent (so deploying this code changes nothing until the owner opts in).

What it reports (all from the app's own database):
  * sign-ups in the month (Google vs email+password), accounts total, how many are verified
  * active people: seen in the month / in the last 30 days (users.last_seen_at)
  * leagues connected, Start/Sit predictions saved and graded, activation events
  * league chat: messages posted and reports filed (nobody else reads those reports)

What it can NOT report: the hosting bill and server error logs (not reachable from inside
the app).

Sending is exactly-once per month: the month is claimed in `report_log` before the email
goes out and released again if the send fails.

    .venv/bin/python -m engine.owner_report --dry-run [--period 2026-10]
"""
import html
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Los_Angeles")      # the owner's months, not UTC's
DAY = 86400


# ---------------------------------------------------------------- periods ----
def previous_period(now=None):
    """The month that just ended, in the owner's time zone: (label, start_epoch, end_epoch)."""
    now = now if now is not None else time.time()
    local = datetime.fromtimestamp(now, ZONE)
    end = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (end.replace(year=end.year - 1, month=12) if end.month == 1 else end.replace(month=end.month - 1))
    return start.strftime("%Y-%m"), start.timestamp(), end.timestamp()


def period_bounds(label):
    start = datetime.strptime(label, "%Y-%m").replace(tzinfo=ZONE)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.timestamp(), end.timestamp()


# ---------------------------------------------------------------- queries ----
# name -> (sql, params builder). Each is run on its own so one missing table or column
# (for example before the migration is applied) shows "unavailable" instead of failing the email.
def _queries(start, end, now):
    p2 = (start, end)
    return {
        "signups": ("SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE google_id IS NOT NULL) AS google, "
                    "count(*) FILTER (WHERE google_id IS NULL AND apple_id IS NULL) AS password "
                    "FROM users WHERE created_at >= %s AND created_at < %s", p2),
        "accounts": ("SELECT count(*) AS total, count(*) FILTER (WHERE email_verified) AS verified, "
                     "count(*) FILTER (WHERE NOT email_verified) AS unverified FROM users", ()),
        "active": ("SELECT count(*) FILTER (WHERE last_seen_at >= %s AND last_seen_at < %s) AS in_month, "
                   "count(*) FILTER (WHERE last_seen_at >= %s) AS last_30d, "
                   "min(last_seen_at) AS tracking_since FROM users", (start, end, now - 30 * DAY)),
        "leagues": ("SELECT count(DISTINCT user_id) AS people_total, "
                    "count(DISTINCT user_id) FILTER (WHERE created_at >= %s AND created_at < %s) AS people_new "
                    "FROM connected_teams", p2),
        "predictions": ("SELECT count(*) FILTER (WHERE created_at >= %s AND created_at < %s) AS saved, "
                        "count(*) FILTER (WHERE resolved_at >= %s AND resolved_at < %s) AS graded, "
                        "count(*) FILTER (WHERE resolved_at >= %s AND resolved_at < %s AND was_correct) AS correct "
                        "FROM predictions", p2 + p2 + p2),
        "activation": ("SELECT event_name, count(*) AS n FROM activation_events "
                       "WHERE occurred_at >= %s AND occurred_at < %s GROUP BY event_name ORDER BY event_name", p2),
        "chat": ("SELECT (SELECT count(*) FROM league_messages WHERE created_at >= %s AND created_at < %s "
                 "AND deleted_at IS NULL) AS messages, "
                 "(SELECT count(*) FROM league_message_reports WHERE created_at >= %s AND created_at < %s) AS reports",
                 p2 + p2),
    }


def _db_runner(sql, params):
    from . import db
    with db._conn() as c:
        c.execute(sql, params)
        return c.fetchall()


def gather(label, now=None, run=None):
    """Collect every number for `label` (YYYY-MM). `run(sql, params) -> list of dict rows`
    defaults to the app database; each query that fails is recorded as None."""
    now = now if now is not None else time.time()
    run = run or _db_runner
    start, end = period_bounds(label)
    stats = {"period": label}
    for name, (sql, params) in _queries(start, end, now).items():
        try:
            rows = run(sql, params)
            stats[name] = rows if name == "activation" else (rows[0] if rows else None)
        except Exception as e:      # noqa: BLE001 - one bad stat must not sink the report
            print(f"[owner_report] {name} unavailable: {type(e).__name__}: {e}")
            stats[name] = None
    return stats


# ------------------------------------------------------------------ email ----
def _n(row, key):
    v = None if row is None else row.get(key)
    return "unavailable" if v is None else str(int(v))


def lines(stats):
    """The report as (heading, [(label, value), ...]) sections: the one source for text and HTML."""
    s = stats
    month = datetime.strptime(s["period"], "%Y-%m").strftime("%B %Y")
    out = []
    su, ac = s["signups"], s["accounts"]
    out.append(("People", [
        ("New sign-ups", _n(su, "total")),
        ("   with Google", _n(su, "google")),
        ("   with email + password", _n(su, "password")),
        ("Accounts in total", _n(ac, "total")),
        ("   verified", _n(ac, "verified")),
        ("   not verified", _n(ac, "unverified")),
    ]))
    av = s["active"]
    since = None if av is None else av.get("tracking_since")
    rows = [("Seen in " + month, _n(av, "in_month")), ("Seen in the last 30 days", _n(av, "last_30d"))]
    if av is not None and since is None:
        rows.append(("Note", "nobody has been recorded yet; visit tracking starts once the migration is live"))
    elif since is not None and since > period_bounds(s["period"])[0]:
        rows.append(("Note", "visit tracking began on " + datetime.fromtimestamp(since, ZONE).strftime("%b %d")
                     + ", so earlier visits in this month are not counted"))
    out.append(("Coming back", rows))
    lg, pr = s["leagues"], s["predictions"]
    graded = None if pr is None else pr.get("graded")
    correct = None if pr is None else pr.get("correct")
    rate = "n/a" if not graded else f"{round(100 * (correct or 0) / graded)}% right of {int(graded)} graded"
    out.append(("Using the app", [
        ("People with a league connected (all time)", _n(lg, "people_total")),
        ("   newly connected this month", _n(lg, "people_new")),
        ("Start/Sit predictions saved", _n(pr, "saved")),
        ("Predictions graded", rate if pr is not None else "unavailable"),
    ] + ([(f"Activation: {r['event_name']}", str(int(r["n"]))) for r in (s["activation"] or [])]
         if s["activation"] is not None else [("Activation events", "unavailable")])))
    ch = s["chat"]
    out.append(("League chat", [("Messages posted", _n(ch, "messages")), ("Reports filed", _n(ch, "reports"))]))
    return month, out


NOT_INCLUDED = "Not included: the hosting bill and server error logs (check Render directly)."


def build(stats):
    """(subject, text, html) for a stats dict."""
    month, sections = lines(stats)
    subject = f"Lineup Lab monthly report: {month}"
    t = [f"Lineup Lab: {month}", ""]
    for head, rows in sections:
        t.append(head.upper())
        t += [f"  {k}: {v}" for k, v in rows]
        t.append("")
    t.append(NOT_INCLUDED)
    h = ['<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:520px;color:#0e1b15">',
         f'<h2 style="margin:0 0 12px">Lineup Lab: {html.escape(month)}</h2>']
    for head, rows in sections:
        h.append(f'<h3 style="margin:18px 0 6px;font-size:13px;letter-spacing:.06em;color:#1f6f52">{html.escape(head.upper())}</h3>'
                 '<table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;font-size:14px">')
        for k, v in rows:
            h.append(f'<tr><td style="padding:4px 0;border-bottom:1px solid #eef1ef;white-space:pre">{html.escape(k)}</td>'
                     f'<td style="padding:4px 0;border-bottom:1px solid #eef1ef;text-align:right;font-weight:700">{html.escape(v)}</td></tr>')
        h.append("</table>")
    h.append(f'<p style="color:#8a988f;font-size:12px;margin-top:20px">{html.escape(NOT_INCLUDED)}</p></div>')
    return subject, "\n".join(t), "".join(h)


# ---------------------------------------------------------------- sending ----
def recipient():
    return (os.environ.get("OWNER_REPORT_EMAIL") or "").strip()


def claim(label, to, run=None):
    """Reserve the month. True only for the single caller that inserted the row."""
    run = run or _db_runner
    rows = run("INSERT INTO report_log (period, sent_at, recipient) VALUES (%s, %s, %s) "
               "ON CONFLICT (period) DO NOTHING RETURNING period", (label, time.time(), to))
    return bool(rows)


def release(label, run=None):
    (run or _db_runner)("DELETE FROM report_log WHERE period = %s RETURNING period", (label,))


def send_if_due(now=None, run=None, send=None):
    """Email last month's report once. Returns a short status string for the log:
    'not-configured', 'already-sent', 'sent' or 'failed'. Never raises."""
    to = recipient()
    if not to:
        return "not-configured"
    run = run or _db_runner
    if send is None:
        from . import mail
        send = mail._send
    label, _, _ = previous_period(now)
    try:
        if not claim(label, to, run):
            return "already-sent"
    except Exception as e:          # noqa: BLE001 - e.g. table not created yet: do nothing rather than risk a double send
        print(f"[owner_report] couldn't reserve {label}: {type(e).__name__}: {e}")
        return "failed"
    try:
        subject, text, body = build(gather(label, now=now, run=run))
        send(to, subject, text, body)
    except Exception as e:          # noqa: BLE001 - release the month so the next nightly run retries
        print(f"[owner_report] send failed for {label}: {type(e).__name__}: {e}")
        try:
            release(label, run)
        except Exception as e2:     # noqa: BLE001
            print(f"[owner_report] couldn't release {label}: {e2}")
        return "failed"
    print(f"[owner_report] sent {label} report")
    return "sent"


def main(argv):
    label = argv[argv.index("--period") + 1] if "--period" in argv else previous_period()[0]
    subject, text, _ = build(gather(label))
    print(subject + "\n\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
