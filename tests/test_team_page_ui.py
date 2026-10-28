"""static/team-page.js: the team page's markup, built from /api/team/{code}. Pure, so it runs under node."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV = """const env = { esc: (s) => s == null ? "" : String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  d1: (v) => v == null ? "\\u2014" : Number(v).toFixed(1), statusFlags: (p) => p.injury_status ? '<span class="injury-flag">' + p.injury_status.toUpperCase() + '</span>' : "",
  headshotAttrs: (p) => 'src="x"', proxyImg: (u) => u, theme: { city: "Detroit", name: "Lions", division: "NFC North", primary: "#0076B6", secondary: "#B0B7BC" } };
const D = { team: "DET", logo: "https://a.espncdn.com/x.png", record: { text: "4-2" }, points_for: 130, points_against: 110,
  games: [{ week: 1, opponent: "GB", home: true, result: "W", team_score: 27, opp_score: 20, date: "2026-09-13" }, { week: 2, opponent: "TB", home: false, result: "L", team_score: 17, opp_score: 24, date: "2026-09-20" },
          { week: 3, opponent: "MIN", home: true, result: null, date: "2026-10-04" }],
  next_game: { week: 3, opponent: "MIN", home: true, date: "2026-10-04", spread: -6.5, total: 50, implied_total: 28.2, opp_implied_total: 21.8 },
  stats: { games: 2, points_for_pg: 22.0, points_against_pg: 22.0, pass_yds_pg: 250, rush_yds_pg: 110 },
  players: [{ player_id: "w", name: "Amon-Ra St. Brown", position: "WR", ppg: 21.4, proj: 17.3, injury_status: "Questionable", headshot_url: null }, { player_id: "r", name: "Jahmyr Gibbs", position: "RB", ppg: 17, proj: 16.2 }] };"""


def run(body):
    code = f'const T = require({json.dumps(os.path.join(ROOT, "static/team-page.js"))});' + ENV + f'console.log(JSON.stringify((() => {{ {body} }})()));'
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class TeamPageUITests(unittest.TestCase):
    def test_header_shows_name_division_record_and_point_differential(self):
        out = run("return T.html(D, env);")
        for needle in ("DETROIT", "LIONS", "NFC North", "4-2", "+20", "130", "110"):
            self.assertIn(needle, out)

    def test_the_status_ribbon_shows_the_next_game_with_the_line_and_implied_score(self):
        out = run("return T.html(D, env);")
        for needle in ("NEXT", "Wk 3", "vs MIN", "DET -6.5", "O/U 50.0", "28.2", "21.8"):
            self.assertIn(needle, out)

    def test_after_the_last_game_without_a_next_game_it_says_so(self):
        out = run("return T.html(Object.assign({}, D, { next_game: null }), env);")
        self.assertIn("No upcoming game", out)

    def test_rate_tiles_show_each_stat_with_a_gauge_and_the_league_average_tick(self):
        out = run("return T.html(D, env);")
        for needle in ("Points / game", "Allowed / game", "Pass yds / game", "Rush yds / game", "250.0", "tpx-gauge", "tpx-avg"):
            self.assertIn(needle, out)

    def test_results_chart_has_one_bar_per_played_game_and_marks_wins_and_losses(self):
        out = run("return T.marginChart(D.games, env);")
        self.assertEqual(out.count("<rect"), 2)                      # the unplayed game has no bar
        self.assertIn("tpx-w", out)
        self.assertIn("tpx-l", out)
        self.assertIn("Wk 1: W 27", out)

    def test_results_list_shows_every_game_including_unplayed(self):
        out = run("return T.html(D, env);")
        self.assertIn("tpx-game res-w", out)
        self.assertIn("tpx-game res-l", out)
        self.assertIn("tpx-game res-pending", out)

    def test_players_table_has_projection_bars_status_tags_and_clickable_rows(self):
        out = run("return T.html(D, env);")
        for needle in ('data-player="w"', 'data-opp="MIN"', "QUESTIONABLE", "17.3", "21.4", "tpx-bar"):
            self.assertIn(needle, out)

    def test_text_from_the_feed_is_escaped(self):
        out = run('return T.html(Object.assign({}, D, { players: [{ player_id: "x", name: "<img src=x>", position: "WR", ppg: 1, proj: 1 }] }), env);')
        self.assertNotIn("<img src=x>", out)

    def test_an_empty_team_still_renders(self):
        out = run('return T.html({ team: "DET", record: { text: "0-0" }, points_for: 0, points_against: 0, games: [], next_game: null, stats: {}, players: [] }, env);')
        self.assertIn("No games yet", out)
        self.assertIn("No player data yet", out)


class WiringTests(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel)) as f:
            return f.read()

    def test_the_modal_uses_the_new_builder_and_the_old_one_is_gone(self):
        js = self.read("static/app.js")
        self.assertIn("TeamPageUI.html(", js)
        self.assertNotIn("function teamPageHtml", js)
        html = self.read("static/index.html")
        self.assertLess(html.index('src="/team-page.js"'), html.index('src="/app.js"'))
        self.assertIn('"/team-page.js"', self.read("static/sw.js"))

    def test_the_page_is_served_without_caching(self):
        from fastapi.testclient import TestClient
        import server
        r = TestClient(server.app).get("/team-page.js")
        self.assertEqual((r.status_code, r.headers.get("cache-control")), (200, "no-cache"))


if __name__ == "__main__":
    unittest.main()
