import os
import re
import unittest

from fastapi.testclient import TestClient

import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LandingPageTest(unittest.TestCase):
    """The signed-out front door at /welcome must run under the app's strict CSP (script-src 'self'): every script
    is a same-origin file, nothing inline, nothing from a CDN."""

    def setUp(self):
        self.client = TestClient(server.app)

    def test_welcome_serves_the_page_uncached(self):
        r = self.client.get("/welcome")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertEqual(r.headers["cache-control"], "no-cache")
        self.assertIn("script-src 'self'", r.headers["content-security-policy"])

    def test_every_script_is_a_same_origin_file_and_none_are_inline(self):
        page = self.client.get("/welcome").text
        tags = re.findall(r"<script\b([^>]*)>(.*?)</script>", page, flags=re.S)
        self.assertTrue(tags)
        for attrs, body in tags:
            m = re.search(r'src="([^"]+)"', attrs)
            self.assertIsNotNone(m, "inline script would be blocked by the CSP")
            self.assertTrue(m.group(1).startswith("/"), m.group(1))
            self.assertEqual(body.strip(), "")
            self.assertEqual(self.client.get(m.group(1)).status_code, 200, m.group(1))

    def test_stylesheet_and_script_routes_exist(self):
        for path, kind in (("/landing.css", "text/css"), ("/landing.js", "text/javascript")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(kind, r.headers["content-type"])

    def test_buttons_go_to_the_real_sign_in_not_a_preview(self):
        js = open(os.path.join(ROOT, "static", "landing.js")).read()
        self.assertIn("/?auth=", js)
        self.assertNotIn("onrender.com", js)
        self.assertNotIn("AuthModal", js)

    def test_app_sends_bare_signed_out_visits_to_welcome_but_not_query_visits(self):
        app = open(os.path.join(ROOT, "static", "app.js")).read()
        self.assertIn('if (!window.location.search) { window.location.replace("/welcome"); return; }', app)


if __name__ == "__main__":
    unittest.main()


class WaitlistTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.client = TestClient(server.app)
        server._RATE_BUCKETS.clear()
        p = mock.patch.object(server.db, "add_waitlist", return_value=True)
        self.add = p.start()
        self.addCleanup(p.stop)
        n = mock.patch.object(server.waitlist_layer, "notify_owner")
        self.notify = n.start()
        self.addCleanup(n.stop)

    def post(self, email="Fan@Example.com ", plan="manager"):
        return self.client.post("/api/waitlist", json={"email": email, "plan": plan})

    def test_joins_with_a_normalised_email(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.add.assert_called_once_with("fan@example.com", "manager")

    def test_free_or_unknown_plans_are_rejected(self):
        for plan in ("free", "gold", ""):
            self.assertEqual(self.post(plan=plan).status_code, 400, plan)
        self.add.assert_not_called()

    def test_bad_emails_are_rejected(self):
        for email in ("nope", "a@b", "a b@c.com", "", "x" * 400 + "@c.com"):
            self.assertEqual(self.post(email=email).status_code, 400, email[:20])
        self.add.assert_not_called()

    def test_missing_table_is_a_friendly_503_not_a_crash(self):
        self.add.side_effect = RuntimeError("relation plan_waitlist does not exist")
        r = self.post(plan="commissioner")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("relation", r.text)

    def test_owner_is_told_about_a_new_request_but_not_a_repeat(self):
        self.post()
        self.notify.assert_called_once_with("manager", "fan@example.com")
        self.notify.reset_mock()
        self.add.return_value = False        # same email and plan again: no new row, no email
        self.assertEqual(self.post().status_code, 200)
        self.notify.assert_not_called()

    def test_rate_limited_after_ten_in_an_hour(self):
        codes = [self.post().status_code for _ in range(11)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)

    def test_page_offers_three_plans_and_start_free(self):
        js = open(os.path.join(ROOT, "static", "landing.js")).read()
        for needle in ("Sync up to 2 leagues", "Sync 3 to 4 leagues", "Sync 5 or more leagues", "/api/waitlist"):
            self.assertIn(needle, js)
        self.assertNotIn("Free Trial", js)


class OwnerNoticeTest(unittest.TestCase):
    COUNTS = {"manager": 4, "commissioner": 2}

    def setUp(self):
        from unittest import mock
        from engine import waitlist as W
        self.W = W
        self.mock = mock
        W._last_notice = 0.0
        env = mock.patch.dict(os.environ, {"WAITLIST_NOTIFY_EMAIL": "owner@example.com"}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.sent = []
        self.send = lambda to, subject, text, body: self.sent.append((to, subject, text, body))

    def test_email_has_the_new_request_and_the_totals(self):
        r = self.W.notify_owner("manager", "fan@example.com", get_counts=lambda: self.COUNTS, send=self.send, now=1000)
        self.assertEqual(r, "sent")
        to, subject, text, body = self.sent[0]
        self.assertEqual(to, "owner@example.com")
        self.assertEqual(subject, "Lineup Lab waitlist: 6 requests (4 Manager, 2 Commissioner)")
        self.assertIn("fan@example.com joined the Manager (3-4 leagues) waitlist", text)
        self.assertIn("Waiting right now: 6 total", text)

    def test_singular_subject(self):
        subject, _, _ = self.W.build("manager", "a@b.co", {"manager": 1})
        self.assertEqual(subject, "Lineup Lab waitlist: 1 request (1 Manager, 0 Commissioner)")

    def test_html_escapes_the_address(self):
        _, _, body = self.W.build("manager", "<b>x</b>@e.com", self.COUNTS)
        self.assertNotIn("<b>x</b>@e.com", body)

    def test_nothing_sent_without_a_recipient(self):
        with self.mock.patch.dict(os.environ, {"WAITLIST_NOTIFY_EMAIL": "", "OWNER_REPORT_EMAIL": ""}):
            self.assertEqual(self.W.notify_owner("manager", "a@b.co", send=self.send, now=1000), "not-configured")
        self.assertEqual(self.sent, [])

    def test_falls_back_to_the_owner_report_address(self):
        with self.mock.patch.dict(os.environ, {"WAITLIST_NOTIFY_EMAIL": "", "OWNER_REPORT_EMAIL": "boss@example.com"}):
            self.assertEqual(self.W.recipient(), "boss@example.com")

    def test_bursts_are_throttled_and_a_failed_send_is_retried(self):
        kw = dict(get_counts=lambda: self.COUNTS, send=self.send)
        self.assertEqual(self.W.notify_owner("manager", "a@b.co", now=1000, **kw), "sent")
        self.assertEqual(self.W.notify_owner("manager", "c@d.co", now=1100, **kw), "throttled")
        self.assertEqual(self.W.notify_owner("manager", "c@d.co", now=1000 + self.W.NOTICE_EVERY_SECONDS + 1, **kw), "sent")
        self.W._last_notice = 0.0
        def boom(*a):
            raise RuntimeError("smtp down")
        self.assertEqual(self.W.notify_owner("manager", "a@b.co", get_counts=lambda: self.COUNTS, send=boom, now=5000), "failed")
        self.assertEqual(self.W.notify_owner("manager", "a@b.co", now=5001, **kw), "sent")
