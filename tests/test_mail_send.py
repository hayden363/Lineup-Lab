"""engine/mail.py's SMTP sending: port order, fallback, and what the errors say.

On Render the first symptom of a blocked/filtered SMTP path was a bare
"Connection unexpectedly closed" with no way to tell which port or step failed.
These pin: 587 first then 465, no pointless fallback after a rejected login,
and an error that names every port and step that failed.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import smtplib
import unittest
from unittest import mock

from engine import mail


def _server(fail_on=None, exc=None):
    """A fake SMTP/SMTP_SSL object usable as a context manager. `fail_on` is the
    method name that raises `exc` ("starttls", "login", "send_message")."""
    s = mock.MagicMock()
    s.__enter__.return_value = s
    s.__exit__.return_value = False
    if fail_on:
        getattr(s, fail_on).side_effect = exc
    return s


class SendPorts(unittest.TestCase):
    def setUp(self):
        p1 = mock.patch.object(mail, "GMAIL_ADDRESS", "from@example.com")
        p2 = mock.patch.object(mail, "GMAIL_APP_PASSWORD", "apppasswordapppass")
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def send(self):
        mail._send("to@example.com", "subject", "text", "<p>html</p>")

    def test_587_success_never_touches_465(self):
        s587 = _server()
        with mock.patch.object(mail.smtplib, "SMTP", return_value=s587) as smtp, \
             mock.patch.object(mail.smtplib, "SMTP_SSL") as smtp_ssl:
            self.send()
        smtp.assert_called_once()
        self.assertEqual(smtp.call_args.args[:2], ("smtp.gmail.com", 587))
        smtp_ssl.assert_not_called()
        s587.starttls.assert_called_once()
        s587.login.assert_called_once_with("from@example.com", "apppasswordapppass")
        s587.send_message.assert_called_once()

    def test_falls_back_to_465_when_587_drops_the_connection(self):
        drop = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        s465 = _server()
        with mock.patch.object(mail.smtplib, "SMTP", side_effect=drop), \
             mock.patch.object(mail.smtplib, "SMTP_SSL", return_value=s465) as smtp_ssl:
            self.send()
        self.assertEqual(smtp_ssl.call_args.args[:2], ("smtp.gmail.com", 465))
        s465.starttls.assert_not_called()  # implicit TLS, no STARTTLS upgrade
        s465.login.assert_called_once()
        s465.send_message.assert_called_once()

    def test_both_failing_reports_each_port_and_the_step(self):
        s587 = _server("starttls", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"))
        refused = ConnectionRefusedError("refused")
        with mock.patch.object(mail.smtplib, "SMTP", return_value=s587), \
             mock.patch.object(mail.smtplib, "SMTP_SSL", side_effect=refused):
            with self.assertRaises(mail.MailSendError) as cm:
                self.send()
        msg = str(cm.exception)
        self.assertIn("port 587 failed at starttls", msg)
        self.assertIn("SMTPServerDisconnected", msg)
        self.assertIn("port 465 failed at connect", msg)
        self.assertIn("ConnectionRefusedError", msg)

    def test_rejected_login_stops_immediately_with_the_app_password_hint(self):
        bad = _server("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))
        with mock.patch.object(mail.smtplib, "SMTP", return_value=bad), \
             mock.patch.object(mail.smtplib, "SMTP_SSL") as smtp_ssl:
            with self.assertRaises(mail.MailSendError) as cm:
                self.send()
        self.assertIn("App Password", str(cm.exception))
        smtp_ssl.assert_not_called()

    def test_not_configured_raises_before_any_network(self):
        with mock.patch.object(mail, "GMAIL_ADDRESS", None), \
             mock.patch.object(mail.smtplib, "SMTP") as smtp, \
             mock.patch.object(mail.smtplib, "SMTP_SSL") as smtp_ssl:
            with self.assertRaises(mail.MailNotConfigured):
                self.send()
        smtp.assert_not_called()
        smtp_ssl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
