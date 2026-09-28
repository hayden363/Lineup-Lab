"""engine.defense factor maths and engine.matchup.matchup_tag.

What is pinned:
  * The direction of composite_multiplier for negative-weight metrics
    (int_rate, sack_rate): a defense forcing MORE than average is a tougher
    matchup and must pull the blend down. A sign-inversion bug was once real
    in this module; the guard needs no I/O.
  * Real-data anchors on the cached 2025 play-by-play (skipped if the parquet
    is absent): 32 defenses, every pass play counted, EPA factors clipped to
    0.7-1.3, and each position's league-average composite centred on 1.0.
  * matchup_tag's boundaries: strictly above 1.10 is soft, strictly below
    0.90 is tough, the endpoints themselves are average.

Per-position composite min/max ranges are deliberately not asserted; they
move with any legitimate re-tune.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import os
import unittest
from unittest import mock

import pandas as pd

from engine import defense
from engine.defense import (
    build_defense_profile,
    composite_multiplier,
    league_average_composite,
    league_relative_factors,
)
from engine.matchup import matchup_tag

PBP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data_cache", "pbp_2025.parquet",
)


class CompositeSignGuard(unittest.TestCase):
    """A sign-inversion bug was once real in this module. This pins the
    direction for negative-weight metrics: a defense forcing more INTs must
    read as a TOUGHER matchup. Pure in-memory check, no data files."""

    WEIGHTS = {"QB": {"int_rate": -10, "yards_per_attempt": 10}}

    def _composite(self, int_factor):
        factors = pd.DataFrame(
            {"int_rate_forced": [int_factor], "ypa_allowed": [1.0]}, index=["DEF"])
        with mock.patch.dict(defense.WEIGHTS, self.WEIGHTS, clear=True):
            return composite_multiplier("QB", "DEF", factors)

    def test_defense_forcing_more_ints_is_a_tougher_matchup(self):
        # effective factors [2 - 1.3, 1.0] -> (10*0.7 + 10*1.0) / 20
        self.assertAlmostEqual(self._composite(1.3), 0.85, places=6)

    def test_defense_forcing_fewer_ints_is_a_softer_matchup(self):
        # effective factors [2 - 0.7, 1.0] -> (10*1.3 + 10*1.0) / 20
        self.assertAlmostEqual(self._composite(0.7), 1.15, places=6)


@unittest.skipUnless(os.path.exists(PBP_PATH), "data_cache/pbp_2025.parquet not present")
class PbpOnlyAnchors(unittest.TestCase):
    """Real-data anchors that use build_defense_profile(pbp) ALONE. board.py
    also joins build_ngs_defense_profile before league_relative_factors, so
    these pin the play-by-play layer only, not the factors the live board
    actually uses."""

    @classmethod
    def setUpClass(cls):
        cls.pbp = pd.read_parquet(PBP_PATH)
        cls.profile = build_defense_profile(cls.pbp)
        cls.factors, _ = league_relative_factors(cls.profile)

    def test_one_profile_row_per_defense(self):
        self.assertEqual(len(self.profile), 32)

    def test_every_pass_play_is_attributed_to_a_defense(self):
        n_pass = int((self.pbp["play_type"] == "pass").sum())
        self.assertEqual(int(self.profile["pass_plays"].sum()), n_pass)
        self.assertEqual(n_pass, 19737)

    def test_epa_pass_factor_is_clipped_to_band(self):
        col = self.factors["epa_per_pass_allowed"]
        self.assertEqual(col.min(), 0.7)
        self.assertEqual(col.max(), 1.3)

    def test_league_average_composite_is_centred_on_one(self):
        for pos in ("QB", "RB", "WR", "TE"):
            with self.subTest(pos=pos):
                self.assertAlmostEqual(
                    league_average_composite(pos, self.factors), 1.0, places=3)

    def test_nyj_forced_zero_interceptions(self):
        # NYJ really forced 0 INTs in the cached 2025 data, so the ratio
        # factor bottoms out at exactly 0.0.
        self.assertEqual(self.factors.loc["NYJ", "int_rate_forced"], 0.0)


class MatchupTagBoundaries(unittest.TestCase):
    def test_upper_boundary(self):
        self.assertEqual(matchup_tag(1.10), "average")
        self.assertEqual(matchup_tag(1.101), "soft")

    def test_lower_boundary(self):
        self.assertEqual(matchup_tag(0.90), "average")
        self.assertEqual(matchup_tag(0.899), "tough")


if __name__ == "__main__":
    unittest.main()
