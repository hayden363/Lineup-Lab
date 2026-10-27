"""Regression tests for the bugs fixed in the October 2026 backend review.
One class per bug. No network, no database, no nflverse: everything external
is mocked.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import server
from engine import board, db, defense_scoring, espn, lineup as L, oauth, sleeper, tools, value, weekly_proj
from engine.scoring import ScoringSettings

USER = {"id": 9, "username": "rev"}


# ---------------------------------------------------------------- lineup ----
class EspnSlotLabels(unittest.TestCase):
    """ESPN slots arrive as "RB/WR/TE", "OP", "D/ST"...; they used to be
    unknown to lineup.ELIGIBLE, so every ESPN flex/D/ST starter was illegal."""

    def test_espn_flex_and_dst_accept_the_right_positions(self):
        self.assertTrue(L.eligible("RB/WR/TE", "TE"))
        self.assertTrue(L.eligible("RB/WR", "RB"))
        self.assertFalse(L.eligible("RB/WR", "TE"))
        self.assertTrue(L.eligible("WR/TE", "TE"))
        self.assertTrue(L.eligible("OP", "QB"))
        self.assertTrue(L.eligible("D/ST", "DEF"))
        self.assertFalse(L.eligible("RB/WR/TE", "QB"))


# ----------------------------------------------------- start/sit suggestions ----
class FlexSuggestionLabels(unittest.TestCase):
    """The FLEX comparison only looked for slot == "FLEX"; ESPN's "RB/WR/TE"
    (and Sleeper's WRRB_FLEX/REC_FLEX) starters were never compared."""

    def test_espn_flex_slot_gets_a_flex_suggestion_with_an_eligible_bench_player(self):
        roster = [
            {"player_id": "a", "position": "WR", "slot": "WR", "is_starter": True, "PROJ": 14.0},
            {"player_id": "b", "position": "TE", "slot": "RB/WR", "is_starter": True, "PROJ": 6.0},
            {"player_id": "c", "position": "TE", "slot": None, "is_starter": False, "PROJ": 11.0},
            {"player_id": "d", "position": "RB", "slot": None, "is_starter": False, "PROJ": 9.0},
        ]
        with mock.patch.object(tools, "start_sit", side_effect=lambda ids, **k: {"players": ids}):
            out = tools.start_sit_suggestions_from_roster(roster, limit=5)
        flex = [s for s in out if s["position"] == "FLEX"]
        self.assertEqual(len(flex), 1)
        # "RB/WR" can't take the TE, so the RB is the bench option
        self.assertEqual(flex[0]["players"], ["b", "d"])
        self.assertEqual(flex[0]["gap"], 3.0)


# ------------------------------------------------------------- team codes ----
class TeamCodeNormalisation(unittest.TestCase):
    def test_to_nflverse_team(self):
        self.assertEqual(defense_scoring.to_nflverse_team("LAR"), "LA")
        self.assertEqual(defense_scoring.to_nflverse_team("WSH"), "WAS")
        self.assertEqual(defense_scoring.to_nflverse_team("KC"), "KC")
        self.assertIsNone(defense_scoring.to_nflverse_team(None))

    def test_sleeper_unscored_player_uses_nflverse_team_and_no_fake_team_for_free_agents(self):
        players = {"111": {"position": "K", "full_name": "Rams Kicker", "team": "LAR"},
                   "222": {"position": "K", "full_name": "Free Agent", "team": None},
                   "LAR": {"position": "DEF", "first_name": "Los Angeles", "last_name": "Rams"}}
        with mock.patch.object(sleeper, "all_players", return_value=players):
            self.assertEqual(sleeper.resolve_unscored_player("111")["recent_team"], "LA")
            self.assertIsNone(sleeper.resolve_unscored_player("222")["recent_team"])
            self.assertEqual(sleeper.resolve_unscored_player("LAR")["recent_team"], "LA")

    def test_espn_washington_dst_resolves_to_a_real_defense(self):
        dst = mock.Mock(playerId=-16028, position="D/ST", proTeam="WSH")
        dst.name = "Commanders D/ST"
        league = mock.Mock(teams=[mock.Mock(roster=[dst])])
        row = espn.build_unscored_resolver(league)("WSH")
        self.assertEqual(row["recent_team"], "WAS")
        board_df = pd.DataFrame({"fpts_per_game": [7.0]}, index=["WAS"])
        self.assertIsNotNone(defense_scoring.resolve_defense_row("WSH", board_df))


# ------------------------------------------------------------ player card ----
class PlayerDetailEarlySeason(unittest.TestCase):
    """player_detail used build_board's ranked-list min_games=2, so every card
    404'd in week 1 and any one-game player 404'd all season."""

    def test_asks_for_the_unfiltered_board(self):
        wk = pd.DataFrame([{"player_id": "p1", "position": "WR", "week": 1}])
        bundle = {"wk": wk, "schedule": pd.DataFrame(), "ngs_rec": pd.DataFrame()}
        calls = []

        def fake_board(pos, season=None, min_games=2, scoring=None):
            calls.append(min_games)
            return pd.DataFrame(index=pd.Index([], name="player_id"))   # empty: stop right after
        with mock.patch.object(board, "load_bundle", return_value=bundle), \
             mock.patch.object(board, "build_board", side_effect=fake_board):
            board.player_detail("p1")
        self.assertEqual(calls, [0])


class BuildBoardMinVolumeCache(unittest.TestCase):
    """min_volume is applied inside the build, so a custom value must not
    land in (or come from) the shared cache."""

    def test_custom_min_volume_bypasses_the_cache(self):
        built = pd.DataFrame({"games": [3], "fpts_per_game": [10.0]}, index=pd.Index(["p"], name="player_id"))
        with mock.patch.object(board, "_build_board_uncached", return_value=built.copy()) as b, \
             mock.patch.dict(board._BOARD_CACHE, clear=True):
            board.build_board("WR", season=2099, min_volume=1)
            self.assertEqual(board._BOARD_CACHE, {})
            board.build_board("WR", season=2099)
            self.assertEqual(len(board._BOARD_CACHE), 1)
            self.assertEqual(b.call_count, 2)


# ----------------------------------------------------------- overall board ----
class OverallByeWeek(unittest.TestCase):
    def test_schedule_bye_is_kept_and_ecr_only_fills_gaps(self):
        frames = {pos: pd.DataFrame([
            {"player_id": f"{pos}1", "player_display_name": f"{pos} One", "recent_team": "AAA",
             "PROJ": 15.0, "bye_week": 9.0},
            {"player_id": f"{pos}2", "player_display_name": f"{pos} Two", "recent_team": "BBB",
             "PROJ": 10.0, "bye_week": np.nan},
        ]).set_index("player_id") for pos in value.POSITIONS}
        ecr = {"qb one|QB": {"ecr": 1.0, "ecr_sd": 1.0, "bye_week": 12},
               "qb two|QB": {"ecr": 5.0, "ecr_sd": 1.0, "bye_week": 7}}
        out = value.compute_value(frames, ecr=ecr)
        self.assertEqual(out.loc["QB1", "bye_week"], 9)    # schedule wins over ECR
        self.assertEqual(out.loc["QB2", "bye_week"], 7)    # ECR fills a missing one
        self.assertEqual(out.loc["RB1", "bye_week"], 9)    # no ECR: schedule bye survives
        no_ecr = value.compute_value(frames, ecr={})
        self.assertEqual(no_ecr.loc["WR1", "bye_week"], 9)


# ------------------------------------------------------------------ oauth ----
class GoogleEmailVerified(unittest.TestCase):
    def _exchange(self, claims):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"id_token": "tok"}
        with mock.patch.object(oauth.requests, "post", return_value=resp), \
             mock.patch.object(oauth, "_verify_id_token", return_value=claims):
            return oauth.google_exchange_code("code", "https://x/cb")

    def test_unverified_email_is_rejected(self):
        for flag in (False, None, "false"):
            with self.assertRaises(oauth.OAuthError):
                self._exchange({"sub": "1", "email": "a@b.co", "email_verified": flag})

    def test_verified_email_passes(self):
        self.assertEqual(self._exchange({"sub": "1", "email": "a@b.co", "email_verified": True})["provider_id"], "1")


