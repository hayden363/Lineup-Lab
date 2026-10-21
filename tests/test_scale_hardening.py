"""Stage-1 scale hardening: bounded scoring caches and public cache headers."""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import board
from engine.scoring import PRESETS


def _custom(i):
    sc = dict(PRESETS["ppr"])
    sc["pass_td"] = 5 + i * 0.25
    return sc


class CacheCap(unittest.TestCase):
    def setUp(self):
        self.cache = {}
        self.sk = board._board_key_scoring

    def _put(self, scoring, pos="QB"):
        board._cache_put(self.cache, (pos, 2026, board._scoring_cache_key(scoring)), object(), self.sk)

    def test_custom_variants_are_bounded_and_oldest_dropped(self):
        with mock.patch.object(board, "MAX_CUSTOM_SCORINGS", 3):
            for i in range(6):
                for pos in ("QB", "RB"):
                    self._put(_custom(i), pos)
        keys = {k[2] for k in self.cache}
        self.assertEqual(len(keys), 3)
        self.assertIn(board._scoring_cache_key(_custom(5)), keys)       # newest kept
        self.assertNotIn(board._scoring_cache_key(_custom(0)), keys)    # oldest gone
        # a variant is dropped for every position at once
        self.assertEqual(len(self.cache), 6)

    def test_default_and_presets_never_evicted(self):
        with mock.patch.object(board, "MAX_CUSTOM_SCORINGS", 1):
            self._put(None)
            for p in PRESETS.values():
                self._put(p)
            for i in range(5):
                self._put(_custom(i))
        keys = {k[2] for k in self.cache}
        self.assertIn(None, keys)
        for p in PRESETS.values():
            self.assertIn(board._scoring_cache_key(p), keys)
        self.assertEqual(len([k for k in keys if k not in board._protected_scoring_keys()]), 1)

    def test_recently_read_variant_survives(self):
        with mock.patch.object(board, "MAX_CUSTOM_SCORINGS", 2):
            self._put(_custom(1))
            self._put(_custom(2))
            board._cache_get(self.cache, ("QB", 2026, board._scoring_cache_key(_custom(1))), self.sk)  # touch #1
            self._put(_custom(3))
        keys = {k[2] for k in self.cache}
        self.assertIn(board._scoring_cache_key(_custom(1)), keys)
        self.assertNotIn(board._scoring_cache_key(_custom(2)), keys)

    def test_pvs_cache_uses_same_bound(self):
        cache = {}
        with mock.patch.object(board, "MAX_CUSTOM_SCORINGS", 2):
            for i in range(5):
                board._cache_put(cache, (2026, board._scoring_cache_key(_custom(i))), {}, board._pvs_key_scoring)
        self.assertEqual(len(cache), 2)


class PublicCacheHeaders(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_signed_out_board_is_publicly_cacheable(self):
        r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), server.PUBLIC_CACHE_CONTROL)
        self.assertIn("cookie", r.headers.get("vary", "").lower())

    def test_session_cookie_gets_no_caching_header(self):
        c = TestClient(server.app)
        c.cookies.set(server.SESSION_COOKIE, "anything")
        with mock.patch.object(server.db, "get_user_by_session", return_value={"id": 1, "email": "a@b.c"}):
            r = c.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("public", r.headers.get("cache-control", ""))
        self.assertIn("cookie", r.headers.get("vary", "").lower())

    def test_private_and_write_endpoints_untouched(self):
        for path in ("/healthz", "/api/auth/me", "/api/teams", "/api/waivers/engine"):
            r = self.client.get(path)
            self.assertNotIn("public", r.headers.get("cache-control", ""), path)
        r = self.client.post("/api/auth/logout")
        self.assertNotIn("public", r.headers.get("cache-control", ""))

    def test_errors_are_not_cached(self):
        r = self.client.get("/api/board?pos=XX")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("public", r.headers.get("cache-control", ""))

    def test_player_subpaths_not_matched(self):
        self.assertTrue(server._PUBLIC_CACHE_PLAYER.match("/api/player/00-0039139"))
        self.assertFalse(server._PUBLIC_CACHE_PLAYER.match("/api/player/00-0039139/news"))


if __name__ == "__main__":
    unittest.main()
