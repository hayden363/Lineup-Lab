"""engine.scoring — custom league scoring.

The anchor is a ground-truth test: nflverse ships its own fantasy_points_ppr,
so the PPR preset run through compute_fantasy_points must reproduce it on every
row of every cached season. That's how the missing special-teams-TD term was
found (28 player-weeks of 2025 off by exactly -6), and it will catch any other
term that goes missing or gets double-counted.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import glob
import json
import os
import unittest

import numpy as np
import pandas as pd

from engine.scoring import PRESETS, ScoringSettings, apply_scoring, compute_fantasy_points
from engine.sleeper import scoring_from_sleeper

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _line(**stats):
    """One weekly stat row; every column not given is simply absent."""
    return pd.DataFrame([stats])


class GroundTruth(unittest.TestCase):
    def test_ppr_preset_reproduces_nflverse_on_every_cached_row(self):
        files = sorted(glob.glob(os.path.join(ROOT, "data_cache", "weekly_*.parquet")))
        if not files:
            self.skipTest("no cached weekly season in data_cache/")
        for path in files:
            wk = pd.read_parquet(path)
            ours = compute_fantasy_points(wk, ScoringSettings.from_preset("ppr"))
            theirs = wk["fantasy_points_ppr"].fillna(0)
            off = (ours - theirs).abs() > 0.011
            with self.subTest(season=os.path.basename(path)):
                self.assertEqual(int(off.sum()), 0,
                                 f"{int(off.sum())} rows differ from nflverse's own PPR column")


class Formula(unittest.TestCase):
    def test_hand_computed_line_including_a_return_td(self):
        # 300 pass yd (12) + 2 pass TD (8) - 1 INT (-2) + 20 rush yd (2)
        # - 1 lost fumble (-2) + 1 special-teams TD (6) = 24.0 under PPR.
        wk = _line(passing_yards=300, passing_tds=2, interceptions=1, rushing_yards=20,
                   rushing_fumbles_lost=1, special_teams_tds=1)
        self.assertAlmostEqual(compute_fantasy_points(wk, ScoringSettings.from_preset("ppr")).iloc[0], 24.0)

    def test_return_td_value_is_honoured(self):
        wk = _line(receptions=3, receiving_yards=40, special_teams_tds=1)
        full = compute_fantasy_points(wk, ScoringSettings.from_preset("ppr")).iloc[0]
        none = compute_fantasy_points(wk, ScoringSettings.from_dict({"return_td": 0})).iloc[0]
        self.assertAlmostEqual(full - none, 6.0)

    def test_fumble_recovery_tds_are_not_counted(self):
        # nflverse's PPR column doesn't count them; the real rows that have one
        # already match without it, so adding a term would break those rows.
        wk = _line(fumble_recovery_tds=1)
        self.assertEqual(compute_fantasy_points(wk, ScoringSettings.from_preset("ppr")).iloc[0], 0.0)

    def test_reception_value_is_the_only_preset_difference(self):
        wk = _line(receptions=10, receiving_yards=100)
        pts = {p: compute_fantasy_points(wk, ScoringSettings.from_preset(p)).iloc[0] for p in PRESETS}
        self.assertEqual((pts["standard"], pts["half_ppr"], pts["ppr"]), (10.0, 15.0, 20.0))

    def test_missing_columns_score_zero_and_stay_a_series(self):
        # The documented crash: a bare 0 fallback would turn the sum into a
        # plain number and .round(2) would fail on it.
        out = compute_fantasy_points(pd.DataFrame(index=[0, 1]), ScoringSettings())
        self.assertIsInstance(out, pd.Series)
        self.assertEqual(out.tolist(), [0.0, 0.0])

    def test_nan_stats_count_as_zero(self):
        wk = _line(passing_yards=np.nan, rushing_tds=1)
        self.assertEqual(compute_fantasy_points(wk, ScoringSettings()).iloc[0], 6.0)


class Settings(unittest.TestCase):
    def test_from_dict_ignores_unknown_keys_and_coerces_numbers(self):
        s = ScoringSettings.from_dict({"pass_td": "6", "not_a_setting": 99})
        self.assertEqual(s.pass_td, 6.0)
        self.assertFalse(hasattr(s, "not_a_setting"))

    def test_settings_saved_before_return_td_existed_default_to_six(self):
        old = {k: v for k, v in PRESETS["ppr"].items() if k != "return_td"}
        self.assertEqual(ScoringSettings.from_dict(old).return_td, 6.0)

    def test_unknown_preset_falls_back_to_ppr(self):
        self.assertEqual(ScoringSettings.from_preset("nope"), ScoringSettings.from_preset("ppr"))

    def test_sleeper_st_td_actually_maps_to_return_td(self):
        # Must use a value that differs from the default 6: both real leagues
        # set st_td to 6.0, so a check against them alone passes even when the
        # mapping is missing entirely (verified by removing it).
        self.assertEqual(scoring_from_sleeper({"st_td": 0}).return_td, 0.0)
        self.assertEqual(scoring_from_sleeper({"st_td": 4}).return_td, 4.0)

    def test_real_sleeper_leagues_map_their_special_teams_td(self):
        files = sorted(glob.glob(os.path.join(ROOT, "data_cache", "sleeper_league_*.json")))
        if not files:
            self.skipTest("no cached Sleeper league in data_cache/")
        for path in files:
            raw = json.load(open(path)).get("scoring_settings") or {}
            s = scoring_from_sleeper(raw)
            with self.subTest(league=os.path.basename(path)):
                if "st_td" in raw:
                    self.assertEqual(s.return_td, float(raw["st_td"]))
                if "pass_td" in raw:
                    self.assertEqual(s.pass_td, float(raw["pass_td"]))


class ApplyScoring(unittest.TestCase):
    def test_default_path_uses_nflverse_column_and_leaves_input_untouched(self):
        wk = pd.DataFrame({"fantasy_points_ppr": [12.3], "receptions": [5]})
        out, settings = apply_scoring(wk)
        self.assertEqual(out["fpts_active"].iloc[0], 12.3)
        self.assertNotIn("fpts_active", wk.columns)
        self.assertEqual(settings, ScoringSettings.from_preset("ppr"))


if __name__ == "__main__":
    unittest.main()
