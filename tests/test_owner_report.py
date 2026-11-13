"""Tests for the monthly owner report (engine/owner_report.py), the once-a-day last-seen
write (engine/db.touch_last_seen), and their hooks in /api/auth/me and the nightly loop.

No database and no network: a small in-memory fake stands in for Postgres and for the mailer.

    .venv/bin/python -m unittest tests.test_owner_report -v
"""
import asyncio
import os
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from engine import db, owner_report as orp
from engine import refresh_scheduler as rs


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


class FakeDb:
    """Answers the report's queries with canned rows and keeps report_log in a set."""
    def __init__(self, fail=()):
        self.log, self.lock, self.fail, self.calls = set(), threading.Lock(), set(fail), []

    def __call__(self, sql, params):
        self.calls.append(sql)
        for name in self.fail:
            if name in sql:
                raise RuntimeError(f"no such table/column ({name})")
        if sql.startswith("INSERT INTO report_log"):
            with self.lock:
                if params[0] in self.log:
                    return []
                self.log.add(params[0])
                return [{"period": params[0]}]
        if sql.startswith("DELETE FROM report_log"):
            with self.lock:
                self.log.discard(params[0])
            return []
        if "FROM users WHERE created_at" in sql:
            return [{"total": 3, "google": 2, "password": 1}]
        if "count(*) FILTER (WHERE email_verified)" in sql:
            return [{"total": 10, "verified": 6, "unverified": 4}]
        if "last_seen_at" in sql:
            return [{"in_month": 5, "last_30d": 4, "tracking_since": utc(2026, 10, 1, 9)}]
        if "FROM connected_teams" in sql:
            return [{"people_total": 7, "people_new": 2}]
        if "FROM predictions" in sql:
            return [{"saved": 12, "graded": 8, "correct": 6}]
        if "FROM activation_events" in sql:
            return [{"event_name": "viewed_team", "n": 4}]
        if "league_messages" in sql:
            return [{"messages": 30, "reports": 1}]
        raise AssertionError("unexpected sql: " + sql[:80])


class Periods(unittest.TestCase):
    def test_the_month_that_just_ended_in_pacific_time(self):
        label, start, end = orp.previous_period(utc(2026, 11, 2, 7, 45))
        self.assertEqual(label, "2026-10")
        self.assertEqual(start, utc(2026, 10, 1, 7))        # Oct 1 00:00 PDT
        self.assertEqual(end, utc(2026, 11, 1, 7))          # Nov 1 00:00 PDT (DST ends 2 am that day)

    def test_pacific_not_utc_decides_which_month_is_over(self):
        # 06:00 UTC on Nov 1 is still 11 pm Oct 31 in Los Angeles: October is not over yet.
        self.assertEqual(orp.previous_period(utc(2026, 11, 1, 6))[0], "2026-09")
        self.assertEqual(orp.previous_period(utc(2026, 11, 1, 8))[0], "2026-10")

    def test_january_reports_december_of_the_year_before(self):
        label, start, end = orp.previous_period(utc(2027, 1, 5))
        self.assertEqual(label, "2026-12")
        self.assertEqual(end, utc(2027, 1, 1, 8))           # Jan 1 00:00 PST

    def test_period_bounds_match(self):
        self.assertEqual(orp.period_bounds("2026-10"), orp.previous_period(utc(2026, 11, 20))[1:])


class Gather(unittest.TestCase):
    def test_every_number_is_collected(self):
        s = orp.gather("2026-10", now=utc(2026, 11, 2), run=FakeDb())
        self.assertEqual(s["signups"]["total"], 3)
        self.assertEqual(s["accounts"]["unverified"], 4)
        self.assertEqual(s["active"]["in_month"], 5)
        self.assertEqual(s["activation"][0]["event_name"], "viewed_team")
        self.assertEqual(s["chat"]["reports"], 1)

    def test_one_failing_query_does_not_sink_the_report(self):
        with mock.patch("builtins.print"):
            s = orp.gather("2026-10", now=utc(2026, 11, 2), run=FakeDb(fail=("last_seen_at",)))
        self.assertIsNone(s["active"])
        self.assertEqual(s["signups"]["total"], 3)
        subject, text, html = orp.build(s)
        self.assertIn("Seen in October 2026: unavailable", text)
        self.assertIn("New sign-ups: 3", text)


