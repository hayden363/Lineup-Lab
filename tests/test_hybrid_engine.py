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


# ------------------------------------------------- My Team matches Start/Sit ----
class MyTeamUsesTheGameEnvironment(unittest.TestCase):
    """My Team's PROJ must be the number Start/Sit and the player page show: that includes the market view of the
    game (implied team total, script, roof), which start_sit applies on top of the matchup projection."""

    def proj(self, env_factor, schedule=object()):
        row = pd.DataFrame({"recent_team": ["DET"], "injury_status": [None], "injury_report": [None]}, index=["arsb"])
        projected = pd.DataFrame({"PROJ": [16.0], "injury_factor": [1.0], "injury_sample_n": [None]})
        with mock.patch.object(tools, "project_vs", return_value=projected), \
                mock.patch.object(tools.data, "next_opponent", return_value=("MIN", 8)), \
                mock.patch.object(tools, "_head_to_head", return_value=None), \
                mock.patch.object(tools.context, "game_context", return_value={"week": 8}) as gc, \
                mock.patch.object(tools.context, "environment_factor", return_value=(env_factor, [])):
            out = tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": schedule}, None)[0]
        return out, gc

    def test_a_high_scoring_spot_lifts_the_projection(self):
        self.assertEqual(self.proj(1.04)[0], 16.6)           # 16.0 x 1.04

    def test_a_low_scoring_spot_lowers_it(self):
        self.assertEqual(self.proj(0.95)[0], 15.2)

    def test_the_games_week_comes_from_the_schedule_lookup(self):
        _, gc = self.proj(1.0)
        self.assertEqual(gc.call_args[0][2], 8)


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
                mock.patch.object(tools, "_head_to_head", return_value=None), \
                mock.patch.object(play_prob, "date", FixedFriday):
            return tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": None}, None)[0]

    def test_healthy_is_the_full_projection(self):
        self.assertEqual(self.proj(None), 17.5)

    def test_questionable_on_a_wednesday_is_ninety_two_percent_not_half(self):
        p = self.proj("Questionable", self.DNP, self.WED)       # a Wednesday non-participant
        self.assertEqual(p, 16.1)                                # 17.5 x 0.92
        self.assertGreater(p, 0.85 * self.BASE)

    def test_questionable_with_no_practice_information_is_ninety_two_percent(self):
        self.assertEqual(self.proj("Questionable"), 16.1)

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


