"""In-app account deletion (App Store Guideline 5.1.1(v)).

Deleting must re-authenticate (typed DELETE, plus the password when the account
has one), remove only the signed-in user's row, and clear the session cookie.
The database is mocked — no network. The cascade itself is a schema fact (every
table referencing users is ON DELETE CASCADE, checked against Supabase), so
these tests pin the one statement that triggers it and the guards around it.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import db

USER = {"id": 7, "username": "sam", "email": "sam@example.com", "email_verified": True}


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.row


def patched_conn(cursor):
    @contextmanager
    def _conn():
        yield cursor
    return mock.patch.object(db, "_conn", _conn)


def deletes(cursor):
    return [e for e in cursor.executed if e[0].startswith("DELETE")]


class DbDeleteAccount(unittest.TestCase):
    def row(self, password="hunter2hunter2"):
        return {"id": 7, "password_hash": db._hash_password(password) if password else ""}

    def test_deletes_only_that_user_with_password_and_confirm(self):
        cur = FakeCursor(self.row())
        with patched_conn(cur):
            db.delete_account(7, "hunter2hunter2", "DELETE")
        self.assertEqual(deletes(cur), [("DELETE FROM users WHERE id = %s", (7,))])

    def test_wrong_password_deletes_nothing(self):
        cur = FakeCursor(self.row())
        with patched_conn(cur), self.assertRaises(db.AuthError):
            db.delete_account(7, "nope", "DELETE")
        self.assertEqual(deletes(cur), [])

    def test_missing_confirmation_deletes_nothing_and_never_queries(self):
        cur = FakeCursor(self.row())
        for confirm in ("", "delete me", None):
            with patched_conn(cur), self.assertRaises(db.AuthError):
                db.delete_account(7, "hunter2hunter2", confirm)
        self.assertEqual(cur.executed, [])

    def test_oauth_only_account_needs_just_the_confirmation(self):
        cur = FakeCursor(self.row(password=None))
        with patched_conn(cur):
            db.delete_account(7, "", "DELETE")
        self.assertEqual(len(deletes(cur)), 1)

    def test_unknown_user_raises(self):
        cur = FakeCursor(None)
        with patched_conn(cur), self.assertRaises(db.AuthError):
            db.delete_account(7, "x", "DELETE")
        self.assertEqual(deletes(cur), [])

    def test_public_user_flags_password_presence_without_leaking_the_hash(self):
        base = {"id": 1, "username": "u", "email": "e", "email_verified": True}
        self.assertTrue(db._public({**base, "password_hash": "$2b$x"})["has_password"])
        self.assertFalse(db._public({**base, "password_hash": ""})["has_password"])
        self.assertNotIn("password_hash", db._public({**base, "password_hash": "$2b$x"}))


class DeleteAccountEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.addCleanup(server.app.dependency_overrides.clear)

    def test_requires_sign_in(self):
        r = self.client.post("/api/auth/delete-account", json={"confirm": "DELETE"})
        self.assertEqual(r.status_code, 401)

    def test_success_deletes_the_signed_in_user_and_clears_the_cookie(self):
        server.app.dependency_overrides[server.require_user] = lambda: USER
        with mock.patch.object(server.db, "delete_account") as d:
            r = self.client.post("/api/auth/delete-account", json={"password": "pw", "confirm": "DELETE"})
        self.assertEqual(r.status_code, 200)
        d.assert_called_once_with(7, "pw", "DELETE")
        self.assertIn(f"{server.SESSION_COOKIE}=", r.headers.get("set-cookie", ""))

    def test_rejection_is_a_400_with_the_reason(self):
        server.app.dependency_overrides[server.require_user] = lambda: USER
        with mock.patch.object(server.db, "delete_account", side_effect=db.AuthError("Password is incorrect.")):
            r = self.client.post("/api/auth/delete-account", json={"password": "bad", "confirm": "DELETE"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Password is incorrect", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
