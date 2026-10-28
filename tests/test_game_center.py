"""engine.game_center: broadcast badges, field position, odds, weather, injuries and the play-by-play with fantasy points,
all parsed defensively from ESPN's public summary/scoreboard JSON. No network."""
import unittest
from unittest import mock

from engine import game_center as G

ET_THU = "2026-10-30T00:15Z"     # Thursday 8:15 pm ET
ET_SUN_NIGHT = "2026-11-02T01:20Z"   # Sunday 8:20 pm ET
ET_MON = "2026-11-03T01:15Z"     # Monday 8:15 pm ET
ET_SUN_AFT = "2026-11-01T17:00Z"     # Sunday 1:00 pm ET


class BadgeTest(unittest.TestCase):
    def test_prime_time_slots(self):
        self.assertEqual(G.broadcast_badge(ET_THU), "TNF")
        self.assertEqual(G.broadcast_badge(ET_SUN_NIGHT), "SNF")
        self.assertEqual(G.broadcast_badge(ET_MON), "MNF")

    def test_regular_windows_and_bad_input_have_no_badge(self):
        self.assertIsNone(G.broadcast_badge(ET_SUN_AFT))
        self.assertIsNone(G.broadcast_badge("2026-10-31T17:00Z"))     # Saturday
        for bad in (None, "", "nonsense"):
            self.assertIsNone(G.broadcast_badge(bad))


class SituationTest(unittest.TestCase):
    TEAMS = {"8": "DET", "9": "GB"}

    def sit(self, **kw):
        d = {"down": 2, "distance": 4, "yardLine": 38, "possession": "8", "possessionText": "DET 38", "isRedZone": False,
             "downDistanceText": "2nd & 4 at DET 38"}
        d.update(kw)
        return G.situation(d, home="DET", away="GB", teams=self.TEAMS)

    def test_home_offense_drives_right_to_left_and_position_is_from_the_left(self):
        s = self.sit()                                   # own 38, DET is home: its goal is on the right
        self.assertEqual((s["possession"], s["direction"], s["down"], s["distance"]), ("DET", "right-to-left", 2, 4))
        self.assertEqual(s["yard_line"], 100 - 38)

    def test_away_offense_drives_left_to_right(self):
        s = self.sit(possession="9", possessionText="GB 25", downDistanceText="1st & 10 at GB 25")
        self.assertEqual((s["possession"], s["direction"], s["yard_line"]), ("GB", "left-to-right", 25))

    def test_opponent_territory_counts_from_the_other_end(self):
        s = self.sit(possession="9", possessionText="DET 18", isRedZone=True)       # GB at the DET 18
        self.assertEqual(s["yard_line"], 82)
        self.assertTrue(s["is_red_zone"])

    def test_line_to_gain_follows_the_drive_direction_and_stops_at_the_goal_line(self):
        s = self.sit(possession="9", possessionText="GB 25", distance=10)
        self.assertEqual(s["line_to_gain"], 35)
        s2 = self.sit(possession="9", possessionText="DET 3", distance=8)
        self.assertEqual(s2["line_to_gain"], 100)
        s3 = self.sit(possessionText="DET 38", distance=10)                          # home: toward the left
        self.assertEqual(s3["line_to_gain"], 52)

    def test_red_zone_is_inferred_from_field_position_when_the_flag_is_missing(self):
        s = self.sit(possession="9", possessionText="DET 15", isRedZone=None)
        self.assertTrue(s["is_red_zone"])

    def test_missing_or_garbled_situation_is_none(self):
        for bad in (None, {}, {"down": 1}, {"possession": "99", "possessionText": "ZZZ 5"}):
            self.assertIsNone(G.situation(bad, home="DET", away="GB", teams=self.TEAMS))


