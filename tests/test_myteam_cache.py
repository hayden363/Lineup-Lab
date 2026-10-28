"""My Team is computed once per few seconds however many panels ask for it at once."""
import threading
import time
import unittest
from unittest import mock

import server

ACTIVE = {"platform": "sleeper", "league_id": "L1", "roster_id": 1}
USER = {"id": 7, "username": "t"}


class MyTeamCacheTests(unittest.TestCase):
    def setUp(self):
        server._MYTEAM_CACHE.clear()
        self.addCleanup(server._MYTEAM_CACHE.clear)
        self.calls = []

        def fake(league, roster, scoring=None, week=None):
            self.calls.append(week)
            time.sleep(0.05)
            return {"my_team": {"players": [{"player_id": "a"}]}, "nfl_week": week or 8}
        self.patches = [mock.patch.object(server.db, "get_active_team", return_value=ACTIVE), mock.patch.object(server, "_effective_scoring", side_effect=lambda s, u: s),
                        mock.patch.object(server.tools, "my_team", side_effect=fake)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_second_call_within_the_window_reuses_the_result(self):
        server._load_my_team(USER, None, None)
        server._load_my_team(USER, None, None)
        self.assertEqual(len(self.calls), 1)

    def test_different_weeks_and_scoring_are_separate_entries(self):
        server._load_my_team(USER, None, None)
        server._load_my_team(USER, 9, None)
        server._load_my_team(USER, None, {"reception": 0.5})
        self.assertEqual(len(self.calls), 3)

    def test_refresh_recomputes_and_replaces_the_entry(self):
        server._load_my_team(USER, None, None)
        server._load_my_team(USER, None, None, refresh=True)
        server._load_my_team(USER, None, None)
        self.assertEqual(len(self.calls), 2)

    def test_the_entry_expires(self):
        server._load_my_team(USER, None, None)
        for k in list(server._MYTEAM_CACHE):
            ts, a, r = server._MYTEAM_CACHE[k]
            server._MYTEAM_CACHE[k] = (ts - server.MYTEAM_TTL - 1, a, r)
        server._load_my_team(USER, None, None)
        self.assertEqual(len(self.calls), 2)

    def test_simultaneous_requests_share_one_computation(self):
        out = []
        ts = [threading.Thread(target=lambda: out.append(server._load_my_team(USER, None, None))) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(out), 5)

    def test_callers_cannot_change_each_others_copy(self):
        _, r1 = server._load_my_team(USER, None, None)
        r1["my_team"]["players"].append({"player_id": "zzz"})
        _, r2 = server._load_my_team(USER, None, None)
        self.assertEqual(len(r2["my_team"]["players"]), 1)

    def test_a_failure_is_not_cached(self):
        with mock.patch.object(server.tools, "my_team", side_effect=RuntimeError("sleeper down")):
            with self.assertRaises(Exception):
                server._load_my_team(USER, None, None)
        server._load_my_team(USER, None, None)
        self.assertEqual(len(self.calls), 1)

    def test_users_never_share_a_cached_roster(self):
        server._load_my_team(USER, None, None)
        server._load_my_team({"id": 8, "username": "other"}, None, None)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
