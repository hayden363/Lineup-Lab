import unittest

import numpy as np
import pandas as pd

from engine import aging


class AgingTests(unittest.TestCase):
    def test_backs_decline_earlier_than_receivers_and_quarterbacks_last(self):
        self.assertLess(aging.delta("RB", 29), aging.delta("WR", 29))
        self.assertLess(aging.delta("WR", 29), aging.delta("QB", 29))
        self.assertEqual(aging.delta("QB", 29), 0.0)

    def test_young_players_progress_and_old_players_regress(self):
        for pos in ("QB", "RB", "WR", "TE"):
            self.assertGreater(aging.delta(pos, 22), 0)
            self.assertLess(aging.delta(pos, 36), 0)

    def test_curve_is_flat_through_the_prime_and_never_runs_away(self):
        self.assertEqual(aging.delta("WR", 26), 0.0)
        self.assertLessEqual(abs(aging.delta("RB", 45)), aging.MAX_DELTA)
        self.assertLessEqual(abs(aging.delta("WR", 15)), aging.MAX_DELTA)

    def test_unknown_age_or_position_changes_nothing(self):
        self.assertEqual(aging.delta("WR", None), 0.0)
        self.assertEqual(aging.delta("WR", float("nan")), 0.0)
        self.assertEqual(aging.delta("K", 30), 0.0)

    def test_the_adjustment_only_applies_to_the_part_of_the_rate_that_came_from_history(self):
        ages = pd.Series({"a": 30.0, "b": 30.0, "c": 30.0})
        hw = pd.Series({"a": 0.0, "b": 0.5, "c": 1.0})
        m = aging.multiplier("RB", ages, hw)
        self.assertEqual(m["a"], 1.0)                      # all this season: he is already this age
        self.assertLess(m["c"], m["b"])
        self.assertAlmostEqual(m["c"] - 1.0, aging.delta("RB", 30), places=6)
        self.assertAlmostEqual(m["b"] - 1.0, 0.5 * aging.delta("RB", 30), places=6)

    def test_missing_ages_are_neutral(self):
        m = aging.multiplier("WR", pd.Series({"a": np.nan}), pd.Series({"a": 1.0}))
        self.assertEqual(m["a"], 1.0)

    def test_ages_come_from_birthdates_on_the_season_start(self):
        cw = pd.DataFrame({"gsis_id": ["x", "y", "z"], "birthdate": ["2000-09-01", "bad", None]})
        a = aging.ages_from(cw, season=2026)
        self.assertAlmostEqual(a["x"], 26.0, places=1)
        self.assertNotIn("y", a.index)
        self.assertNotIn("z", a.index)


if __name__ == "__main__":
    unittest.main()


class BoardWiringTests(unittest.TestCase):
    def _rb_board(self, age):
        from unittest import mock
        from engine import board
        real = board.load_bundle()
        b = board._build_board_uncached("RB", real["season"], None, None)
        with mock.patch.object(aging, "ages", lambda season: pd.Series(age, index=b.index)):
            b["rate"] = board.shrunk_rate(b, "RB", None, real["season"])
        return b

    def test_an_older_roster_projects_lower_than_a_young_one_where_history_exists(self):
        old, young = self._rb_board(33.0), self._rb_board(22.0)
        self.assertTrue((old["age_factor"] <= 1.0).all())
        self.assertTrue((young["age_factor"] >= 1.0).all())
        self.assertGreater(float((young["rate"] - old["rate"]).max()), 0.0)
        self.assertTrue((young["rate"] >= old["rate"] - 1e-9).all())
