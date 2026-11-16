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
        p = mock.patch.object(server.db, "add_waitlist")
        self.add = p.start()
        self.addCleanup(p.stop)

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

    def test_rate_limited_after_ten_in_an_hour(self):
        codes = [self.post().status_code for _ in range(11)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)

    def test_page_offers_three_plans_and_start_free(self):
        js = open(os.path.join(ROOT, "static", "landing.js")).read()
        for needle in ("Sync up to 2 leagues", "Sync 3 to 4 leagues", "Sync 5 or more leagues", "/api/waitlist"):
            self.assertIn(needle, js)
        self.assertNotIn("Free Trial", js)
