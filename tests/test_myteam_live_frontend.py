"""My Team live scoring in static/app.js + style.css: string-level pins, plus the pure view functions run under node."""
import json
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


JS, CSS = read("static/app.js"), read("static/style.css")


def body_of(sig):
    i = JS.index(sig)
    return JS[i:i + 3500]


def run_js(expr):
    start = JS.index("function liveRowView(")
    end = JS.index("// Counts el's number from")
    cut = JS[start:end]
    t0 = JS.index("function teamTotalLabel(")
    t1 = JS.index("// A big center", t0)
    code = ("const FMT = { d1: (v) => (v == null ? '—' : Number(v).toFixed(1)) };"
            + JS[t0:t1] + cut + f"console.log(JSON.stringify({expr}));")
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class ViewTests(unittest.TestCase):
    def test_pre_game_row_is_blue_projected(self):
        v = run_js('liveRowView({PROJ: 14.2, final: false}, {game_state: "pre", points: null, live_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("pre", 14.2, ""))

    def test_in_game_row_shows_points_big_and_live_projection_small(self):
        v = run_js('liveRowView({PROJ: 14.2}, {game_state: "in", points: 6.4, live_proj: 15.8, quarter: 3, clock: "10:42", pregame_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"], v["title"]), ("in", 6.4, "proj 15.8", "Q3 10:42"))

    def test_final_row_shows_points_and_a_quiet_final(self):
        v = run_js('liveRowView({PROJ: 14.2}, {game_state: "post", points: 19.1, live_proj: 19.1, pregame_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"], v["title"]), ("post", 19.1, "Final", "Projected 14.2"))

    def test_server_settled_rows_stay_final_without_live_data(self):
        v = run_js('liveRowView({PROJ: 17.3, final: true}, null)')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("post", 17.3, "Final"))

    def test_unknown_points_fall_back_to_the_blue_projection(self):
        v = run_js('liveRowView({PROJ: 9}, {game_state: "in", points: null, live_proj: null})')
        self.assertEqual(v["state"], "pre")

    def test_overtime_label(self):
        v = run_js('liveRowView({PROJ: 9}, {game_state: "in", points: 3, live_proj: 3, quarter: 5, clock: "7:00"})')
        self.assertEqual(v["title"], "OT 7:00")

    def test_team_total_states(self):
        team = '{total_proj: 100, players: [{is_starter: true}]}'
        pre = run_js(f'liveTeamView({team}, {{points_total: 0, live_proj_total: 101.5, final: false, players: [{{game_state: "pre"}}]}})')
        self.assertEqual((pre["state"], pre["main"], pre["sub"]), ("pre", 101.5, ""))
        live = run_js(f'liveTeamView({team}, {{points_total: 38.2, live_proj_total: 104.9, final: false, players: [{{game_state: "in"}}, {{game_state: "pre"}}]}})')
        self.assertEqual((live["state"], live["main"], live["sub"], live["label"]), ("in", 38.2, "proj 104.9", "LIVE (STARTERS)"))
        fin = run_js(f'liveTeamView({team}, {{points_total: 99.0, live_proj_total: 99.0, final: true, players: [{{game_state: "post"}}]}})')
        self.assertEqual((fin["state"], fin["main"], fin["label"]), ("post", 99.0, "FINAL (STARTERS)"))

    def test_team_total_without_live_points_keeps_the_old_label_logic(self):
        v = run_js('liveTeamView({total_proj: 88, players: [{is_starter: true, final: true}]}, null)')
        self.assertEqual((v["state"], v["label"]), ("post", "FINAL (STARTERS)"))


class WiringTests(unittest.TestCase):
    def test_starters_get_the_live_number_and_bench_rows_do_not(self):
        b = body_of("function rosterRowHtml")
        self.assertIn("isBench ? null : liveRowView", b)
        self.assertIn('class="proj-num tabular lv"', b)

    def test_polls_the_endpoint_every_30_seconds_only_on_the_my_team_tab(self):
        self.assertIn("const LIVE_POLL_MS = 30000;", JS)
        self.assertIn("/api/myteam/live?", JS)
        poll = body_of("async function pollMyTeamLive")
        self.assertIn('state.tab !== "myteam"', poll)
        self.assertIn("document.hidden", poll)
        self.assertIn("live.active", poll)
        self.assertIn("wake_in_seconds", poll)

    def test_polling_stops_on_tab_switch_and_before_each_reload(self):
        self.assertIn('if (tab !== "myteam") stopMyTeamLive();', JS)
        self.assertIn("stopMyTeamLive();\n  content.innerHTML", JS)

    def test_only_the_live_week_polls(self):
        b = body_of("function startMyTeamLive")
        self.assertIn("data.live_week === data.nfl_week", b)

    def test_count_up_respects_reduced_motion_and_cancels_stale_animations(self):
        b = body_of("function animateNumber")
        self.assertIn("prefersReducedMotion", b)
        self.assertIn("_lvTok", b)
        self.assertIn("_lvTok", body_of("function countUpTotals"))

    def test_matchup_center_and_bar_use_live_totals_and_keep_the_settled_logic(self):
        self.assertIn("live_proj_total", body_of("function liveEdge"))
        self.assertIn("matchupSettled(mine, opp)", body_of("function matchupCenterHtml"))
        self.assertIn("liveEdge(mine, opp, live)", body_of("function matchupBarHtml"))
        self.assertIn("matchupCenterHtml(data.my_team, data.opponent, live)", JS)

    def test_colors_are_fixed_tokens_not_theme_variables(self):
        self.assertIn("--live-pts: #00ceb8; --live-proj: #58a7ff;", CSS)
        self.assertRegex(CSS, r'\.lv\[data-state="pre"\] \.lv-main \{ color: var\(--live-proj\); \}')
        self.assertRegex(CSS, r'\.lv\[data-state="in"\] \.lv-main, \.lv\[data-state="post"\] \.lv-main \{ color: var\(--live-pts\); \}')
        themes = read("static/team-themes.js")
        self.assertNotIn("--live-pts", themes)
        self.assertNotIn("--live-proj", themes)

    def test_endpoint_is_declared_and_no_store(self):
        server = read("server.py")
        self.assertIn('@app.get("/api/myteam/live")', server)
        self.assertIn('"/api/myteam"', server)      # the no-store prefix covers it


if __name__ == "__main__":
    unittest.main()
