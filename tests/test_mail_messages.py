"""Signup / resend / forgot-password must not claim an email is on its way
when it isn't.

Signup returns `verification_email` ("sent" | "failed" | "not_configured") so
the page can tell the truth. Forgot-password stays enumeration-safe per email
(same reply whether or not the account exists), but says so plainly when mail is
down server-wide, since that reveals nothing about any one address.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import db, mail

USER = {"id": 7, "username": "sam", "email": "sam@example.com", "email_verified": False}


class Messages(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.addCleanup(mock.patch.stopall)

    def start_signup_patches(self, configured=True, send_exc=None):
        mock.patch.object(db, "create_user", return_value=dict(USER)).start()
        mock.patch.object(db, "create_session", return_value="sess").start()
        mock.patch.object(db, "create_verification_token", return_value="tok").start()
        mock.patch.object(mail, "configured", return_value=configured).start()
        mock.patch.object(mail, "send_verification_email", side_effect=send_exc).start()

    def signup(self):
        return self.client.post("/api/auth/signup", json={
            "username": "sam", "email": "sam@example.com", "password": "hunter2hunter2"})

    def test_signup_reports_sent(self):
        self.start_signup_patches()
        r = self.signup()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["verification_email"], "sent")

    def test_signup_reports_failed_when_send_raises(self):
        self.start_signup_patches(send_exc=mail.MailSendError("boom"))
        r = self.signup()
        self.assertEqual(r.status_code, 200)  # the account is still created
        self.assertEqual(r.json()["verification_email"], "failed")

    def test_signup_reports_not_configured(self):
        self.start_signup_patches(configured=False)
        self.assertEqual(self.signup().json()["verification_email"], "not_configured")

    def test_forgot_password_503_when_mail_not_configured(self):
        mock.patch.object(mail, "configured", return_value=False).start()
        r = self.client.post("/api/auth/forgot-password", json={"email": "who@example.com"})
        self.assertEqual(r.status_code, 503)

    def test_forgot_password_same_reply_for_unknown_and_known(self):
        mock.patch.object(mail, "configured", return_value=True).start()
        mock.patch.object(db, "create_reset_token", return_value="t").start()
        mock.patch.object(mail, "send_password_reset_email").start()
        lookup = mock.patch.object(db, "get_user_by_email", return_value=None).start()
        a = self.client.post("/api/auth/forgot-password", json={"email": "a@example.com"})
        lookup.return_value = dict(USER)
        b = self.client.post("/api/auth/forgot-password", json={"email": "sam@example.com"})
        self.assertEqual(a.json(), b.json())
        self.assertNotIn("on its way", a.json()["message"])


if __name__ == "__main__":
    unittest.main()
