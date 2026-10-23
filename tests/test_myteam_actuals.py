"""My Team: completed games show what happened, and availability weights a projection."""
import unittest
from unittest import mock

import pandas as pd

from engine import tools


def bundle(played_weeks=(1,), stats_weeks=(1,)):
    sched = pd.DataFrame([
        {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "BUF", "home_score": 27.0, "away_score": 20.0},
        {"week": 1, "game_type": "REG", "home_team": "DET", "away_team": "GB", "home_score": None, "away_score": None},
        {"week": 2, "game_type": "REG", "home_team": "KC", "away_team": "GB", "home_score": None, "away_score": None},
    ])
    wk = pd.DataFrame([
        {"week": 1, "player_id": "kc_wr", "recent_team": "KC", "position": "WR", "fantasy_points_ppr": 17.4},
        {"week": 1, "player_id": "buf_rb", "recent_team": "BUF", "position": "RB", "fantasy_points_ppr": 8.2},
    ])
    return {"schedule": sched, "wk": wk, "pbp": pd.DataFrame()}


def actuals(b, week):
    """_Actuals with DEF and K scoring stubbed: KC's defence scored 12, BUF's 3,
    and kicker k1 (KC) scored 9."""
    d = pd.DataFrame({"defteam": ["KC", "BUF"], "week": [1, 1]})
    k = pd.DataFrame({"player_id": ["k1"], "week": [1]})
    with mock.patch.object(tools.defense_scoring, "build_defense_weekly", return_value=d), \
            mock.patch.object(tools.defense_scoring, "score_defense_weekly", return_value=pd.Series([12.0, 3.0])), \
            mock.patch.object(tools.kicker_scoring, "build_kicker_weekly", return_value=k), \
            mock.patch.object(tools.kicker_scoring, "score_kicker_weekly", return_value=pd.Series([9.0])):
        return tools._Actuals(b, None, week)


class ActualsTests(unittest.TestCase):
    def test_played_game_returns_real_points(self):
        a = actuals(bundle(), 1)
        self.assertEqual(a.skill("kc_wr", "KC"), 17.4)
        self.assertEqual(a.skill("buf_rb", "BUF"), 8.2)

    def test_rostered_player_with_no_stat_line_scored_zero(self):
        a = actuals(bundle(), 1)
        self.assertEqual(a.skill("never_played", "KC"), 0.0)

    def test_unplayed_game_has_no_actual(self):
        a = actuals(bundle(), 1)
        self.assertIsNone(a.skill("det_wr", "DET"))      # DET-GB has no score yet
        self.assertEqual(a.final_teams, {"KC", "BUF"})

    def test_future_week_has_no_actuals(self):
        a = actuals(bundle(), 2)
        self.assertFalse(a.any())
        self.assertIsNone(a.skill("kc_wr", "KC"))

    def test_score_posted_but_stats_not_loaded_keeps_projection(self):
        b = bundle()
        b["wk"] = b["wk"][b["wk"]["recent_team"] == "BUF"]      # KC's stat lines haven't arrived
        a = actuals(b, 1)
        self.assertIsNone(a.skill("kc_wr", "KC"))
        self.assertEqual(a.skill("buf_rb", "BUF"), 8.2)

    def test_points_by_roster_row(self):
        a = actuals(bundle(), 1)
        self.assertEqual(a.points({"position": "WR", "player_id": "kc_wr", "recent_team": "KC"}), 17.4)
        self.assertIsNone(a.points({"position": "WR", "player_id": "det_wr", "recent_team": "DET"}))


    def test_defense_and_kicker_actuals(self):
        a = actuals(bundle(), 1)
        self.assertEqual(a.defense("KC"), 12.0)
        self.assertIsNone(a.defense("DET"))                    # game not played
        self.assertEqual(a.kicker("k1"), 9.0)
        self.assertEqual(a.kicker("unknown", team="KC"), 0.0)  # his team played, no kicks
        self.assertIsNone(a.kicker("unknown", team="DET"))
        self.assertEqual(a.points({"position": "DEF", "player_id": "KC"}), 12.0)
        self.assertEqual(a.points({"position": "K", "player_id": "k1", "recent_team": "KC"}), 9.0)


def board(status=None, report=None):
    return pd.DataFrame({"recent_team": ["KC"], "injury_status": [status], "injury_report": [report]},
                        index=["p1"])


class AvailabilityTests(unittest.TestCase):
    def proj(self, status, p_play=None, report=None):
        projected = pd.DataFrame({"PROJ": [12.0], "injury_factor": [None], "injury_sample_n": [None]})
        with mock.patch.object(tools, "project_vs", return_value=projected), \
                mock.patch.object(tools.data, "next_opponent", return_value=("BUF", True)), \
                mock.patch.object(tools, "_team_on_bye", return_value=False), \
                mock.patch.object(tools.play_prob, "play_probability",
                                  return_value=None if p_play is None else {"p_play": p_play}):
            return tools._opponent_adjusted_proj_full(board(status, report), "p1", "WR", {"schedule": None}, None, week=2)[0]

    def test_healthy_player_keeps_full_projection(self):
        self.assertEqual(self.proj(None), 12.0)

    def test_out_and_ir_players_score_zero(self):
        for status in ("Out", "IR", "PUP", "Sus"):
            self.assertEqual(self.proj(status), 0.0, status)

    def test_questionable_weighted_by_chance_of_playing(self):
        self.assertEqual(self.proj("Questionable", p_play=0.5), 6.0)

    def test_doubtful_with_low_chance_is_nearly_zero(self):
        self.assertEqual(self.proj("Doubtful", p_play=0.1), 1.2)

    def test_questionable_without_a_known_rate_keeps_projection(self):
        self.assertEqual(self.proj("Questionable", p_play=None), 12.0)


if __name__ == "__main__":
    unittest.main()
