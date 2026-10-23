import unittest
from unittest import mock

import numpy as np
import pandas as pd

from engine import history, projmodel


def _wk(rows):
    return pd.DataFrame(rows, columns=["player_id", "position", "week", "targets", "carries", "fpts_active"])


class PredictTests(unittest.TestCase):
    COEF = {"WR": np.array([1.0, 0.25, 0.15, 0.30, 0.20])}
    PPO = {"WR": (2.0, 0.5)}

    def _model(self, prior):
        return {"coef": self.COEF, "ppo": self.PPO, "prior": pd.Series(prior, dtype=float)}

    def test_matches_hand_calculation(self):
        wk = _wk([("a", "WR", w, 8, 0, pts) for w, pts in enumerate([10, 20, 12, 18, 14], 1)])
        with mock.patch.object(projmodel, "model", return_value=self._model({"a": 16.0})):
            out = projmodel.predict("WR", wk, None, 2026)
        ppg, l4 = 74 / 5, np.mean([20, 12, 18, 14])
        opp4 = 2.0 * 8
        expect = 1.0 + 0.25 * ppg + 0.15 * l4 + 0.30 * opp4 + 0.20 * 16.0
        self.assertAlmostEqual(float(out.loc["a", "rate"]), expect, places=6)

    def test_no_last_season_uses_his_season_average(self):
        wk = _wk([("a", "WR", w, 6, 0, 12.0) for w in (1, 2, 3)])
        with mock.patch.object(projmodel, "model", return_value=self._model({})):
            out = projmodel.predict("WR", wk, None, 2026)
        self.assertAlmostEqual(float(out.loc["a", "rate"]), 1.0 + 0.25 * 12 + 0.15 * 12 + 0.30 * 12 + 0.20 * 12, places=6)
        self.assertEqual(float(out.loc["a", "history_weight"]), 0.0)

    def test_history_weight_is_the_prior_share_of_the_weights(self):
        wk = _wk([("a", "WR", w, 6, 0, 12.0) for w in (1, 2, 3)])
        with mock.patch.object(projmodel, "model", return_value=self._model({"a": 15.0})):
            out = projmodel.predict("WR", wk, None, 2026)
        self.assertAlmostEqual(float(out.loc["a", "history_weight"]), 0.20 / 0.90, places=6)

    def test_thin_samples_are_left_to_the_old_formula(self):
        wk = _wk([("a", "WR", 1, 6, 0, 12.0), ("a", "WR", 2, 6, 0, 12.0)])
        with mock.patch.object(projmodel, "model", return_value=self._model({})):
            self.assertIsNone(projmodel.predict("WR", wk, None, 2026))

    def test_no_model_means_no_prediction(self):
        wk = _wk([("a", "WR", w, 6, 0, 12.0) for w in (1, 2, 3)])
        with mock.patch.object(projmodel, "model", return_value=None):
            self.assertIsNone(projmodel.predict("WR", wk, None, 2026))

    def test_never_negative(self):
        wk = _wk([("a", "WR", w, 0, 0, 0.0) for w in (1, 2, 3)])
        coef = {"WR": np.array([-5.0, 0.2, 0.2, 0.2, 0.2])}
        with mock.patch.object(projmodel, "model", return_value={"coef": coef, "ppo": self.PPO, "prior": pd.Series(dtype=float)}):
            self.assertEqual(float(projmodel.predict("WR", wk, None, 2026).loc["a", "rate"]), 0.0)


@unittest.skipUnless(history.available() and history._frames()["skill"]["season"].nunique() >= 3,
                     "needs three seasons of history_data")
class BacktestTests(unittest.TestCase):
    """The evidence for replacing the shrink-to-position-average formula,
    rerun on every test run so a change to the model can't quietly lose it."""

    @classmethod
    def setUpClass(cls):
        cls.bt = projmodel.backtest()

    def test_beats_the_old_formula(self):
        self.assertLess(self.bt["rmse"], self.bt["old"]["rmse"])
        self.assertGreater(self.bt["r2"], self.bt["old"]["r2"])

    def test_unbiased_overall(self):
        self.assertLess(abs(self.bt["bias"]), 0.25)

    def test_top_tier_is_calibrated(self):
        top = self.bt["top"]
        self.assertGreater(top["n"], 100)
        self.assertLess(abs(top["predicted"] - top["actual"]), 1.0)

    def test_old_formula_under_projected_the_top_tier(self):
        old = self.bt["old"]["top"]
        self.assertGreater(old["actual"] - old["predicted"], 0.5)

    def test_model_fits_for_every_position(self):
        m = projmodel.model(None, int(history._frames()["skill"]["season"].max()) + 1)
        self.assertEqual(set(m["coef"]), set(projmodel.POSITIONS))
        for pos, c in m["coef"].items():
            self.assertGreater(c[1:].sum(), 0.5)      # a real signal, not noise
            self.assertLess(c[1:].sum(), 1.3)         # and not an amplifier


if __name__ == "__main__":
    unittest.main()
