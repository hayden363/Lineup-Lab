"""engine.team_page: a team's record, weekly results, next game outlook, team stats and roster. No network."""
import unittest

import pandas as pd

from engine import team_page as T


def sched():
    rows = [  # week, away, home, away_score, home_score, spread_line (home favored when positive), total_line, gameday
        (1, "GB", "DET", 20, 27, 3.0, 48.0, "2026-09-13"),
        (2, "DET", "TB", 17, 24, -2.0, 46.0, "2026-09-20"),
        (3, "DET", "GB", 21, 21, 1.0, 45.0, "2026-09-27"),
        (4, "MIN", "DET", None, None, 6.5, 50.0, "2026-10-04"),
        (5, "DET", "CHI", None, None, -3.0, 44.0, "2026-10-11"),
        (1, "NE", "NYJ", 10, 13, 1.0, 40.0, "2026-09-13"),
    ]
    return pd.DataFrame(rows, columns=["week", "away_team", "home_team", "away_score", "home_score", "spread_line", "total_line", "gameday"])


def weekly():
    rows = []
    for wk in (1, 2, 3):
        rows += [dict(player_id="q", player_display_name="Jared Goff", position="QB", recent_team="DET", week=wk, passing_yards=250, rushing_yards=0, receiving_yards=0, fantasy_points_ppr=18.0),
                 dict(player_id="r", player_display_name="Jahmyr Gibbs", position="RB", recent_team="DET", week=wk, passing_yards=0, rushing_yards=80, receiving_yards=20, fantasy_points_ppr=17.0),
                 dict(player_id="w", player_display_name="Amon-Ra St. Brown", position="WR", recent_team="DET", week=wk, passing_yards=0, rushing_yards=0, receiving_yards=90, fantasy_points_ppr=20.0),
                 dict(player_id="x", player_display_name="Other Guy", position="WR", recent_team="GB", week=wk, passing_yards=0, rushing_yards=0, receiving_yards=50, fantasy_points_ppr=9.0)]
    return pd.DataFrame(rows)


class TeamPageTest(unittest.TestCase):
    def setUp(self):
        self.p = T.build("DET", sched(), weekly())

    def test_record_and_points_come_from_played_games(self):
        self.assertEqual(self.p["record"], {"wins": 1, "losses": 1, "ties": 1, "text": "1-1-1"})
        self.assertEqual((self.p["points_for"], self.p["points_against"]), (65, 65))

    def test_weekly_results_list_every_game_with_w_l_t_and_scores(self):
        g = self.p["games"]
        self.assertEqual([(x["week"], x["opponent"], x["home"], x["result"]) for x in g[:3]], [(1, "GB", True, "W"), (2, "TB", False, "L"), (3, "GB", False, "T")])
        self.assertEqual((g[0]["team_score"], g[0]["opp_score"]), (27, 20))
        self.assertEqual(g[3]["result"], None)            # not played yet

    def test_next_game_has_opponent_date_and_betting_outlook(self):
        n = self.p["next_game"]
        self.assertEqual((n["week"], n["opponent"], n["home"]), (4, "MIN", True))
        self.assertEqual(n["spread"], -6.5)               # negative = this team favored
        self.assertEqual(n["implied_total"], 28.2)        # (50 + 6.5) / 2 for the home side, rounded
        self.assertEqual(n["opp_implied_total"], 21.8)

    def test_team_stats_are_per_game_from_player_lines(self):
        s = self.p["stats"]
        self.assertEqual((s["points_for_pg"], s["points_against_pg"]), (21.7, 21.7))
        self.assertEqual((s["pass_yds_pg"], s["rush_yds_pg"]), (250.0, 80.0))

    def test_roster_is_this_teams_players_best_first_with_season_ppg(self):
        r = self.p["players"]
        self.assertEqual([x["name"] for x in r], ["Amon-Ra St. Brown", "Jared Goff", "Jahmyr Gibbs"])
        self.assertEqual(r[0]["ppg"], 20.0)
        self.assertEqual(r[0]["player_id"], "w")

    def test_roster_rows_carry_headshots_when_the_data_has_them(self):
        w = weekly()
        w["headshot_url"] = w["player_id"].map({"w": "https://a.espncdn.com/w.png", "q": None})
        by = {x["player_id"]: x for x in T.build("DET", sched(), w)["players"]}
        self.assertEqual(by["w"]["headshot_url"], "https://a.espncdn.com/w.png")
        self.assertIsNone(by["q"]["headshot_url"])
        self.assertIsNone(T.build("DET", sched(), weekly())["players"][0]["headshot_url"])     # column absent

    def test_a_team_with_no_games_or_players_still_builds(self):
        p = T.build("DET", sched().iloc[0:0], weekly().iloc[0:0])
        self.assertEqual((p["games"], p["players"], p["next_game"]), ([], [], None))
        self.assertEqual(p["record"]["text"], "0-0")

    def test_unknown_team_is_none(self):
        self.assertIsNone(T.build("XYZ", sched(), weekly()))