# ------------------------------------------------------------ head-to-head ----
class HeadToHeadInTheProjection(unittest.TestCase):
    """His own record against this week's opponent, over the last two seasons and this one, enters the projection
    as a small multiplier (engine/history.py explains why it is small)."""
    PRIOR = ([{"season": 2024, "week": 7, "opponent": "MIN", "points": 25.2}, {"season": 2024, "week": 18, "opponent": "MIN", "points": 13.7},
              {"season": 2023, "week": 16, "opponent": "MIN", "points": 28.6}, {"season": 2023, "week": 18, "opponent": "MIN", "points": 27.4}]
             + [{"season": 2024, "week": w, "opponent": "GB", "points": 19.0} for w in range(1, 7)])

    def bundle(self, current):
        wk = pd.DataFrame([{"player_id": "arsb", "week": w, "opponent_team": o, "fantasy_points_ppr": p}
                           for w, o, p in current])
        return {"season": 2026, "wk": wk}

    def h2h(self, current, prior=None):
        with mock.patch.object(tools.history, "available", return_value=True), \
                mock.patch.object(tools.history, "player_games", return_value=self.PRIOR if prior is None else prior):
            return tools._head_to_head("arsb", "MIN", None, self.bundle(current), 18.0)

    def test_only_the_last_two_seasons_and_this_one_count(self):
        # 2023 is outside the window: just the two 2024 meetings (25.2, 13.7) against his ~19 norm
        out = self.h2h([(1, "GB", 19.0), (2, "GB", 19.0)])
        self.assertEqual(out["meetings"], 2)
        self.assertAlmostEqual(out["avg"], 19.45, delta=0.06)

    def test_this_seasons_earlier_meeting_counts_too(self):
        out = self.h2h([(2, "MIN", 30.0), (3, "GB", 19.0)])
        self.assertEqual(out["meetings"], 3)

    def test_no_meetings_or_no_history_is_none_and_neutral(self):
        self.assertIsNone(self.h2h([(1, "GB", 19.0)], prior=[]))
        with mock.patch.object(tools.history, "available", return_value=False):
            self.assertIsNone(tools._head_to_head("arsb", "MIN", None, self.bundle([]), 18.0))
        self.assertIsNone(tools._head_to_head("arsb", None, None, self.bundle([]), 18.0))

    def test_the_factor_is_small_and_signed_by_his_record(self):
        strong = self.h2h([(1, "MIN", 40.0), (2, "MIN", 38.0), (3, "GB", 10.0), (4, "GB", 10.0), (5, "GB", 10.0)])
        weak = self.h2h([(1, "MIN", 2.0), (2, "MIN", 3.0), (3, "GB", 25.0), (4, "GB", 25.0), (5, "GB", 25.0)])
        self.assertGreater(strong["factor"], 1.0)
        self.assertLess(weak["factor"], 1.0)
        self.assertLessEqual(strong["factor"], 1.05 + 1e-9)
        self.assertGreaterEqual(weak["factor"], 0.95 - 1e-9)

    def test_it_multiplies_the_weekly_projection_before_the_injury_weighting(self):
        row = pd.DataFrame({"recent_team": ["DET"], "injury_status": ["Questionable"], "injury_report": [None]}, index=["arsb"])
        projected = pd.DataFrame({"PROJ": [17.5], "injury_factor": [1.0], "injury_sample_n": [None]})
        with mock.patch.object(tools, "project_vs", return_value=projected), \
                mock.patch.object(tools.data, "next_opponent", return_value=("MIN", 8)), \
                mock.patch.object(tools, "_head_to_head", return_value={"factor": 1.04, "meetings": 4, "avg": 20.0}):
            q = tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": None}, None)[0]
            row.loc["arsb", "injury_status"] = None
            healthy = tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": None}, None)[0]
        self.assertEqual(healthy, 18.2)            # 17.5 x 1.04
        self.assertEqual(q, 16.7)                  # then x 0.92 for Questionable

    def test_no_head_to_head_leaves_the_projection_alone(self):
        row = pd.DataFrame({"recent_team": ["DET"], "injury_status": [None], "injury_report": [None]}, index=["arsb"])
        projected = pd.DataFrame({"PROJ": [17.5], "injury_factor": [1.0], "injury_sample_n": [None]})
        with mock.patch.object(tools, "project_vs", return_value=projected), \
                mock.patch.object(tools.data, "next_opponent", return_value=("MIN", 8)), \
                mock.patch.object(tools, "_head_to_head", return_value=None):
            self.assertEqual(tools._opponent_adjusted_proj_full(row, "arsb", "WR", {"schedule": None}, None)[0], 17.5)


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


class MyTeamRowRange(unittest.TestCase):
    """Each scored My Team row carries the range around his projection and, when he's Questionable/Doubtful, the chance he plays."""

    def rng(self, proj, status=None, cv=0.5, games=8):
        row = {"cv": cv, "games": games}
        return tools._row_range(row, proj, "WR", status, None, "p123")

    def test_healthy_player_has_a_floor_below_and_a_ceiling_above_his_projection(self):
        r = self.rng(17.3)
        self.assertLess(r["floor"], 17.3)
        self.assertGreater(r["ceiling"], 17.3)
        self.assertIsNone(r["p_play"])

    def test_the_range_is_deterministic(self):
        self.assertEqual(self.rng(17.3), self.rng(17.3))

    def test_questionable_keeps_the_ceiling_and_loses_the_floor_and_shows_the_chance(self):
        healthy = self.rng(17.3)
        q = self.rng(15.6, "Questionable")                  # row PROJ is already x0.92
        self.assertGreaterEqual(q["p_play"], 0.5)
        self.assertLess(q["p_play"], 1.0)
        self.assertLess(q["floor"], healthy["floor"] + 0.01)
        self.assertGreater(q["ceiling"], 17.3 * 0.9)

    def test_out_players_and_zero_projections_have_no_range(self):
        self.assertEqual(self.rng(0.0, "Out"), {})
        self.assertEqual(self.rng(0.0), {})

    def test_missing_cv_falls_back_to_the_position_default(self):
        r = tools._row_range({"cv": float("nan"), "games": 0}, 12.0, "RB", None, None, "x1")
        self.assertLess(r["floor"], 12.0)
