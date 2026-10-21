"""ESPN trade finder inputs: ESPN slot labels, records and rosters feed the same
trade engine Sleeper leagues use."""

import unittest
from types import SimpleNamespace as NS

import pandas as pd

from engine import trade_engine as T


class LeagueShapeTests(unittest.TestCase):
    def test_espn_flex_labels_count_as_flex(self):
        s = T.league_shape(["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE", "WR/TE", "D/ST", "K"], 10)
        self.assertEqual(s["slots"]["FLEX"], 2)
        self.assertEqual((s["slots"]["QB"], s["slots"]["RB"], s["slots"]["WR"], s["slots"]["TE"]), (1, 2, 2, 1))

    def test_op_is_superflex(self):
        self.assertEqual(T.league_shape(["QB", "OP", "RB", "WR"], 12)["slots"]["SUPERFLEX"], 1)

    def test_sleeper_labels_unchanged(self):
        s = T.league_shape(["QB", "RB", "FLEX", "SUPER_FLEX", "BN"], 12)
        self.assertEqual((s["slots"]["FLEX"], s["slots"]["SUPERFLEX"]), (1, 1))


class RecordTests(unittest.TestCase):
    def test_record_shape_matches_sleepers(self):
        r = T.record_espn(NS(wins=5, losses=2, ties=1))
        self.assertEqual((r["text"], r["pct"]), ("5-2-1", 0.688))

    def test_no_games_has_no_percentage(self):
        self.assertIsNone(T.record_espn(NS(wins=0, losses=0, ties=0))["pct"])


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.pool = pd.DataFrame({
            "player_display_name": ["A Back", "B Wide", "C Tight"], "position": ["RB", "WR", "TE"],
            "recent_team": ["AAA", "BBB", "CCC"], "headshot_url": [None] * 3, "value": [15.0, 12.0, 8.0],
            "injury_status": [None, "Questionable", None],
        }, index=["g1", "g2", "g3"])
        self.values = {g: {"trade": 50.0, "tier": 3, "ecr": None} for g in self.pool.index}
        self.cw = {"101": "g1", "102": "g2", "103": "g3"}

    def _team(self, players):
        return NS(team_id=7, team_name=" The Team ", wins=2, losses=1, ties=0,
                  roster=[NS(playerId=pid, lineupSlot=slot) for pid, slot in players])

    def test_builds_valued_rosters_keyed_by_team_id(self):
        league = NS(teams=[self._team([(101, "RB"), (102, "BE")])])
        out = T.build_rosters_espn(league, self.pool, self.values, self.cw)
        self.assertEqual(out[7]["name"], "The Team")
        self.assertEqual([p["player_id"] for p in out[7]["players"]], ["g1", "g2"])
        self.assertEqual(out[7]["players"][1]["injury_status"], "Questionable")
        self.assertEqual(out[7]["record"]["text"], "2-1")

    def test_ir_players_are_left_out(self):
        league = NS(teams=[self._team([(101, "RB"), (102, "IR")])])
        self.assertEqual([p["player_id"] for p in T.build_rosters_espn(league, self.pool, self.values, self.cw)[7]["players"]], ["g1"])

    def test_unknown_ids_and_unvalued_players_are_skipped(self):
        league = NS(teams=[self._team([(999, "BE"), (103, "BE")])])
        self.values.pop("g3")
        self.assertEqual(T.build_rosters_espn(league, self.pool, self.values, self.cw)[7]["players"], [])


if __name__ == "__main__":
    unittest.main()
