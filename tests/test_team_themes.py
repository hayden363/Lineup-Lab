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
THEME_JS = os.path.join(ROOT, "static", "theme.js")
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
const TeamTheme = window.TeamTheme, ThemePicker = window.ThemePicker, ThemeFX = window.ThemeFX;
process.on("unhandledRejection", (e) => {{ console.error("UNHANDLED REJECTION " + e); process.exit(3); }});
Promise.resolve((() => {{ {body} }})()).then((out) => console.log(JSON.stringify(out)));
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


PICKER_SETUP = """
window.__store = {}; window.__fail = false; window.__posts = []; window.__fx = []; window.__signed = false; window.__post_fails = false;
window.localStorage = {
  getItem: (k) => { if (window.__fail) throw new Error("blocked"); return k in window.__store ? window.__store[k] : null; },
  setItem: (k, v) => { if (window.__fail) throw new Error("blocked"); window.__store[k] = String(v); },
  removeItem: (k) => { if (window.__fail) throw new Error("blocked"); delete window.__store[k]; },
};
document.createElement = (tag) => ({ tag, className: "", textContent: "", style: { setProperty(k, v) { this[k] = v; } }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
  remove() { const b = document.body; b.children = b.children.filter((c) => c !== this); this.removed = true; } });
document.body = { children: [], appendChild(n) { this.children.push(n); return n; } };
window.__timers = []; window.__reduced = false;
window.setTimeout = (fn, ms) => { window.__timers.push({ fn, ms }); return window.__timers.length; };
window.clearTimeout = () => {};
window.matchMedia = () => ({ matches: window.__reduced });
document.getElementById = (id) => (id === "team-hero" ? window.__hero || null : null);
"""
PICKER_AFTER = """
ThemePicker.configure({ isSignedIn: () => window.__signed,
  saveToAccount: (c) => { window.__posts.push(c); return window.__post_fails ? Promise.reject(new Error("offline")) : Promise.resolve(); } });
"""


FX_STUB = """window.ThemeFX = { kickoff: (c) => window.__fx.push("kickoff:" + c), renderHero: () => window.__fx.push("hero") };
"""


def run_picker(body, real_fx=False):
    """Runs `body` with the palette + engine + theme.js loaded in the stub browser (storage and account saving stubbed).
    The picker tests record ThemeFX calls with a stub installed after load; real_fx=True keeps the real ThemeFX."""
    return run_js(PICKER_AFTER + ("" if real_fx else FX_STUB) + body, setup=PICKER_SETUP, files=(THEME_JS,))


def run_fx(body):
    return run_picker(body, real_fx=True)


def fake_host():
    return """const handlers = {}; const host = { innerHTML: "", _bound: false,
      addEventListener(t, fn, cap) { (handlers[t + (cap ? ":capture" : "")] = handlers[t + (cap ? ":capture" : "")] || []).push(fn); },
      querySelectorAll() { return []; }, querySelector() { return null; }, contains() { return false; } };
    const fire = (type, el, extra) => { (handlers[type] || []).forEach((fn) => fn(Object.assign({ type, target: el, relatedTarget: null, preventDefault() {} }, extra || {}))); };
    const chip = (code) => ({ dataset: code === "" ? { default: "1" } : { team: code }, closest(sel) { return (sel.includes("data-team") && code !== "") || (sel.includes("data-default") && code === "") ? this : null; } });"""