class OddsWeatherInjuriesTest(unittest.TestCase):
    def test_odds_give_spread_total_and_each_sides_implied_score(self):
        js = {"pickcenter": [{"details": "DET -3.5", "overUnder": 48.0, "spread": -3.5, "homeTeamOdds": {"favorite": True}}]}
        o = G.parse_odds(js, home="DET", away="GB")
        self.assertEqual((o["favorite"], o["spread"], o["total"]), ("DET", 3.5, 48.0))
        self.assertEqual((o["home_implied"], o["away_implied"]), (25.8, 22.2))

    def test_moneylines_are_read_from_the_pick_center_too(self):
        js = {"pickcenter": [{"details": "DET -3.5", "overUnder": 48.0, "homeTeamOdds": {"favorite": True, "moneyLine": -170}, "awayTeamOdds": {"moneyLine": 145}}]}
        o = G.parse_odds(js, home="DET", away="GB")
        self.assertEqual((o["home_ml"], o["away_ml"]), (-170, 145))

    def test_odds_missing_is_none_and_pickem_has_no_favorite(self):
        self.assertIsNone(G.parse_odds({}, home="DET", away="GB"))
        o = G.parse_odds({"pickcenter": [{"details": "EVEN", "overUnder": 40.0, "spread": 0}]}, home="DET", away="GB")
        self.assertIsNone(o["favorite"])
        self.assertEqual((o["home_implied"], o["away_implied"]), (20.0, 20.0))

    def test_weather_flags_wind_of_fifteen_or_more(self):
        js = {"gameInfo": {"weather": {"temperature": 41, "displayValue": "Cloudy", "windSpeed": 17, "precipitation": 20}, "venue": {"indoor": False}}}
        w = G.parse_weather(js)
        self.assertEqual((w["temp"], w["wind"], w["wind_alert"], w["indoor"]), (41, 17, True, False))
        w2 = G.parse_weather({"gameInfo": {"weather": {"temperature": 70, "windSpeed": 6}}})
        self.assertFalse(w2["wind_alert"])

    def test_indoor_and_missing_weather(self):
        self.assertTrue(G.parse_weather({"gameInfo": {"venue": {"indoor": True}}})["indoor"])
        self.assertIsNone(G.parse_weather({}))

    def test_injuries_are_listed_by_team(self):
        js = {"injuries": [{"team": {"abbreviation": "DET"}, "injuries": [
            {"athlete": {"displayName": "Amon-Ra St. Brown", "position": {"abbreviation": "WR"}}, "status": "Questionable", "details": {"type": "Ankle"}}]}]}
        inj = G.parse_injuries(js)
        self.assertEqual(inj, {"DET": [{"name": "Amon-Ra St. Brown", "position": "WR", "status": "Questionable", "detail": "Ankle"}]})
        self.assertEqual(G.parse_injuries({}), {})


def play(pid, text, kind, yds=0, td=False, period=3, clock="8:42", away=10, home=17, parts=(), scoring=False, down=2, dist=4):
    return {"id": pid, "text": text, "type": {"text": kind}, "statYardage": yds, "scoringPlay": scoring or td, "scoreValue": 6 if td else 0,
            "period": {"number": period}, "clock": {"displayValue": clock}, "awayScore": away, "homeScore": home,
            "start": {"down": down, "distance": dist, "yardLine": 38, "team": {"id": "8"}},
            "participants": [{"type": t, "athlete": {"id": a}} for t, a in parts]}


SUMMARY = {"drives": {"previous": [{"team": {"abbreviation": "DET"}, "plays": [
    play("1", "J.Gibbs rush up the middle for 14 yards, TOUCHDOWN", "Rushing Touchdown", 14, True, parts=[("rusher", "g")], scoring=True),
    play("2", "J.Goff pass incomplete short right intended for A.St. Brown", "Pass Incompletion", 0, parts=[("passer", "q"), ("target", "w")]),
    play("3", "J.Goff pass short left to A.St. Brown for 12 yards", "Pass Reception", 12, parts=[("passer", "q"), ("receiver", "w")]),
    play("4", "J.Goff pass intercepted by X", "Pass Interception Return", 0, parts=[("passer", "q")]),
    play("5", "Punt for 45 yards", "Punt", 45),
]}], "current": {"team": {"abbreviation": "GB"}, "plays": [play("6", "J.Love sacked", "Sack", -7, parts=[("passer", "l")])]}}}
NAMES = {"g": ("Jahmyr Gibbs", "RB", "DET"), "q": ("Jared Goff", "QB", "DET"), "w": ("Amon-Ra St. Brown", "WR", "DET"), "l": ("Jordan Love", "QB", "GB")}


