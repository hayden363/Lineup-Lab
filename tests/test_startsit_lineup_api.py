import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server


def _result():
    mk = lambda pid, pos, proj, starter, slot: {  # noqa: E731
        "player_id": pid, "player_display_name": pid.upper(), "position": pos, "recent_team": "AAA",
        "PROJ": proj, "is_starter": starter, "slot": slot, "headshot_url": None, "injury_status": None}
    return {"nfl_week": 6, "league_name": "L", "my_team": {"players": [
        mk("q1", "QB", 20, True, "QB"), mk("w1", "WR", 8, True, "WR"), mk("w2", "WR", 15, False, None)]}}


def _outcomes(mean):
    return {"mean": mean, "p10": mean * .5, "p50": mean, "p90": mean * 1.5}


class LineupAdvisorApiTests(unittest.TestCase):
    def setUp(self):
        server.app.dependency_overrides[server.require_user] = lambda: {"id": 1}
        self.client = TestClient(server.app)

    def tearDown(self):
        server.app.dependency_overrides.clear()

    def test_swaps_bench_player_in(self):
        ss = {"players": [{"player_id": pid, "outcomes": _outcomes(m)} for pid, m in (("q1", 20), ("w1", 8), ("w2", 15))]}
        with mock.patch.object(server, "_load_my_team", return_value=({}, _result())), \
             mock.patch.object(server, "_effective_scoring", return_value=None), \
             mock.patch.object(server.tools, "start_sit", return_value=ss), \
             mock.patch.object(server, "load_bundle", return_value={"schedule": None}), \
             mock.patch.object(server.lineup_advisor.locks, "kickoff", return_value=1), \
             mock.patch.object(server.lineup_advisor.locks, "is_locked", return_value=False):
            r = self.client.get("/api/startsit/lineup?mode=balanced")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual([c["in"] for c in d["changes"]], ["w2"])
        self.assertEqual(d["drops"][0]["player_id"], "w1")
        self.assertGreater(d["best_mean"], d["current_mean"])
        self.assertEqual([x["player_id"] for x in d["lineup"]], ["q1", "w2"])

    def test_rejects_unknown_mode(self):
        self.assertEqual(self.client.get("/api/startsit/lineup?mode=wild").status_code, 422)


if __name__ == "__main__":
    unittest.main()