class PickerTests(unittest.TestCase):
    def test_choose_applies_stores_posts_when_signed_in_and_plays_the_kickoff(self):
        out = run_picker("""window.__signed = true; ThemePicker.choose("DET");
            return { cur: TeamTheme.current(), store: window.__store.eb_team, posts: window.__posts, fx: window.__fx, team: root.getAttribute("data-team") };""")
        self.assertEqual((out["cur"], out["store"], out["posts"], out["team"]), ("DET", "DET", ["DET"], "DET"))
        self.assertEqual(out["fx"], ["kickoff:DET", "hero"])

    def test_signed_out_choose_never_posts(self):
        out = run_picker('ThemePicker.choose("GB"); return { posts: window.__posts, store: window.__store.eb_team, cur: TeamTheme.current() };')
        self.assertEqual((out["posts"], out["store"], out["cur"]), ([], "GB", "GB"))

    def test_blocked_storage_still_applies_for_the_session_and_does_not_throw(self):
        out = run_picker("""window.__fail = true; ThemePicker.choose("KC"); const a = TeamTheme.current();
            ThemePicker.syncFromAccount("GB"); ThemePicker.choose(""); return { a, after: TeamTheme.current() };""")
        self.assertEqual((out["a"], out["after"]), ("KC", ""))

    def test_a_failing_account_save_is_swallowed(self):
        out = run_picker("""window.__signed = true; window.__post_fails = true; ThemePicker.choose("DET");
            await_ = new Promise((r) => setTimeout(r, 20)); return await_.then(() => ({ cur: TeamTheme.current() }));""")
        self.assertEqual(out["cur"], "DET")

    def test_sync_from_account_applies_only_when_the_browser_has_no_valid_team(self):
        out = run_picker("""ThemePicker.syncFromAccount("GB"); const fresh = { cur: TeamTheme.current(), store: window.__store.eb_team };
            ThemePicker.syncFromAccount("KC"); const second = TeamTheme.current(); return { fresh, second };""")
        self.assertEqual(out["fresh"], {"cur": "GB", "store": "GB"})
        self.assertEqual(out["second"], "GB")                     # the browser now has a team: the account no longer overrides it

    def test_browser_choice_beats_the_account_value(self):
        out = run_picker('window.__store.eb_team = "KC"; ThemePicker.syncFromAccount("DET"); return { cur: TeamTheme.current(), store: window.__store.eb_team };')
        self.assertEqual(out, {"cur": "", "store": "KC"})          # sync never overrides; the boot script is what applied KC

    def test_a_valid_browser_team_applied_by_boot_wins_over_the_account(self):
        out = run_picker('TeamTheme.apply("KC"); window.__store.eb_team = "KC"; ThemePicker.init(); ThemePicker.syncFromAccount("DET"); return { cur: TeamTheme.current() };')
        self.assertEqual(out["cur"], "KC")

    def test_unknown_account_theme_is_ignored(self):
        out = run_picker('for (const bad of ["XYZ", "", null, undefined, 5, "<b>"]) ThemePicker.syncFromAccount(bad); return { cur: TeamTheme.current(), store: window.__store.eb_team || null };')
        self.assertEqual(out, {"cur": "", "store": None})

    def test_unknown_codes_are_ignored_by_choose_and_preview(self):
        out = run_picker('ThemePicker.choose("XYZ"); ThemePicker.preview("XYZ"); return { cur: TeamTheme.current(), store: window.__store.eb_team || null, posts: window.__posts, fx: window.__fx };')
        self.assertEqual(out, {"cur": "", "store": None, "posts": [], "fx": []})

    def test_preview_then_end_preview_restores_the_committed_team(self):
        out = run_picker("""ThemePicker.choose("DET"); const seen = [];
            for (const c of ["GB", "KC", "SEA", "GB", "NE"]) { ThemePicker.preview(c); seen.push(TeamTheme.current()); }
            ThemePicker.endPreview(); const a = { cur: TeamTheme.current(), team: root.getAttribute("data-team") };
            ThemePicker.endPreview(); return { seen, a, again: TeamTheme.current(), store: window.__store.eb_team };""")
        self.assertEqual(out["seen"], ["GB", "KC", "SEA", "GB", "NE"])
        self.assertEqual((out["a"], out["again"], out["store"]), ({"cur": "DET", "team": "DET"}, "DET", "DET"))   # previews never persist

    def test_preview_with_nothing_committed_returns_to_the_default_theme(self):
        out = run_picker('ThemePicker.preview("GB"); ThemePicker.endPreview(); return { cur: TeamTheme.current(), team: root.getAttribute("data-team") };')
        self.assertEqual(out, {"cur": "", "team": None})

    def test_rapid_hover_across_chips_then_a_click_commits_exactly_the_clicked_team(self):
        out = run_picker(fake_host() + """ThemePicker.render(host);
            for (const c of ["GB", "KC", "SEA"]) fire("pointerover", chip(c));
            fire("click", chip("NE")); const committed = { cur: TeamTheme.current(), store: window.__store.eb_team };
            fire("pointerover", chip("GB")); fire("pointerleave", host);
            return { committed, afterLeave: TeamTheme.current() };""")
        self.assertEqual(out["committed"], {"cur": "NE", "store": "NE"})
        self.assertEqual(out["afterLeave"], "NE")

    def test_the_default_chip_clears_the_team_everywhere(self):
        out = run_picker("""window.__signed = true; ThemePicker.choose("DET"); window.__fx.length = 0; ThemePicker.choose("");
            return { cur: TeamTheme.current(), team: root.getAttribute("data-team"), store: window.__store.eb_team || null, posts: window.__posts, fx: window.__fx };""")
        self.assertEqual((out["cur"], out["team"], out["store"]), ("", None, None))
        self.assertEqual(out["posts"], ["DET", None])
        self.assertEqual(out["fx"], ["hero"])                       # the hero empties; there is no kickoff for the default theme

    def test_choosing_the_team_that_is_already_chosen_does_not_replay_the_kickoff(self):
        out = run_picker('ThemePicker.choose("DET"); window.__fx.length = 0; ThemePicker.choose("DET"); return { fx: window.__fx };')
        self.assertEqual(out["fx"], ["hero"])

    def test_a_logo_that_fails_to_load_becomes_the_abbreviation(self):
        out = run_picker(fake_host() + """ThemePicker.render(host);
            const img = { dataset: { logo: "DET" }, tagName: "IMG", replaced: null, replaceWith(n) { this.replaced = n; }, closest() { return null; } };
            fire("error", img, {}); (handlers["error:capture"] || []).forEach((fn) => fn({ type: "error", target: img }));
            return { cls: img.replaced && img.replaced.className, text: img.replaced && img.replaced.textContent };""")
        self.assertEqual(out["text"], "DET")
        self.assertIn("tp-abbr", out["cls"])

    def test_chips_html_has_every_team_the_default_chip_and_no_inline_handlers(self):
        out = run_picker('return { html: ThemePicker.chipsHtml("GB") };')
        html = out["html"]
        self.assertEqual(html.count("data-team="), 32)
        self.assertEqual(html.count("data-default="), 1)
        self.assertEqual(html.count("tp-div-h"), 8)
        self.assertEqual(html.count('aria-pressed="true"'), 1)
        self.assertRegex(html, r'data-team="GB"[^>]*aria-pressed="true"')
        self.assertNotRegex(html, r"\son[a-z]+\s*=")            # the CSP forbids inline handlers
        self.assertIn("/api/img?url=", html)                      # logos go through the same-origin image proxy
        self.assertIn("AFC East", html)
        self.assertIn("NFC West", html)
        default_pressed = run_picker('return { html: ThemePicker.chipsHtml("") };')["html"]
        self.assertRegex(default_pressed, r'data-default="1"[^>]*aria-pressed="true"')


