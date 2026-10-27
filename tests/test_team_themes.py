"""static/team-themes.js: the 32-team palette table (and, in later tasks, the derivation engine and picker)."""
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES_JS = os.path.join(ROOT, "static", "team-themes.js")
FIELDS = ("code", "name", "city", "division", "primary", "secondary", "deep", "onPrimary", "logo")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def load_themes():
    """json.loads of the `window.TEAM_THEMES = { ... };` object literal."""
    with open(THEMES_JS) as f:
        src = f.read()
    m = re.search(r"window\.TEAM_THEMES\s*=\s*(\{.*?\n\});", src, re.S)
    if not m:
        raise AssertionError("window.TEAM_THEMES literal not found in static/team-themes.js")
    return json.loads(m.group(1))


BOOT_JS = os.path.join(ROOT, "static", "theme-boot.js")
NODE = shutil.which("node")
SEMANTIC = {"--pos", "--neg", "--avg", "--tough", "--soft"}
VAR_KEYS = {"--accent", "--accent-dim", "--accent-glow", "--brand", "--border-bright", "--bg", "--panel", "--panel-2",
            "--panel-glass", "--violet", "--info", "--violet-glow", "--info-glow", "--tm", "--tm-rgb", "--on-accent",
            "--team-secondary"}


def run_js(body, setup="", files=()):
    """Run `body` (a function body that returns JSON-able data) in node against static/team-themes.js loaded into a
    stub browser: window, document.documentElement (style + attributes) and a theme-color meta tag. Extra scripts in
    `files` are run in the same context after it. Skips the test when node is not installed."""
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    extra = "".join(f'vm.runInContext(fs.readFileSync({json.dumps(f)},"utf8"), ctx);\n' for f in files)
    script = f"""
const fs = require("fs"), vm = require("vm");
const root = {{ style: {{ props: {{}}, setProperty(k, v) {{ this.props[k] = v; }}, removeProperty(k) {{ delete this.props[k]; }} }},
  attrs: {{}}, setAttribute(k, v) {{ this.attrs[k] = String(v); }}, removeAttribute(k) {{ delete this.attrs[k]; }},
  getAttribute(k) {{ return k in this.attrs ? this.attrs[k] : null; }} }};
const meta = {{ content: "#070b09", setAttribute(k, v) {{ if (k === "content") this.content = v; }} }};
const document = {{ documentElement: root, querySelector: (sel) => (String(sel).includes("theme-color") ? meta : null) }};
const window = {{ document }};
const ctx = vm.createContext({{ window, document, console }});
{setup}
vm.runInContext(fs.readFileSync({json.dumps(THEMES_JS)}, "utf8"), ctx);
{extra}
const TeamTheme = window.TeamTheme;
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


def all_vars():
    return run_js("const o = {}; for (const c of Object.keys(window.TEAM_THEMES)) o[c] = TeamTheme.vars(c); return o;")


def luminance(hex_color):
    def ch(i):
        v = int(hex_color[i:i + 2], 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class PaletteTableTests(unittest.TestCase):
    def setUp(self):
        self.themes = load_themes()

    def test_32_teams_with_unique_codes(self):
        self.assertEqual(len(self.themes), 32)
        self.assertEqual(len({t["code"] for t in self.themes.values()}), 32)
        for key, t in self.themes.items():
            self.assertEqual(key, t["code"])

    def test_every_field_present_and_hex_valid(self):
        for code, t in self.themes.items():
            self.assertEqual(set(t), set(FIELDS), code)
            for f in ("primary", "secondary", "deep", "onPrimary"):
                self.assertRegex(t[f], HEX, f"{code}.{f}")
            for f in ("name", "city", "division", "logo"):
                self.assertTrue(t[f] and isinstance(t[f], str), f"{code}.{f}")

    def test_each_division_has_four_teams(self):
        counts = {}
        for t in self.themes.values():
            counts[t["division"]] = counts.get(t["division"], 0) + 1
        self.assertEqual(len(counts), 8)
        self.assertTrue(all(n == 4 for n in counts.values()), counts)

    def test_codes_match_the_news_team_table(self):
        from engine import news
        self.assertEqual(set(self.themes), set(news._TEAMS))

    def test_logo_urls_follow_the_news_logo_helper(self):
        from engine import news
        for code, t in self.themes.items():
            self.assertEqual(t["logo"], news.team_logo(code), code)

    def test_on_primary_is_the_higher_contrast_of_black_or_white(self):
        for code, t in self.themes.items():
            best = "#000000" if contrast(t["primary"], "#000000") >= contrast(t["primary"], "#ffffff") else "#ffffff"
            self.assertEqual(t["onPrimary"].lower(), best, code)


class EngineTests(unittest.TestCase):
    def test_unknown_or_empty_code_gives_no_vars_and_no_error(self):
        out = run_js("""return { x: TeamTheme.vars("XYZ"), e: TeamTheme.vars(""), n: TeamTheme.vars(null), u: TeamTheme.vars(undefined),
            lower: TeamTheme.vars("det"), applied: TeamTheme.apply("XYZ"), team: root.getAttribute("data-team"),
            props: Object.keys(root.style.props), cur: TeamTheme.current() };""")
        self.assertEqual((out["x"], out["e"], out["n"], out["u"], out["lower"]), ({}, {}, {}, {}, {}))
        self.assertEqual((out["applied"], out["team"], out["props"], out["cur"]), (False, None, [], ""))

    def test_semantic_variables_are_never_themed(self):
        for code, v in all_vars().items():
            self.assertFalse(SEMANTIC & set(v), code)

    def test_every_team_vars_has_the_exact_key_set(self):
        for code, v in all_vars().items():
            self.assertEqual(set(v), VAR_KEYS, code)

    def test_derived_values_follow_the_spec(self):
        t = load_themes()["DET"]
        v = run_js('return TeamTheme.vars("DET");')
        self.assertEqual((v["--accent"], v["--bg"], v["--on-accent"], v["--team-secondary"], v["--tm"]),
                         (t["primary"], t["deep"], t["onPrimary"], t["secondary"], t["primary"]))
        self.assertEqual((v["--violet"], v["--info"]), (t["secondary"], t["secondary"]))
        r, g, b = (int(t["primary"][i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(v["--tm-rgb"], f"{r},{g},{b}")
        self.assertEqual(v["--accent-glow"], f"rgba({r}, {g}, {b}, 0.38)")
        self.assertEqual(v["--border-bright"], f"rgba({r}, {g}, {b}, 0.28)")
        d = [int(t["deep"][i:i + 2], 16) for i in (1, 3, 5)]
        want = "#" + "".join(f"{round(c * 0.93 + 255 * 0.07):02x}" for c in d)          # deep mixed 7% toward white
        self.assertEqual(v["--panel"], want)
        dim = "#" + "".join(f"{round(int(t['primary'][i:i + 2], 16) * 0.82):02x}" for i in (1, 3, 5))   # primary 18% toward black
        self.assertEqual((v["--accent-dim"], v["--brand"]), (dim, dim))

    def test_apply_sets_the_attribute_and_vars_clear_removes_them_and_theme_color_follows(self):
        out = run_js("""const a = TeamTheme.apply("GB"); const set = { a, team: root.getAttribute("data-team"), cur: TeamTheme.current(),
            accent: root.style.props["--accent"], meta: meta.content };
            TeamTheme.apply("KC"); set.second = root.getAttribute("data-team"); set.kcAccent = root.style.props["--accent"];
            TeamTheme.clear(); set.after = { team: root.getAttribute("data-team"), props: Object.keys(root.style.props), cur: TeamTheme.current(), meta: meta.content };
            return set;""")
        themes = load_themes()
        self.assertEqual((out["a"], out["team"], out["cur"]), (True, "GB", "GB"))
        self.assertEqual((out["accent"], out["meta"]), (themes["GB"]["primary"], themes["GB"]["deep"]))
        self.assertEqual((out["second"], out["kcAccent"]), ("KC", themes["KC"]["primary"]))
        self.assertEqual(out["after"], {"team": None, "props": [], "cur": "", "meta": "#070b09"})

    def test_valid_get_and_all(self):
        out = run_js("""return { v: ["DET", "WAS", "XYZ", "det", "", null, "__proto__", "constructor"].map((c) => TeamTheme.valid(c)),
            g: TeamTheme.get("DET").name, none: TeamTheme.get("XYZ"), all: TeamTheme.all().map((t) => t.code + "|" + t.division) };""")
        self.assertEqual(out["v"], [True, True, False, False, False, False, False, False])
        self.assertEqual((out["g"], out["none"]), ("Lions", None))
        self.assertEqual(len(out["all"]), 32)
        self.assertTrue(out["all"][0].endswith("AFC East") and out["all"][-1].endswith("NFC West"))

    def test_contrast_accent_text_and_surfaces_on_every_team(self):
        for code, v in all_vars().items():
            t = load_themes()[code]
            panel = v["--panel"]
            self.assertGreaterEqual(contrast(t["primary"], panel), 4.5, f"{code}: primary on panel {contrast(t['primary'], panel):.2f}")
            self.assertGreaterEqual(contrast(t["onPrimary"], t["primary"]), 4.5, f"{code}: onPrimary on primary {contrast(t['onPrimary'], t['primary']):.2f}")
            self.assertGreaterEqual(contrast("#fafafa", panel), 7.0, f"{code}: --text on panel")
            self.assertGreaterEqual(contrast("#a1a1aa", panel), 4.5, f"{code}: --muted on panel")
            self.assertGreaterEqual(contrast("#a1a1aa", v["--bg"]), 4.5, f"{code}: --muted on bg")


class BootTests(unittest.TestCase):
    def boot(self, storage):
        return run_js("return { team: root.getAttribute('data-team'), accent: root.style.props['--accent'] || null };",
                      setup=f"window.localStorage = {storage};", files=(BOOT_JS,))

    def test_a_saved_team_is_applied_before_anything_else(self):
        out = self.boot('{ getItem: (k) => (k === "eb_team" ? "DET" : null) }')
        self.assertEqual((out["team"], out["accent"]), ("DET", load_themes()["DET"]["primary"]))

    def test_an_unknown_saved_code_falls_back_to_the_default_theme_without_an_error(self):
        for bad in ("XYZ", "", "<img src=x>", "det", "DET; background:red"):
            out = self.boot('{ getItem: () => %s }' % json.dumps(bad))
            self.assertEqual((out["team"], out["accent"]), (None, None), bad)

    def test_nothing_saved_or_storage_throwing_is_the_default_theme(self):
        self.assertEqual(self.boot("{ getItem: () => null }")["team"], None)
        self.assertEqual(self.boot('{ getItem: () => { throw new Error("blocked"); } }')["team"], None)
        self.assertEqual(self.boot("undefined")["team"], None)


class WiringTests(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel)) as f:
            return f.read()

    def test_index_loads_the_palette_and_boot_before_the_stylesheet(self):
        html = self.read("static/index.html")
        a, b, c = html.index('src="/team-themes.js"'), html.index('src="/theme-boot.js"'), html.index('href="/style.css"')
        self.assertTrue(a < b < c)

    def test_service_worker_precaches_the_theme_files_and_bumps_the_cache(self):
        sw = self.read("static/sw.js")
        for f in ("/team-themes.js", "/theme-boot.js", "/theme.js"):
            self.assertIn(f'"{f}"', sw)
        self.assertNotIn("lineup-lab-shell-v5", sw)

    def test_text_on_the_accent_follows_the_team(self):
        css = self.read("static/style.css")
        for color in ("#0e1b15", "#f0fdf7"):
            for m in re.finditer(re.escape(color), css):
                self.assertTrue(css[:m.start()].endswith("var(--on-accent, "), f"{color} at {m.start()} is not behind --on-accent")

    def test_theme_scripts_are_served_with_no_cache(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        for f in ("/team-themes.js", "/theme-boot.js"):
            r = client.get(f)
            self.assertEqual(r.status_code, 200, f)
            self.assertEqual(r.headers.get("cache-control"), "no-cache", f)


if __name__ == "__main__":
    unittest.main()
