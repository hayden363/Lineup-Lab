"""Resend sending (with Gmail fallback) and the welcome / password-changed emails."""

import unittest
from unittest import mock

import requests
from fastapi.testclient import TestClient

import server
from engine import db, mail

USER = {"id": 7, "username": "sam", "email": "sam@example.com", "email_verified": True}


def _resp(status=200, body=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body if body is not None else {"id": "abc"}
    r.text = str(body)
    return r


class Providers(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        for name, val in (("GMAIL_ADDRESS", None), ("GMAIL_APP_PASSWORD", None), ("RESEND_API_KEY", None),
                          ("MAIL_FROM", None), ("MAIL_REPLY_TO", None)):
            mock.patch.object(mail, name, val).start()

    def resend_on(self, reply_to=None):
        mock.patch.object(mail, "RESEND_API_KEY", "re_test").start()
        mock.patch.object(mail, "MAIL_FROM", "Lineup Lab <hello@example.com>").start()
        if reply_to:
            mock.patch.object(mail, "MAIL_REPLY_TO", reply_to).start()

    def gmail_on(self):
        mock.patch.object(mail, "GMAIL_ADDRESS", "g@example.com").start()
        mock.patch.object(mail, "GMAIL_APP_PASSWORD", "apppasswordapppass").start()

    def test_configured_combinations(self):
        self.assertFalse(mail.configured())
        mock.patch.object(mail, "RESEND_API_KEY", "re_test").start()
        self.assertFalse(mail.configured())          # a key without a From address is not enough
        mock.patch.object(mail, "MAIL_FROM", "Lineup Lab <hello@example.com>").start()
        self.assertTrue(mail.configured())

    def test_resend_payload(self):
        self.resend_on(reply_to="help@example.com")
        with mock.patch.object(mail.requests, "post", return_value=_resp()) as post:
            mail._send("to@example.com", "Subj", "plain", "<p>html</p>")
        args, kw = post.call_args
        self.assertEqual(args[0], "https://api.resend.com/emails")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer re_test")
        j = kw["json"]
        self.assertEqual(j["from"], "Lineup Lab <hello@example.com>")
        self.assertEqual(j["to"], ["to@example.com"])
        self.assertEqual((j["subject"], j["text"], j["html"]), ("Subj", "plain", "<p>html</p>"))
        self.assertEqual(j["reply_to"], "help@example.com")
        self.assertEqual(j["headers"]["Auto-Submitted"], "auto-generated")
        self.assertGreater(kw["timeout"], 0)

    def test_resend_rejection_names_the_reason(self):
        self.resend_on()
        with mock.patch.object(mail.requests, "post", return_value=_resp(403, {"message": "domain not verified"})):
            with self.assertRaises(mail.MailSendError) as cm:
                mail._send("to@example.com", "s", "t", "h")
        self.assertIn("403", str(cm.exception))
        self.assertIn("domain not verified", str(cm.exception))

    def test_network_error_is_a_mail_send_error(self):
        self.resend_on()
        with mock.patch.object(mail.requests, "post", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(mail.MailSendError):
                mail._send("to@example.com", "s", "t", "h")

    def test_falls_back_to_gmail_when_resend_fails(self):
        self.resend_on()
        self.gmail_on()
        with mock.patch.object(mail.requests, "post", return_value=_resp(500, {"message": "oops"})), \
             mock.patch.object(mail, "_send_gmail") as gm:
            mail._send("to@example.com", "s", "t", "h")
        gm.assert_called_once_with("to@example.com", "s", "t", "h")

    def test_both_fail_reports_both(self):
        self.resend_on()
        self.gmail_on()
        with mock.patch.object(mail.requests, "post", return_value=_resp(500, {"message": "oops"})), \
             mock.patch.object(mail, "_send_gmail", side_effect=mail.MailSendError("gmail down")):
            with self.assertRaises(mail.MailSendError) as cm:
                mail._send("to@example.com", "s", "t", "h")
        self.assertIn("oops", str(cm.exception))
        self.assertIn("gmail down", str(cm.exception))

    def test_resend_success_never_touches_gmail(self):
        self.resend_on()
        self.gmail_on()
        with mock.patch.object(mail.requests, "post", return_value=_resp()), \
             mock.patch.object(mail, "_send_gmail") as gm:
            mail._send("to@example.com", "s", "t", "h")
        gm.assert_not_called()

    def test_nothing_configured(self):
        with self.assertRaises(mail.MailNotConfigured):
            mail._send("to@example.com", "s", "t", "h")


class Templates(unittest.TestCase):
    def capture(self, fn, *a, **k):
        with mock.patch.object(mail, "_send") as send:
            fn(*a, **k)
        return send.call_args.args

    def test_welcome(self):
        to, subject, text, html = self.capture(mail.send_welcome_email, "a@b.com", "sam", "https://app.example.com/x?y=1")
        self.assertEqual((to, subject), ("a@b.com", "Welcome to Lineup Lab"))
        self.assertIn("Hi sam", text)
        self.assertIn("https://app.example.com", text)
        self.assertNotIn("?y=1", text)             # the link is the app's origin, not the page it was triggered from
        self.assertIn("https://app.example.com/icons/email-logo.png", html)
        self.assertIn("Open Lineup Lab", html)

    def test_password_changed(self):
        to, subject, text, html = self.capture(mail.send_password_changed_email, "a@b.com", "sam",
                                               "https://app.example.com/", when=0)
        self.assertEqual(subject, "Your Lineup Lab password was changed")
        self.assertIn("January 01, 1970 at 00:00 UTC", text)
        self.assertIn("Forgot password", text)
        self.assertIn("If it wasn't you", html)
        self.assertNotIn("token", text.lower())    # nothing that could log someone in


class Triggers(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, follow_redirects=False)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(mail, "configured", return_value=True).start()
        self.welcome = mock.patch.object(mail, "send_welcome_email").start()
        self.changed = mock.patch.object(mail, "send_password_changed_email").start()

    def test_verify_sends_welcome_once_per_valid_token(self):
        with mock.patch.object(db, "consume_verification_token", return_value=dict(USER)):
            r = self.client.get("/api/auth/verify?token=good")
        self.assertEqual(r.status_code, 307)
        self.assertIn("verified=1", r.headers["location"])
        self.welcome.assert_called_once()
        self.assertEqual(self.welcome.call_args.args[:2], ("sam@example.com", "sam"))
        self.assertTrue(self.welcome.call_args.args[2].startswith("http"))

    def test_bad_token_sends_nothing(self):
        with mock.patch.object(db, "consume_verification_token", side_effect=db.AuthError("bad")):
            r = self.client.get("/api/auth/verify?token=bad")
        self.assertIn("verified=0", r.headers["location"])
        self.welcome.assert_not_called()

    def test_mail_failure_does_not_break_verify(self):
        self.welcome.side_effect = mail.MailSendError("down")
        with mock.patch.object(db, "consume_verification_token", return_value=dict(USER)):
            r = self.client.get("/api/auth/verify?token=good")
        self.assertIn("verified=1", r.headers["location"])

    def test_not_configured_sends_nothing(self):
        mail.configured.return_value = False
        with mock.patch.object(db, "consume_verification_token", return_value=dict(USER)):
            self.client.get("/api/auth/verify?token=good")
        self.welcome.assert_not_called()

    def test_change_password_sends_notice(self):
        with mock.patch.object(server, "current_user", return_value=dict(USER)), \
             mock.patch.object(db, "get_user_by_session", return_value=dict(USER)), \
             mock.patch.object(db, "change_password"):
            self.client.cookies.set(server.SESSION_COOKIE, "s")
            r = self.client.post("/api/auth/change-password",
                                 json={"current_password": "oldpassword1", "new_password": "newpassword1"})
        self.assertEqual(r.status_code, 200)
        self.changed.assert_called_once()
        self.assertEqual(self.changed.call_args.args[:2], ("sam@example.com", "sam"))

    def test_failed_change_sends_nothing(self):
        with mock.patch.object(db, "get_user_by_session", return_value=dict(USER)), \
             mock.patch.object(db, "change_password", side_effect=db.AuthError("wrong")):
            self.client.cookies.set(server.SESSION_COOKIE, "s")
            r = self.client.post("/api/auth/change-password",
                                 json={"current_password": "x" * 8, "new_password": "newpassword1"})
        self.assertEqual(r.status_code, 400)
        self.changed.assert_not_called()

    def test_reset_password_sends_notice(self):
        with mock.patch.object(db, "reset_password", return_value=dict(USER)), \
             mock.patch.object(db, "create_session", return_value="sess"):
            r = self.client.post("/api/auth/reset-password", json={"token": "t", "new_password": "newpassword1"})
        self.assertEqual(r.status_code, 200)
        self.changed.assert_called_once()

    def test_invalid_reset_sends_nothing(self):
        with mock.patch.object(db, "reset_password", side_effect=db.AuthError("expired")):
            r = self.client.post("/api/auth/reset-password", json={"token": "t", "new_password": "newpassword1"})
        self.assertEqual(r.status_code, 400)
        self.changed.assert_not_called()

    def _google(self, user):
        self.client.cookies.set(server.OAUTH_STATE_COOKIE, "st")
        with mock.patch.object(server.oauth_layer, "google_exchange_code",
                               return_value={"provider_id": "g1", "email": "sam@example.com", "name": "sam"}), \
             mock.patch.object(db, "find_or_create_oauth_user", return_value=user), \
             mock.patch.object(db, "create_session", return_value="sess"):
            return self.client.get("/api/auth/google/callback?code=c&state=st")

    def test_new_google_account_gets_welcome(self):
        r = self._google({**USER, "just_created": True})
        self.assertEqual(r.status_code, 307)
        self.welcome.assert_called_once()

    def test_returning_google_sign_in_gets_nothing(self):
        r = self._google(dict(USER))
        self.assertEqual(r.status_code, 307)
        self.welcome.assert_not_called()


if __name__ == "__main__":
    unittest.main()
