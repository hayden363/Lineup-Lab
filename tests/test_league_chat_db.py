"""League chat data layer (engine/chat.py) and its migration.

The database is mocked — no network. FakeCursor replays queued rows in the
order the code under test reads them, and records every statement so the tests
can assert what was (and was not) written.

    .venv/bin/python -m unittest tests.test_league_chat_db -v
"""

import re
import unittest
import psycopg
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from engine import chat, db

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "20261025000000_league_chat.sql"


class FakeCursor:
    def __init__(self, rows=(), all_rows=(), raise_on=None):
        self.rows = list(rows)
        self.all_rows = list(all_rows)
        self.raise_on = raise_on or {}
        self.executed = []

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.executed.append((text, params))
        for fragment, exc in self.raise_on.items():
            if fragment in text:
                raise exc

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.all_rows


def patched_conn(cursor):
    @contextmanager
    def _conn():
        yield cursor
    return mock.patch.object(db, "_conn", _conn)


def inserted(cursor, table):
    return [s for s, _ in cursor.executed if s.startswith(f"INSERT INTO {table}")]


class PostMessage(unittest.TestCase):
    def test_blank_body_is_rejected_before_touching_the_database(self):
        cur = FakeCursor()
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.post_message(7, "sleeper", "L1", "   \n ")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(cur.executed, [])

    def test_501_characters_is_rejected_and_500_is_not(self):
        member = {"role": "member", "muted_until": None, "external_id": "s1"}
        saved = {"id": 1, "user_id": 7, "body": "x" * 500, "created_at": 1.0}
        cur = FakeCursor(rows=[member, saved])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.post_message(7, "sleeper", "L1", "x" * 501)
            self.assertEqual(ctx.exception.status, 400)
            self.assertEqual(inserted(cur, "league_messages"), [])
            self.assertEqual(chat.post_message(7, "sleeper", "L1", "x" * 500)["id"], 1)

    def test_a_nul_character_is_rejected_before_the_database(self):
        cur = FakeCursor()
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.post_message(7, "sleeper", "L1", "a\x00b")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(cur.executed, [])

    def test_a_body_of_only_invisible_characters_is_rejected(self):
        cur = FakeCursor()
        with patched_conn(cur):
            for body in ("\u200b", "\u200b \u2060\ufeff", "\u200e\u200f"):
                with self.assertRaises(chat.ChatError) as ctx:
                    chat.post_message(7, "sleeper", "L1", body)
                self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(cur.executed, [])

    def test_non_member_cannot_post(self):
        cur = FakeCursor(rows=[None])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.post_message(7, "sleeper", "L1", "hi")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(inserted(cur, "league_messages"), [])

    def test_muted_member_cannot_post_until_the_mute_expires(self):
        member = {"role": "member", "muted_until": 2000.0, "external_id": "s1"}
        saved = {"id": 2, "user_id": 7, "body": "hi", "created_at": 3000.0}
        with mock.patch.object(chat.time, "time", return_value=1000.0):
            cur = FakeCursor(rows=[member])
            with patched_conn(cur):
                with self.assertRaises(chat.ChatError) as ctx:
                    chat.post_message(7, "sleeper", "L1", "hi")
            self.assertEqual(ctx.exception.status, 403)
            self.assertEqual(inserted(cur, "league_messages"), [])
        with mock.patch.object(chat.time, "time", return_value=3000.0):
            cur = FakeCursor(rows=[member, saved])
            with patched_conn(cur):
                self.assertEqual(chat.post_message(7, "sleeper", "L1", "hi")["id"], 2)


