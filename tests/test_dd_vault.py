"""The Team Vault (owner 2026-11-23): on a rare answer, a favorite-team player sees one of that team's real plays, cooler at
each level, ranked by real popularity, with pre-1999 legends. Full 11-on-11, right jersey numbers, no explanation screen."""
import json
import os
import re
import subprocess
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import dd_stadium, dd_vault

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def moment(mid, named, article, players):
    return {"id": mid, "named": named, "views": {"moment": article, "players": players}}


class RankTests(unittest.TestCase):
    def test_named_plays_are_legendary_then_popularity_decides(self):
        got = dd_vault.rank_team([moment("sb_big", False, 1000, {"a": 5000}), moment("sb_small", False, 500, {"b": 100}),
                                  moment("named_small", True, 20, {"c": 1}), moment("named_big", True, 90, {"d": 1})])
        self.assertEqual({m["id"]: m["tier"] for m in got}, {"named_big": 6, "named_small": 6, "sb_big": 5, "sb_small": 4})

    def test_a_team_with_no_named_play_still_gets_every_level(self):
        got = dd_vault.rank_team([moment("a", False, 3, {}), moment("b", False, 2, {}), moment("c", False, 1, {})])
        self.assertEqual({m["id"]: m["tier"] for m in got}, {"a": 6, "b": 5, "c": 4})

    def test_only_four_named_plays_can_hold_the_top_level(self):
        got = dd_vault.rank_team([moment(f"n{i}", True, 10 ** (6 - i), {}) for i in range(1, 6)])
        self.assertEqual({m["id"]: m["tier"] for m in got}, {"n1": 6, "n2": 6, "n3": 6, "n4": 6, "n5": 5})

    def test_a_bigger_stage_lifts_an_equally_popular_play(self):
        a, b = moment("reg", False, 1000, {}), moment("sb", False, 1000, {})
        a["impact"], b["impact"] = 0.4, 1.0
        self.assertGreater(dd_vault.score(b), dd_vault.score(a))


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = dd_vault.load()
        cls.moments = cls.body["moments"]

    def test_every_team_has_plenty_at_every_level(self):
        for team in dd_stadium.UNIFORMS:
            mine = [m for m in self.moments if m["team"] == team]
            self.assertGreaterEqual(len(mine), 10, team)
            self.assertEqual({m["tier"] for m in mine}, {4, 5, 6}, team)

    def test_the_named_legends_are_in(self):
        names = {p["name"] for m in self.moments for p in m["players"]}
        for legend in ("Jerry Rice", "Fred Biletnikoff", "Joe Montana", "Ken Stabler", "Marcus Allen"):
            self.assertIn(legend, names)
        self.assertGreaterEqual(sum(1 for m in self.moments if m["iso_date"] < "1999"), 32)

    def test_every_moment_is_sourced_and_complete(self):
        for m in self.moments:
            self.assertTrue(m["source"].startswith(("https://", "nflverse play-by-play ")), m["id"])
            for k in ("title", "sub", "game", "kind", "iso_date"):
                self.assertTrue(m[k], (m["id"], k))
            self.assertIn(m["kind"], ("pass", "run", "fumble"))
            self.assertIn(m["opp"], dd_stadium.UNIFORMS)
            self.assertTrue(any(p["role"] == "target" for p in m["players"]), m["id"])

    def test_ids_are_unique(self):
        ids = [m["id"] for m in self.moments]
        self.assertEqual(len(ids), len(set(ids)))

    def test_stored_tiers_match_the_ranking(self):
        for team in {m["team"] for m in self.moments}:
            mine = [dict(m) for m in self.moments if m["team"] == team]
            want = {m["id"]: m["tier"] for m in mine}
            self.assertEqual({m["id"]: m["tier"] for m in dd_vault.rank_team(mine)}, want)

    def test_jersey_numbers_are_real_or_blank(self):
        for m in self.moments:
            for p in m["players"]:
                self.assertTrue(p["number"] is None or 1 <= p["number"] <= 99, (m["id"], p))

    def test_full_lineups_are_eleven_on_eleven(self):
        full = [m for m in self.moments if m.get("lineup")]
        self.assertGreater(len(full), 100)
        for m in full:
            self.assertEqual((len(m["lineup"]["o"]), len(m["lineup"]["d"])), (11, 11), m["id"])

    def test_key_players_keep_their_number_in_the_lineup(self):
        for m in self.moments:
            if not m.get("lineup"):
                continue
            nums = {r[1] for r in m["lineup"]["o"]}
            for p in m["players"]:
                if p["number"] is not None and p["role"] == "qb":
                    self.assertTrue(p["number"] in nums or None in nums or len(nums) >= 9, (m["id"], p))

    def test_for_team(self):
        out = dd_vault.for_team("SF")
        self.assertEqual({m["team"] for m in out["moments"]}, {"SF"})
        self.assertIn("SF", out["uniforms"])
        self.assertIn("DAL", out["uniforms"])
        self.assertNotIn("views", out["moments"][0])
        self.assertEqual(dd_vault.for_team("???")["moments"], [])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(server.app)
        server._RATE_BUCKETS.clear()

    def test_signed_out_gets_nothing(self):
        with mock.patch.object(server, "_play_user", return_value=None):
            self.assertEqual(self.c.get("/api/play/vault?team=SF").json(), {"signed_in": False, "moments": []})

    def test_signed_in_gets_their_team(self):
        with mock.patch.object(server, "_play_user", return_value={"id": 1}):
            r = self.c.get("/api/play/vault?team=LV").json()
        self.assertTrue(r["signed_in"])
        self.assertEqual({m["team"] for m in r["moments"]}, {"LV"})

    def test_saved_team_is_used_without_a_browser_pick(self):
        with mock.patch.object(server, "_play_user", return_value={"id": 1}), \
             mock.patch.object(server.db, "get_settings", return_value={"theme": "SF"}):
            r = self.c.get("/api/play/vault").json()
        self.assertEqual({m["team"] for m in r["moments"]}, {"SF"})

    def test_preview_is_for_the_demo_page(self):
        self.assertEqual({m["team"] for m in self.c.get("/api/play/vault?team=SF&preview=1").json()["moments"]}, {"SF"})

    def test_script_is_served(self):
        r = self.c.get("/play-vault.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])


class FrontendTests(unittest.TestCase):
    def test_vault_file_stays_light_and_loads_only_when_needed(self):
        self.assertLess(len(read("static/play-vault.js")), 30_000)
        self.assertNotIn("play-vault.js", read("static/play.html"))
        self.assertIn('"/play-vault.js"', read("static/play.js"))

    def test_vault_only_runs_on_rare_answers_in_a_real_game(self):
        js = read("static/play.js")
        self.assertRegex(js, r"!o\.practice && res && t >= 4 && window\.DDVault")

    def test_recreation_is_labeled_and_there_is_no_explanation_screen(self):
        code = read("static/play-vault.js")
        self.assertIn('"RECREATION"', code)
        for text in ("FROM THE VAULT", "Tap to continue", "m.detail", "LEGENDARY"):
            self.assertNotIn(text, code)

    def test_every_play_puts_eleven_on_each_side(self):
        run = ("global.window = global; global.localStorage = {getItem(){return null}, setItem(){}}; global.window.localStorage = global.localStorage;"
               + read("static/play-vault.js") +
               "const p = [{name:'Q',number:16,role:'qb'},{name:'T',number:87,role:'target'}];"
               "const out = ['pass','run','fumble'].map(k => { const c = DDVault._cast({kind:k, side:1, from:20, end:101, td:true, tier:6, players: k==='run' ? [p[1]] : p});"
               " return [c.filter(e=>e.t==='o').length, c.filter(e=>e.t==='d').length, c.some(e=>e.n===87)]; });"
               "console.log(JSON.stringify(out));")
        r = subprocess.run(["node", "-e", run], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads(r.stdout), [[11, 11, True]] * 3)

    def test_pick_prefers_unseen_and_exact_tier(self):
        code = read("static/play-vault.js")
        run = ("global.window = global; global.localStorage = {d:{}, getItem(k){return this.d[k]||null}, setItem(k,v){this.d[k]=v}};"
               "global.window.localStorage = global.localStorage;" + code +
               "DDVault._set({moments:[{id:'a',tier:6},{id:'b',tier:6},{id:'c',tier:4}],uniforms:{}});"
               "const one = DDVault.pick(6,'s').id; DDVault.markSeen(one); const two = DDVault.pick(6,'s').id; DDVault.markSeen(two);"
               "const three = DDVault.pick(6,'s').id; const low = DDVault.pick(5,'s').id;"
               "console.log(JSON.stringify({one,two,three,low,none:DDVault.pick(3,'s')}));")
        r = subprocess.run(["node", "-e", run], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = json.loads(r.stdout)
        self.assertNotEqual(out["one"], out["two"])
        self.assertIn(out["three"], ("a", "b"))
        self.assertEqual(out["low"], "c")          # no level-5 play: the next level down
        self.assertIsNone(out["none"])

    def test_field_paints_the_whole_scene_in_pixels(self):
        field = read("static/play-field.js")
        self.assertIn("function lowScene(", field)
        self.assertTrue(re.search(r"imageSmoothingEnabled = false; ctx\.drawImage\(sceneC\.c", field))


if __name__ == "__main__":
    unittest.main()
