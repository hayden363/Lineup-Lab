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
    code = ("const FMT = { d1: (v) => (v == null ? '—' : Number(v).toFixed(1)) };"
            + JS[start:end] + f"console.log(JSON.stringify({expr}));")
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class ViewTests(unittest.TestCase):
    def test_pre_game_row_is_one_big_green_number_and_nothing_under_it(self):
        v = run_js('liveRowView({PROJ: 14.2, final: false}, {game_state: "pre", points: null, live_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("pre", 14.2, None))

    def test_in_game_row_is_white_points_with_the_green_live_projection_under(self):
        v = run_js('liveRowView({PROJ: 14.2}, {game_state: "in", points: 6.4, live_proj: 15.8, quarter: 3, clock: "10:42", pregame_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"], v["title"]), ("in", 6.4, 15.8, "Q3 10:42"))

    def test_final_row_keeps_the_same_two_numbers_and_no_word(self):
        v = run_js('liveRowView({PROJ: 14.2}, {game_state: "post", points: 19.1, live_proj: 19.1, pregame_proj: 14.2})')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("post", 19.1, 19.1))
        self.assertNotIn("Final", json.dumps(v))
        self.assertNotIn("proj", json.dumps(v).replace("Projected", "").lower().replace("pregame_proj", ""))

    def test_server_settled_rows_are_post_without_live_data(self):
        v = run_js('liveRowView({PROJ: 17.3, final: true}, null)')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("post", 17.3, 17.3))

    def test_unknown_points_fall_back_to_the_green_projection(self):
        v = run_js('liveRowView({PROJ: 9}, {game_state: "in", points: null, live_proj: null})')
        self.assertEqual((v["state"], v["main"], v["sub"]), ("pre", 9, None))

    def test_overtime_label_stays_in_the_tooltip(self):
        v = run_js('liveRowView({PROJ: 9}, {game_state: "in", points: 3, live_proj: 3, quarter: 5, clock: "7:00"})')
        self.assertEqual(v["title"], "OT 7:00")

    def test_team_total_states(self):
        team = '{total_proj: 100, players: [{is_starter: true}]}'
        pre = run_js(f'liveTeamView({team}, {{points_total: 0, live_proj_total: 101.5, final: false, players: [{{game_state: "pre"}}]}})')
        self.assertEqual((pre["state"], pre["main"], pre["sub"]), ("pre", 101.5, None))
        live = run_js(f'liveTeamView({team}, {{points_total: 38.2, live_proj_total: 104.9, final: false, players: [{{game_state: "in"}}, {{game_state: "pre"}}]}})')
        self.assertEqual((live["state"], live["main"], live["sub"]), ("in", 38.2, 104.9))
        fin = run_js(f'liveTeamView({team}, {{points_total: 99.0, live_proj_total: 99.0, final: true, players: [{{game_state: "post"}}]}})')
        self.assertEqual((fin["state"], fin["main"], fin["sub"]), ("post", 99.0, 99.0))

    def test_team_total_without_live_points(self):
        done = run_js('liveTeamView({total_proj: 88, players: [{is_starter: true, final: true}]}, null)')
        self.assertEqual((done["state"], done["main"]), ("post", 88))
        pre = run_js('liveTeamView({total_proj: 88, players: [{is_starter: true, final: false}]}, null)')
        self.assertEqual((pre["state"], pre["main"], pre["sub"]), ("pre", 88, None))


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

    def test_starter_rows_carry_no_words_or_range_text(self):
        b = JS[JS.index("function rosterRowHtml"):JS.index("// ---- live scoring on My Team")]
        starter = b[b.index(": `<span class=\"proj-num tabular lv\""):b.index("return `<div class=\"myteam-roster-row")]
        self.assertNotIn("proj-range", starter)         # the range lives in the tooltip
        self.assertNotRegex(starter, r">\s*(proj|Final|Projected)")
        live = JS[JS.index("function liveRowView"):JS.index("function animateNumber")]
        for word in ('"Final"', "`proj ", '"proj '):
            self.assertNotIn(word, live)
        self.assertNotIn("PROJECTED (STARTERS)", JS)
        self.assertNotIn("FINAL (STARTERS)", JS)
        self.assertNotIn("LIVE (STARTERS)", JS)
        self.assertNotIn("mt-total-lbl", JS)

    def test_win_probability_ring_replaces_the_split_bar_and_updates_in_place(self):
        self.assertNotIn("matchupBarHtml", JS)
        self.assertNotIn("share of combined projected points", JS)
        self.assertIn("matchupCenterHtml(data.my_team, data.opponent, data.win_prob", JS)
        self.assertIn("live.win_prob", body_of("function applyMyTeamLive"))
        self.assertIn("paintWinProb(", body_of("function applyMyTeamLive"))
        self.assertIn("stroke-dashoffset", body_of("function paintWinProb"))
        self.assertIn("transition: stroke-dashoffset", CSS)

    def test_wp_display_never_rounds_a_live_edge_to_a_false_certainty(self):
        start = JS.index("function wpShown(")
        code = JS[start:JS.index("\n", start)] + ";console.log(JSON.stringify([wpShown(0.004), wpShown(0.996), wpShown(1), wpShown(0), wpShown(0.5)]))"
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), [1, 99, 100, 0, 50])

    def test_motion_pieces_and_reduced_motion(self):
        for token in ("lvPulse", "lvBump", "mtRowIn", "stroke-dashoffset"):
            self.assertIn(token, CSS)
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS[CSS.index("lvBump"):])
        self.assertIn("prefersReducedMotion", body_of("function bumpNumber"))
        self.assertIn("lv-dot", body_of("function rosterRowHtml"))
        self.assertIn("bumpNumber(mainEl)", body_of("function paintLiveNum"))

    def test_colors_are_the_green_token_and_text_not_theme_variables(self):
        self.assertIn("--live-pts: var(--text); --live-proj: var(--pos);", CSS)
        self.assertRegex(CSS, r'\.lv\[data-state="pre"\] \.lv-main \{ color: var\(--live-proj\); \}')
        self.assertRegex(CSS, r'\.lv\[data-state="in"\] \.lv-main, \.lv\[data-state="post"\] \.lv-main \{ color: var\(--live-pts\); \}')
        self.assertRegex(CSS, r"\.lv-sub \{[^}]*color: var\(--live-proj\)")
        self.assertIn("--pos: #2fd9a0", CSS)
        themes = read("static/team-themes.js")
        for tok in ("--live-pts", "--live-proj", "'--pos'", '"--pos"', "'--text'", '"--text"'):
            self.assertNotIn(tok, themes)


