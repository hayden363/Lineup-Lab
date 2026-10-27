import unittest

import numpy as np
import pandas as pd

from engine import kdef_model as M


def sched(rows):
    return pd.DataFrame(rows, columns=["week", "home_team", "away_team", "home_score", "spread_line", "total_line", "roof"])


class GameContextTest(unittest.TestCase):
    S = sched([(5, "DET", "GB", np.nan, 3.0, 50.0, "dome"),        # DET favored by 3, total 50
               (6, "CHI", "DET", np.nan, 7.0, 44.0, "outdoors"),   # DET is the away underdog
               (7, "DET", "MIN", np.nan, np.nan, np.nan, "dome")])  # no line posted yet

    def test_home_and_away_implied_totals(self):
        home = M.game_context(self.S, "DET", 5)
        self.assertEqual((home["itt"], home["itt_opp"], home["indoor"]), (26.5, 23.5, 1.0))
        away = M.game_context(self.S, "DET", 6)
        self.assertEqual((away["itt"], away["itt_opp"], away["indoor"]), (18.5, 25.5, 0.0))

    def test_no_line_is_none_not_a_guess(self):
        c = M.game_context(self.S, "DET", 7)
        self.assertIsNone(c["itt"]); self.assertIsNone(c["itt_opp"])

    def test_default_week_is_the_next_unplayed_game(self):
        s = self.S.copy(); s.loc[0, "home_score"] = 20.0
        self.assertEqual(M.game_context(s, "DET")["itt_opp"], 25.5)   # week 5 is played, so week 6
        self.assertIsNone(M.game_context(self.S, "BUF", 5))


class DefenseProjectionTest(unittest.TestCase):
    def test_average_defense_in_an_average_game_projects_the_league_average(self):
        self.assertAlmostEqual(M.defense_projection(6.2, 6.2, 22.0), 6.2, delta=0.1)

    def test_a_weak_offense_is_worth_more_than_a_strong_one(self):
        lo, hi = M.defense_projection(6.2, 6.2, 16.0), M.defense_projection(6.2, 6.2, 28.0)
        self.assertGreater(lo, 6.2); self.assertLess(hi, 6.2)
        self.assertGreater(lo - hi, 4.0)     # the market is the big lever for a defense

    def test_a_better_defense_projects_a_little_higher_not_a_lot(self):
        good, avg = M.defense_projection(9.0, 6.2, 22.0), M.defense_projection(6.2, 6.2, 22.0)
        self.assertGreater(good, avg); self.assertLess(good - avg, 1.0)

    def test_no_line_means_neutral(self):
        self.assertEqual(M.defense_projection(7.0, 6.2, None), M.defense_projection(7.0, 6.2, 22.0))

    def test_scale_free_so_custom_scoring_just_rescales(self):
        a = M.defense_projection(7.0, 6.2, 18.0)
        b = M.defense_projection(14.0, 12.4, 18.0)       # a league that pays everything double
        self.assertAlmostEqual(b, 2 * a, delta=0.15)

    def test_freak_lines_are_clamped(self):
        self.assertEqual(M.defense_projection(6.2, 6.2, 80.0), M.defense_projection(6.2, 6.2, 31.0))
        self.assertGreaterEqual(M.defense_projection(6.2, 6.2, 0.0), 0.0)

    def test_bad_pool_falls_back_to_the_rate(self):
        self.assertEqual(M.defense_projection(5.5, 0, 20.0), 5.5)


class KickerProjectionTest(unittest.TestCase):
    def test_average_kicker_in_an_average_spot(self):
        self.assertAlmostEqual(M.kicker_projection(8.2, 8.2, 22.0, 0.33), 8.2, delta=0.2)

    def test_better_offense_and_a_dome_help(self):
        base = M.kicker_projection(8.2, 8.2, 22.0, 0.0)
        self.assertGreater(M.kicker_projection(8.2, 8.2, 28.0, 0.0), base)
        self.assertGreater(M.kicker_projection(8.2, 8.2, 22.0, 1.0), base)

    def test_kicker_history_barely_matters(self):
        self.assertLess(M.kicker_projection(11.0, 8.2, 22.0, 0.0) - M.kicker_projection(8.2, 8.2, 22.0, 0.0), 0.6)

    def test_no_context_is_neutral(self):
        self.assertEqual(M.kicker_projection(9.0, 8.2), M.kicker_projection(9.0, 8.2, 22.0, 0.33))


if __name__ == "__main__":
    unittest.main()
