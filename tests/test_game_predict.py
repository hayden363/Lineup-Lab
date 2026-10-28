"""engine.game_predict: Lineup Lab's own pick for a game, from each team's scoring and defense, blended with the market."""
import unittest

from engine import game_predict as G


def team(pf, pa, n=6):
    return {"games": n, "pf_pg": pf, "pa_pg": pa}


class PredictTest(unittest.TestCase):
    def test_a_better_team_at_home_is_favored_and_scores_come_from_both_sides_of_the_ball(self):
        p = G.predict(home=team(28, 17), away=team(20, 24), market=None)
        self.assertGreater(p["home_score"], p["away_score"])
        self.assertGreater(p["home_win_pct"], 60)
        self.assertEqual(p["home_win_pct"] + p["away_win_pct"], 100)
        self.assertEqual(p["pick"], "home")

    def test_evenly_matched_teams_give_the_home_side_the_small_home_field_edge(self):
        p = G.predict(home=team(22.5, 22.5), away=team(22.5, 22.5), market=None)
        self.assertGreater(p["home_score"], p["away_score"])
        self.assertTrue(50 < p["home_win_pct"] < 60)

    def test_the_market_pulls_the_pick_toward_the_betting_line(self):
        no_mkt = G.predict(home=team(22.5, 22.5), away=team(22.5, 22.5), market=None)
        with_mkt = G.predict(home=team(22.5, 22.5), away=team(22.5, 22.5), market={"home_implied": 28.0, "away_implied": 17.0})
        self.assertGreater(with_mkt["home_win_pct"], no_mkt["home_win_pct"])
        self.assertTrue(with_mkt["used_market"])
        self.assertFalse(no_mkt["used_market"])

    def test_small_samples_are_pulled_toward_the_league_average(self):
        hot_small = G.predict(home=team(40, 10, 1), away=team(22.5, 22.5, 8), market=None)
        hot_big = G.predict(home=team(40, 10, 10), away=team(22.5, 22.5, 8), market=None)
        self.assertLess(hot_small["home_score"], hot_big["home_score"])

    def test_no_data_gives_no_prediction(self):
        self.assertIsNone(G.predict(home=None, away=team(20, 20), market=None))
        self.assertIsNone(G.predict(home=team(20, 20, 0), away=team(20, 20, 0), market=None))

    def test_the_edge_against_the_market_is_reported_when_there_is_a_line(self):
        p = G.predict(home=team(30, 15), away=team(18, 26), market={"home_implied": 24.0, "away_implied": 21.0})
        self.assertIn("vs_market", p)
        self.assertGreater(p["vs_market"]["margin_edge"], 0)          # we like the home side more than the market does

    def test_scores_are_rounded_and_the_total_is_the_sum(self):
        p = G.predict(home=team(24.3, 20.1), away=team(21.7, 23.9), market=None)
        self.assertEqual(p["total"], round(p["home_score"] + p["away_score"], 1))
        self.assertEqual(p["margin"], round(p["home_score"] - p["away_score"], 1))


if __name__ == "__main__":
    unittest.main()
