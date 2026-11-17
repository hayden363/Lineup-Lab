"""Server pieces for the Lineup Lab iOS app (docs/superpowers/specs/2026-11-17-ios-app-design.md): Sign in with Apple,
the Google sign-in hand-off, push device registration and the daily reminder, the support page, and the web's in-app
mode."""
import datetime as dt
import hashlib
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import oauth, push

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _r(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()


class AppleNativeTests(unittest.TestCase):
    def test_token_must_be_ours_and_match_the_nonce(self):
        claims = {"sub": "apple-123", "email": "x@privaterelay.appleid.com", "nonce": hashlib.sha256(b"n0nce").hexdigest()}
        with mock.patch.object(oauth, "_verify_id_token", return_value=claims) as v:
            out = oauth.apple_verify_native("tok", "n0nce")
        self.assertEqual(out["provider_id"], "apple-123")
        self.assertEqual(v.call_args[0][2], oauth.APPLE_APP_BUNDLE_ID)            # audience = the app's bundle ID
        with mock.patch.object(oauth, "_verify_id_token", return_value=claims):
            with self.assertRaises(oauth.OAuthError):
                oauth.apple_verify_native("tok", "a-different-nonce")
        with self.assertRaises(oauth.OAuthError):
            oauth.apple_verify_native("", "n0nce")

    def test_endpoint_starts_a_session(self):
        c = TestClient(server.app)
        server._RATE_BUCKETS.clear()
        with mock.patch.object(server.oauth_layer, "apple_verify_native", return_value={"provider_id": "a1", "email": "a@b.co", "name": None}), \
             mock.patch.object(server.db, "find_or_create_oauth_user", return_value={"id": 5}) as f, \
             mock.patch.object(server.db, "create_session", return_value="sess-tok"):
            r = c.post("/api/auth/apple", json={"identity_token": "t", "nonce": "n", "full_name": "Pat Doe"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("sess-tok", r.headers.get("set-cookie", ""))
        self.assertEqual(f.call_args[0][:2], ("apple", "a1"))
        with mock.patch.object(server.oauth_layer, "apple_verify_native", side_effect=oauth.OAuthError("bad")):
            self.assertEqual(c.post("/api/auth/apple", json={"identity_token": "t", "nonce": "n"}).status_code, 400)


class GoogleHandOffTests(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(server.app)
        server._RATE_BUCKETS.clear()

    def test_one_time_code_works_once_and_expires(self):
        code = server._issue_app_code("sess-1")
        self.assertEqual(server._redeem_app_code(code), "sess-1")
        self.assertIsNone(server._redeem_app_code(code))                            # single use
        code = server._issue_app_code("sess-2")
        with mock.patch.object(server.time, "time", return_value=server.time.time() + server.APP_CODE_TTL + 5):
            self.assertIsNone(server._redeem_app_code(code))                        # expired

    def test_exchange_sets_the_session_cookie(self):
        code = server._issue_app_code("sess-3")
        r = self.c.post("/api/auth/app-exchange", json={"code": code})
        self.assertEqual(r.status_code, 200)
        self.assertIn("sess-3", r.headers.get("set-cookie", ""))
        self.assertEqual(self.c.post("/api/auth/app-exchange", json={"code": code}).status_code, 400)

    def test_callback_from_the_app_redirects_to_the_app_scheme(self):
        with mock.patch.object(server.oauth_layer, "google_exchange_code", return_value={"provider_id": "g1", "email": "g@b.co"}), \
             mock.patch.object(server.db, "find_or_create_oauth_user", return_value={"id": 9}), \
             mock.patch.object(server.db, "create_session", return_value="sess-g"):
            self.c.cookies.set(server.OAUTH_STATE_COOKIE, "st")
            self.c.cookies.set(server.OAUTH_APP_COOKIE, "1")
            r = self.c.get("/api/auth/google/callback?code=c&state=st", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        loc = r.headers["location"]
        self.assertTrue(loc.startswith("lineuplab://auth?code="), loc)
        self.assertNotIn("sess-g", loc)                                             # the session itself never rides in the URL
        self.assertEqual(server._redeem_app_code(loc.split("code=", 1)[1]), "sess-g")


class PushEndpointTests(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(server.app)
        server.app.dependency_overrides[server.require_user] = lambda: {"id": 3}

    def tearDown(self):
        server.app.dependency_overrides.clear()

    def test_register_validates_and_saves(self):
        tok = "ab" * 32
        with mock.patch.object(server.db, "save_push_device") as s:
            self.assertEqual(self.c.post("/api/push/register", json={"token": tok, "environment": "sandbox"}).status_code, 200)
        s.assert_called_once_with(3, tok, "sandbox", True)
        for bad in ({"token": "not-hex!"}, {"token": tok, "environment": "prod"}):
            self.assertEqual(self.c.post("/api/push/register", json=bad).status_code, 400)

    def test_unregister_only_touches_this_account(self):
        with mock.patch.object(server.db, "delete_push_device") as d:
            self.assertEqual(self.c.post("/api/push/unregister", json={"token": "AB" * 32}).status_code, 200)
        d.assert_called_once_with("ab" * 32, 3)


class PushModuleTests(unittest.TestCase):
    def test_off_without_a_key(self):
        with mock.patch.object(push, "APNS_KEY_ID", None):
            self.assertFalse(push.configured())
            self.assertEqual(push.send({"token": "x"}, {}), "error")
            self.assertIsNone(push.start_reminder_loop(None, None))

    def test_reminder_skips_people_who_played(self):
        devices = [{"token": "a", "user_id": 1}, {"token": "b", "user_id": 2}, {"token": "c", "user_id": 3}]
        self.assertEqual([d["token"] for d in push.reminder_targets(devices, {2})], ["a", "c"])

    def test_payload_opens_the_game(self):
        p = push.payload("T", "B", url="/play", thread="daily-drive")
        self.assertEqual(p["url"], "/play")
        self.assertEqual(p["aps"]["alert"], {"title": "T", "body": "B"})

    def test_next_reminder_is_11am_eastern(self):
        now = dt.datetime(2026, 11, 17, 15, 0, tzinfo=dt.timezone.utc)            # 10:00 EST
        self.assertEqual(push.seconds_until_next_reminder(now), 3600)
        now = dt.datetime(2026, 11, 17, 17, 0, tzinfo=dt.timezone.utc)            # 12:00 EST -> tomorrow 11:00
        self.assertEqual(push.seconds_until_next_reminder(now), 23 * 3600)


class PagesAndInAppModeTests(unittest.TestCase):
    def test_support_page(self):
        c = TestClient(server.app)
        r = c.get("/support")
        self.assertEqual(r.status_code, 200)
        self.assertIn("lineuplabfootball@gmail.com", r.text)
        self.assertIn("Delete account", r.text)

    def test_privacy_policy_covers_the_app(self):
        p = _r("legal/PRIVACY_POLICY.md")
        self.assertIn("Sign in with Apple", p)
        self.assertIn("Push notification device token", p)

    def test_web_hides_its_navigation_inside_the_app(self):
        self.assertIn("LineupLabApp", _r("static/theme-boot.js"))
        self.assertIn("html.in-app #sidebar", _r("static/style.css"))
        self.assertIn("html.in-app .ll-nav", _r("static/play.css"))
        js = _r("static/app.js")
        self.assertIn("switchTab(requestedTab())", js)
        play = _r("static/play.js")
        self.assertIn('nativeCall("share", text)', play)
        self.assertIn('nativeCall("haptic"', play)

    def test_migration(self):
        sql = _r("migrations/20261117000000_push_devices.sql")
        self.assertIn("CREATE TABLE IF NOT EXISTS public.push_devices", sql)
        self.assertIn("ON DELETE CASCADE", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)


if __name__ == "__main__":
    unittest.main()
