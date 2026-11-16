"""Paid-plan waitlist: tell the owner how many people are waiting.

When someone newly joins the Manager or Commissioner waitlist, the owner gets one plain email with the new
request and the running totals, so "how many people want this?" is answered without opening the database.

Recipient: WAITLIST_NOTIFY_EMAIL, else OWNER_REPORT_EMAIL. If neither is set nothing is sent (the waitlist
itself still works). Notices are throttled to one per NOTICE_EVERY_SECONDS per server process, so a burst of
sign-ups (or someone hammering the form) cannot flood the inbox; the next notice carries the full total.
Never raises: a mail problem must not break the visitor's sign-up.
"""
import html
import os
import time

NOTICE_EVERY_SECONDS = 15 * 60
PLAN_LABELS = {"manager": "Manager (3-4 leagues)", "commissioner": "Commissioner (5+ leagues)"}
_last_notice = 0.0


def recipient():
    return (os.environ.get("WAITLIST_NOTIFY_EMAIL") or os.environ.get("OWNER_REPORT_EMAIL") or "").strip()


def build(plan, email, counts):
    total = sum(counts.values())
    parts = ", ".join(f"{counts.get(p, 0)} {name.split(' ')[0]}" for p, name in PLAN_LABELS.items())
    subject = f"Lineup Lab waitlist: {total} request{'' if total == 1 else 's'} ({parts})"
    label = PLAN_LABELS.get(plan, plan)
    lines = [f"New request: {email} joined the {label} waitlist.", "",
             f"Waiting right now: {total} total"]
    lines += [f"  {name}: {counts.get(p, 0)}" for p, name in PLAN_LABELS.items()]
    text = "\n".join(lines) + "\n"
    rows = "".join(f"<tr><td style='padding:4px 16px 4px 0'>{html.escape(name)}</td><td><b>{counts.get(p, 0)}</b></td></tr>"
                   for p, name in PLAN_LABELS.items())
    body = (f"<p>New request: <b>{html.escape(email)}</b> joined the <b>{html.escape(label)}</b> waitlist.</p>"
            f"<p>Waiting right now: <b>{total}</b> total</p><table>{rows}</table>")
    return subject, text, body


def notify_owner(plan, email, get_counts=None, send=None, now=None):
    """Email the owner the new request and the totals. Returns 'not-configured', 'throttled', 'sent' or 'failed'."""
    global _last_notice
    to = recipient()
    if not to:
        return "not-configured"
    now = now if now is not None else time.time()
    if now - _last_notice < NOTICE_EVERY_SECONDS:
        return "throttled"
    try:
        if get_counts is None:
            from . import db
            get_counts = db.waitlist_counts
        if send is None:
            from . import mail
            send = mail._send
        subject, text, body = build(plan, email, get_counts())
        send(to, subject, text, body)
    except Exception as e:      # noqa: BLE001 - the visitor's sign-up already succeeded
        print(f"[waitlist] owner notice failed: {type(e).__name__}")
        return "failed"
    _last_notice = now          # only after a send, so a failed one is retried at the next sign-up
    return "sent"