class PlaysTest(unittest.TestCase):
    def setUp(self):
        self.plays = G.parse_plays(SUMMARY, NAMES, None, mine={"g", "w"})

    def test_newest_first_with_clock_quarter_and_scoring_flag(self):
        self.assertEqual([p["id"] for p in self.plays][:2], ["6", "5"])
        td = next(p for p in self.plays if p["id"] == "1")
        self.assertTrue(td["scoring"])
        self.assertEqual((td["quarter"], td["clock"], td["team"]), (3, "8:42", "DET"))

    def test_rushing_td_credits_the_runner_with_yards_and_the_touchdown(self):
        td = next(p for p in self.plays if p["id"] == "1")
        self.assertEqual(td["fantasy"], [{"name": "Jahmyr Gibbs", "position": "RB", "points": 7.4, "mine": True}])    # 14 x 0.1 + 6

    def test_a_reception_credits_the_receiver_ppr_and_the_passer_yardage(self):
        r = next(p for p in self.plays if p["id"] == "3")
        by = {f["name"]: f for f in r["fantasy"]}
        self.assertEqual(by["Amon-Ra St. Brown"]["points"], 2.2)         # 1 rec + 1.2
        self.assertTrue(by["Amon-Ra St. Brown"]["mine"])
        self.assertEqual(by["Jared Goff"]["points"], 0.5)                # 12 x 0.04
        self.assertFalse(by["Jared Goff"]["mine"])

    def test_an_interception_costs_the_passer_and_an_incompletion_scores_nobody(self):
        ic = next(p for p in self.plays if p["id"] == "4")
        self.assertEqual(ic["fantasy"], [{"name": "Jared Goff", "position": "QB", "points": -2.0, "mine": False}])
        inc = next(p for p in self.plays if p["id"] == "2")
        self.assertEqual(inc["fantasy"], [])
        self.assertEqual(inc["target"], "Amon-Ra St. Brown")             # the intended receiver is still named

    def test_scoring_follows_the_leagues_settings(self):
        std = G.parse_plays(SUMMARY, NAMES, {"reception": 0.0}, mine=set())
        r = next(p for p in std if p["id"] == "3")
        self.assertEqual({f["name"]: f["points"] for f in r["fantasy"]}["Amon-Ra St. Brown"], 1.2)

    def test_garbage_degrades_to_no_plays(self):
        for bad in (None, {}, {"drives": None}, {"drives": {"previous": [{"plays": None}]}}):
            self.assertEqual(G.parse_plays(bad, NAMES, None, mine=set()), [])


class CenterTest(unittest.TestCase):
    def test_center_bundles_everything_and_never_raises_on_a_bare_summary(self):
        out = G.center({}, game={"home": {"abbr": "DET"}, "away": {"abbr": "GB"}}, names={}, scoring=None, mine=set())
        self.assertEqual((out["plays"], out["injuries"]), ([], {}))
        self.assertIsNone(out["odds"])
        self.assertIsNone(out["weather"])

    def test_situation_comes_from_the_summary_when_present(self):
        js = {"situation": {"down": 3, "distance": 7, "possession": "9", "possessionText": "GB 41", "downDistanceText": "3rd & 7 at GB 41"},
              "header": {"competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "8", "abbreviation": "DET"}},
                                                           {"homeAway": "away", "team": {"id": "9", "abbreviation": "GB"}}]}]}}
        out = G.center(js, game={"home": {"abbr": "DET"}, "away": {"abbr": "GB"}}, names={}, scoring=None, mine=set())
        self.assertEqual((out["situation"]["possession"], out["situation"]["yard_line"]), ("GB", 41))