class PickerWiringTests(WiringTests):
    def test_theme_js_loads_before_app_js_and_the_picker_mount_is_outside_the_login_gates(self):
        html = self.read("static/index.html")
        self.assertLess(html.index('src="/theme.js"'), html.index('src="/app.js"'))
        mount = html.index('id="team-picker"')
        self.assertLess(mount, html.index('id="settings-logged-out"'))
        self.assertGreater(mount, html.index('id="tab-settings"'))

    def test_app_js_hands_the_account_theme_to_the_picker_and_renders_it_in_settings(self):
        js = self.read("static/app.js")
        for needle in ("ThemePicker.syncFromAccount(", "ThemePicker.render(", "ThemePicker.configure(", "TeamTheme.get("):
            self.assertTrue(needle in js, f"app.js does not call {needle}")
        self.assertFalse("const TEAM_COLORS" in js, "the player-card tint must read the one palette table")

    def test_picker_styles_exist(self):
        css = self.read("static/style.css")
        for sel in (".tp-grid", ".tp-chip", ".tp-chip[aria-pressed=\"true\"]", ".tp-abbr", ".tp-div-h"):
            self.assertTrue(sel in css, f"style.css lacks {sel}")


HERO_HOST = """const hh = {}; const hero = { innerHTML: "", _tpBound: false,
      addEventListener(t, fn, cap) { (hh[t + (cap ? ":capture" : "")] = hh[t + (cap ? ":capture" : "")] || []).push(fn); } };
    window.__hero = hero;"""


