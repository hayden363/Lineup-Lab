"""engine.board.load_bundle must run the cold load once even when several
requests hit a cold process together. Two parallel loads held two copies of
every raw table and got the 512 MB Render instance OOM-killed (2026-10-16)."""
import threading
import time
import unittest
from unittest import mock

from engine import board


class BundleLockTests(unittest.TestCase):
    def setUp(self):
        board._BUNDLE_CACHE.clear()
        self.addCleanup(board._BUNDLE_CACHE.clear)
        self.calls = 0

    def fake_load(self, season, key, force):
        self.calls += 1
        time.sleep(0.2)              # long enough for every thread to pile up
        bundle = {"season": season}
        board._BUNDLE_CACHE[key] = bundle
        return bundle

    def test_concurrent_cold_calls_load_once_and_share_the_bundle(self):
        results = []
        with mock.patch.object(board, "_load_bundle_locked", side_effect=self.fake_load):
            threads = [threading.Thread(target=lambda: results.append(board.load_bundle(2026))) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(r is results[0] for r in results))

    def test_warm_cache_skips_the_load(self):
        board._BUNDLE_CACHE[2026] = {"season": 2026}
        with mock.patch.object(board, "_load_bundle_locked", side_effect=self.fake_load):
            board.load_bundle(2026)
        self.assertEqual(self.calls, 0)

    def test_force_reloads_even_when_warm(self):
        board._BUNDLE_CACHE[2026] = {"season": 2026, "old": True}
        with mock.patch.object(board, "_load_bundle_locked", side_effect=self.fake_load):
            out = board.load_bundle(2026, force=True)
        self.assertEqual(self.calls, 1)
        self.assertNotIn("old", out)


if __name__ == "__main__":
    unittest.main()