class Email(unittest.TestCase):
    def setUp(self):
        self.stats = orp.gather("2026-10", now=utc(2026, 11, 2), run=FakeDb())

    def test_subject_and_numbers(self):
        subject, text, html = orp.build(self.stats)
        self.assertEqual(subject, "Lineup Lab monthly report: October 2026")
        for want in ("New sign-ups: 3", "with Google: 2", "verified: 6", "not verified: 4", "Seen in the last 30 days: 4",
                     "People with a league connected (all time): 7", "Start/Sit predictions saved: 12",
                     "75% right of 8 graded", "Activation: viewed_team: 4", "Reports filed: 1"):
            self.assertIn(want, "\n".join(l.strip() for l in text.splitlines()), want)

    def test_says_what_it_cannot_report(self):
        _, text, html = orp.build(self.stats)
        self.assertIn("hosting bill", text)
        self.assertIn("hosting bill", html)

    def test_a_late_start_of_tracking_is_called_out(self):
        s = dict(self.stats, active={"in_month": 1, "last_30d": 1, "tracking_since": utc(2026, 10, 20, 9)})
        _, text, _ = orp.build(s)
        self.assertIn("visit tracking began on Oct 20", text)

    def test_no_tracking_yet_is_called_out(self):
        s = dict(self.stats, active={"in_month": 0, "last_30d": 0, "tracking_since": None})
        _, text, _ = orp.build(s)
        self.assertIn("starts once the migration is live", text)

    def test_html_is_escaped(self):
        s = dict(self.stats, activation=[{"event_name": "<script>x</script>", "n": 1}])
        _, _, html = orp.build(s)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_graded_predictions_is_not_a_division_error(self):
        s = dict(self.stats, predictions={"saved": 0, "graded": 0, "correct": 0})
        _, text, _ = orp.build(s)
        self.assertIn("Predictions graded: n/a", text)


class Sending(unittest.TestCase):
    NOW = utc(2026, 11, 2, 7, 45)

    def setUp(self):
        mock.patch.dict(os.environ, {"OWNER_REPORT_EMAIL": "owner@example.test"}).start()
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)
        self.sent = []
        self.send = lambda to, subject, text, html: self.sent.append((to, subject))

    def test_does_nothing_without_a_recipient_and_never_touches_the_database(self):
        os.environ.pop("OWNER_REPORT_EMAIL")
        boom = mock.Mock(side_effect=AssertionError("database touched"))
        self.assertEqual(orp.send_if_due(self.NOW, run=boom, send=self.send), "not-configured")
        boom.assert_not_called()
        self.assertEqual(self.sent, [])

    def test_sends_last_month_once(self):
        fake = FakeDb()
        self.assertEqual(orp.send_if_due(self.NOW, run=fake, send=self.send), "sent")
        self.assertEqual(self.sent, [("owner@example.test", "Lineup Lab monthly report: October 2026")])
        self.assertEqual(orp.send_if_due(self.NOW, run=fake, send=self.send), "already-sent")
        self.assertEqual(len(self.sent), 1)

    def test_next_month_is_a_new_report(self):
        fake = FakeDb()
        orp.send_if_due(self.NOW, run=fake, send=self.send)
        orp.send_if_due(utc(2026, 12, 2, 8), run=fake, send=self.send)
        self.assertEqual([s[1] for s in self.sent],
                         ["Lineup Lab monthly report: October 2026", "Lineup Lab monthly report: November 2026"])

    def test_two_instances_at_the_same_moment_send_exactly_one(self):
        fake, results = FakeDb(), []
        barrier = threading.Barrier(6)

        def go():
            barrier.wait(timeout=5)
            results.append(orp.send_if_due(self.NOW, run=fake, send=self.send))
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join(timeout=10) for t in ts]
        self.assertEqual(sorted(results), ["already-sent"] * 5 + ["sent"])
        self.assertEqual(len(self.sent), 1)

    def test_a_failed_send_gives_the_month_back_so_the_next_night_retries(self):
        fake = FakeDb()

        def broken(*a):
            raise RuntimeError("mail provider down")
        self.assertEqual(orp.send_if_due(self.NOW, run=fake, send=broken), "failed")
        self.assertEqual(fake.log, set())
        self.assertEqual(orp.send_if_due(self.NOW, run=fake, send=self.send), "sent")

    def test_if_the_month_cannot_be_reserved_nothing_is_sent(self):
        fake = FakeDb(fail=("report_log",))
        self.assertEqual(orp.send_if_due(self.NOW, run=fake, send=self.send), "failed")
        self.assertEqual(self.sent, [])


