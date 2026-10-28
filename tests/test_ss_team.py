"""Start/Sit command center (static/ss-team.js): the pure helpers run under node, plus wiring checks."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(body):
    code = f'const S = require({json.dumps(os.path.join(ROOT, "static/ss-team.js"))});' \
           f'const P = (id, slot, pos, proj, st, x) => Object.assign({{ player_id: id, slot, position: pos, PROJ: proj, is_starter: st, floor: proj * 0.5, ceiling: proj * 1.6 }}, x || {{}});' \
           f'console.log(JSON.stringify((() => {{ {body} }})()));'
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class HelperTests(unittest.TestCase):
    ROSTER = 'const me = [P("a","QB","QB",20,true), P("b","FLEX","WR",12,true), P("c",null,"RB",14.4,false), P("d",null,"QB",19,false), P("e",null,"WR",9,false,{on_bye:true})];'

    def test_total_counts_starters_only(self):
        self.assertEqual(run(self.ROSTER + "return S.total(me);"), 32)

    def test_a_flex_slot_takes_rb_wr_te_but_a_qb_slot_only_a_qb(self):
        out = run("return [S.eligible('FLEX','RB'), S.eligible('FLEX','QB'), S.eligible('QB','QB'), S.eligible('QB','RB'), S.eligible('SUPER_FLEX','QB'), S.eligible('RB/WR','TE'), S.eligible('D/ST','DEF')];")
        self.assertEqual(out, [True, False, True, False, True, False, True])

    def test_candidates_are_eligible_bench_players_best_first_with_the_point_change(self):
        out = run(self.ROSTER + 'return [S.candidates(me, "b").map(c => [c.player.player_id, c.delta]), S.candidates(me, "a").map(c => [c.player.player_id, c.delta])];')
        self.assertEqual(out[0], [["c", 2.4]])                  # the bye-week WR is not offered, the QB cannot take a FLEX
        self.assertEqual(out[1], [["d", -1.0]])

    def test_swap_moves_the_slot_and_leaves_the_original_untouched(self):
        out = run(self.ROSTER + 'const n = S.swap(me, "b", "c"); return [n.filter(p => p.is_starter).map(p => p.player_id + ":" + p.slot), me.filter(p => p.is_starter).map(p => p.player_id), S.total(n)];')
        self.assertEqual(out[0], ["a:QB", "c:FLEX"])
        self.assertEqual(out[1], ["a", "b"])
        self.assertEqual(out[2], 34.4)

    def test_an_illegal_swap_returns_the_roster_unchanged(self):
        out = run(self.ROSTER + 'return [S.swap(me, "b", "d") === me, S.swap(me, "c", "b") === me, S.swap(me, "zz", "c") === me];')
        self.assertEqual(out, [True, True, True])

    def test_status_counts_active_open_and_bye_or_out(self):
        out = run('const me = [P("a","QB","QB",20,true), P("b","WR","WR",0,true,{on_bye:true}), P("c","RB","RB",8,true,{injury_status:"Out"}), P("d",null,"WR",9,false,{on_bye:true})]; return S.status(me);')
        self.assertEqual(out, {"active": 1, "open": 2, "offline": 3})

    def test_win_probability_rises_with_the_projected_margin_and_is_even_when_level(self):
        out = run('const mk = (n) => [P("a","QB","QB",n,true)]; return [S.winProb(mk(100), mk(100)), S.winProb(mk(120), mk(100)) > 55, S.winProb(mk(80), mk(100)) < 45, S.winProb(mk(100), null)];')
        self.assertEqual(out[0], 50)
        self.assertEqual(out[1:3], [True, True])
        self.assertIsNone(out[3])

    def test_apply_lineup_reseats_everyone(self):
        out = run(self.ROSTER + 'const n = S.applyLineup(me, [{slot:"QB", player_id:"d"}, {slot:"FLEX", player_id:"c"}]); return n.filter(p => p.is_starter).map(p => p.player_id + ":" + p.slot);')
        self.assertEqual(sorted(out), ["c:FLEX", "d:QB"])


class WiringTests(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel)) as f:
            return f.read()

    def test_the_command_center_sits_at_the_top_of_start_sit_with_a_drawer(self):
        html = self.read("static/index.html")
        body = html.index('id="startsit-body"')
        self.assertLess(body, html.index('id="ss-hero"'))
        self.assertLess(html.index('id="ss-hero"'), html.index('id="track-record-strip"'))
        self.assertIn('id="sst-drawer"', html)
        self.assertLess(html.index('src="/ss-team.js"'), html.index('src="/app.js"'))

    def test_start_sit_loads_it_and_never_sends_you_to_the_big_board(self):
        js = self.read("static/app.js")
        body = js[js.index("async function loadStartSitTab"):]
        self.assertIn("SSTeam.load()", body[:900])
        ss = self.read("static/ss-team.js")
        self.assertNotIn("switchTab", ss)
        self.assertNotIn('"board"', ss)

    def test_it_is_precached_and_served_without_caching(self):
        self.assertIn('"/ss-team.js"', self.read("static/sw.js"))
        from fastapi.testclient import TestClient
        import server
        r = TestClient(server.app).get("/ss-team.js")
        self.assertEqual((r.status_code, r.headers.get("cache-control")), (200, "no-cache"))

    def test_motion_is_switched_off_for_reduced_motion(self):
        css = self.read("static/style.css")
        self.assertIn("@keyframes sstSwap", css)
        self.assertIn(".sst-drawer, .sst-scrim { transition: none; }", css)


if __name__ == "__main__":
    unittest.main()