# ------------------------------------------------------- weekly projection ----
class WeeklyProjectionLeagueExtras(unittest.TestCase):
    def test_te_premium_and_first_downs_count(self):
        s = ScoringSettings.from_dict({"reception": 1, "te_reception": 0.5, "rec_fd": 0.5})
        line = {"rec": 4, "rec_yd": 40, "rec_fd": 2}
        self.assertEqual(weekly_proj.points(line, s, "WR"), 4 + 4 + 1)
        self.assertEqual(weekly_proj.points(line, s, "TE"), 4 + 4 + 1 + 2)
        self.assertEqual(weekly_proj.projected_line(line, s, "TE")["fpts"], 11.0)


# ----------------------------------------------------------- track record ----
class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


@contextmanager
def _conn_with(cur):
    with mock.patch.object(db, "_conn", lambda: _yield(cur)):
        yield


@contextmanager
def _yield(cur):
    yield cur


class TrackRecordVoids(unittest.TestCase):
    """A player with no stats in a finished week used to keep his row (and a
    pair's whole group) pending forever."""

    rows = [{"id": 1, "comparison_id": "g1", "player_id": "a", "tier": "START"},
            {"id": 2, "comparison_id": "g1", "player_id": "b", "tier": "SIT"},
            {"id": 3, "comparison_id": "g1", "player_id": "dnp", "tier": "SIT"},
            {"id": 4, "comparison_id": "g2", "player_id": "a", "tier": "START"},
            {"id": 5, "comparison_id": "g2", "player_id": "dnp", "tier": "SIT"}]

    def test_unplayed_rows_are_voided_once_stats_exist(self):
        cur = FakeCursor(self.rows)
        with _conn_with(cur):
            n = db.resolve_predictions(2026, 6, {"a": 20.0, "b": 10.0})
        self.assertEqual(n, 5)
        voided = sorted(p[-1] for s, p in cur.executed if "was_correct = NULL" in s)
        self.assertEqual(voided, [3, 4, 5])
        graded = {p[-1]: p[2] for s, p in cur.executed if "was_correct = %s" in s}
        self.assertEqual(graded, {1: True, 2: False})

    def test_nothing_is_voided_before_the_weeks_stats_exist(self):
        cur = FakeCursor(self.rows)
        with _conn_with(cur):
            self.assertEqual(db.resolve_predictions(2026, 6, {}), 0)
        self.assertEqual([s for s, _ in cur.executed if s.startswith("UPDATE")], [])


