import copy
import unittest
from unittest import mock

from engine import boxscore as B


def _cat(name, keys, rows):
    return {"name": name, "keys": keys, "athletes": [
        {"athlete": {"id": i, "displayName": n, "position": {"abbreviation": pos}}, "stats": st} for i, n, pos, st in rows]}


# Shaped like ESPN's /summary boxscore.players block.
SUMMARY = {"boxscore": {"players": [
    {"team": {"abbreviation": "DET", "shortDisplayName": "Lions"}, "statistics": [
        _cat("passing", ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt", "passingTouchdowns", "interceptions", "sacks-sackYardsLost"],
             [("1", "Jared Goff", "QB", ["22/30", "250", "8.3", "2", "1", "2-15"])]),
        _cat("rushing", ["carries", "rushingYards", "yardsPerRushAttempt", "rushingTouchdowns", "longRushing"],
             [("1", "Jared Goff", "QB", ["2", "-3", "-1.5", "0", "1"]), ("2", "Jahmyr Gibbs", "RB", ["15", "90", "6.0", "1", "30"])]),
        _cat("receiving", ["receptions", "receivingYards", "yardsPerReception", "receivingTouchdowns", "longReception", "receivingTargets"],
             [("3", "Amon-Ra St. Brown", "WR", ["8", "100", "12.5", "1", "30", "11"]), ("2", "Jahmyr Gibbs", "RB", ["3", "20", "6.7", "0", "9", "4"])]),
        _cat("fumbles", ["fumbles", "fumblesLost", "fumblesRecovered"], [("3", "Amon-Ra St. Brown", "WR", ["1", "1", "0"])]),
        _cat("kicking", ["fieldGoalsMade/fieldGoalAttempts", "extraPointsMade/extraPointAttempts"],
             [("9", "Jake Bates", "K", ["2/3", "3/3"])]),
    ]},
    {"team": {"abbreviation": "GB", "shortDisplayName": "Packers"}, "statistics": [
        _cat("receiving", ["receptions", "receivingYards", "receivingTouchdowns"], [("7", "Christian Watson", "WR", ["4", "60", "0"])]),
    ]},
]}}


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.t = {t["abbr"]: t for t in B.parse_summary(SUMMARY)["teams"]}

    def test_one_row_per_player_with_categories_merged(self):
        goff = next(p for p in self.t["DET"]["players"] if p["name"] == "Jared Goff")
        self.assertEqual(set(goff["stats"]), {"passing", "rushing"})
        self.assertEqual(len(self.t["DET"]["players"]), 4)

    def test_packed_stats_are_split_and_negatives_survive(self):
        goff = next(p for p in self.t["DET"]["players"] if p["name"] == "Jared Goff")
        self.assertEqual(goff["stats"]["passing"]["completions"], 22)
        self.assertEqual(goff["stats"]["passing"]["passingAttempts"], 30)
        self.assertEqual(goff["stats"]["passing"]["sackYardsLost"], 15)
        self.assertEqual(goff["stats"]["rushing"]["rushingYards"], -3)

    def test_garbage_degrades_to_no_teams(self):
        for bad in (None, {}, {"boxscore": None}, {"boxscore": {"players": [{"team": None, "statistics": [{"name": None}]}]}}, []):
            try:
                out = B.parse_summary(bad)
            except Exception as e:
                self.fail(f"{bad!r} raised {e!r}")
            self.assertIsInstance(out["teams"], list)


