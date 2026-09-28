"""engine.metrics.form_adjustment — the FORM read built on the recency math.

tests/test_form_math.py pins the two helpers; this pins the behaviour layered
on top of them, each of which a refactor could quietly undo: the +/-40% cap,
the mid-season team-change reset, and the EPA luck-check blend (which, when
play quality is flat, must land at exactly half the points-only read).

Note: analysis/form_backtest.py found FORM doesn't measurably improve
next-week accuracy on 2025. These tests pin what it DOES, not whether it
should — so a deliberate change to FORM shows up here as intended.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import os
import unittest

import numpy as np
import pandas as pd

from engine.metrics import form_adjustment

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _wk(player_id, points, team="AAA", position="WR", start_week=1, teams=None):
    """Weekly rows for one player: `points` in week order; `teams` optionally
    gives the team per week (for a mid-season trade)."""
    teams = teams or [team] * len(points)
    return pd.DataFrame({
        "player_id": player_id, "position": position,
        "week": range(start_week, start_week + len(points)),
        "recent_team": teams, "fpts_active": points,
    })


def _epa(player_id, values, start_week=1):
    idx = pd.MultiIndex.from_tuples([(player_id, start_week + i) for i in range(len(values))],
                                    names=["player_id", "week"])
    return pd.Series(values, index=idx, dtype=float)


class FormAdjustment(unittest.TestCase):
    def test_flat_player_reads_zero(self):
        self.assertEqual(form_adjustment(_wk("p1", [12.0] * 8), "WR")["p1"], 0.0)

    def test_recent_surge_positive_and_slump_negative(self):
        up = form_adjustment(_wk("p1", [8.0] * 6 + [16.0, 20.0]), "WR")["p1"]
        down = form_adjustment(_wk("p1", [16.0] * 6 + [8.0, 4.0]), "WR")["p1"]
        self.assertGreater(up, 0.0)
        self.assertLess(down, 0.0)

    def test_capped_at_plus_minus_forty(self):
        self.assertEqual(form_adjustment(_wk("p1", [1.0] * 7 + [100.0]), "WR")["p1"], 40.0)
        # A sustained collapse (four 20s, then four zeros) is about -50% raw and
        # must floor at -40. Note one bad week after seven great ones is NOT
        # enough: the earlier games still dominate the weighted average and it
        # reads about -16.7%, which is the intended behaviour, not a cap miss.
        self.assertEqual(form_adjustment(_wk("p1", [20.0] * 4 + [0.0] * 4), "WR")["p1"], -40.0)
        self.assertAlmostEqual(form_adjustment(_wk("p1", [100.0] * 7 + [0.5]), "WR")["p1"], -16.7, delta=0.1)

    def test_team_change_resets_the_baseline(self):
        # 20 a game on the old team, a flat 10 a game since the trade. Against
        # the whole season that reads as a slump; against the current team's
        # own games there's no trend at all, which is what FORM is meant to say.
        wk = _wk("p1", [20.0] * 4 + [10.0] * 4, teams=["AAA"] * 4 + ["BBB"] * 4)
        self.assertEqual(form_adjustment(wk, "WR")["p1"], 0.0)

    def test_only_the_requested_position_is_read(self):
        wk = pd.concat([_wk("wr", [10.0] * 8), _wk("rb", [10.0] * 8, position="RB")])
        self.assertEqual(list(form_adjustment(wk, "WR").index), ["wr"])


class EpaLuckCheck(unittest.TestCase):
    POINTS = [8.0] * 6 + [16.0, 20.0]          # a clear recent surge

    def test_flat_play_quality_halves_a_points_surge(self):
        # Constant EPA has zero spread, so its swing is 0 and the 50/50 blend
        # leaves exactly half the points-only read.
        points_only = form_adjustment(_wk("p1", self.POINTS), "WR")["p1"]
        blended = form_adjustment(_wk("p1", self.POINTS), "WR", weekly_epa=_epa("p1", [0.1] * 8))["p1"]
        self.assertAlmostEqual(blended, points_only / 2, delta=0.1)

    def test_agreeing_play_quality_keeps_the_read_positive(self):
        epa = _epa("p1", [0.0] * 6 + [0.3, 0.4])
        blended = form_adjustment(_wk("p1", self.POINTS), "WR", weekly_epa=epa)["p1"]
        self.assertGreater(blended, 0.0)

    def test_under_two_epa_games_falls_back_to_points_only(self):
        points_only = form_adjustment(_wk("p1", self.POINTS), "WR")["p1"]
        one_game = form_adjustment(_wk("p1", self.POINTS), "WR", weekly_epa=_epa("p1", [0.2], start_week=8))["p1"]
        self.assertEqual(one_game, points_only)

    def test_player_missing_from_epa_is_points_only(self):
        points_only = form_adjustment(_wk("p1", self.POINTS), "WR")["p1"]
        other = form_adjustment(_wk("p1", self.POINTS), "WR", weekly_epa=_epa("someone_else", [0.1, 0.2, 0.3]))["p1"]
        self.assertEqual(other, points_only)


class RealSeason(unittest.TestCase):
    def test_real_2025_reads_are_bounded_and_one_per_player(self):
        path = os.path.join(ROOT, "data_cache", "weekly_2025.parquet")
        if not os.path.exists(path):
            self.skipTest("weekly_2025 not cached")
        from engine.scoring import apply_scoring
        wk, _ = apply_scoring(pd.read_parquet(path))
        for pos in ("QB", "RB", "WR", "TE"):
            with self.subTest(position=pos):
                form = form_adjustment(wk, pos)
                self.assertTrue(form.index.is_unique)
                self.assertTrue(bool(np.all((form >= -40.0) & (form <= 40.0))))
                self.assertEqual(len(form), wk.loc[wk["position"] == pos, "player_id"].nunique())


if __name__ == "__main__":
    unittest.main()
