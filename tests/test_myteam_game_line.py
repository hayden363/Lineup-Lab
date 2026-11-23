"""My Team game line (owner 2026-11-22): under every player, his real NFL game and his stats, on my team and my opponent's.
No network: the scoreboard and box scores are fixtures."""
import json
import os
import subprocess
import unittest
from unittest import mock

import server
from engine import boxscore as bx
from engine import myteam_live as ml
from tests.test_myteam_live import NOW, game, iso

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "static/app.js")) as f:
    JS = f.read()


def roster(pid, name, pos, team, starter=True, **kw):
    return {"player_id": pid, "player_display_name": name, "position": pos, "recent_team": team, "is_starter": starter, "PROJ": 10.0, **kw}


def result():
    mine = {"roster_id": 1, "players": [roster("a", "James Cook", "RB", "BUF"), roster("b", "Stefon Diggs", "WR", "WAS", starter=False),
                                        roster("c", "Bye Guy", "WR", "SEA", on_bye=True)]}
    opp = {"roster_id": 2, "players": [roster("d", "Josh Allen", "QB", "BUF")]}
    return {"nfl_week": 11, "live_week": 11, "my_team": mine, "opponent": opp}


def parsed():
    return {"teams": [{"abbr": "BUF", "players": [
        {"athlete_id": "1", "name": "James Cook", "position": "RB", "team": "BUF",
         "stats": {"rushing": {"rushingAttempts": 22, "rushingYards": 89, "rushingTouchdowns": 1},
                   "receiving": {"receptions": 2, "receivingYards": 3, "receivingTouchdowns": 0, "receivingTargets": 2}}},
        {"athlete_id": "2", "name": "Josh Allen", "position": "QB", "team": "BUF",
         "stats": {"passing": {"completions": 27, "passingAttempts": 45, "passingYards": 304, "passingTouchdowns": 1, "interceptions": 2}}},
    ]}]}


class ShortStatTests(unittest.TestCase):
    def test_main_line_then_a_short_second_line(self):
        lines = [{"label": "Rushing", "text": "22 car, 89 yds, 1 TD"}, {"label": "Receiving", "text": "2 rec, 3 yds, 0 TD, 2 tgt"}]
        self.assertEqual(bx.short_stat(lines), "22 car, 89 yds, 1 TD · 3 rec yds")

    def test_drops_zero_tds_and_targets(self):
        self.assertEqual(bx.short_stat([{"label": "Receiving", "text": "8 rec, 91 yds, 0 TD, 10 tgt"}]), "8 rec, 91 yds")

    def test_keeps_a_qbs_picks(self):
        self.assertEqual(bx.short_stat([{"label": "Passing", "text": "27/45, 304 yds, 1 TD, 2 INT"}]), "27/45, 304 yds, 1 TD, 2 INT")

    def test_an_empty_second_line_is_left_out_and_defense_is_ignored(self):
        lines = [{"label": "Receiving", "text": "4 rec, 40 yds, 0 TD"}, {"label": "Rushing", "text": "1 car, 0 yds, 0 TD"},
                 {"label": "Defense", "text": "1 tkl, 0 sk"}]
        self.assertEqual(bx.short_stat(lines), "4 rec, 40 yds")


class StatLinesTests(unittest.TestCase):
    def test_matches_by_name_position_and_team(self):
        got = bx.stat_lines(parsed(), [{"player_id": "a", "name": "James Cook", "position": "RB", "team": "BUF"},
                                       {"player_id": "x", "name": "James Cook", "position": "RB", "team": "KC"}])
        self.assertEqual(got, {"a": "22 car, 89 yds, 1 TD · 3 rec yds"})


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.base = ml.make_base(result(), {}, "sleeper")
        self.games = [game("BUF", "MIA", "post", 4, "0:00", hs=26, as_=9), game("WSH", "CIN", "pre", 0, "15:00", kick=3000)]

    def out(self, stats=None):
        return ml.compose(self.base, self.games, {"source": "sleeper", "by_roster": {}}, now=NOW, stats=stats)["game_lines"]

    def test_every_rostered_player_with_a_game_gets_one_bench_and_opponent_too(self):
        self.assertEqual(set(self.out()), {"a", "b", "d"})

    def test_a_player_on_bye_gets_none(self):
        self.assertNotIn("c", self.out())

    def test_score_and_opponent_from_his_side(self):
        a = self.out()["a"]
        self.assertEqual((a["state"], a["score"], a["opp_score"], a["opp"], a["home"]), ("post", 26, 9, "MIA", True))

    def test_pregame_has_kickoff_and_never_a_stat(self):
        b = self.out({"b": "1 rec, 5 yds"})["b"]
        self.assertEqual((b["state"], b["kickoff"], b["stat"]), ("pre", iso(3000), None))

    def test_stat_is_attached_once_the_game_started(self):
        self.assertEqual(self.out({"a": "22 car"})["a"]["stat"], "22 car")

    def test_another_nfl_week_has_no_lines(self):
        b = {**self.base, "week": 9}
        self.assertEqual(ml.compose(b, self.games, None, now=NOW)["game_lines"], {})

    def test_only_started_games_need_a_box_score(self):
        games = [{**self.games[0], "game_id": "401873070"}, {**self.games[1], "game_id": "401873078"}]
        self.assertEqual(ml.box_games(self.base, games), {"401873070": True})