class Membership(unittest.TestCase):
    def member_insert(self, cur):
        return [p for sql, p in cur.executed if sql.startswith("INSERT INTO league_chat_members")][0]

    def test_add_member_refuses_a_sleeper_user_already_claimed_by_someone_else(self):
        cur = FakeCursor(rows=[{"user_id": 99}])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.add_member(7, "sleeper", "L1", "sleeper-user-1", "member")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(inserted(cur, "league_chat_members"), [])

    def test_the_commissioner_becomes_a_moderator(self):
        cur = FakeCursor(rows=[None, {"user_id": 7, "role": "moderator", "external_id": "s1"}])
        with patched_conn(cur):
            chat.add_member(7, "sleeper", "L1", "s1", "moderator")
        self.assertIn("moderator", self.member_insert(cur))

    def test_everyone_else_is_a_plain_member_even_when_first_to_join(self):
        cur = FakeCursor(rows=[None, {"user_id": 8, "role": "member", "external_id": "s2"}])
        with patched_conn(cur):
            chat.add_member(8, "sleeper", "L1", "s2", "member")
        params = self.member_insert(cur)
        self.assertIn("member", params)
        self.assertNotIn("moderator", params)

    def test_an_unknown_role_is_stored_as_member(self):
        cur = FakeCursor(rows=[None, {"user_id": 8, "role": "member", "external_id": "s2"}])
        with patched_conn(cur):
            chat.add_member(8, "sleeper", "L1", "s2", "owner")
        self.assertNotIn("owner", self.member_insert(cur))

    def test_joins_to_one_league_are_serialised_by_an_advisory_lock(self):
        cur = FakeCursor(rows=[None, {"user_id": 7, "role": "member", "external_id": "s1"}])
        with patched_conn(cur):
            chat.add_member(7, "sleeper", "L1", "s1", "member")
        self.assertIn("pg_advisory_xact_lock", cur.executed[0][0])

    def test_a_simultaneous_claim_of_one_sleeper_user_is_a_409_not_a_500(self):
        cur = FakeCursor(rows=[None], raise_on={"INSERT INTO league_chat_members": psycopg.errors.UniqueViolation()})
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.add_member(7, "sleeper", "L1", "s1", "member")
        self.assertEqual(ctx.exception.status, 409)


class Challenges(unittest.TestCase):
    def test_token_has_the_llab_prefix_and_is_stored_for_this_user(self):
        cur = FakeCursor()
        with patched_conn(cur):
            token = chat.create_challenge(7, "sleeper", "L1")
        self.assertRegex(token, r"^llab-[0-9a-f]{8}$")
        params = [p for s, p in cur.executed if s.startswith("INSERT INTO league_chat_challenges")][0]
        self.assertIn(token, params)
        self.assertIn(7, params)

    def test_consume_is_scoped_to_user_and_a_fifteen_minute_window(self):
        cur = FakeCursor(rows=[{"id": 5}])
        with mock.patch.object(chat.time, "time", return_value=10000.0), patched_conn(cur):
            self.assertTrue(chat.consume_challenge(7, "sleeper", "L1", "llab-aaaa1111"))
        sql, params = cur.executed[0]
        self.assertIn("used_at IS NULL", sql)
        self.assertIn(7, params)
        self.assertIn("llab-aaaa1111", params)
        self.assertIn(10000.0 - 15 * 60, params)

    def test_consume_returns_false_when_nothing_matches(self):
        cur = FakeCursor(rows=[None])
        with patched_conn(cur):
            self.assertFalse(chat.consume_challenge(7, "sleeper", "L1", "llab-nope0000"))


