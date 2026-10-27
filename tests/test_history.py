"""History: scoring under the viewer's league settings, the blend, spread, and
head-to-head. Uses small hand-built frames so it does not depend on the
shipped history_data files, plus a few checks that read them."""

import unittest

import pandas as pd

from engine import history as H
from engine import ros_projection as R


def _career(rows):
    return pd.DataFrame(rows, columns=["id", "h", "ppg", "cv", "games", "seasons"]).set_index("id")


class BlendTests(unittest.TestCase):
    def setUp(self):
        self.cur = pd.Series({"vet": 20.0, "rookie": 20.0})
        self.n = pd.Series({"vet": 5, "rookie": 5})

    def test_no_history_matches_the_old_formula(self):
        rate, share = H.blend(self.cur, self.n, _career([]), pool_mean=10.0)
        self.assertAlmostEqual(rate["rookie"], (5 * 20.0 + 3 * 10.0) / 8)
        self.assertEqual(share["rookie"], 0.0)

    def test_history_pulls_toward_his_own_career(self):
        career = _career([("vet", 30.0, 12.0, 0.4, 32, 3)])
        rate, share = H.blend(self.cur, self.n, career, pool_mean=10.0)
        no_hist, _ = H.blend(self.cur, self.n, _career([]), pool_mean=10.0)
        self.assertLess(rate["vet"], 20.0)
        self.assertLess(rate["vet"], no_hist["vet"])             # pulled harder than the pool prior alone
        self.assertGreater(rate["vet"], 11.8)                      # but still above his career-based prior
        self.assertGreater(share["vet"], 0.3)

    def test_more_history_means_more_weight(self):
        short = _career([("vet", 6.0, 12.0, 0.4, 8, 1)])
        full = _career([("vet", 30.0, 12.0, 0.4, 32, 3)])
        _, s_short = H.blend(self.cur, self.n, short, 10.0)
        _, s_full = H.blend(self.cur, self.n, full, 10.0)
        self.assertGreater(s_full["vet"], s_short["vet"])

    def test_more_games_this_season_means_less_history(self):
        career = _career([("vet", 30.0, 12.0, 0.4, 32, 3)])
        _, early = H.blend(self.cur, pd.Series({"vet": 3, "rookie": 3}), career, 10.0)
        _, late = H.blend(self.cur, pd.Series({"vet": 16, "rookie": 16}), career, 10.0)
        self.assertGreater(early["vet"], late["vet"])

    def test_kicker_and_defense_lean_less_on_history(self):
        career = _career([("vet", 30.0, 12.0, 0.4, 32, 3)])
        _, skill = H.blend(self.cur, self.n, career, 10.0)
        _, kick = H.blend(self.cur, self.n, career, 10.0, hist_k=H.K_HIST_K)
        self.assertLess(kick["vet"], skill["vet"])


class SpreadTests(unittest.TestCase):
    def test_blend_cv_weights_by_games(self):
        self.assertAlmostEqual(H.blend_cv(0.5, 5, 0.3, 15), (5 * 0.5 + 15 * 0.3) / 20)

    def test_blend_cv_falls_back(self):
        self.assertEqual(H.blend_cv(None, 0, 0.3, 15), 0.3)
        self.assertEqual(H.blend_cv(0.5, 5, None, 0), 0.5)
        self.assertIsNone(H.blend_cv(None, 0, None, 0))


class HeadToHeadTests(unittest.TestCase):
    def _games(self, vs, other, n_vs):
        return ([{"season": 2025, "week": i + 1, "opponent": "DET", "points": vs} for i in range(n_vs)]
                + [{"season": 2025, "week": 10 + i, "opponent": "GB", "points": other} for i in range(8)])

    def test_one_meeting_is_neutral(self):
        self.assertEqual(H.h2h_factor(self._games(30, 15, 1), "DET", 15), 1.0)

    def test_unknown_opponent_is_neutral(self):
        self.assertEqual(H.h2h_factor(self._games(30, 15, 3), "ZZZ", 15), 1.0)

    def test_big_gap_is_capped(self):
        f = H.h2h_factor(self._games(40, 10, 4), "DET", 15)
        self.assertLessEqual(f, 1 + H.H2H_CAP + 1e-9)
        self.assertGreater(f, 1.0)

    def test_struggling_against_a_team_lowers_it(self):
        self.assertLess(H.h2h_factor(self._games(5, 20, 4), "DET", 15), 1.0)

    def test_more_meetings_move_it_further(self):
        two = H.h2h_factor(self._games(20, 15, 2), "DET", 15)
        six = H.h2h_factor(self._games(20, 15, 6), "DET", 15)
        self.assertGreater(six, two)

    def test_versus_summary(self):
        v = H.versus(self._games(18, 10, 3), "DET")
        self.assertEqual((v["games"], v["avg"], v["best"]), (3, 18.0, 18))
        self.assertIsNone(H.versus(self._games(18, 10, 3), "ZZZ"))


class TierMergeTests(unittest.TestCase):
    def test_earlier_games_fold_into_tier_averages(self):
        cur = {"soft": {"games": 2, "avg": 20.0}}
        earlier = [{"tier": "soft", "points": 10.0}, {"tier": "tough", "points": 8.0}, {"tier": None, "points": 99}]
        out = R.merge_tiers(cur, earlier)
        self.assertEqual(out["soft"]["games"], 3)
        self.assertAlmostEqual(out["soft"]["avg"], round((40 + 10) / 3, 1))
        self.assertEqual(out["soft"]["earlier"]["games"], 1)
        self.assertEqual(out["tough"]["games"], 1)
        self.assertIsNone(out["tough"]["current"])


class ShippedDataTests(unittest.TestCase):
    def test_files_load_and_cover_three_seasons(self):
        self.assertTrue(H.available())
        seasons = set(H._frames()["skill"]["season"].unique())
        self.assertEqual(seasons, {2023, 2024, 2025})

    def test_no_playoff_games_in_any_history_table(self):
        # kicker/defense rows used to include weeks 19-22, lifting next season's prior for good teams
        for name, df in H._frames().items():
            self.assertTrue(df.empty or int(df["week"].max()) <= H.REG_SEASON_LAST_WEEK, name)

    def test_ppr_career_matches_stored_ppr_column(self):
        """With default scoring the recomputed points reproduce nflverse's own PPR number."""
        df = H._frames()["skill"]
        df = df[df["season"] == 2025].copy()
        from engine.scoring import apply_scoring
        scored, _ = apply_scoring(df, {"reception": 1.0})
        diff = (scored["fpts_active"] - scored["fantasy_points_ppr"]).abs()
        self.assertLess(diff.mean(), 0.05)

    def test_future_season_ignores_nothing_it_should_not(self):
        # asking for history as of 2024 must not leak 2024/2025 games
        df = H._scored_skill(None, 2024)
        self.assertTrue((df["season"] < 2024).all())

    def test_summary_for_unknown_player_is_empty_not_error(self):
        out = H.summary("00-9999999", "QB", None, 2026)
        self.assertEqual(out["seasons"], [])
        self.assertEqual(out["career_games"], 0)


if __name__ == "__main__":
    unittest.main()