class ServerTests(unittest.TestCase):
    def setUp(self):
        server._FINAL_BOX.clear()
        self.addCleanup(server._FINAL_BOX.clear)
        self.base = ml.make_base(result(), {}, "sleeper")
        self.games = [{**game("BUF", "MIA", "post", 4, "0:00", hs=26, as_=9), "game_id": "401873070"}]

    def test_reads_lines_and_keeps_no_raw_feed(self):
        with mock.patch.object(server.boxscore_layer, "game_boxscore", return_value=parsed()) as box:
            got = server._game_stat_lines(self.base, self.games)
        self.assertEqual(got["a"], "22 car, 89 yds, 1 TD · 3 rec yds")
        self.assertEqual(got["d"], "27/45, 304 yds, 1 TD, 2 INT")
        box.assert_called_once_with("401873070", keep_raw=False)

    def test_a_finished_game_is_read_once(self):
        with mock.patch.object(server.boxscore_layer, "game_boxscore", return_value=parsed()) as box:
            server._game_stat_lines(self.base, self.games)
            server._game_stat_lines(self.base, self.games)
        self.assertEqual(box.call_count, 1)

    def test_a_live_game_is_read_again(self):
        live = [{**self.games[0], "state": "in", "period": 3, "display_clock": "5:00"}]
        with mock.patch.object(server.boxscore_layer, "game_boxscore", return_value=parsed()) as box:
            server._game_stat_lines(self.base, live)
            server._game_stat_lines(self.base, live)
        self.assertEqual(box.call_count, 2)

    def test_a_failed_feed_just_means_no_stats(self):
        with mock.patch.object(server.boxscore_layer, "game_boxscore", side_effect=RuntimeError("down")):
            self.assertEqual(server._game_stat_lines(self.base, self.games), {})


class RawCacheTests(unittest.TestCase):
    def setUp(self):
        bx._CACHE.clear(); bx._RAW.clear()
        self.addCleanup(bx._CACHE.clear); self.addCleanup(bx._RAW.clear)
        self.resp = mock.Mock(); self.resp.json.return_value = {"boxscore": {"players": []}, "plays": [1]}

    def test_keep_raw_false_stores_no_raw_and_the_game_center_still_gets_it(self):
        with mock.patch.object(bx.requests, "get", return_value=self.resp) as get:
            bx.game_boxscore("401873070", keep_raw=False)
            self.assertEqual(bx.game_summary_raw("401873070"), {})
            bx.game_boxscore("401873070", keep_raw=False)
            self.assertEqual(get.call_count, 1)                 # the 20 s cache still works
            bx.game_boxscore("401873070")                       # the game center needs the raw feed: fetched
            self.assertEqual(get.call_count, 2)
        self.assertEqual(bx.game_summary_raw("401873070")["plays"], [1])


class FrontendTests(unittest.TestCase):
    def run_js(self, expr):
        start, end = JS.index("function gameClockLabel("), JS.index("// ---- end game line")
        code = ("const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');" + JS[start:end]
                + f"console.log(JSON.stringify({expr}));")
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True, env={**os.environ, "TZ": "America/Los_Angeles"})
        if r.returncode:
            raise AssertionError(r.stderr[-1500:])
        return json.loads(r.stdout)

    def test_final(self):
        h = self.run_js('gameLineHtml({state:"post",opp:"MIA",home:true,score:26,opp_score:9,stat:"8 rec, 91 yds, 1 TD"})')
        self.assertIn('class="mg-w">W 26–9</b> vs MIA', h)
        self.assertIn("8 rec, 91 yds, 1 TD", h)

    def test_loss_and_away(self):
        self.assertIn('class="mg-l">L 21–31</b> @ DET', self.run_js('gameLineHtml({state:"post",opp:"DET",home:false,score:21,opp_score:31})'))

    def test_live(self):
        h = self.run_js('gameLineHtml({state:"in",opp:"SF",home:false,score:0,opp_score:7,period:1,clock:"1:28",stat:"1 rec, 29 yds"})')
        self.assertIn("Q1 1:28", h)
        self.assertIn("Down 0–7 @ SF", h)

    def test_halftime_and_overtime(self):
        self.assertEqual(self.run_js('gameClockLabel({period:2,clock:"0:00",detail:"Halftime"})'), "Half")
        self.assertEqual(self.run_js('gameClockLabel({period:5,clock:"7:00"})'), "OT 7:00")

    def test_pregame_shows_local_kickoff_and_no_stat(self):
        h = self.run_js('gameLineHtml({state:"pre",opp:"WSH",home:false,kickoff:"2026-11-24T01:15Z",stat:"junk"})')
        self.assertIn("Mon 5:15 PM @ WSH", h.replace(" ", " "))
        self.assertNotIn("junk", h)

    def test_no_game_is_empty_and_text_is_escaped(self):
        self.assertEqual(self.run_js("gameLineHtml(null)"), "")
        self.assertNotIn("<x", self.run_js('gameLineHtml({state:"post",opp:"<x",home:true,score:1,opp_score:0})'))


if __name__ == "__main__":
    unittest.main()