if __name__ == "__main__":
    unittest.main()


class MatchupProfileTest(unittest.TestCase):
    def test_both_teams_are_summarized_with_a_prediction(self):
        from unittest import mock
        from engine import tools
        with mock.patch.object(tools, "load_bundle", return_value={"schedule": sched(), "wk": weekly()}):
            m = tools.matchup_profile("DET", "GB", {"home_implied": 25.0, "away_implied": 21.0})
        self.assertEqual((m["home"]["abbr"], m["away"]["abbr"]), ("DET", "GB"))
        self.assertEqual(m["home"]["record"], "1-1-1")
        self.assertEqual(m["home"]["pf_pg"], 21.7)
        self.assertEqual([r["result"] for r in m["home"]["recent"]], ["W", "L", "T"])
        self.assertEqual(m["home"]["top_players"][0]["name"], "Amon-Ra St. Brown")
        self.assertIn(m["prediction"]["pick"], ("home", "away"))
        self.assertTrue(m["prediction"]["used_market"])

    def test_a_team_with_no_games_has_no_prediction_but_the_profile_still_builds(self):
        from unittest import mock
        from engine import tools
        with mock.patch.object(tools, "load_bundle", return_value={"schedule": sched().iloc[0:0], "wk": weekly().iloc[0:0]}):
            m = tools.matchup_profile("DET", "GB", None)
        self.assertIsNone(m["prediction"])
        self.assertEqual(m["home"]["recent"], [])

    def test_bad_input_is_none(self):
        from unittest import mock
        from engine import tools
        with mock.patch.object(tools, "load_bundle", return_value={"schedule": sched(), "wk": weekly()}):
            self.assertIsNone(tools.matchup_profile("XYZ", "GB", None))


class EndpointTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from fastapi.testclient import TestClient
        import server
        self.server, self.mock = server, mock
        self.client = TestClient(server.app)

    def test_team_endpoint_returns_the_page_with_a_logo(self):
        page = T.build("DET", sched(), weekly())
        with self.mock.patch.object(self.server.tools, "team_profile", return_value=page) as m:
            body = self.client.get("/api/team/det").json()
        self.assertEqual(body["team"], "DET")
        self.assertTrue(body["logo"].endswith("/det.png"))
        self.assertEqual(m.call_args[0][0], "DET")

    def test_unknown_team_is_404(self):
        self.assertEqual(self.client.get("/api/team/XYZ").status_code, 404)

    def test_every_player_carries_how_he_is_listed(self):
        from engine import tools
        bundle = {"schedule": sched(), "wk": weekly()}
        with self.mock.patch.object(tools, "load_bundle", return_value=bundle), \
                self.mock.patch.object(tools.sleeper, "live_injury_statuses", return_value={"w": "Questionable", "r": "IR"}), \
                self.mock.patch.object(tools, "start_sit", return_value={"players": []}):
            page = tools.team_profile("DET")
        by = {p["player_id"]: p["injury_status"] for p in page["players"]}
        self.assertEqual(by, {"w": "Questionable", "q": None, "r": "IR"})

    def test_projections_attach_for_the_top_players_and_failure_degrades(self):
        from engine import tools
        bundle = {"schedule": sched(), "wk": weekly()}
        res = {"players": [{"player_id": "w", "PROJ": 18.34, "injury_status": None, "outcomes": {}},
                           {"player_id": "q", "PROJ": 15.0, "outcomes": {"out": True}}]}
        with self.mock.patch.object(tools, "load_bundle", return_value=bundle), \
                self.mock.patch.object(tools, "start_sit", return_value=res) as ss:
            page = tools.team_profile("DET")
        self.assertEqual(ss.call_args.kwargs["opponents"]["w"], "MIN")
        by = {p["player_id"]: p for p in page["players"]}
        self.assertEqual(by["w"]["proj"], 18.3)
        self.assertIsNone(by["q"]["proj"])                 # ruled out
        with self.mock.patch.object(tools, "load_bundle", return_value=bundle), \
                self.mock.patch.object(tools, "start_sit", side_effect=RuntimeError("boom")):
            self.assertEqual(len(tools.team_profile("DET")["players"]), 3)


class TeamPageSpeedTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from fastapi.testclient import TestClient
        import server
        self.server, self.mock = server, mock
        server._TEAM_CACHE.clear()
        self.addCleanup(server._TEAM_CACHE.clear)
        self.client = TestClient(server.app)

    def test_lite_skips_projections_and_injury_lookups(self):
        from engine import tools
        bundle = {"schedule": sched(), "wk": weekly()}
        with self.mock.patch.object(tools, "load_bundle", return_value=bundle), \
                self.mock.patch.object(tools, "start_sit", side_effect=AssertionError("lite must not project")), \
                self.mock.patch.object(tools.sleeper, "live_injury_statuses", side_effect=AssertionError("lite must not look up injuries")):
            page = tools.team_profile("DET", lite=True)
        self.assertEqual(page["record"]["text"], "1-1-1")
        self.assertIsNotNone(page["next_game"])

    def test_the_route_caches_each_version_for_a_few_minutes(self):
        page = T.build("DET", sched(), weekly())
        with self.mock.patch.object(self.server.tools, "team_profile", return_value=page) as tp:
            self.client.get("/api/team/DET")
            self.client.get("/api/team/DET")
            self.client.get("/api/team/DET?lite=1")
            self.client.get("/api/team/DET?lite=1")
        self.assertEqual(tp.call_count, 2)
        self.assertEqual([c.kwargs.get("lite") for c in tp.call_args_list], [False, True])

    def test_the_cache_expires(self):
        page = T.build("DET", sched(), weekly())
        with self.mock.patch.object(self.server.tools, "team_profile", return_value=page) as tp:
            self.client.get("/api/team/DET")
            for k in list(self.server._TEAM_CACHE):
                ts, v = self.server._TEAM_CACHE[k]
                self.server._TEAM_CACHE[k] = (ts - self.server.TEAM_TTL - 1, v)
            self.client.get("/api/team/DET")
        self.assertEqual(tp.call_count, 2)

    def test_the_header_strip_asks_for_the_light_version(self):
        import os
        theme = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static/theme.js")).read()
        self.assertIn('"/api/team/" + encodeURIComponent(code) + "?lite=1"', theme)


class StandingsTests(unittest.TestCase):
    def sched_div(self):
        # NFC North after three weeks: DET 3-0, GB 2-1, CHI 1-2, MIN 0-3. Rows are (week, away, home, away_score, home_score).
        rows = [(1, "GB", "DET", 10, 20), (2, "CHI", "DET", 7, 24), (3, "MIN", "DET", 3, 30), (1, "CHI", "GB", 13, 17),
                (2, "MIN", "GB", 6, 14), (1, "MIN", "CHI", 10, 14)]
        return pd.DataFrame([(w, a, h, as_, hs, "REG", "2026-09-1%d" % w, 40.0, 3.0) for w, a, h, as_, hs in rows],
                            columns=["week", "away_team", "home_team", "away_score", "home_score", "game_type", "gameday", "total_line", "spread_line"])

    def test_division_rank_comes_from_the_win_percentage_of_the_four_teams(self):
        s = T.standing("DET", self.sched_div())
        self.assertEqual((s["rank"], s["division"], s["text"]), (1, "NFC North", "1st NFC North"))
        self.assertEqual(T.standing("GB", self.sched_div())["text"], "2nd NFC North")
        self.assertEqual(T.standing("MIN", self.sched_div())["text"], "4th NFC North")

    def test_ties_in_the_standings_break_on_point_differential(self):
        rows = [(1, "A", "DET", 0, 7, "REG"), (1, "GB", "B", 10, 0, "REG")]       # DET beat A by 7, GB beat B by 10: both 1-0
        df = pd.DataFrame([(w, a, h, as_, hs, g, "2026-09-13", 40.0, 3.0) for w, a, h, as_, hs, g in rows],
                          columns=["week", "away_team", "home_team", "away_score", "home_score", "game_type", "gameday", "total_line", "spread_line"])
        self.assertEqual(T.standing("GB", df)["rank"], 1)
        self.assertEqual(T.standing("DET", df)["rank"], 2)

    def test_before_any_game_there_is_no_rank_text(self):
        df = sched().iloc[0:0]
        self.assertIsNone(T.standing("DET", df)["rank"])

    def test_a_win_streak_counts_back_from_the_last_game(self):
        games = [{"result": "L"}, {"result": "W"}, {"result": "W"}, {"result": "W"}, {"result": None}]
        self.assertEqual(T.streak(games), {"type": "W", "n": 3})
        self.assertEqual(T.streak([{"result": "W"}, {"result": "L"}]), {"type": "L", "n": 1})
        self.assertEqual(T.streak([]), {"type": None, "n": 0})
        self.assertEqual(T.streak([{"result": "T"}]), {"type": "T", "n": 1})

    def test_build_carries_standing_streak_and_bye_week(self):
        p = T.build("DET", sched(), weekly())
        self.assertIn("standing", p)
        self.assertEqual(p["streak"]["type"], "T")
        self.assertIsNone(p["bye_week"])                   # DET plays every week of the fixture

    def test_every_team_has_a_division(self):
        self.assertEqual(len(T.DIVISIONS), 32)
        from collections import Counter
        self.assertEqual(set(Counter(T.DIVISIONS.values()).values()), {4})
