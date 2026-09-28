"""Tests for the recency/confidence math behind FORM (engine/metrics.py).

Stdlib unittest on purpose: pytest is not a dependency of this project, and the
point of the first test suite is to run with nothing installed beyond what the
app already needs. Run it with:

    .venv/bin/python -m unittest discover -s tests -v

These cover `_recency_weighted_pct` and `_recency_weighted_zscore` because they
are the pure, deterministic core of the FORM read — everything above them needs
a real weekly DataFrame, so they are the part that can be pinned exactly. The
expected numbers below are derived from the documented formula by hand, not
copied from a run, so a refactor that quietly changes the weighting will fail
here instead of silently moving every player's PROJ.
"""

import math
import unittest

import numpy as np

from engine.metrics import _recency_weighted_pct, _recency_weighted_zscore


class RecencyWeightedPct(unittest.TestCase):
    def test_empty_is_neutral(self):
        self.assertEqual(_recency_weighted_pct(np.array([]), 2.5, 8), 0.0)

    def test_flat_performer_is_neutral(self):
        # Every week identical: the recency-weighted average equals the season
        # average, so there is no "form" to report regardless of weighting.
        vals = np.array([10.0] * 6)
        self.assertAlmostEqual(_recency_weighted_pct(vals, 2.5, 8), 0.0, places=12)

    def test_zero_season_average_is_neutral_not_a_division_error(self):
        # A player who scored nothing must not blow up the ratio.
        self.assertEqual(_recency_weighted_pct(np.array([0.0, 0.0, 0.0]), 2.5, 8), 0.0)

    def test_mean_of_zero_from_cancelling_values_is_neutral(self):
        # Mean is exactly 0 here without every value being 0 — still guarded.
        self.assertEqual(_recency_weighted_pct(np.array([-5.0, 5.0]), 2.5, 8), 0.0)

    def test_recent_surge_reads_positive_and_recent_slump_negative(self):
        rising = np.array([5.0, 5.0, 5.0, 15.0])
        falling = np.array([15.0, 5.0, 5.0, 5.0])
        self.assertGreater(_recency_weighted_pct(rising, 2.5, 8), 0.0)
        self.assertLess(_recency_weighted_pct(falling, 2.5, 8), 0.0)

    def test_newest_game_carries_more_weight_than_oldest(self):
        # Same multiset of scores, opposite order: the late-surge version must
        # read strictly higher. This is what pins the weight ORDER — a reversed
        # `np.arange` would still pass the sign tests above but fail this.
        late = np.array([4.0, 6.0, 8.0, 20.0])
        early = np.array([20.0, 8.0, 6.0, 4.0])
        self.assertGreater(
            _recency_weighted_pct(late, 2.5, 8),
            _recency_weighted_pct(early, 2.5, 8),
        )

    def test_exact_value_for_a_hand_computed_case(self):
        # halflife=1 -> decay=0.5. values [0, 2]: season_avg=1.0,
        # weights oldest->newest = [0.5, 1.0], weighted_avg = 2/1.5 = 4/3,
        # raw_pct = (4/3 - 1)/1 = 1/3, confidence = 2/8 = 0.25.
        expected = (1.0 / 3.0) * 0.25
        got = _recency_weighted_pct(np.array([0.0, 2.0]), 1.0, 8)
        self.assertAlmostEqual(got, expected, places=12)

    def test_confidence_shrinks_a_short_sample(self):
        # Identical shape, different sample size: the 3-game read must be
        # damped relative to the 8-game one. An early-season hot streak is not
        # yet evidence.
        short = np.array([5.0, 5.0, 15.0])
        long = np.array([5.0] * 6 + [5.0, 15.0])
        self.assertLess(
            _recency_weighted_pct(short, 2.5, 8),
            _recency_weighted_pct(long, 2.5, 8),
        )

    def test_confidence_is_capped_at_full(self):
        # Past min_games_full_confidence the multiplier must stop at 1.0, so a
        # long season cannot amplify the read beyond the raw percentage.
        vals = np.array([5.0] * 19 + [15.0])
        raw_only = _recency_weighted_pct(vals, 2.5, 1)   # confidence pinned to 1.0
        at_eight = _recency_weighted_pct(vals, 2.5, 8)   # 20/8 -> also capped
        self.assertAlmostEqual(raw_only, at_eight, places=12)


class RecencyWeightedZscore(unittest.TestCase):
    def test_single_game_is_neutral(self):
        # Needs at least two games for a standard deviation to mean anything.
        self.assertEqual(_recency_weighted_zscore(np.array([3.0]), 2.5, 8), 0.0)

    def test_empty_is_neutral(self):
        self.assertEqual(_recency_weighted_zscore(np.array([]), 2.5, 8), 0.0)

    def test_zero_variance_is_neutral_not_a_division_error(self):
        self.assertEqual(_recency_weighted_zscore(np.array([2.0] * 5), 2.5, 8), 0.0)

    def test_negative_values_still_produce_a_signed_read(self):
        # EPA crosses zero, which is the whole reason this is a z-score rather
        # than a percent-of-baseline. An all-negative series must still work.
        improving = np.array([-0.4, -0.3, -0.2, -0.05])
        worsening = np.array([-0.05, -0.2, -0.3, -0.4])
        self.assertGreater(_recency_weighted_zscore(improving, 2.5, 8), 0.0)
        self.assertLess(_recency_weighted_zscore(worsening, 2.5, 8), 0.0)

    def test_exact_value_for_a_hand_computed_case(self):
        # halflife=1 -> decay=0.5. values [0, 2]: mean=1.0,
        # population std (numpy default ddof=0) = 1.0,
        # weighted_avg = 4/3, z = (4/3 - 1)/1 = 1/3, confidence = 2/8 = 0.25.
        expected = (1.0 / 3.0) * 0.25
        got = _recency_weighted_zscore(np.array([0.0, 2.0]), 1.0, 8)
        self.assertAlmostEqual(got, expected, places=12)

    def test_result_is_finite_for_a_realistic_epa_series(self):
        vals = np.array([-0.12, 0.31, 0.04, -0.22, 0.18, 0.09])
        self.assertTrue(math.isfinite(_recency_weighted_zscore(vals, 2.5, 8)))


if __name__ == "__main__":
    unittest.main()