class LastSeen(unittest.TestCase):
    def setUp(self):
        db._LAST_SEEN_MEMO.clear()
        self.addCleanup(db._LAST_SEEN_MEMO.clear)
        self.cur = mock.MagicMock()
        cm = mock.MagicMock()
        cm.__enter__.return_value = self.cur
        patcher = mock.patch.object(db, "_conn", return_value=cm)
        self.conn = patcher.start()
        self.addCleanup(patcher.stop)

    def test_writes_once_then_not_again_for_a_day(self):
        self.assertTrue(db.touch_last_seen(5, now=1_000_000))
        self.assertFalse(db.touch_last_seen(5, now=1_000_000 + 3600))
        self.assertEqual(self.cur.execute.call_count, 1)
        self.assertTrue(db.touch_last_seen(5, now=1_000_000 + 25 * 3600))
        self.assertEqual(self.cur.execute.call_count, 2)

    def test_each_person_is_tracked_separately(self):
        db.touch_last_seen(1, now=1_000_000)
        self.assertTrue(db.touch_last_seen(2, now=1_000_001))

    def test_the_sql_only_moves_the_timestamp_forward_once_a_day(self):
        db.touch_last_seen(5, now=1_000_000)
        sql, params = self.cur.execute.call_args[0]
        self.assertIn("last_seen_at IS NULL OR last_seen_at <", sql)
        self.assertEqual(params, (1_000_000, 5, 1_000_000 - 86400))

    def test_a_failed_write_is_retried_on_the_next_load(self):
        self.cur.execute.side_effect = RuntimeError("column does not exist")
        with self.assertRaises(RuntimeError):
            db.touch_last_seen(5, now=1_000_000)
        self.cur.execute.side_effect = None
        self.assertTrue(db.touch_last_seen(5, now=1_000_010))


class Hooks(unittest.TestCase):
    def test_a_last_seen_failure_cannot_break_the_signed_in_check(self):
        import server
        user = {"id": 9, "username": "x", "email": "x@x", "email_verified": True, "has_password": True}
        with mock.patch.object(server.db, "touch_last_seen", side_effect=RuntimeError("boom")):
            self.assertEqual(server.me(user=user), user)

    def test_me_records_the_visit(self):
        import server
        with mock.patch.object(server.db, "touch_last_seen") as t:
            server.me(user={"id": 9})
        t.assert_called_once_with(9)

    def test_the_nightly_loop_checks_the_report_and_survives_its_failure(self):
        for effect in ("sent", RuntimeError("boom")):
            with self.subTest(effect=str(effect)), mock.patch("builtins.print"), \
                    mock.patch.object(rs.board, "load_bundle", return_value={"season": 2026, "wk": object()}), \
                    mock.patch.object(rs, "_warm_model_tables", new=mock.AsyncMock()), \
                    mock.patch.object(rs.tools, "resolve_track_record", return_value=0) as rtr, \
                    mock.patch.object(rs.owner_report, "send_if_due",
                                      **({"side_effect": effect} if isinstance(effect, Exception) else {"return_value": effect})) as sid:
                state = {"n": 0}

                async def fake(seconds):
                    if seconds == rs._interval_seconds():
                        state["n"] += 1
                        if state["n"] > 1:
                            raise asyncio.CancelledError
                with mock.patch.object(rs.asyncio, "sleep", fake):
                    with self.assertRaises(asyncio.CancelledError):
                        asyncio.run(rs._refresh_loop())
                sid.assert_called_once_with()
                rtr.assert_called_once_with()


class Migration(unittest.TestCase):
    def test_migration_is_additive_and_creates_what_the_code_uses(self):
        path = os.path.join(os.path.dirname(__file__), "..", "migrations", "20261112000000_owner_report.sql")
        sql = open(path).read()
        self.assertIn("ADD COLUMN IF NOT EXISTS last_seen_at", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS public.report_log", sql)
        self.assertIn("period    text PRIMARY KEY", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        for forbidden in ("DROP ", "DELETE ", "TRUNCATE"):
            self.assertNotIn(forbidden, sql)


if __name__ == "__main__":
    unittest.main()
