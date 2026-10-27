"""tools.news_rosters (cheap names+teams lookup) and GET /api/news. No network, no database."""
import unittest
from unittest import mock

import pandas as pd
from fastapi.testclient import TestClient

import server
from engine import news, tools

WK = pd.DataFrame([
    {"player_id": "g1", "week": 1, "player_display_name": "Kenneth Walker III", "recent_team": "SEA", "headshot_url": "http://h/old.png"},
    {"player_id": "g1", "week": 2, "player_display_name": "Kenneth Walker III", "recent_team": "SEA", "headshot_url": "http://h/walker.png"},
    {"player_id": "g2", "week": 2, "player_display_name": "CeeDee Lamb", "recent_team": "DAL", "headshot_url": "http://h/lamb.png"},
    {"player_id": "g3", "week": 2, "player_display_name": "Josh Allen", "recent_team": "BUF", "headshot_url": "http://h/allen.png"},
])
SNAP = {"teams": [{"roster_id": 1, "team_name": "Mine", "player_ids": ["g1", "gX"]},
                  {"roster_id": 2, "team_name": "Theirs", "player_ids": ["g2", "g3"]}]}


def item(title, link, ts=0):
    return {"source": "t", "title": title, "summary": "", "link": link, "published": "", "image": None, "ts": ts}


class NewsRostersTests(unittest.TestCase):
    def setUp(self):
        tools._NEWS_ROSTER_CACHE.clear()
        for p in (mock.patch.object(tools.sleeper, "league_snapshot", return_value=SNAP),
                  mock.patch.object(tools.sleeper, "get_nfl_state", return_value={"season_type": "regular", "week": 7}),
                  mock.patch.object(tools.sleeper, "matchups_for_week", return_value=[{"roster_ids": [1, 2]}]),
                  mock.patch.object(tools, "load_bundle", return_value={"wk": WK})):
            p.start(); self.addCleanup(p.stop)

    def test_names_and_teams_for_me_and_my_opponent_without_projecting_anyone(self):
        out = tools.news_rosters("L1", 1)
        self.assertEqual(out["nfl_week"], 7)
        self.assertEqual(out["my_team"]["team_name"], "Mine")
        self.assertEqual(out["my_team"]["players"], [{"player_id": "g1", "player_display_name": "Kenneth Walker III",
                                                      "recent_team": "SEA", "headshot_url": "http://h/walker.png"}])
        self.assertEqual(out["opponent"]["team_name"], "Theirs")
        self.assertEqual({(p["player_display_name"], p["recent_team"]) for p in out["opponent"]["players"]},
                         {("CeeDee Lamb", "DAL"), ("Josh Allen", "BUF")})

    def test_no_matchup_means_no_opponent_and_unknown_roster_raises(self):
        with mock.patch.object(tools.sleeper, "matchups_for_week", side_effect=RuntimeError("no schedule")):
            self.assertIsNone(tools.news_rosters("L1", 1)["opponent"])
        with self.assertRaises(ValueError):
            tools.news_rosters("L1", 99)

    def test_preseason_defaults_to_week_one_and_results_are_cached(self):
        with mock.patch.object(tools.sleeper, "get_nfl_state", return_value={"season_type": "off", "week": 0}):
            self.assertEqual(tools.news_rosters("L1", 1)["nfl_week"], 1)
        with mock.patch.object(tools.sleeper, "league_snapshot", side_effect=AssertionError("should be cached")):
            tools.news_rosters("L1", 1)


class ApiNewsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server.app.dependency_overrides[server.current_user] = lambda: {"id": 1, "username": "t"}
        self.addCleanup(server.app.dependency_overrides.clear)
        self.items = [item("CeeDee Lamb scores twice", "a", 100), item("Cowboys notebook", "b", 200),
                      item("Seahawks: Walker questionable", "c", 300), item("Packers sign a punter", "d", 400)]
        team = {"nfl_week": 7, "my_team": {"team_name": "Mine", "players": [
            {"player_id": "g1", "player_display_name": "Kenneth Walker III", "recent_team": "SEA", "headshot_url": "http://h/walker.png"},
            {"player_id": "g2", "player_display_name": "CeeDee Lamb", "recent_team": "DAL", "headshot_url": "http://h/lamb.png"}]},
            "opponent": {"team_name": "Theirs", "players": [{"player_id": "g3", "player_display_name": "Josh Allen", "recent_team": "BUF"}]}}
        for p in (mock.patch.object(server.news_layer, "all_headlines", return_value=self.items),
                  mock.patch.object(server.db, "get_active_team", return_value={"platform": "sleeper", "league_id": "L1", "roster_id": 1}),
                  mock.patch.object(server.tools, "news_rosters", return_value=team),
                  mock.patch.object(server.tools, "team_player_roster", return_value=[]),
                  mock.patch.object(server.tools, "my_team", side_effect=AssertionError("my_team is too heavy for news"))):
            p.start(); self.addCleanup(p.stop)

    def test_team_scope_ranks_matches_then_adds_team_news_and_skips_my_team(self):
        body = self.client.get("/api/news?scope=team").json()
        self.assertEqual([i["link"] for i in body["items"]], ["a", "c", "b"])         # name, surname+team, team news
        self.assertEqual([i["match_kind"] for i in body["items"]], ["name", "surname", "team"])
        self.assertEqual(body["team_name"], "Mine")
        self.assertEqual(body["sources"], list(news.FEEDS))
        # every card has a stand-in picture before its own photo is known: headshot for a player, logo for team news
        self.assertEqual(body["items"][0]["fallback_image"], "http://h/lamb.png")
        self.assertEqual(body["items"][1]["fallback_image"], "http://h/walker.png")
        self.assertTrue(body["items"][2]["fallback_image"].endswith("/dal.png"))

    def test_opponent_scope_only_shows_opponent_matches(self):
        body = self.client.get("/api/news?scope=opponent").json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["team_name"], "Theirs")

    def test_league_scope_puts_matches_first_then_newest(self):
        with mock.patch.object(server.db, "get_active_team", return_value={"platform": "sleeper", "league_id": "L1", "roster_id": 1}), \
                mock.patch.object(server.tools, "league_all_player_names", return_value=[
                    {"player_id": "g2", "player_display_name": "CeeDee Lamb", "recent_team": "DAL"}]):
            body = self.client.get("/api/news?scope=league").json()
        self.assertEqual([i["link"] for i in body["items"]], ["a", "d", "c", "b"])    # match, then the rest newest-first
        self.assertNotIn("match_kind", body["items"][1])

    def test_team_scope_needs_no_sign_in_and_lists_only_that_teams_stories_newest_first(self):
        server.app.dependency_overrides[server.current_user] = lambda: None
        body = self.client.get("/api/news?scope=favorite&team=DAL").json()
        self.assertEqual([i["link"] for i in body["items"]], ["b"])                     # the Lamb story names no team word, the Cowboys notebook does
        self.assertEqual(body["team"], "DAL")

    def test_favorite_scope_matches_city_and_nickname_and_ignores_other_teams(self):
        self.items.append(item("Seattle signs a corner", "e", 500))
        body = self.client.get("/api/news?scope=favorite&team=SEA").json()
        self.assertEqual([i["link"] for i in body["items"]], ["e", "c"])
        self.assertTrue(all(i["match_kind"] == "team" for i in body["items"]))
        self.assertTrue(body["items"][0]["fallback_image"].endswith("/sea.png"))

    def test_favorite_scope_rejects_a_missing_or_unknown_team(self):
        self.assertEqual(self.client.get("/api/news?scope=favorite").status_code, 422)
        self.assertEqual(self.client.get("/api/news?scope=favorite&team=XYZ").status_code, 422)

    def test_favorite_scope_names_the_player_each_story_is_about(self):
        self.items[:] = [item("Cowboys: CeeDee Lamb scores twice", "a", 100), item("Cowboys notebook", "b", 200)]
        roster = [{"player_id": "g2", "player_display_name": "CeeDee Lamb", "recent_team": "DAL", "headshot_url": "http://h/lamb.png"}]
        with mock.patch.object(server.tools, "team_player_roster", return_value=roster):
            body = self.client.get("/api/news?scope=favorite&team=DAL").json()
        by = {i["link"]: i for i in body["items"]}
        self.assertEqual([m["name"] for m in by["a"]["matched_players"]], ["CeeDee Lamb"])
        self.assertEqual(by["a"]["match_kind"], "name")
        self.assertEqual(by["a"]["fallback_image"], "http://h/lamb.png")
        self.assertEqual(by["b"]["matched_players"], [])
        self.assertEqual(by["b"]["match_kind"], "team")

    def test_favorite_scope_survives_a_roster_lookup_failure(self):
        with mock.patch.object(server.tools, "team_player_roster", side_effect=RuntimeError("no data")):
            body = self.client.get("/api/news?scope=favorite&team=DAL").json()
        self.assertEqual([i["link"] for i in body["items"]], ["b"])


if __name__ == "__main__":
    unittest.main()
