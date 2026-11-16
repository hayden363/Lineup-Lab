"""engine.win_prob (matchup win probability) and its fitted variance params (engine/live_var_params.json). No network."""
import json
import math
import os
import unittest

from engine import myteam_live as ml, win_prob as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MathTests(unittest.TestCase):
    def test_even_matchup_is_a_coin_flip(self):
        self.assertAlmostEqual(W.win_probability(100, 50, 100, 50), 0.5)

    def test_matches_the_normal_cdf(self):
        # margin 10, combined SD sqrt(100) = 10 -> z = 1 -> 0.8413
        self.assertAlmostEqual(W.win_probability(110, 50, 100, 50), 0.8413447, places=6)
        self.assertAlmostEqual(W.win_probability(100, 50, 110, 50), 1 - 0.8413447, places=6)

    def test_complementary_from_each_side(self):
        a = W.win_probability(123.4, 80, 118.1, 95)
        b = W.win_probability(118.1, 95, 123.4, 80)
        self.assertAlmostEqual(a + b, 1.0)

    def test_no_variance_left_is_decided_by_the_scores_and_ties_are_half(self):
        self.assertEqual(W.win_probability(101, 0, 99.5, 0), 1.0)
        self.assertEqual(W.win_probability(99.5, 0, 101, 0), 0.0)
        self.assertEqual(W.win_probability(100, 0, 100, 0), 0.5)

    def test_missing_values_give_none_and_missing_variance_counts_as_zero(self):
        self.assertIsNone(W.win_probability(None, 10, 5, 10))
        self.assertIsNone(W.win_probability(5, 10, float("nan"), 10))
        self.assertEqual(W.win_probability(5, None, 4, None), 1.0)

    def test_more_variance_pulls_a_favorite_toward_a_coin_flip(self):
        self.assertGreater(W.win_probability(110, 10, 100, 10), W.win_probability(110, 400, 100, 400))


class SdTests(unittest.TestCase):
    def test_params_load_from_the_fitted_json(self):
        with open(os.path.join(ROOT, "engine", "live_var_params.json")) as f:
            raw = json.load(f)
        self.assertEqual(raw["fit_seasons"], [2023, 2024, 2025])
        for pos in ("QB", "RB", "WR", "TE", "ALL"):
            p = raw["sd"][pos]
            self.assertGreater(p["a"], 0)
            self.assertTrue(0 < p["b"] < 1)
        self.assertEqual(W.params()["WR"]["a"], raw["sd"]["WR"]["a"])

    def test_calibration_is_stored_and_two_sd_holds_on_the_held_out_season(self):
        with open(os.path.join(ROOT, "engine", "live_var_params.json")) as f:
            raw = json.load(f)
        for pos in ("QB", "RB", "WR", "TE"):
            c = raw["sd"][pos]["calib_test"]
            self.assertGreater(c["n"], 1000)
            self.assertTrue(0.93 <= c["within_2sd"] <= 0.97, (pos, c))

    def test_nothing_left_means_no_uncertainty(self):
        self.assertEqual(W.rog_sd("WR", 0), 0.0)
        self.assertEqual(W.rog_sd("WR", None), 0.0)
        self.assertEqual(W.rog_sd("WR", -3), 0.0)

    def test_sd_grows_with_expected_remaining_points(self):
        self.assertLess(W.rog_sd("WR", 3), W.rog_sd("WR", 12))

    def test_k_def_and_unknown_positions_use_the_agnostic_fit(self):
        allp = W.params()["ALL"]
        for pos in ("K", "DEF", None, "XYZ"):
            self.assertAlmostEqual(W.rog_sd(pos, 8.0), max(allp["floor"], allp["a"] * 8.0 ** allp["b"]))


class TeamTests(unittest.TestCase):
    def team(self, rows):
        return {"players": [{"is_starter": True, "position": pos, "PROJ": proj, "final": fin} for pos, proj, fin in rows]
                + [{"is_starter": False, "position": "WR", "PROJ": 99.0, "final": False}]}

    def test_pregame_bench_is_ignored_and_equal_teams_are_even(self):
        t = self.team([("QB", 20, False), ("RB", 15, False)])
        self.assertAlmostEqual(W.pregame_win_prob(t, t), 0.5)

    def test_pregame_favorite_is_above_half(self):
        self.assertGreater(W.pregame_win_prob(self.team([("QB", 25, False)]), self.team([("QB", 15, False)])), 0.5)

    def test_a_finished_week_is_100_or_0(self):
        a, b = self.team([("QB", 21.0, True)]), self.team([("QB", 18.0, True)])
        self.assertEqual(W.pregame_win_prob(a, b), 1.0)
        self.assertEqual(W.pregame_win_prob(b, a), 0.0)
        self.assertEqual(W.pregame_win_prob(a, a), 0.5)

    def test_no_opponent_is_none(self):
        self.assertIsNone(W.pregame_win_prob(self.team([("QB", 20, False)]), None))


class LiveTests(unittest.TestCase):
    def test_compose_win_prob_goes_to_one_when_every_game_is_over_and_i_lead(self):
        def team(rid, pts):
            return {"roster_id": rid, "starters": [{"player_id": f"p{rid}", "raw_id": f"r{rid}", "position": "WR", "team": "SEA",
                                                      "proj": 10.0, "settled": False, "on_bye": False}]}
        base = {"week": 11, "live_week": 11, "platform": "sleeper", "my_team": team(1, 0), "opponent": team(2, 0)}
        g = [{"game_id": "x", "week": 11, "kickoff": "2026-11-16T18:00:00Z", "state": "post", "period": 4, "display_clock": "0:00",
              "status_detail": "", "home": {"abbr": "SEA", "score": 20}, "away": {"abbr": "SF", "score": 10}}]
        r = ml.compose(base, g, {"source": "sleeper", "by_roster": {1: {"r1": 14.0}, 2: {"r2": 9.0}}}, now=0)
        self.assertEqual(r["win_prob"], 1.0)
        r2 = ml.compose(base, g, {"source": "sleeper", "by_roster": {1: {"r1": 9.0}, 2: {"r2": 14.0}}}, now=0)
        self.assertEqual(r2["win_prob"], 0.0)

    def test_pregame_live_and_halftime_probabilities_are_proper(self):
        def team(rid):
            return {"roster_id": rid, "starters": [{"player_id": f"p{rid}", "raw_id": f"r{rid}", "position": "WR", "team": "SEA" if rid == 1 else "SF",
                                                      "proj": 10.0, "settled": False, "on_bye": False}]}
        base = {"week": 11, "live_week": 11, "platform": "sleeper", "my_team": team(1), "opponent": team(2)}

        def game(state, period, clock):
            return [{"game_id": "x", "week": 11, "kickoff": "2026-11-16T18:00:00Z", "state": state, "period": period, "display_clock": clock,
                     "status_detail": "", "home": {"abbr": "SEA", "score": 10}, "away": {"abbr": "SF", "score": 10}}]
        pre = ml.compose(base, game("pre", 0, None), {"source": "sleeper", "by_roster": {}}, now=0)["win_prob"]
        self.assertAlmostEqual(pre, 0.5)
        lead = ml.compose(base, game("in", 3, "10:00"), {"source": "sleeper", "by_roster": {1: {"r1": 12.0}, 2: {"r2": 2.0}}}, now=0)["win_prob"]
        self.assertGreater(lead, 0.8)


if __name__ == "__main__":
    unittest.main()