# ---------------------------------------------------------------- server ----
class NewsForEspnTeam(unittest.TestCase):
    def setUp(self):
        server.app.dependency_overrides[server.current_user] = lambda: USER
        self.addCleanup(server.app.dependency_overrides.clear)
        self.client = TestClient(server.app)

    def test_team_news_uses_the_espn_loader(self):
        team = {"nfl_week": 6, "opponent": None,
                "my_team": {"team_name": "Mine", "players": [{"player_id": "x", "player_display_name": "Some Guy"}]}}
        with mock.patch.object(server.db, "get_active_team",
                               return_value={"platform": "espn", "league_id": "123456", "roster_id": 2}), \
             mock.patch.object(server.db, "get_espn_secrets", return_value=("s2", "swid")), \
             mock.patch.object(server.news_layer, "all_headlines",
                               return_value=[{"link": "l", "title": "Some Guy scores", "summary": ""}]), \
             mock.patch.object(server.tools, "my_team", side_effect=AssertionError("Sleeper loader used")), \
             mock.patch.object(server.tools, "my_team_espn", return_value=team) as espn_loader:
            r = self.client.get("/api/news?scope=team")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["items"]), 1)
        espn_loader.assert_called_once_with("123456", 2, espn_s2="s2", swid="swid")


class StartSitSizeCap(unittest.TestCase):
    def test_too_many_players_is_a_400_before_any_work(self):
        client = TestClient(server.app)
        with mock.patch.object(server.tools, "start_sit", side_effect=AssertionError("ran")):
            r = client.post("/api/startsit", json={"player_ids": [str(i) for i in range(50)]})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
