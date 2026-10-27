"""The projection engine's two guards: injuries scale the WEEKLY projection by policy (never a flat half), and a
hot or cold streak can't move a projection by more than 1.5 points / 20%. No network: frames are hand-built."""
import unittest
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd

from engine import board as board_mod, injuries, play_prob, projmodel, tools


class FixedFriday(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 23)


def _wk(rows):
    return pd.DataFrame(rows, columns=["player_id", "position", "week", "targets", "carries", "fpts_active"])


# ------------------------------------------------------------------ injuries ----
class WeeklyInjuryProjection(unittest.TestCase):
    """Amon-Ra at 17.5 PPG against his real opponent, under each designation."""
    BASE = 17.5
    WED = "2026-10-21T18:00Z"
    FRI = "2026-10-23T18:00Z"
    DNP = "St. Brown (ankle) was a non-participant in practice."

    def proj(self, status, note=None, updated=None):
        row = pd.DataFrame({"recent_team": ["DET"], "injury_status": [status],
                            "injury_report": [{"note": note, "updated": updated} if note else None]}, index=["arsb"])
        projected = pd.DataFrame({"PROJ": [self.BASE], "injury_factor": [1.0], "injury_sample_n": [None]})
        with mock.patch.object(tools, "project_vs", return_value=projected), \
                mock.patch.object(tools.data, "next_opponent", return_value=("MIN", 8)), \
                mock.patch.object(play_prob, "date", FixedFriday):
            return tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": None}, None)[0]

    def test_healthy_is_the_full_projection(self):
        self.assertEqual(self.proj(None), 17.5)

    def test_questionable_on_a_wednesday_is_ninety_percent_not_half(self):
        p = self.proj("Questionable", self.DNP, self.WED)       # a Wednesday non-participant
        self.assertEqual(p, 15.8)                                # 17.5 x 0.90
        self.assertGreater(p, 0.85 * self.BASE)

    def test_questionable_with_no_practice_information_is_ninety_percent(self):
        self.assertEqual(self.proj("Questionable"), 15.8)

    def test_questionable_after_a_friday_did_not_practice_is_sixty_percent(self):
        self.assertEqual(self.proj("Questionable", self.DNP, self.FRI), 10.5)

    def test_doubtful_is_a_quarter(self):
        self.assertEqual(self.proj("Doubtful"), 4.4)             # 17.5 x 0.25

    def test_out_and_ir_are_zero(self):
        self.assertEqual(self.proj("Out"), 0.0)
        self.assertEqual(self.proj("IR"), 0.0)


class RestOfSeasonValueIsNotTheWeeklyMultiplier(unittest.TestCase):
    """Trade value reads the rest-of-season number: a Questionable tag must not cut it, and Out/IR are
    discounted by the games they are expected to miss."""

    def value(self, status, report=None, games=10):
        board = pd.DataFrame({"rate": [17.9], "FORM": [0.0], "FORM_ADJ": [0.0], "injury_status": [status],
                              "injury_body_part": [None], "injury_report": [report], "recent_team": ["DET"]}, index=["p"])
        sched = pd.DataFrame({"game_type": ["REG"] * games, "week": range(1, games + 1), "home_team": ["DET"] * games,
                              "away_team": ["XXX"] * games, "home_score": [None] * games,
                              "gameday": [f"2026-11-{d:02d}" for d in range(1, games + 1)]})
        with mock.patch.object(board_mod.defense_layer, "league_average_composite", return_value=1.0):
            return float(board_mod.rest_of_season_value(board, "WR", bundle={"defense_factors": None, "schedule": sched}).iloc[0])

    def test_a_questionable_tag_does_not_touch_trade_value_even_after_a_friday_dnp(self):
        healthy = self.value(None)
        friday_dnp = {"note": "St. Brown did not practice.", "updated": "2026-10-23T18:00Z", "return_date": None}
        self.assertEqual(self.value("Questionable", friday_dnp), healthy)
        self.assertEqual(self.value("Questionable"), healthy)

    def test_ir_and_out_are_discounted_by_expected_missed_games_without_an_espn_report(self):
        self.assertEqual(self.value("IR"), round(17.9 * 0.6, 1))      # the 4-game IR minimum of 10 left
        self.assertEqual(self.value("Out"), round(17.9 * 0.9, 1))     # the next game
        self.assertEqual(self.value("Doubtful"), 17.9)                # a weekly status: no ROS discount

    def test_a_season_ending_return_date_zeroes_it(self):
        self.assertEqual(self.value("IR", {"return_date": "2027-02-15"}), 0.0)


