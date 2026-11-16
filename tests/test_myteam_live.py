"""engine.myteam_live (clock -> seconds left, team aliases, per-player and team totals) and GET /api/myteam/live with the
league site and the scoreboard mocked. No network."""
import unittest
from unittest import mock

from engine import myteam_live as ml

NOW = 1_800_000_000.0


def iso(offset):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(NOW + offset, timezone.utc).isoformat().replace("+00:00", "Z")


def game(home, away, state, period=0, clock=None, hs=0, as_=0, kick=0, week=11):
    return {"game_id": home + away, "week": week, "kickoff": iso(kick), "state": state, "period": period,
            "display_clock": clock, "status_detail": f"{clock} - Q{period}",
            "home": {"abbr": home, "score": hs}, "away": {"abbr": away, "score": as_}}


class ClockTests(unittest.TestCase):
    def test_parse_clock(self):
        self.assertEqual(ml.parse_clock("10:42"), 642.0)
        self.assertEqual(ml.parse_clock("0:48"), 48.0)
        self.assertEqual(ml.parse_clock("48.0"), 48.0)
        self.assertIsNone(ml.parse_clock(""))
        self.assertIsNone(ml.parse_clock(None))
        self.assertIsNone(ml.parse_clock("Final"))

    def test_seconds_left_by_quarter(self):
        self.assertEqual(ml.seconds_left("in", 1, "15:00"), 3600)
        self.assertEqual(ml.seconds_left("in", 3, "10:42"), 900 + 642)
        self.assertEqual(ml.seconds_left("in", 4, "0:30"), 30)
        self.assertEqual(ml.seconds_left("in", 4, "0:00"), 0)

    def test_halftime_is_1800(self):
        self.assertEqual(ml.seconds_left("in", 2, "0:00"), 1800)

    def test_overtime_and_final_are_zero_and_pre_or_unreadable_is_none(self):
        self.assertEqual(ml.seconds_left("in", 5, "7:00"), 0)
        self.assertEqual(ml.seconds_left("post", 4, "0:00"), 0)
        self.assertIsNone(ml.seconds_left("pre", 0, None))
        self.assertIsNone(ml.seconds_left("in", 2, "garbled"))
        self.assertIsNone(ml.seconds_left("in", None, "5:00"))


class AliasTests(unittest.TestCase):
    def test_team_aliases(self):
        for raw, want in [("WSH", "WAS"), ("was", "WAS"), ("LAR", "LA"), ("LA", "LA"), ("JAC", "JAX"), ("JAX", "JAX"), ("SEA", "SEA")]:
            self.assertEqual(ml.norm_team(raw), want)
        self.assertIsNone(ml.norm_team(None))

    def test_game_index_matches_players_on_aliased_teams_and_signs_the_margin(self):
        idx = ml.game_index([game("WSH", "LAR", "in", 3, "10:00", hs=10, as_=17)], 11)
        self.assertEqual(idx["WAS"]["score_diff"], -7)
        self.assertEqual(idx["LA"]["score_diff"], 7)
        self.assertEqual(idx["LA"]["seconds_left"], 900 + 600)

    def test_a_game_from_another_week_is_ignored(self):
        self.assertEqual(ml.game_index([game("SEA", "SF", "in", 1, "5:00", week=12)], 11), {})


def starter(pid, pos, team, proj, settled=False, raw=None):
    return {"player_id": pid, "raw_id": raw or pid, "position": pos, "team": team, "proj": proj, "settled": settled, "on_bye": False}