class AnnotateTest(unittest.TestCase):
    ROSTER = [{"player_display_name": "Amon-Ra St. Brown", "position": "WR", "recent_team": "DET"},
              {"player_display_name": "Jahmyr Gibbs", "position": "RB", "recent_team": "DET"}]

    def test_points_follow_the_leagues_scoring(self):
        ppr = B.annotate(B.parse_summary(SUMMARY), self.ROSTER, None)
        std = B.annotate(B.parse_summary(SUMMARY), self.ROSTER, {"reception": 0.0})
        pts = lambda out, n: next(p for t in out["teams"] for p in t["players"] if p["name"] == n)["fantasy_points"]
        # Amon-Ra: 8 rec, 100 yds, 1 TD, 1 fumble lost -> 8 + 10 + 6 - 2 = 22 (PPR), 14 (standard)
        self.assertEqual(pts(ppr, "Amon-Ra St. Brown"), 22.0)
        self.assertEqual(pts(std, "Amon-Ra St. Brown"), 14.0)
        # Goff: 250 yds, 2 TD, 1 INT, -3 rush -> 10 + 8 - 2 - 0.3 = 15.7
        self.assertEqual(pts(ppr, "Jared Goff"), 15.7)

    def test_mine_flagged_and_summed(self):
        out = B.annotate(B.parse_summary(SUMMARY), self.ROSTER, None)
        det = next(t for t in out["teams"] if t["abbr"] == "DET")["players"]
        self.assertEqual({p["name"] for p in det if p["mine"]}, {"Amon-Ra St. Brown", "Jahmyr Gibbs"})
        self.assertEqual(out["mine_count"], 2)
        # Gibbs: 90 + 20 yds -> 11, 1 TD -> 6, 3 rec -> 3 = 20.0 ; plus Amon-Ra 22
        self.assertEqual(out["mine_points"], 42.0)

    def test_players_are_grouped_qb_rb_wr_te_k_then_best_fantasy_points_first(self):
        s = copy.deepcopy(SUMMARY)
        det = s["boxscore"]["players"][0]["statistics"]
        det[0]["athletes"].append({"athlete": {"id": "11", "displayName": "Backup QB", "position": {"abbreviation": "QB"}},
                                   "stats": ["3/4", "20", "5.0", "0", "0", "0-0"]})
        det[1]["athletes"].extend([
            {"athlete": {"id": "12", "displayName": "RB Two", "position": {"abbreviation": "RB"}}, "stats": ["4", "10", "2.5", "0", "5"]},
            {"athlete": {"id": "13", "displayName": "RB Three", "position": {"abbreviation": "RB"}}, "stats": ["20", "120", "6.0", "1", "40"]}])
        out = B.annotate(B.parse_summary(s), [], None)
        names = [p["name"] for p in next(t for t in out["teams"] if t["abbr"] == "DET")["players"]]
        self.assertEqual(names, ["Jared Goff", "Backup QB", "Jahmyr Gibbs", "RB Three", "RB Two", "Amon-Ra St. Brown", "Jake Bates"])

    def test_stat_lines_lead_with_the_positions_main_category(self):
        out = B.annotate(B.parse_summary(SUMMARY), [], None)
        by = {p["name"]: [l["label"] for l in p["lines"]] for t in out["teams"] for p in t["players"]}
        self.assertEqual(by["Jahmyr Gibbs"], ["Rushing", "Receiving"])
        self.assertEqual(by["Jared Goff"], ["Passing", "Rushing"])
        self.assertEqual(by["Amon-Ra St. Brown"][0], "Receiving")

    def test_players_and_teams_carry_logo_and_headshot(self):
        s = copy.deepcopy(SUMMARY)
        s["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["athlete"]["headshot"] = {"href": "https://a.espncdn.com/x.png"}
        s["boxscore"]["players"][0]["team"]["logo"] = "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"
        out = B.annotate(B.parse_summary(s), [], None)
        det = next(t for t in out["teams"] if t["abbr"] == "DET")
        self.assertTrue(det["logo"].endswith("/det.png"))
        self.assertEqual(det["players"][0]["headshot"], "https://a.espncdn.com/x.png")
        self.assertEqual(det["players"][0]["team"], "DET")

    def test_wrong_team_is_not_mine(self):
        roster = [{"player_display_name": "Christian Watson", "position": "WR", "recent_team": "DET"}]
        self.assertEqual(B.annotate(B.parse_summary(SUMMARY), roster, None)["mine_count"], 0)

    def test_team_aliases_match(self):
        s = copy.deepcopy(SUMMARY)
        s["boxscore"]["players"][1]["team"]["abbreviation"] = "WSH"
        roster = [{"player_display_name": "Christian Watson", "position": "WR", "recent_team": "WAS"}]
        self.assertEqual(B.annotate(B.parse_summary(s), roster, None)["mine_count"], 1)

    def test_kicker_has_lines_but_no_points(self):
        out = B.annotate(B.parse_summary(SUMMARY), [], None)
        k = next(p for t in out["teams"] for p in t["players"] if p["name"] == "Jake Bates")
        self.assertIsNone(k["fantasy_points"])
        self.assertEqual(k["lines"][0]["text"], "2/3 FG, 3/3 XP")

    def test_annotate_does_not_edit_the_cached_parse(self):
        parsed = B.parse_summary(SUMMARY)
        B.annotate(parsed, self.ROSTER, None)
        B.annotate(parsed, self.ROSTER, None)   # a second request must still work
        self.assertIn("stats", parsed["teams"][0]["players"][0])

    def test_no_roster_means_nothing_highlighted(self):
        out = B.annotate(B.parse_summary(SUMMARY), None, None)
        self.assertEqual((out["mine_count"], out["mine_points"]), (0, 0.0))


class FetchTest(unittest.TestCase):
    def setUp(self):
        B._CACHE.clear()

    def test_bad_ids_are_rejected_before_any_request(self):
        for bad in ("", "abc", "../etc", "401772?x=1", None, "1"):
            with mock.patch.object(B.requests, "get") as g:
                with self.assertRaises(ValueError):
                    B.game_boxscore(bad)
                g.assert_not_called()

    def test_cached_within_ttl_and_failure_serves_last_good(self):
        ok = mock.Mock(); ok.json.return_value = SUMMARY; ok.raise_for_status.return_value = None
        with mock.patch.object(B.requests, "get", return_value=ok) as g:
            B.game_boxscore("401772510"); B.game_boxscore("401772510")
            self.assertEqual(g.call_count, 1)
            first = B.game_boxscore("401772510")
        with mock.patch.object(B.requests, "get", side_effect=RuntimeError("down")):
            self.assertIs(B.game_boxscore("401772510", force=True), first)
            self.assertEqual(B.game_boxscore("401772999"), {"teams": []})


if __name__ == "__main__":
    unittest.main()


class EndpointTest(unittest.TestCase):
    """GET /api/live-scores/{game_id}: no network, no database."""

    def setUp(self):
        from fastapi.testclient import TestClient
        import server
        self.server = server
        server.app.dependency_overrides[server.scoring_from_query] = lambda: None
        self.client = TestClient(server.app)
        self.addCleanup(server.app.dependency_overrides.clear)
        p = mock.patch.object(server.boxscore_layer, "game_boxscore", side_effect=lambda gid: B.parse_summary(SUMMARY))
        p.start(); self.addCleanup(p.stop)

    def test_bad_id_is_400(self):
        self.server.app.dependency_overrides[self.server.current_user] = lambda: None
        self.assertEqual(self.client.get("/api/live-scores/not-a-game").status_code, 400)

    def test_signed_out_gets_points_but_no_highlights(self):
        self.server.app.dependency_overrides[self.server.current_user] = lambda: None
        r = self.client.get("/api/live-scores/401772510")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["mine_count"], 0)
        self.assertFalse(any(p["mine"] for t in body["teams"] for p in t["players"]))
        self.assertIn("fantasy_points", body["teams"][0]["players"][0])

    def test_signed_in_players_are_highlighted(self):
        self.server.app.dependency_overrides[self.server.current_user] = lambda: {"id": 1, "username": "t"}
        team = {"my_team": {"players": [{"player_display_name": "Jahmyr Gibbs", "position": "RB", "recent_team": "DET"}]}}
        with mock.patch.object(self.server, "_load_my_team", return_value=({}, team)), \
                mock.patch.object(self.server, "_effective_scoring", return_value=None):
            body = self.client.get("/api/live-scores/401772510").json()
        self.assertEqual(body["mine_count"], 1)
        self.assertEqual([p["name"] for t in body["teams"] for p in t["players"] if p["mine"]], ["Jahmyr Gibbs"])

    def test_roster_failure_still_returns_the_box_score(self):
        self.server.app.dependency_overrides[self.server.current_user] = lambda: {"id": 1, "username": "t"}
        with mock.patch.object(self.server, "_load_my_team", side_effect=RuntimeError("sleeper down")), \
                mock.patch.object(self.server, "_effective_scoring", return_value=None):
            r = self.client.get("/api/live-scores/401772510")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["mine_count"], 0)

    def test_settings_store_down_still_returns_the_box_score(self):
        self.server.app.dependency_overrides[self.server.current_user] = lambda: {"id": 1, "username": "t"}
        with mock.patch.object(self.server, "_load_my_team", side_effect=RuntimeError("db down")), \
                mock.patch.object(self.server, "_effective_scoring", side_effect=RuntimeError("db down")):
            r = self.client.get("/api/live-scores/401772510")
        self.assertEqual(r.status_code, 200)