# ------------------------------------------------------------------- recency ----
class RecencyCap(unittest.TestCase):
    def test_a_streak_cannot_move_a_projection_more_than_one_and_a_half_points(self):
        self.assertAlmostEqual(projmodel.cap_recency(19.1, 15.9), 17.4)       # +3.2 raw lift -> +1.5
        self.assertAlmostEqual(projmodel.cap_recency(18.0, 20.6), 19.1)       # -2.6 raw lift -> -1.5

    def test_small_lifts_pass_through_untouched(self):
        self.assertAlmostEqual(projmodel.cap_recency(16.4, 16.0), 16.4)
        self.assertAlmostEqual(projmodel.cap_recency(15.7, 16.0), 15.7)

    def test_the_lift_never_exceeds_twenty_percent_of_the_baseline(self):
        # a 5-point player: 20% is 1.0, tighter than 1.5
        self.assertAlmostEqual(projmodel.cap_recency(8.0, 5.0), 6.0)
        self.assertAlmostEqual(projmodel.cap_recency(2.0, 5.0), 4.0)
        base = np.array([5.0, 10.0, 18.0, 25.0])
        lift = projmodel.cap_recency(base + 50, base) - base
        self.assertTrue(np.all(lift / (base + lift) <= 0.2 + 1e-9))       # baseline is always >= 80% of the projection

    def test_degenerate_baselines_do_not_break(self):
        self.assertEqual(projmodel.cap_recency(3.0, 0.0), 0.0)
        self.assertEqual(projmodel.cap_recency(3.0, -2.0), -2.0)

    def test_predict_holds_a_hot_streak_to_the_cap(self):
        coef = {"WR": np.array([0.57, 0.246, 0.149, 0.316, 0.213])}       # the fitted WR weights
        ppo = {"WR": (2.0, 0.5)}
        model = {"coef": coef, "ppo": ppo, "prior": pd.Series(dtype=float)}
        hot = [("hot", "WR", w, t, 0, p) for w, (t, p) in enumerate([(5, 10), (5, 12), (5, 11), (5, 12), (12, 30), (12, 28), (12, 26), (12, 25)], 1)]
        steady = [("steady", "WR", w, 8, 0, 17) for w in range(1, 9)]
        with mock.patch.object(projmodel, "model", return_value=model):
            out = projmodel.predict("WR", _wk(hot + steady), None, 2026)
        h, s = out.loc["hot"], out.loc["steady"]
        self.assertGreater(h["recency_lift_raw"], 1.5)                    # the raw regression would have inflated him
        self.assertAlmostEqual(h["recency_lift"], 1.5, places=6)          # and the cap held it
        self.assertLessEqual(h["recency_lift"] / h["rate"], 0.20)
        self.assertAlmostEqual(s["recency_lift"], 0.0, places=6)          # no streak, no lift
        self.assertAlmostEqual(h["rate"], h["baseline"] + 1.5, places=6)

    def test_the_cap_costs_almost_nothing_in_accuracy_on_real_history(self):
        from engine import history
        if not history.available():
            self.skipTest("no history_data on this machine")
        r = projmodel.backtest()
        if r is None:
            self.skipTest("fewer than three seasons of history")
        self.assertLess(r["rmse"], r["uncapped"]["rmse"] + 0.05)          # capped vs uncapped, out of sample
        self.assertLess(r["rmse"], r["old"]["rmse"])                      # and still better than the formula it replaced
        self.assertLess(abs(r["bias"]), 0.1)


class CappedFormMultiplier(unittest.TestCase):
    """For the older formula some players still use: FORM (a percent) turned into a multiplier."""

    def test_a_forty_percent_streak_is_held_to_one_and_a_half_points(self):
        self.assertAlmostEqual(projmodel.capped_form_multiplier(18.0, 40.0), 1 + 1.5 / 18.0)
        self.assertAlmostEqual(projmodel.capped_form_multiplier(18.0, -40.0), 1 - 1.5 / 18.0)

    def test_a_modest_form_is_untouched(self):
        self.assertAlmostEqual(projmodel.capped_form_multiplier(18.0, 5.0), 1.05)

    def test_missing_or_zero_inputs_are_neutral(self):
        self.assertEqual(projmodel.capped_form_multiplier(18.0, float("nan")), 1.0)
        self.assertEqual(projmodel.capped_form_multiplier(0.0, 30.0), 1.0)

    def test_works_on_a_series_and_keeps_the_index(self):
        out = projmodel.capped_form_multiplier(pd.Series([18.0, 5.0], index=["a", "b"]), pd.Series([40.0, 40.0], index=["a", "b"]))
        self.assertEqual(list(out.index), ["a", "b"])
        self.assertAlmostEqual(out["a"], 1 + 1.5 / 18.0)
        self.assertAlmostEqual(out["b"], 1.2)                              # 20% of 5 is the tighter cap


if __name__ == "__main__":
    unittest.main()