class Messages(unittest.TestCase):
    def test_list_skips_deleted_caps_at_50_and_floors_after_at_zero(self):
        cur = FakeCursor(all_rows=[{"id": 1}])
        with patched_conn(cur):
            out = chat.list_messages("sleeper", "L1", after=-5, limit=500)
        sql, params = cur.executed[0]
        self.assertIn("deleted_at IS NULL", sql)
        self.assertIn("ORDER BY m.id", sql)
        self.assertEqual(params[-1], 50)
        self.assertIn(0, params)
        self.assertEqual(out, [{"id": 1}])

    def test_first_load_returns_the_latest_page_oldest_first(self):
        # the database hands back newest-first; callers must get 8 then 9
        cur = FakeCursor(all_rows=[{"id": 9}, {"id": 8}])
        with patched_conn(cur):
            out = chat.list_messages("sleeper", "L1", after=0)
        self.assertIn("ORDER BY m.id DESC", cur.executed[0][0])
        self.assertEqual([m["id"] for m in out], [8, 9])

    def test_polling_after_an_id_returns_the_next_messages_oldest_first(self):
        cur = FakeCursor(all_rows=[{"id": 4}, {"id": 5}])
        with patched_conn(cur):
            out = chat.list_messages("sleeper", "L1", after=3)
        self.assertNotIn("DESC", cur.executed[0][0])
        self.assertEqual([m["id"] for m in out], [4, 5])

    def test_delete_requires_author_or_moderator(self):
        msg = {"id": 3, "user_id": 5, "platform": "sleeper", "league_id": "L1", "deleted_at": None}
        # a plain member who is not the author
        cur = FakeCursor(rows=[msg, {"role": "member", "muted_until": None, "external_id": "x"}])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.delete_message(6, 3)
        self.assertEqual(ctx.exception.status, 403)
        self.assertFalse([s for s, _ in cur.executed if s.startswith("UPDATE league_messages")])
        # the author
        cur = FakeCursor(rows=[msg])
        with patched_conn(cur):
            chat.delete_message(5, 3)
        self.assertTrue([s for s, _ in cur.executed if s.startswith("UPDATE league_messages")])
        # a moderator
        cur = FakeCursor(rows=[msg, {"role": "moderator", "muted_until": None, "external_id": "x"}])
        with patched_conn(cur):
            chat.delete_message(9, 3)
        self.assertTrue([s for s, _ in cur.executed if s.startswith("UPDATE league_messages")])

    def test_delete_of_a_missing_message_is_404(self):
        cur = FakeCursor(rows=[None])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.delete_message(5, 999)
        self.assertEqual(ctx.exception.status, 404)

    def test_only_a_moderator_can_mute(self):
        cur = FakeCursor(rows=[{"role": "member", "muted_until": None, "external_id": "x"}])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.mute_member(6, 8, "sleeper", "L1", 30)
        self.assertEqual(ctx.exception.status, 403)

    def test_mute_minutes_must_be_positive(self):
        cur = FakeCursor(rows=[{"role": "moderator", "muted_until": None, "external_id": "x"}])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.mute_member(6, 8, "sleeper", "L1", 0)
        self.assertEqual(ctx.exception.status, 400)

    def test_report_requires_membership_in_the_messages_league(self):
        msg = {"platform": "sleeper", "league_id": "L1"}
        cur = FakeCursor(rows=[msg, None])
        with patched_conn(cur):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.report_message(6, 3)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(inserted(cur, "league_message_reports"), [])


class Migration(unittest.TestCase):
    def test_every_user_reference_cascades_on_delete(self):
        sql = MIGRATION.read_text()
        refs = re.findall(r"REFERENCES\s+public\.(?:users|league_messages)\s*\(id\)[^,\n]*", sql)
        self.assertGreaterEqual(len(refs), 4)
        for ref in refs:
            self.assertIn("ON DELETE CASCADE", ref, ref)

    def test_row_level_security_is_enabled_on_every_new_table(self):
        sql = MIGRATION.read_text()
        tables = re.findall(r"CREATE TABLE public\.(\w+)", sql)
        self.assertEqual(sorted(tables), sorted([
            "league_chat_challenges", "league_chat_members", "league_message_reports", "league_messages"]))
        for t in tables:
            self.assertIn(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY", sql)

    def test_one_sleeper_user_maps_to_one_account_per_league(self):
        self.assertRegex(" ".join(MIGRATION.read_text().split()),
                         r"UNIQUE \(platform, league_id, external_id\)")


if __name__ == "__main__":
    unittest.main()