class EndpointTest(unittest.TestCase):
    GAME = {"game_id": "401772510", "home": {"abbr": "DET"}, "away": {"abbr": "GB"}, "badge": "SNF", "state": "in",
            "odds": {"favorite": "DET", "spread": 3.5, "total": 48.0}, "weather": None, "situation": {"possession": "DET"}}

    def setUp(self):
        from fastapi.testclient import TestClient
        import server
        from engine import boxscore as B
        self.server, self.B = server, B
        self.client = TestClient(server.app)
        server.app.dependency_overrides[server.current_user] = lambda: {"id": 1, "username": "t"}
        self.addCleanup(server.app.dependency_overrides.clear)
        parsed = {"teams": [{"abbr": "DET", "name": "Lions", "logo": None, "players": [
            {"athlete_id": "g", "name": "Jahmyr Gibbs", "position": "RB", "team": "DET", "headshot": None, "stats": {"rushing": {"rushingYards": 90, "rushingTouchdowns": 1, "carries": 15}}}]}]}
        for p in (mock.patch.object(server.boxscore_layer, "game_boxscore", return_value=parsed),
                  mock.patch.object(server.boxscore_layer, "game_summary_raw", return_value=SUMMARY),
                  mock.patch.object(server.live_scores_layer, "live_scoreboard", return_value=[self.GAME]),
                  mock.patch.object(server, "_effective_scoring", return_value=None),
                  mock.patch.object(server.tools, "matchup_profile", return_value={"home": {"abbr": "DET"}, "away": {"abbr": "GB"}, "prediction": {"pick": "home"}}),
                  mock.patch.object(server, "_load_my_team", return_value=({}, {"my_team": {"players": [
                      {"player_id": "x", "player_display_name": "Jahmyr Gibbs", "position": "RB", "recent_team": "DET", "PROJ": 17.0,
                       "floor": 8, "ceiling": 28, "is_starter": True, "injury_status": None},
                      {"player_id": "y", "player_display_name": "Other Guy", "position": "WR", "recent_team": "KC", "PROJ": 9.0}]}}))):
            p.start(); self.addCleanup(p.stop)

    def test_center_returns_box_plays_and_the_viewers_projections_for_this_game_only(self):
        body = self.client.get("/api/live-scores/401772510/center").json()
        self.assertEqual(body["game"]["badge"], "SNF")
        self.assertEqual(body["box"]["mine_count"], 1)
        self.assertEqual([p["name"] for p in body["projections"]], ["Jahmyr Gibbs"])        # the KC player is not in this game
        self.assertEqual(body["projections"][0]["proj"], 17.0)
        td = next(p for p in body["plays"] if p["id"] == "1")
        self.assertEqual(td["fantasy"][0]["mine"], True)
        self.assertEqual(body["odds"]["favorite"], "DET")        # falls back to the scoreboard's odds

    def test_the_matchup_and_the_lineup_lab_pick_are_included(self):
        body = self.client.get("/api/live-scores/401772510/center").json()
        self.assertEqual(body["matchup"]["prediction"]["pick"], "home")

    def test_a_failing_matchup_lookup_does_not_break_the_page(self):
        with mock.patch.object(self.server.tools, "matchup_profile", side_effect=RuntimeError("no data")):
            r = self.client.get("/api/live-scores/401772510/center")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["matchup"])

    def test_bad_game_id_is_400(self):
        self.assertEqual(self.client.get("/api/live-scores/abc/center").status_code, 400)

    def test_athlete_index_flags_the_viewers_players(self):
        parsed = {"teams": [{"abbr": "DET", "players": [{"athlete_id": "g", "name": "Jahmyr Gibbs", "position": "RB", "team": "DET"},
                                                         {"athlete_id": "q", "name": "Jared Goff", "position": "QB", "team": "DET"}]}]}
        names, mine = self.B.athlete_index(parsed, [{"player_display_name": "Jahmyr Gibbs", "position": "RB", "recent_team": "DET"}])
        self.assertEqual(names["g"], ("Jahmyr Gibbs", "RB", "DET"))
        self.assertEqual(mine, {"g"})


if __name__ == "__main__":
    unittest.main()