def base(mine, opp, week=11, live=11):
    return {"week": week, "live_week": live, "platform": "sleeper",
            "my_team": {"roster_id": 1, "starters": mine}, "opponent": {"roster_id": 2, "starters": opp}}


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.games = [game("SEA", "SF", "in", 3, "10:00", hs=14, as_=14),
                      game("KC", "BUF", "post", 4, "0:00", hs=24, as_=20),
                      game("DAL", "PHI", "pre", 0, "15:00", kick=3000)]
        self.b = base([starter("a", "WR", "SEA", 12.0, raw="s1"), starter("b", "RB", "KC", 10.0, raw="s2"), starter("c", "TE", "DAL", 6.0, raw="s3")],
                      [starter("d", "QB", "BUF", 18.0, raw="s4"), starter("e", "K", "SF", 8.0, raw="s5")])
        self.pts = {"source": "sleeper", "by_roster": {1: {"s1": 5.0, "s2": 14.5, "s3": 0.0}, 2: {"s4": 21.0, "s5": 3.0}}}

    def out(self):
        return ml.compose(self.b, self.games, self.pts, now=NOW)

    def test_states_and_points_per_player(self):
        r = self.out()
        a, b, c = r["my_team"]["players"]
        self.assertEqual((a["game_state"], a["points"], a["quarter"], a["clock"]), ("in", 5.0, 3, "10:00"))
        self.assertEqual((b["game_state"], b["points"], b["live_proj"]), ("post", 14.5, 14.5))
        self.assertEqual((c["game_state"], c["points"], c["live_proj"], c["pregame_proj"]), ("pre", None, 6.0, 6.0))

    def test_in_game_live_projection_never_below_points_so_far_and_matches_the_model(self):
        a = self.out()["my_team"]["players"][0]
        self.assertGreaterEqual(a["live_proj"], 5.0)
        from engine import live_proj
        want = live_proj.live_projection("WR", 12.0, 5.0, 900 + 600, 0)["live_proj"]
        self.assertAlmostEqual(a["live_proj"], want)

    def test_team_totals(self):
        r = self.out()
        mine = r["my_team"]
        self.assertEqual(mine["points_total"], 19.5)                # 5.0 + 14.5 + 0 (pre-game player adds nothing)
        a_live = mine["players"][0]["live_proj"]
        self.assertAlmostEqual(mine["live_proj_total"], round(a_live + 14.5 + 6.0, 1), places=1)   # in-game live, final points, pre-game projection
        self.assertFalse(mine["final"])

    def test_active_when_a_game_is_on_and_wake_time_otherwise(self):
        self.assertTrue(self.out()["active"])
        quiet = [game("DAL", "PHI", "pre", 0, "15:00", kick=3000)]
        r = ml.compose(base([starter("c", "TE", "DAL", 6.0)], []), quiet, self.pts, now=NOW)
        self.assertFalse(r["active"])
        self.assertEqual(r["wake_in_seconds"], 3000 - 600)
        soon = [game("DAL", "PHI", "pre", 0, "15:00", kick=500)]
        self.assertTrue(ml.compose(base([starter("c", "TE", "DAL", 6.0)], []), soon, self.pts, now=NOW)["active"])

    def test_nothing_active_after_every_game_is_over(self):
        done = [game("KC", "BUF", "post", 4, "0:00")]
        r = ml.compose(base([starter("b", "RB", "KC", 10.0, raw="s2")], [starter("d", "QB", "BUF", 18.0, raw="s4")]), done, self.pts, now=NOW)
        self.assertFalse(r["active"])
        self.assertIsNone(r["wake_in_seconds"])
        self.assertTrue(r["my_team"]["final"])

    def test_points_unavailable_is_null_not_zero(self):
        r = ml.compose(self.b, self.games, {"source": None, "by_roster": {}, "note": "x"}, now=NOW)
        a = r["my_team"]["players"][0]
        self.assertIsNone(a["points"])
        self.assertIsNone(a["live_proj"])
        self.assertIsNone(r["my_team"]["points_total"])
        self.assertIsNone(r["points_source"])
        # the projected total still counts his pregame number
        self.assertEqual(r["my_team"]["live_proj_total"], 12.0 + 10.0 + 6.0)

    def test_settled_rows_stay_final_with_their_real_score(self):
        b = base([starter("x", "RB", "KC", 17.3, settled=True, raw="s9")], [])
        r = ml.compose(b, self.games, {"source": "sleeper", "by_roster": {1: {}}}, now=NOW)
        p = r["my_team"]["players"][0]
        self.assertEqual((p["game_state"], p["points"], p["pregame_proj"]), ("post", 17.3, None))

    def test_not_the_live_week_returns_live_false(self):
        r = ml.compose(base([], [], week=9, live=11), self.games, self.pts, now=NOW)
        self.assertFalse(r["live"])

    def test_aliased_team_codes_resolve_for_players_and_games(self):
        b = base([starter("w", "WR", "WAS", 9.0, raw="s7"), starter("r", "WR", "LA", 9.0, raw="s8")], [])
        g = [game("WSH", "LAR", "in", 1, "10:00")]
        r = ml.compose(b, g, {"source": "sleeper", "by_roster": {1: {"s7": 2.0, "s8": 1.0}}}, now=NOW)
        self.assertEqual([p["game_state"] for p in r["my_team"]["players"]], ["in", "in"])

    def test_overtime_live_proj_equals_points(self):
        g = [game("SEA", "SF", "in", 5, "5:00", hs=20, as_=20)]
        r = ml.compose(base([starter("a", "WR", "SEA", 12.0, raw="s1")], []), g, {"source": "sleeper", "by_roster": {1: {"s1": 9.0}}}, now=NOW)
        self.assertEqual(r["my_team"]["players"][0]["live_proj"], 9.0)

    def test_def_falls_back_to_time_scaling(self):
        g = [game("SEA", "SF", "in", 3, "15:00", hs=0, as_=0)]       # 1800 s left
        r = ml.compose(base([starter("SEA", "DEF", "SEA", 10.0, raw="SEA")], []), g, {"source": "sleeper", "by_roster": {1: {"SEA": 4.0}}}, now=NOW)
        self.assertAlmostEqual(r["my_team"]["players"][0]["live_proj"], 4.0 + 10.0 * 1800 / 3600)


