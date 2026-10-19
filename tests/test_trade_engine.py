import unittest

import pandas as pd

from engine import trade_engine as T

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def P(pid, pos, value, trade):
    return {"player_id": pid, "name": pid, "position": pos, "value": value, "trade": trade, "injury_status": None}


class ValueTest(unittest.TestCase):
    def test_curve_is_steep_and_never_zero(self):
        self.assertEqual(T.rank_value(1), 100.0)
        self.assertGreater(T.rank_value(1) - T.rank_value(10), T.rank_value(100) - T.rank_value(110))
        self.assertGreater(T.rank_value(300), 0)

    def test_package_discount_means_two_mids_dont_buy_a_star(self):
        self.assertLess(T.package_value([55, 55]), 100)
        self.assertEqual(T.package_value([80]), 80)

    def test_league_shape(self):
        shape = T.league_shape(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN"], 10)
        self.assertEqual(shape["slots"]["SUPERFLEX"], 1)
        self.assertEqual(shape["teams"], 10)

    def test_trade_values_rank_qbs_down_in_one_qb_league(self):
        pool = pd.DataFrame([
            {"player_display_name": "Q1", "position": "QB", "value": 22.0},
            {"player_display_name": "Q2", "position": "QB", "value": 20.0},
            {"player_display_name": "W1", "position": "WR", "value": 18.0},
            {"player_display_name": "W2", "position": "WR", "value": 8.0},
        ], index=["q1", "q2", "w1", "w2"])
        vals = T.trade_values(pool, T.league_shape(["QB", "WR"], 12), rostered_ids={"q1", "w1"}, ecr={})
        # Q2 sits on waivers at 20, so Q1 is only +2 over free; W1 is +10.
        self.assertLess(vals["q1"]["rank"], 99)
        self.assertGreater(vals["w1"]["trade"], vals["q1"]["trade"])


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.mine = [P("q", "QB", 20, 60), P("r1", "RB", 15, 70), P("r2", "RB", 6, 20), P("w1", "WR", 16, 75),
                     P("w2", "WR", 14, 65), P("w3", "WR", 13, 55), P("t", "TE", 5, 10), P("w4", "WR", 12, 40)]
        self.theirs = [P("Q", "QB", 19, 55), P("R1", "RB", 16, 72), P("R2", "RB", 14, 62), P("W1", "WR", 9, 30),
                       P("W2", "WR", 8, 25), P("T", "TE", 17, 50), P("T2", "TE", 10, 50), P("R3", "RB", 12, 22)]

    def run_eval(self, give, get):
        return T.evaluate(give, get, self.mine, self.theirs, SLOTS, len(self.mine), len(self.theirs),
                          T.strength(self.mine, SLOTS), T.strength(self.theirs, SLOTS))

    def test_lopsided_star_grab_rejected(self):
        self.assertIsNone(self.run_eval([P("t", "TE", 5, 10)], [self.theirs[1]]))

    def test_fair_mutual_upgrade_accepted(self):
        # My WR3 (13) for their bench TE (10): my TE goes 5 -> 10 and my flex
        # only 13 -> 12 (+4); their WR2 goes 8 -> 13 (+5), their TE stays 17.
        res = self.run_eval([self.mine[5]], [self.theirs[6]])
        self.assertIsNotNone(res)
        self.assertGreater(res["my_gain"], 0.5)
        self.assertGreaterEqual(res["their_gain"], 0)

    def test_two_for_one_forces_a_drop(self):
        roster, dropped = T.after_trade(self.theirs, {"R1"}, [self.mine[3], self.mine[5]], len(self.theirs))
        self.assertEqual(len(roster), len(self.theirs))
        self.assertEqual([p["player_id"] for p in dropped], ["R3"])  # lowest trade value goes


class FindTest(unittest.TestCase):
    def test_spreads_suggestions_and_requires_shopped_player(self):
        mine = [P("q", "QB", 20, 60), P("r1", "RB", 15, 70), P("r2", "RB", 6, 20), P("w1", "WR", 16, 75),
                P("w2", "WR", 14, 65), P("w3", "WR", 13, 55), P("t", "TE", 5, 10)]
        rosters = {1: {"name": "Me", "players": mine}}
        for rid in range(2, 6):
            rosters[rid] = {"name": f"T{rid}", "players": [P(f"Q{rid}", "QB", 19, 55), P(f"R{rid}", "RB", 14, 60),
                                                           P(f"S{rid}", "RB", 12, 50), P(f"W{rid}", "WR", 9, 30),
                                                           P(f"X{rid}", "WR", 8, 25), P(f"T{rid}", "TE", 12, 52)]}
        out = T.find_trades(rosters, 1, SLOTS, None, None, max_suggestions=10)
        per_opp = {}
        for s in out:
            per_opp[s["opponent_roster_id"]] = per_opp.get(s["opponent_roster_id"], 0) + 1
            self.assertIn("you", s["reasons"])
        self.assertTrue(all(n <= 2 for n in per_opp.values()))
        shopped = T.find_trades(rosters, 1, SLOTS, None, None, give_ids=["w3"])
        self.assertTrue(all(any(p["player_id"] == "w3" for p in s["you_give"]) for s in shopped))


if __name__ == "__main__":
    unittest.main()
