"""The Sleeper-style skin: position-colored chips, a bottom tab bar on phones, and the palette tokens."""
import json
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def run(body):
    code = f'const S = require({json.dumps(os.path.join(ROOT, "static/skin.js"))});console.log(JSON.stringify((() => {{ {body} }})()));'
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class PositionTests(unittest.TestCase):
    def test_labels_map_to_the_six_position_colors(self):
        out = run('return ["QB","RB","WR","TE","K","DEF","PK","D/ST","DST","FLEX","SUPER_FLEX","SUPERFLEX","RB/WR/TE","WR/TE","OP","REC_FLEX","WRRB_FLEX"].map(S.posOf);')
        self.assertEqual(out, ["QB", "RB", "WR", "TE", "K", "DEF", "K", "DEF", "DEF", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"])

    def test_noise_is_ignored(self):
        out = run('return ["", null, undefined, "BN", "FA", "Week 8", " rb ", "qb\\n"].map(S.posOf);')
        self.assertEqual(out, [None, None, None, None, None, None, "RB", "QB"])

    def test_decorate_tags_chips_once_and_leaves_other_elements_alone(self):
        out = run("""const mk = (t) => ({ textContent: t, dataset: {} });
          const a = mk("RB"), b = mk("FLEX"), c = mk("zzz");
          const root = { querySelectorAll: () => [a, b, c] };
          const n1 = S.decorate(root), n2 = S.decorate(root);
          return { a: a.dataset.pos, b: b.dataset.pos, c: c.dataset.pos || null, n1, n2 };""")
        self.assertEqual((out["a"], out["b"], out["c"]), ("RB", "FLEX", None))
        self.assertEqual((out["n1"], out["n2"]), (2, 0))


class SkinWiringTests(unittest.TestCase):
    def test_palette_is_sleeper_like_and_position_colors_are_defined(self):
        css = read("static/style.css")
        for needle in ("--pos-qb: #ff2a6d", "--pos-rb: #00ceb8", "--pos-wr: #58a7ff", "--pos-te: #ffae58", "--pos-k: #bd66ff", "--pos-def: #7988a1", '[data-pos="QB"]'):
            self.assertIn(needle, css)

    def test_the_bottom_tab_bar_exists_with_the_main_tabs_and_a_more_button(self):
        html = read("static/index.html")
        nav = html[html.index('id="bottom-nav"'):][:2200]
        for tab in ("myteam", "live", "startsit", "trade"):
            self.assertIn(f'data-go="{tab}"', nav)
        self.assertIn('id="bn-more"', nav)
        self.assertIn('id="bn-live-dot"', nav)
        css = read("static/style.css")
        self.assertRegex(css, r"@media \(max-width: 900px\)[^{]*\{[^@]*#bottom-nav \{ display: flex")

    def test_skin_script_is_loaded_precached_and_served_fresh(self):
        self.assertLess(read("static/index.html").index('src="/skin.js"'), read("static/index.html").index('src="/app.js"'))
        self.assertIn('"/skin.js"', read("static/sw.js"))
        from fastapi.testclient import TestClient
        import server
        r = TestClient(server.app).get("/skin.js")
        self.assertEqual((r.status_code, r.headers.get("cache-control")), (200, "no-cache"))

    def test_numbers_use_tabular_sans_not_a_terminal_font(self):
        css = read("static/style.css")
        m = re.search(r"--mono:\s*([^;]+);", css[css.index("/* ---- Sleeper skin"):])
        self.assertIsNotNone(m)
        self.assertNotIn("Mono", m.group(1))

    def test_the_theme_color_meta_matches_the_new_background(self):
        self.assertIn('content="#101520"', read("static/index.html"))


if __name__ == "__main__":
    unittest.main()