class MakeBaseTests(unittest.TestCase):
    def test_raw_ids_come_back_through_the_inverse_crosswalk(self):
        res = {"nfl_week": 11, "live_week": 11, "my_team": {"roster_id": 3, "players": [
            {"player_id": "00-1", "position": "WR", "recent_team": "WSH", "PROJ": 11.0, "is_starter": True},
            {"player_id": "SEA", "position": "DEF", "recent_team": "SEA", "PROJ": 7.0, "is_starter": True},
            {"player_id": "00-2", "position": "RB", "recent_team": "KC", "PROJ": 3.0, "is_starter": False}]}, "opponent": None}
        b = ml.make_base(res, {"4046": "00-1"}, "sleeper")
        st = b["my_team"]["starters"]
        self.assertEqual([s["raw_id"] for s in st], ["4046", "SEA"])
        self.assertEqual(st[0]["team"], "WAS")
        self.assertEqual(len(st), 2)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        server._LIVE_BASE_CACHE.clear()
        server._MYTEAM_CACHE.clear()
        self.addCleanup(server._LIVE_BASE_CACHE.clear)
        self.addCleanup(server._MYTEAM_CACHE.clear)
        self.result = {"nfl_week": 11, "live_week": 11, "season": 2026, "my_team": {"roster_id": 1, "players": [
            {"player_id": "00-1", "position": "WR", "recent_team": "SEA", "PROJ": 12.0, "is_starter": True}]},
            "opponent": {"roster_id": 2, "players": [{"player_id": "00-9", "position": "QB", "recent_team": "SF", "PROJ": 18.0, "is_starter": True}]}}
        self.active = {"platform": "sleeper", "league_id": "L1", "roster_id": 1}
        self.calls = {"my_team": 0, "matchups": 0}

        def fake_my_team(league, roster, scoring=None, week=None):
            self.calls["my_team"] += 1
            return self.result

        def fake_matchups(league_id, week):
            self.calls["matchups"] += 1
            return [{"roster_id": 1, "players_points": {"111": 6.5}}, {"roster_id": 2, "players_points": {"222": 11.0}}]
        patches = [mock.patch.object(server.db, "get_active_team", return_value=self.active),
                   mock.patch.object(server, "_effective_scoring", side_effect=lambda s, u: s),
                   mock.patch.object(server.tools, "my_team", side_effect=fake_my_team),
                   mock.patch.object(server.sleeper_layer, "id_crosswalk", return_value={"111": "00-1", "222": "00-9"}),
                   mock.patch.object(server.sleeper_layer, "live_matchups", side_effect=fake_matchups),
                   mock.patch.object(server.live_scores_layer, "live_scoreboard",
                                     return_value=[game("SEA", "SF", "in", 2, "5:00", hs=7, as_=3)])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.user = {"id": 5, "username": "t"}

    def call(self):
        return self.server.api_my_team_live(week=None, scoring=None, user=self.user)

    def test_shape_and_values(self):
        r = self.call()
        self.assertTrue(r["live"])
        self.assertEqual(r["points_source"], "sleeper")
        me = r["my_team"]["players"][0]
        self.assertEqual((me["player_id"], me["game_state"], me["points"], me["pregame_proj"], me["quarter"], me["clock"]),
                         ("00-1", "in", 6.5, 12.0, 2, "5:00"))
        self.assertGreaterEqual(me["live_proj"], 6.5)
        self.assertEqual(r["opponent"]["players"][0]["points"], 11.0)
        self.assertEqual(r["my_team"]["points_total"], 6.5)
        self.assertTrue(r["active"])

    def test_live_response_carries_a_win_probability(self):
        r = self.call()
        self.assertIsInstance(r["win_prob"], float)
        self.assertTrue(0.0 < r["win_prob"] < 1.0)
        self.assertEqual(r["my_team"]["players"][0]["rog"] >= 0, True)

    def test_my_team_response_carries_the_pregame_win_probability(self):
        r = self.server.api_my_team(week=None, refresh=False, scoring=None, user=self.user)
        self.assertIsInstance(r["win_prob"], float)
        self.assertTrue(0.0 < r["win_prob"] < 1.0)          # 12.0 projected WR vs 18.0 projected QB: behind, but not 0

    def test_non_live_week_response_has_a_null_win_prob_key(self):
        self.result["live_week"] = 12
        self.assertIn("win_prob", self.call())

    def test_polls_reuse_the_cached_team_instead_of_rebuilding_it(self):
        self.call(); self.call(); self.call()
        self.assertEqual(self.calls["my_team"], 1)
        self.assertEqual(self.calls["matchups"], 3)             # the (short-TTL) points path is still asked each poll

    def test_a_failed_points_fetch_gives_null_points_and_says_so(self):
        with mock.patch.object(self.server.sleeper_layer, "live_matchups", side_effect=RuntimeError("down")):
            r = self.call()
        self.assertIsNone(r["points_source"])
        self.assertIsNone(r["my_team"]["players"][0]["points"])
        self.assertIn("not available", r["points_note"])

    def test_a_non_live_week_skips_the_network(self):
        self.result["live_week"] = 12
        with mock.patch.object(self.server.live_scores_layer, "live_scoreboard") as sb:
            r = self.call()
        self.assertFalse(r["live"])
        sb.assert_not_called()


class SleeperTtlTests(unittest.TestCase):
    def test_live_matchups_asks_for_a_30_second_cache_without_changing_the_default(self):
        from engine import sleeper
        with mock.patch.object(sleeper, "_cached_get", return_value=[]) as cg:
            sleeper.live_matchups("L", 5)
            self.assertEqual(cg.call_args[0][2], 30)
            sleeper.get_matchups("L", 5)
            self.assertEqual(cg.call_args[0][2], sleeper.ROSTER_TTL)


if __name__ == "__main__":
    unittest.main()
