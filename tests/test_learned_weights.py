import json
import os
import unittest

import numpy as np
import pandas as pd

import weight_tuner as T
from engine import metrics as M


class LearnedWeightsFileTest(unittest.TestCase):
    """engine/learned_weights.json is committed so production scores with it. These guard its shape and sanity."""

    @classmethod
    def setUpClass(cls):
        with open(M.LEARNED_WEIGHTS_PATH) as f:
            cls.data = json.load(f)
        cls.w = cls.data["weights"]

    def test_lives_in_the_repo_not_the_ignored_cache(self):
        self.assertTrue(M.LEARNED_WEIGHTS_PATH.endswith(os.path.join("engine", "learned_weights.json")))
        self.assertEqual(T.LEARNED_WEIGHTS_PATH, M.LEARNED_WEIGHTS_PATH)

    def test_only_positions_that_beat_hand_picked_out_of_sample_are_overridden(self):
        self.assertEqual(set(self.w), {"QB", "RB", "TE"})        # WR learned weights did not beat hand-picked held-out

    def test_every_metric_is_a_real_one_and_no_sign_is_flipped(self):
        for pos, weights in self.w.items():
            for metric, value in weights.items():
                self.assertIn(metric, M._DEFAULT_WEIGHTS[pos], (pos, metric))
                self.assertGreaterEqual(value * M._DEFAULT_WEIGHTS[pos][metric], 0, (pos, metric))

    def test_total_weight_stays_near_the_hand_picked_total(self):
        for pos, weights in self.w.items():
            merged = M.WEIGHTS[pos]
            self.assertAlmostEqual(sum(abs(v) for v in merged.values()),
                                   sum(abs(v) for v in M._DEFAULT_WEIGHTS[pos].values()), delta=2.0, msg=pos)

    def test_app_uses_the_learned_weights_and_wr_keeps_hand_picked(self):
        self.assertEqual(M.WEIGHTS["RB"]["touches_per_game"], self.w["RB"]["touches_per_game"])
        self.assertEqual(M.WEIGHTS["WR"], M._DEFAULT_WEIGHTS["WR"])
        self.assertEqual(M.WEIGHTS["QB"]["dakota"], M._DEFAULT_WEIGHTS["QB"]["dakota"])   # no history to learn it from

    def test_volume_now_outweighs_efficiency_for_rb(self):
        w = M.WEIGHTS["RB"]
        self.assertGreater(w["touches_per_game"], w["yards_per_carry"])


class TunerTest(unittest.TestCase):
    def frame(self, n=80):
        rng = np.random.default_rng(1)
        df = pd.DataFrame({c: rng.normal(size=n) for c in M._DEFAULT_WEIGHTS["QB"]})
        df["dakota"] = np.nan                                  # not in the historical weekly files
        df["target_fpts_per_game"] = 10 + 3 * df["yards_per_attempt"] + rng.normal(size=n)
        return df

    def test_a_metric_with_no_history_is_not_a_regression_column(self):
        self.assertNotIn("dakota", T._usable_features("QB", self.frame()))

    def test_qb_regression_no_longer_learns_nothing(self):
        learned = T._fit("QB", [self.frame()])
        self.assertGreater(learned["yards_per_attempt"], 0)
        self.assertNotIn("dakota", learned)

    def test_wrong_sign_coefficients_are_zeroed_not_flipped(self):
        df = self.frame()
        df["completion_pct"] = df["yards_per_attempt"] * -1 + np.random.default_rng(2).normal(size=len(df)) * 0.1
        learned = T._fit("QB", [df])
        self.assertEqual(learned["completion_pct"], 0.0)       # hand-picked sign is +, data said -
        self.assertTrue(all(v * M._DEFAULT_WEIGHTS["QB"][k] >= 0 for k, v in learned.items()))


if __name__ == "__main__":
    unittest.main()
