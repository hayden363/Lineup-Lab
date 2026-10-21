import sys
import types
import unittest
from unittest import mock

from engine import espn


class LeagueCacheTests(unittest.TestCase):
    def setUp(self):
        espn._LEAGUE_CACHE.clear()
        self.calls = []
        outer = self

        class FakeLeague:
            def __init__(self, **kw):
                outer.calls.append(kw)
                if kw["league_id"] == 13:
                    raise RuntimeError("down")

        mod = types.ModuleType("espn_api.football")
        mod.League = FakeLeague
        self.p = mock.patch.dict(sys.modules, {"espn_api": types.ModuleType("espn_api"), "espn_api.football": mod})
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_second_call_reuses_league(self):
        a = espn.get_league("1", 2026)
        b = espn.get_league("1", 2026)
        self.assertIs(a, b)
        self.assertEqual(len(self.calls), 1)

    def test_different_credentials_not_shared(self):
        espn.get_league("1", 2026)
        espn.get_league("1", 2026, espn_s2="a", swid="b")
        self.assertEqual(len(self.calls), 2)

    def test_failure_not_cached(self):
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                espn.get_league("13", 2026)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
