import os
import unittest
from unittest import mock

from engine import security as sec


class BaseUrlTests(unittest.TestCase):
    def test_a_forged_host_never_reaches_an_email_link(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
                os.environ.pop(k, None)
            self.assertEqual(sec.public_base_url("https://evil.example/"), sec.DEFAULT_BASE_URL)
            self.assertEqual(sec.public_base_url("https://lineup-lab-awdv.onrender.com/"), "https://lineup-lab-awdv.onrender.com")
            self.assertEqual(sec.public_base_url("http://localhost:8000/"), "http://localhost:8000")
            self.assertEqual(sec.public_base_url("https://x.onrender.com.evil.io/"), sec.DEFAULT_BASE_URL)

    def test_configured_origin_wins(self):
        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://app.example.com/path"}):
            self.assertEqual(sec.public_base_url("https://evil.example/"), "https://app.example.com")


class OriginTests(unittest.TestCase):
    def test_cross_site_post_is_refused_but_same_site_and_headerless_pass(self):
        self.assertTrue(sec.same_origin({"origin": "https://a.com"}, "a.com"))
        self.assertFalse(sec.same_origin({"origin": "https://evil.com"}, "a.com"))
        self.assertFalse(sec.same_origin({"referer": "https://evil.com/x"}, "a.com"))
        self.assertTrue(sec.same_origin({"referer": "https://a.com/x"}, "a.com"))
        self.assertTrue(sec.same_origin({}, "a.com"))
        self.assertFalse(sec.same_origin({"origin": "null"}, "a.com"))


class ThrottleTests(unittest.TestCase):
    def test_blocks_after_the_limit_and_recovers_with_time_or_success(self):
        t = sec.AccountThrottle(limit=3, window=60)
        for i in range(3):
            self.assertFalse(t.blocked("a", now=i))
            t.fail("a", now=i)
        self.assertTrue(t.blocked("a", now=10))
        self.assertFalse(t.blocked("b", now=10))
        self.assertFalse(t.blocked("a", now=100))       # window passed
        t.fail("a", now=100); t.clear("a")
        self.assertFalse(t.blocked("a", now=101))

    def test_idle_keys_do_not_pile_up(self):
        t = sec.AccountThrottle(limit=3, window=10)
        for i in range(50):
            t.fail(f"k{i}", now=0)
        t.blocked("k0", now=100)
        for i in range(50):
            t.blocked(f"k{i}", now=100)
        self.assertEqual(t.size(), 0)


class PasswordTests(unittest.TestCase):
    def test_rules(self):
        self.assertIsNotNone(sec.check_password("short"))
        self.assertIsNotNone(sec.check_password("password123"))
        self.assertIsNotNone(sec.check_password("aaaaaaaaaa"))
        self.assertIsNotNone(sec.check_password("x" * 80))
        self.assertIsNotNone(sec.check_password("hayden363", username="Hayden363"))
        self.assertIsNone(sec.check_password("correct horse battery"))


class TokenAndAuditTests(unittest.TestCase):
    def test_hash_is_stable_and_not_the_token(self):
        self.assertEqual(sec.hash_token("abc"), sec.hash_token("abc"))
        self.assertNotIn("abc", sec.hash_token("abc"))
        self.assertEqual(len(sec.hash_token("abc")), 64)

    def test_audit_cannot_be_forged_by_hostile_values(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sec.audit("login_failed", who="bob event=login_ok\n[security] event=x")
        out = buf.getvalue()
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(out.count("[security]"), 1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import server
        self.client = TestClient(server.app, raise_server_exceptions=False)
        server._RATE_BUCKETS.clear()

    def test_security_headers_are_on_every_response(self):
        r = self.client.get("/healthz")
        csp = r.headers["content-security-policy"]
        for part in ("base-uri 'self'", "form-action 'self'", "object-src 'none'", "frame-ancestors 'none'"):
            self.assertIn(part, csp)
        self.assertEqual(r.headers["cross-origin-opener-policy"], "same-origin")
        self.assertEqual(r.headers["x-frame-options"], "DENY")

    def test_security_txt_is_published(self):
        r = self.client.get("/.well-known/security.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Contact:", r.text)

    def test_cross_site_post_with_a_session_cookie_is_blocked(self):
        r = self.client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}, cookies={"eb_session": "x"})
        self.assertEqual(r.status_code, 403)

    def test_same_site_post_still_works(self):
        r = self.client.post("/api/auth/logout", headers={"Origin": "http://testserver"}, cookies={"eb_session": "x"})
        self.assertNotEqual(r.status_code, 403)

    def test_oversized_bodies_are_refused(self):
        r = self.client.post("/api/auth/login", content=b"x" * 1_100_000, headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_auth_responses_are_never_cached(self):
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_a_forged_host_cannot_steer_the_reset_link(self):
        sent = {}
        import server
        with mock.patch.object(server.mail_layer, "configured", return_value=True), \
             mock.patch.object(server.db, "get_user_by_email", return_value={"id": 1, "email": "a@b.co", "username": "a"}), \
             mock.patch.object(server.db, "create_reset_token", return_value="TOKEN"), \
             mock.patch.object(server.mail_layer, "send_password_reset_email", side_effect=lambda e, u, url: sent.update(url=url)):
            r = self.client.post("/api/auth/forgot-password", json={"email": "a@b.co"}, headers={"Host": "evil.example"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(sent["url"].startswith(sec.DEFAULT_BASE_URL + "/?reset_token="), sent["url"])

    def test_repeated_failures_lock_the_account_even_from_new_addresses(self):
        import server
        server._login_throttle = sec.AccountThrottle(limit=3, window=60)
        with mock.patch.object(server.db, "authenticate", side_effect=server.db.AuthError("Incorrect")):
            codes = [self.client.post("/api/auth/login", json={"identifier": "Victim", "password": "x"}).status_code for _ in range(5)]
        self.assertEqual(codes[:3], [401, 401, 401])
        self.assertEqual(codes[3:], [429, 429])

    def test_unexpected_errors_do_not_leak_details(self):
        import server
        with mock.patch.object(server.db, "get_user_by_session", side_effect=RuntimeError("secret sql detail")):
            r = self.client.get("/api/auth/me", cookies={"eb_session": "x"})
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("secret", r.text)
