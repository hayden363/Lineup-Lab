"""projmodel._training_rows was rewritten for speed (pandas group operations instead of a Python function per
player-season). It must give EXACTLY the same table as the original, which is kept here as the reference."""
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from engine import projmodel as pm


def reference_training_rows(df, ppo):
    """The original implementation, unchanged."""
    d = df.copy()
    d["opp"] = [ppo[p][0] * t + ppo[p][1] * c if p in ppo else 0.0
                for p, t, c in zip(d["position"], d["targets"], d["carries"])]
    g = d.groupby(["player_id", "season"], sort=False)
    d["n"] = g.cumcount()
    d["ppg"] = g["fpts_active"].transform(lambda s: s.shift(1).expanding().mean())
    d["l4"] = g["fpts_active"].transform(lambda s: s.shift(1).rolling(pm.RECENT, min_periods=1).mean())
    d["opp4"] = g["opp"].transform(lambda s: s.shift(1).rolling(pm.RECENT, min_periods=1).mean())
    d["opp_ppg"] = g["opp"].transform(lambda s: s.shift(1).expanding().mean())
    per = d.groupby(["player_id", "season"])["fpts_active"].agg(["mean", "count"])
    per = per[per["count"] >= pm.MIN_PRIOR_GAMES]["mean"]
    prior = pd.Series([per.get((p, s - 1), np.nan) for p, s in zip(d["player_id"], d["season"])], index=d.index)
    d["has_prior"] = prior.notna()
    d["prior"] = prior.fillna(d["ppg"])
    first = d["season"].min()
    return d[(d["n"] >= pm.MIN_GAMES) & (d["season"] > first)]


def synthetic(seed=0, players=60):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(players):
        pos = ["QB", "RB", "WR", "TE"][i % 4]
        for season in (2022, 2023, 2024, 2025):
            if season == 2023 and i % 7 == 0:
                continue                                  # a missed season: no prior for the next one
            games = int(rng.choice([1, 2, 4, 5, 6, 9, 14, 17]))   # includes 1-game groups and the 6-game prior bar
            for week in range(1, games + 1):
                rows.append({"player_id": f"p{i:03d}", "position": pos, "season": season, "week": week,
                             "targets": float(rng.integers(0, 14)) if i % 5 else np.nan,
                             "carries": float(rng.integers(0, 25)), "fpts_active": float(rng.normal(11, 6))})
    df = pd.DataFrame(rows).sort_values(["player_id", "season", "week"]).reset_index(drop=True)
    df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
    return df


PPO = {"QB": (0.0, 0.3), "RB": (0.9, 1.1), "WR": (1.7, 0.2)}   # TE deliberately missing: the "not in ppo" branch


class TrainingRowsMatchReference(unittest.TestCase):
    def check(self, df, ppo=PPO):
        assert_frame_equal(pm._training_rows(df, ppo), reference_training_rows(df, ppo), check_exact=True)

    def test_synthetic_many_shapes(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                self.check(synthetic(seed))

    def test_a_non_default_index_is_preserved(self):
        df = synthetic(3)
        df.index = df.index * 3 + 10                      # unique but not 0..n-1
        got = pm._training_rows(df, PPO)
        assert_frame_equal(got, reference_training_rows(df, PPO), check_exact=True)
        self.assertTrue(set(got.index) <= set(df.index))

    def test_float32_points_like_the_real_history_match_and_stay_quiet(self):
        """Real fpts_active is float32. The prior column must still be float64 and raise no numpy deprecation."""
        import warnings
        df = synthetic(2)
        df["fpts_active"] = df["fpts_active"].astype("float32")
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            got = pm._training_rows(df, PPO)
        assert_frame_equal(got, reference_training_rows(df, PPO), check_exact=True)
        self.assertEqual(str(got["prior"].dtype), "float64")

    def test_float_season_and_missing_keys_match(self):
        df = synthetic(4)
        df["season"] = df["season"].astype(float)
        df.loc[df.index[::97], "fpts_active"] = np.nan
        self.check(df)

    def test_input_is_not_modified(self):
        df = synthetic(1); before = df.copy()
        pm._training_rows(df, PPO)
        assert_frame_equal(df, before, check_exact=True)

    def test_real_history_under_default_and_a_custom_scoring(self):
        from engine import history, board
        from engine.scoring import ScoringSettings
        if not history.available():
            self.skipTest("no history on disk")
        cur = board.load_bundle()["season"]
        customs = [None, ScoringSettings(reception=0.5, pass_td=6.0)]
        for sc in customs:
            with self.subTest(scoring=sc):
                df = pm._scored_history(sc, cur)
                if df.empty:
                    self.skipTest("empty history")
                self.check(df, pm._opportunity_values(df))


if __name__ == "__main__":
    unittest.main()
