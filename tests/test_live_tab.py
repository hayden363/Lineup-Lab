"""Live Games tab (static/live.js): pure builders under node, plus wiring checks."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(body):
    code = f'const L = require({json.dumps(os.path.join(ROOT, "static/live.js"))});' \
           f'console.log(JSON.stringify((() => {{ {body} }})()));'
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


GAME = '''const G = (o) => Object.assign({ game_id: "1", state: "in", period: 3, display_clock: "8:42", kickoff: "2026-11-02T01:20:00Z",
  home: { abbr: "DET", name: "Lions", score: 17, winner: false }, away: { abbr: "GB", name: "Packers", score: 10, winner: false }, badge: null, network: null }, o || {});'''


class PureTests(unittest.TestCase):
    def test_games_sort_live_first_then_upcoming_by_kickoff_then_final(self):
        out = run('return L.sortGames([{state:"post",kickoff:"3"},{state:"pre",kickoff:"2"},{state:"in",kickoff:"9"},{state:"pre",kickoff:"1"}]).map(g => g.state + g.kickoff);')
        self.assertEqual(out, ["in9", "pre1", "pre2", "post3"])

    def test_score_change_names_the_side_that_scored_and_only_for_live_games(self):
        out = run(GAME + 'return [L.scoreChange("10-17", G({away:{score:13}})), L.scoreChange("10-17", G({home:{score:24}})), L.scoreChange("10-17", G()), L.scoreChange(undefined, G()), L.scoreChange("10-14", G({state:"post"}))];')
        self.assertEqual(out, ["away", "home", None, None, None])

    def test_field_x_maps_yards_into_the_field_between_the_end_zones(self):
        self.assertEqual(run("return [L.fieldX(0), L.fieldX(50), L.fieldX(100)];"), [100, 500, 900])

    def test_field_svg_has_ball_first_down_line_end_zones_and_a_red_zone_only_when_in_it(self):
        sit = '{yard_line: 62, line_to_gain: 52, direction: "right-to-left", is_red_zone: %s}'
        svg = run(f'return L.fieldSvg({sit % "false"}, "DET", "GB");')
        self.assertIn('cx="596"', svg)                    # ball at 100 + 62 * 8
        self.assertIn('x1="516"', svg)                    # line to gain at yard 52
        self.assertIn(">GB<", svg)
        self.assertIn(">DET<", svg)
        self.assertNotIn("fld-rz", svg)
        self.assertIn("fld-rz", run(f'return L.fieldSvg({sit % "true"}, "DET", "GB");'))

    def test_red_zone_overlay_sits_at_the_end_the_offense_is_attacking(self):
        right = run('return L.fieldSvg({yard_line: 85, line_to_gain: 95, direction: "left-to-right", is_red_zone: true}, "DET", "GB");')
        left = run('return L.fieldSvg({yard_line: 15, line_to_gain: 5, direction: "right-to-left", is_red_zone: true}, "DET", "GB");')
        self.assertIn('class="fld-rz" x="740"', right)
        self.assertIn('class="fld-rz" x="100"', left)

    def test_down_and_distance_banner(self):
        out = run(GAME + 'return L.bannerText({possession:"DET", direction:"right-to-left", yard_line:62, down:2, distance:4}, G());')
        self.assertEqual(out, "2nd & 4 at DET 38 • 8:42 3rd Qtr")

    def test_banner_in_the_opponents_territory(self):
        out = run(GAME + 'return L.bannerText({possession:"GB", direction:"left-to-right", yard_line:82, down:1, distance:10}, G());')
        self.assertEqual(out, "1st & 10 at DET 18 • 8:42 3rd Qtr")

    def test_scoring_plays_get_neon_headlines_and_fantasy_chips(self):
        out = run('''const p = {id:"1", type:"Rushing Touchdown", scoring:true, yards:14, quarter:3, clock:"8:42", fantasy:[{name:"Jahmyr Gibbs", position:"RB", points:7.4, mine:true}]};
          return [L.playHeadline(p), L.playRowHtml(p)];''')
        self.assertEqual(out[0], "TD Run: Jahmyr Gibbs 14 yds")
        self.assertIn("pbp-pts mine", out[1])
        self.assertIn("+7.4 pts", out[1])
        self.assertIn("pbp-row scoring mine", out[1])

    def test_an_incompletion_names_the_intended_receiver(self):
        out = run('return L.playHeadline({type:"Pass Incompletion", scoring:false, yards:0, target:"Amon-Ra St. Brown", text:"x", fantasy:[]});')
        self.assertEqual(out, "Pass Incomplete: Target intended for Amon-Ra St. Brown")

    def test_play_text_is_escaped(self):
        out = run('return L.playRowHtml({id:"1", type:"Rush", text:"<img src=x onerror=1>", fantasy:[]});')
        self.assertNotIn("<img", out)

    def test_scorebug_has_badge_glow_only_when_a_roster_player_is_in_it_and_live_state(self):
        out = run(GAME + 'return [L.scorebugHtml(G({badge:"SNF", network:"NBC"}), 2), L.scorebugHtml(G(), 0), L.scorebugHtml(G({state:"pre"}), 0, null)];')
        self.assertIn("sb-badge snf", out[0])
        self.assertIn("has-mine", out[0])
        self.assertNotIn("has-mine", out[1])
        self.assertNotIn("sb-badge", out[1])
        self.assertIn("live", out[0])
        self.assertIn(" pre", out[2])
        self.assertNotIn("★", out[0])                 # no per-player star icons on the card

    def test_scorebug_uses_both_teams_colors_for_the_gradient_border(self):
        out = run(GAME + 'return L.scorebugHtml(G(), 0);')
        self.assertIn("--c1:", out)
        self.assertIn("--c2:", out)


    def test_scorebug_shows_your_players_on_the_right_with_projections_before_kickoff(self):
        out = run(GAME + '''const mine = [{name:"Amon-Ra St. Brown", headshot:"https://a.espncdn.com/x.png", value:17.3, kind:"proj", status:null},
          {name:"Jahmyr Gibbs", headshot:null, value:16.2, kind:"proj", status:"Questionable"}];
          return L.scorebugHtml(G({state:"pre"}), 2, null, mine);''')
        self.assertIn("sb-mine", out)
        self.assertIn("17.3", out)
        self.assertIn("16.2", out)
        self.assertIn("proj", out)
        self.assertIn("QUESTIONABLE", out)

    def test_a_live_game_shows_current_points_not_projections(self):
        out = run(GAME + '''const mine = [{name:"Jahmyr Gibbs", headshot:null, value:12.4, kind:"pts", status:null}];
          return L.scorebugHtml(G(), 1, null, mine);''')
        self.assertIn("12.4", out)
        self.assertIn('data-kind="pts"', out)
        self.assertNotIn('data-kind="proj"', out)

    def test_more_than_four_players_collapse_into_a_count(self):
        out = run(GAME + '''const mine = [1,2,3,4,5,6].map((i) => ({name:"P"+i, headshot:null, value:i, kind:"proj", status:null}));
          return L.scorebugHtml(G({state:"pre"}), 6, null, mine);''')
        self.assertEqual(out.count('class="sb-p"'), 4)
        self.assertIn("+2", out)

    def test_a_live_card_carries_the_red_glowing_marker_and_a_pre_game_card_does_not(self):
        live = run(GAME + 'return L.scorebugHtml(G(), 0);')
        pre = run(GAME + 'return L.scorebugHtml(G({state:"pre"}), 0);')
        self.assertIn("sb-live", live)
        self.assertNotIn("sb-live", pre)

    def test_your_players_names_are_escaped(self):
        out = run(GAME + 'return L.scorebugHtml(G({state:"pre"}), 1, null, [{name:"<b>x</b>", headshot:null, value:1, kind:"proj"}]);')
        self.assertNotIn("<b>x</b>", out)

    def test_live_teams_are_collected_for_other_screens(self):
        out = run(GAME + 'return L.liveTeamKeys([G(), G({state:"pre", home:{abbr:"KC"}, away:{abbr:"BUF"}}), G({home:{abbr:"WSH"}, away:{abbr:"NYJ"}})]);')
        self.assertEqual(sorted(out), ["DET", "GB", "NYJ", "WAS"])

    def test_a_favorite_team_game_gets_the_crest_ribbon_and_the_fav_class(self):
        out = run(GAME + 'return [L.scorebugHtml(G(), 0, null, null, "DET"), L.scorebugHtml(G(), 0, null, null, "KC")];')
        self.assertIn("sb-fav", out[0])
        self.assertIn("YOUR TEAM", out[0])
        self.assertNotIn("sb-fav", out[1])

    def test_the_favorite_team_row_is_highlighted_inside_the_card(self):
        out = run(GAME + 'return L.scorebugHtml(G(), 0, null, null, "DET");')
        self.assertIn("sb-team fav", out)

    def test_cards_show_records_and_the_line(self):
        out = run(GAME + 'return L.scorebugHtml(G({state:"pre", home:{abbr:"DET", name:"Lions", score:null, record:"4-2"}, away:{abbr:"GB", name:"Packers", score:null, record:"3-3"}, odds:{favorite:"DET", spread:3.5, total:48}}), 0);')
        for needle in ("4-2", "3-3", "DET -3.5", "O/U 48"):
            self.assertIn(needle, out)

    def test_a_final_card_says_whether_the_favorite_covered(self):
        out = run(GAME + 'return [L.scorebugHtml(G({state:"post", home:{abbr:"DET", score:27, winner:true, record:"5-2"}, away:{abbr:"GB", score:20, winner:false, record:"3-4"}, odds:{favorite:"DET", spread:3.5, total:48}}), 0), L.scorebugHtml(G({state:"post", home:{abbr:"DET", score:21, winner:true}, away:{abbr:"GB", score:20}, odds:{favorite:"DET", spread:3.5, total:48}}), 0)];')
        self.assertIn("DET covered", out[0])
        self.assertIn("GB covered", out[1])

    def test_the_grid_pins_your_teams_game_first_and_can_filter(self):
        out = run(GAME + '''const gs = [G({game_id:"1", state:"pre", kickoff:"b", home:{abbr:"KC"}, away:{abbr:"BUF"}}), G({game_id:"2", state:"in", home:{abbr:"DET"}, away:{abbr:"GB"}}), G({game_id:"3", state:"post", home:{abbr:"SF"}, away:{abbr:"SEA"}})];
          return [L.gridSections(gs, "DET", "all", () => 0).map(s => [s.label, s.games.map(g => g.game_id)]), L.gridSections(gs, "DET", "fav", () => 0).map(s => s.games.length), L.gridSections(gs, "DET", "mine", (g) => g.game_id === "3" ? 2 : 0).map(s => s.games.map(g => g.game_id))];''')
        self.assertEqual(out[0][0], ["Your team", ["2"]])
        self.assertEqual([x[0] for x in out[0][1:]], ["Upcoming", "Final"])
        self.assertEqual(out[1], [1])
        self.assertEqual(out[2], [["3"]])

    def test_all_three_badges_render(self):
        for b, cls in (("TNF", "tnf"), ("SNF", "snf"), ("MNF", "mnf")):
            out = run(GAME + f'return L.scorebugHtml(G({{badge:"{b}"}}), 0);')
            self.assertIn(f"sb-badge {cls}", out)

    def test_scoring_flash_overlay_marks_the_scoring_side(self):
        out = run(GAME + 'return L.scorebugHtml(G(), 0, "home");')
        self.assertIn("sb-flash home", out)

    def test_fantasy_audit_compares_actual_points_with_projections(self):
        out = run('''const d = {box:{teams:[{abbr:"DET", players:[{name:"Jahmyr Gibbs", position:"RB", mine:true, fantasy_points:20},{name:"Jared Goff", position:"QB", mine:false, fantasy_points:15.7}]}]},
          projections:[{name:"Jahmyr Gibbs", proj:17.0}]};
          return [L.audit(d), L.mvp(d).name, L.leaders(d, 1).map(p => p.name)];''')
        self.assertEqual(out[0]["actual"], 20.0)
        self.assertEqual((out[0]["projected"], out[0]["delta"]), (17.0, 3.0))
        self.assertEqual(out[1], "Jahmyr Gibbs")
        self.assertEqual(out[2], ["Jahmyr Gibbs"])

    MATCHUP = """const M = { home: { abbr: "DET", record: "4-2", games: 6, pf_pg: 27.5, pa_pg: 19.0, pass_yds_pg: 250, rush_yds_pg: 120,
          recent: [{week:3,opponent:"A",home:true,result:"W",team_score:30,opp_score:10},{week:4,opponent:"B",home:false,result:"L",team_score:17,opp_score:24}],
          top_players: [{name:"Amon-Ra St. Brown", position:"WR", ppg:21.4, headshot_url:null}] },
        away: { abbr: "GB", record: "3-3", games: 6, pf_pg: 21.0, pa_pg: 23.0, pass_yds_pg: 230, rush_yds_pg: 100, recent: [], top_players: [] },
        prediction: { home_score: 26.1, away_score: 21.4, total: 47.5, margin: 4.7, home_win_pct: 64, away_win_pct: 36, pick: "home", used_market: true,
                      vs_market: { market_margin: 3.5, margin_edge: 1.2 } } };"""
    PRE = """const d = { weather:{temp:41, summary:"Cloudy", wind:17, wind_alert:true, indoor:false},
          odds:{favorite:"DET", spread:3.5, total:48, home_implied:25.8, away_implied:22.2, home_ml:-170, away_ml:145},
          projections:[{name:"Amon-Ra St. Brown", position:"WR", team:"DET", proj:17.3, floor:7, ceiling:28, is_starter:true}],
          injuries:{DET:[{name:"Someone", position:"WR", status:"Questionable", detail:"Ankle"}]}, matchup: M };"""

    def pre(self, extra="", fav=""):
        return run(GAME + self.MATCHUP + self.PRE + extra + f'return L.preHtml(d, G({{state:"pre", kickoff:"2026-11-01T18:00:00Z", status_detail:"Sun 1:00 PM"}}), "{fav}");')

    def test_pre_game_has_no_countdown_and_lists_the_kickoff_time(self):
        out = self.pre()
        self.assertNotIn("gc-count", out)
        self.assertNotIn("Kickoff in", out)
        head = run(GAME + 'return L.headerHtml(G({state:"pre", kickoff:"2026-11-01T18:00:00Z"}), "");')
        self.assertIn("KICKOFF", head)
        self.assertRegex(head, r"(Sun|Mon|Sat)[^<]*\d")            # a weekday and a time, in the header

    def test_pre_game_shows_the_current_odds_for_both_sides(self):
        out = self.pre()
        for needle in ("DET -3.5", "GB +3.5", "-170", "+145", "O/U", "48.0", "implied totals"):
            self.assertIn(needle, out)

    def test_pre_game_shows_the_lineup_lab_pick_with_scores_win_chance_and_market_view(self):
        out = self.pre()
        for needle in ("Lineup Lab pick", "26.1", "21.4", "64%", "36%", "by 4.7", "vs the market"):
            self.assertIn(needle, out)

    def test_pre_game_compares_the_two_teams_with_bars_and_shows_recent_form(self):
        out = self.pre()
        for needle in ("Points per game", "Points allowed", "Passing yards", "Rushing yards", "27.5", "19.0", "cmp-row", "form-pip", "Players to watch", "Amon-Ra St. Brown"):
            self.assertIn(needle, out)

    def test_pre_game_keeps_weather_your_players_and_injuries(self):
        out = self.pre()
        for needle in ("wind alert", "17.3", "Questionable"):
            self.assertIn(needle, out)

    def test_the_pick_says_your_team_when_your_favorite_is_playing(self):
        out = self.pre(fav="DET")
        self.assertIn("Your team", out)
        self.assertIn("gc-fav", out)
        self.assertNotIn("gc-fav", self.pre(fav="KC"))

    def test_records_are_shown_in_the_game_header(self):
        out = run(GAME + 'const g = G({state:"pre", home:{abbr:"DET", name:"Lions", score:null, record:"4-2"}, away:{abbr:"GB", name:"Packers", score:null, record:"3-3"}}); return L.headerHtml(g, "");')
        self.assertIn("4-2", out)
        self.assertIn("3-3", out)

    def test_the_header_marks_your_team_with_a_ribbon(self):
        out = run(GAME + 'return [L.headerHtml(G({state:"pre"}), "DET"), L.headerHtml(G({state:"pre"}), "KC")];')
        self.assertIn("YOUR TEAM", out[0])
        self.assertNotIn("YOUR TEAM", out[1])

    def test_a_missing_matchup_still_renders_the_other_pre_game_cards(self):
        out = run(GAME + 'return L.preHtml({ odds: null, matchup: null, weather: null, injuries: {}, projections: [] }, G({state:"pre", kickoff:"2026-11-01T18:00:00Z"}), "");')
        self.assertIn("No betting line posted yet", out)
        self.assertIn("Lineup Lab pick", out)
        self.assertIn("not enough games", out.lower())

    def test_pre_game_without_data_degrades_gracefully(self):
        out = run(GAME + 'return L.preHtml({}, G({state:"pre"}), "");')
        self.assertIn("No betting line posted yet", out)
        self.assertIn("Not available yet", out)

    def test_live_view_has_field_play_log_and_your_players_and_a_between_drives_fallback(self):
        out = run(GAME + '''const d = {situation:{possession:"DET", direction:"right-to-left", yard_line:62, line_to_gain:52, down:2, distance:4, is_red_zone:false},
          plays:[{id:"1", type:"Rush", text:"Gibbs rush", scoring:false, fantasy:[]}], box:{mine_points:12.4, teams:[{abbr:"DET", players:[{name:"Jahmyr Gibbs", position:"RB", mine:true, fantasy_points:12.4}]}]}};
          return [L.liveHtml(d, G(), ""), L.liveHtml({plays:[], situation:null, box:{teams:[]}}, G(), "")];''')
        self.assertIn("<svg", out[0])
        self.assertIn("2nd &amp; 4 at DET 38", out[0])
        self.assertIn("Play by play", out[0])
        self.assertIn("12.4", out[0])
        self.assertNotIn("<svg", out[1])
        self.assertIn("Between drives", out[1])

    def test_post_game_has_mvp_impact_audit_and_leaders(self):
        out = run(GAME + '''const d = {box:{teams:[{abbr:"DET", name:"Lions", players:[{name:"Jahmyr Gibbs", position:"RB", mine:true, fantasy_points:20},{name:"Jared Goff", position:"QB", mine:false, fantasy_points:15.7}]}]}, projections:[{name:"Jahmyr Gibbs", proj:17}]};
          return L.postHtml(d, G({state:"post", home:{abbr:"DET", name:"Lions", score:27, winner:true}}), "");''')
        for needle in ("Game MVP", "Jahmyr Gibbs", "Fantasy impact audit", "pts for your matchup", "Top fantasy scorers", "Final"):
            self.assertIn(needle, out)


class WiringTests(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel)) as f:
            return f.read()

    def test_the_tab_is_called_nfl_games_with_a_live_marker_in_the_nav(self):
        html = self.read("static/index.html")
        self.assertIn('<span class="nav-label">NFL Games</span>', html)
        self.assertIn("<h1>NFL Games</h1>", html)
        self.assertNotIn("Live Games", html)
        self.assertIn('id="nav-live-dot"', html)
        css = self.read("static/style.css")
        self.assertIn(".nav-live-dot", css)

    def test_live_tab_is_in_the_nav_the_tab_list_and_the_page(self):
        html, js = self.read("static/index.html"), self.read("static/app.js")
        self.assertIn('data-tab="live"', html)
        self.assertIn('id="tab-live"', html)
        self.assertIn('id="gc-root"', html)
        self.assertIn('"live"', js[js.index("const TAB_IDS"):js.index("const TAB_IDS") + 120])
        self.assertIn("LiveTab.load()", js)
        self.assertLess(html.index('src="/live.js"'), html.index('src="/app.js"'))

    def test_the_old_my_team_strip_and_modal_are_gone(self):
        js, html = self.read("static/app.js"), self.read("static/index.html")
        self.assertNotIn("live-scores-strip", html)
        self.assertNotIn("openGameModal", js)

    def test_the_card_expands_with_a_shared_layout_animation_and_honours_reduced_motion(self):
        live = self.read("static/live.js")
        self.assertIn("panel.animate", live)
        self.assertIn("reduced()", live)
        css = self.read("static/style.css")
        self.assertIn("rgba(16,185,129,.35)", css)                 # the emerald glow
        self.assertIn(".sb-card.has-mine, .sb-live i", css)        # switched off under reduced motion

    def test_precached_and_served_without_caching(self):
        self.assertIn('"/live.js"', self.read("static/sw.js"))
        from fastapi.testclient import TestClient
        import server
        r = TestClient(server.app).get("/live.js")
        self.assertEqual((r.status_code, r.headers.get("cache-control")), (200, "no-cache"))


if __name__ == "__main__":
    unittest.main()