class AtmosphereTests(unittest.TestCase):
    def test_hero_is_empty_without_a_team(self):
        out = run_fx(HERO_HOST + 'hero.innerHTML = "stale"; ThemeFX.renderHero(); return { html: hero.innerHTML };')
        self.assertEqual(out["html"], "")

    def test_hero_shows_logo_city_and_name_for_a_team(self):
        t = load_themes()["DET"]
        out = run_fx(HERO_HOST + 'TeamTheme.apply("DET"); ThemeFX.renderHero(); return { html: hero.innerHTML };')
        html = out["html"]
        self.assertIn("Detroit", html)
        self.assertIn("Lions", html)
        self.assertIn("/api/img?url=" + t["logo"].replace(":", "%3A").replace("/", "%2F"), html)
        self.assertIn('data-logo="DET"', html)
        self.assertIn("th-band", html)
        self.assertNotRegex(html, r"\son[a-z]+\s*=")

    def test_hero_follows_the_current_team_and_clears_back_to_default(self):
        out = run_fx(HERO_HOST + """TeamTheme.apply("GB"); ThemeFX.renderHero(); const gb = hero.innerHTML;
            TeamTheme.apply("KC"); ThemeFX.renderHero(); const kc = hero.innerHTML; TeamTheme.clear(); ThemeFX.renderHero();
            return { gb: gb.includes("Packers"), kc: kc.includes("Chiefs") && !kc.includes("Packers"), cleared: hero.innerHTML };""")
        self.assertEqual((out["gb"], out["kc"], out["cleared"]), (True, True, ""))

    def test_hero_logo_error_falls_back_to_the_abbreviation(self):
        out = run_fx(HERO_HOST + """TeamTheme.apply("DET"); ThemeFX.renderHero();
            const img = { dataset: { logo: "DET" }, replaceWith(n) { this.replaced = n; } };
            (hh["error:capture"] || []).forEach((fn) => fn({ type: "error", target: img }));
            return { text: img.replaced && img.replaced.textContent, cls: img.replaced && img.replaced.className, bound: (hh["error:capture"] || []).length };""")
        self.assertEqual((out["text"], out["bound"]), ("DET", 1))
        self.assertIn("th-abbr", out["cls"])

    def test_hero_binds_its_error_listener_once_however_often_it_renders(self):
        out = run_fx(HERO_HOST + 'TeamTheme.apply("DET"); for (let i = 0; i < 5; i++) ThemeFX.renderHero(); return { n: (hh["error:capture"] || []).length };')
        self.assertEqual(out["n"], 1)

    def test_a_missing_hero_mount_is_not_an_error(self):
        run_fx('window.__hero = null; TeamTheme.apply("DET"); ThemeFX.renderHero(); return 1;')

    def test_kickoff_adds_an_overlay_that_removes_itself(self):
        out = run_fx("""ThemeFX.kickoff("DET"); const during = document.body.children.length; const t = window.__timers[window.__timers.length - 1];
            t.fn(); return { during, after: document.body.children.length, ms: t.ms, cls: null };""")
        self.assertEqual((out["during"], out["after"]), (1, 0))
        self.assertGreaterEqual(out["ms"], 700)

    def test_kickoff_is_skipped_for_reduced_motion_and_for_unknown_teams(self):
        out = run_fx("""window.__reduced = true; ThemeFX.kickoff("DET"); const a = document.body.children.length;
            window.__reduced = false; ThemeFX.kickoff("XYZ"); ThemeFX.kickoff(""); return { a, b: document.body.children.length };""")
        self.assertEqual((out["a"], out["b"]), (0, 0))

    def test_kickoff_called_twice_leaves_one_overlay_at_most(self):
        out = run_fx("""ThemeFX.kickoff("DET"); ThemeFX.kickoff("GB"); ThemeFX.kickoff("KC");
            const n = document.body.children.length; const stale = window.__timers[0]; stale.fn();     // an old timer firing must not remove the new overlay
            return { n, still: document.body.children.length };""")
        self.assertEqual((out["n"], out["still"]), (1, 1))

    def test_kickoff_colors_come_from_the_palette(self):
        t = load_themes()["GB"]
        out = run_fx('ThemeFX.kickoff("GB"); const el = document.body.children[0]; return { a: el.style["--k1"], b: el.style["--k2"], cls: el.className };')
        self.assertEqual((out["a"], out["b"]), (t["primary"], t["secondary"]))
        self.assertIn("th-kick", out["cls"])


class AtmosphereWiringTests(WiringTests):
    def test_hero_mount_is_at_the_top_of_the_app_above_every_tab(self):
        html = self.read("static/index.html")
        self.assertLess(html.index('id="team-hero"'), html.index('id="tab-board"'))
        self.assertGreater(html.index('id="team-hero"'), html.index('id="app"'))

    def test_atmosphere_styles_exist_and_reduced_motion_is_honoured(self):
        css = self.read("static/style.css")
        for sel in (".th-band", ".th-art", ".th-lines", ".th-logo", ".th-name", ".th-kick", "html[data-team] body::before", "#team-hero:empty"):
            self.assertTrue(sel in css, f"style.css lacks {sel}")
        block = css[css.index("/* ---- team atmosphere"):]
        self.assertIn("prefers-reduced-motion", block)
        self.assertRegex(block, r"@media \(max-width: 5\d\dpx\)")      # the phone layout collapses the band


if __name__ == "__main__":
    unittest.main()