class TradesPanelTests(unittest.TestCase):
    """Regression for 'League trades below aren't shown' (see README, My Team)."""

    def test_trades_load_starts_right_after_render_before_anything_that_can_throw(self):
        b = body_of("async function loadMyTeam")
        i = b.index("content.innerHTML = html;")
        tail = b[i:]
        self.assertTrue(tail.lstrip("content.innerHTML = html;").lstrip().startswith("loadTradesPanel();"), tail[:200])
        self.assertLess(b.index("loadTradesPanel();"), b.index("startMyTeamLive("))
        self.assertLess(b.index("loadTradesPanel();"), b.index('$("#mt-refresh")'))

    def test_the_section_is_visible_while_loading_and_has_a_timeout_and_retry(self):
        b = JS[JS.index("async function loadTradesPanel"):JS.index('$("#myteam-gate-btn")')]
        self.assertIn("Loading trades", b)
        self.assertIn("AbortController", b)
        self.assertIn("tr-retry", b)
        self.assertIn("isConnected", b)

    def test_live_repaint_never_touches_the_trades_panel(self):
        b = JS[JS.index("function applyMyTeamLive"):JS.index("// The two team totals count up")]
        self.assertNotIn("trades-panel", b)
        self.assertNotIn("innerHTML", b)


    def test_endpoint_is_declared_and_no_store(self):
        server = read("server.py")
        self.assertIn('@app.get("/api/myteam/live", dependencies=[Depends(myteam_live_rate_limit)])', server)   # polled: rate limited
        self.assertIn('"/api/myteam"', server)      # the no-store prefix covers it


if __name__ == "__main__":
    unittest.main()
