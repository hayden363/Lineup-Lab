"""engine.advanced.weekly_epa anchored to nflverse's own published EPA columns,
plus the explosive-play thresholds in the season-level *_advanced() functions.

What is pinned:
  * Real-data anchors (cached 2025 play-by-play and weekly stats, skipped if a
    parquet is absent): mean EPA per play times play count equals the weekly
    rushing_epa / receiving_epa column on every RB/WR/TE player-week.
  * The output shape: MultiIndex (player_id, week), Series named "epa", only
    rows whose play_type matches the position.
  * The explosive thresholds: pass >= 20 yards (QB, WR/TE), run >= 10 yards.

Deliberately NOT asserted: QB weekly_epa against passing_epa. It matches only
547 of 658 player-weeks and the cause is unverified (dropping sacks gives
122/656). Season row counts against official carries/targets also differ by
1-3 for some players; cause unverified.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import os
import unittest

import pandas as pd

from engine.advanced import qb_advanced, rb_advanced, weekly_epa, wr_advanced

_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_cache")
PBP_PATH = os.path.join(_CACHE, "pbp_2025.parquet")
WEEKLY_PATH = os.path.join(_CACHE, "weekly_2025.parquet")


@unittest.skipUnless(
    os.path.exists(PBP_PATH) and os.path.exists(WEEKLY_PATH),
    "data_cache/pbp_2025.parquet or weekly_2025.parquet not present",
)
class RealDataAnchors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pbp = pd.read_parquet(PBP_PATH)
        cls.weekly = pd.read_parquet(WEEKLY_PATH)

    def _anchor(self, position, col, play_type, weekly_col, expected_rows):
        epa = weekly_epa(self.pbp, position).reset_index()
        counts = (
            self.pbp[self.pbp["play_type"] == play_type]
            .groupby([col, "week"]).size().rename("plays").reset_index()
            .rename(columns={col: "player_id"})
        )
        merged = epa.merge(counts, on=["player_id", "week"])
        merged["total"] = merged["epa"] * merged["plays"]
        official = self.weekly[self.weekly["position"] == position][["player_id", "week", weekly_col]]
        joined = merged.merge(official, on=["player_id", "week"])
        # row count first, so a silent join shrink fails
        self.assertEqual(len(joined), expected_rows)
        off = (joined["total"] - joined[weekly_col]).abs()
        self.assertTrue((off <= 0.01).all(), f"max difference {off.max():.4f}")

    def test_rb_matches_rushing_epa(self):
        self._anchor("RB", "rusher_player_id", "run", "rushing_epa", 1332)

    def test_wr_matches_receiving_epa(self):
        self._anchor("WR", "receiver_player_id", "pass", "receiving_epa", 2200)

    def test_te_matches_receiving_epa(self):
        self._anchor("TE", "receiver_player_id", "pass", "receiving_epa", 1172)


def _plays(rows):
    """Minimal play-by-play frame; unused columns get neutral values."""
    base = {
        "play_type": "pass", "week": 1, "epa": 0.0, "yards_gained": 0,
        "passer_player_id": "QB1", "rusher_player_id": "RB1", "receiver_player_id": "WR1",
        "sack": 0, "qb_hit": 0, "complete_pass": 1,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _empty_ngs(*cols):
    return pd.DataFrame({c: [] for c in ("player_gsis_id",) + cols})


class Shape(unittest.TestCase):
    def setUp(self):
        self.pbp = _plays([
            {"receiver_player_id": "A", "week": 1, "epa": 1.0},
            {"receiver_player_id": "A", "week": 1, "epa": 0.0},
            {"receiver_player_id": "B", "week": 1, "epa": 2.0},
            {"receiver_player_id": "A", "week": 2, "epa": -1.0},
            {"receiver_player_id": "A", "week": 1, "epa": 9.0, "play_type": "run"},
        ])

    def test_index_and_series_names(self):
        out = weekly_epa(self.pbp, "WR")
        self.assertEqual(list(out.index.names), ["player_id", "week"])
        self.assertEqual(out.name, "epa")

    def test_values_are_group_means_and_other_play_types_excluded(self):
        out = weekly_epa(self.pbp, "WR")
        self.assertEqual(out[("A", 1)], 0.5)   # the run play (epa 9.0) is not counted
        self.assertEqual(out[("B", 1)], 2.0)
        self.assertEqual(out[("A", 2)], -1.0)
        self.assertEqual(len(out), 3)


class ExplosiveThresholds(unittest.TestCase):
    def test_qb_explosive_pass_at_20_yards(self):
        pbp = _plays([{"yards_gained": 19}, {"yards_gained": 20}])
        out = qb_advanced(pbp, _empty_ngs("avg_time_to_throw", "aggressiveness", "completion_percentage_above_expectation"))
        self.assertEqual(out.loc["QB1", "explosive_pass_rate"], 50)

    def test_rb_explosive_run_at_10_yards(self):
        pbp = _plays([{"play_type": "run", "yards_gained": 9}, {"play_type": "run", "yards_gained": 10}])
        out = rb_advanced(pbp, _empty_ngs("rush_yards_over_expected_per_att", "efficiency", "percent_attempts_gte_eight_defenders"))
        self.assertEqual(out.loc["RB1", "explosive_run_rate"], 50)

    def test_receiver_explosive_rec_at_20_yards(self):
        pbp = _plays([{"yards_gained": 19}, {"yards_gained": 20}])
        out = wr_advanced(pbp, _empty_ngs("avg_separation", "avg_cushion", "avg_yac_above_expectation"))
        self.assertEqual(out.loc["WR1", "explosive_rec_rate"], 50)


if __name__ == "__main__":
    unittest.main()
