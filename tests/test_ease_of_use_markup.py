"""Batch B ease-of-use changes: bottom nav, friendly api() errors, dialog semantics, no inline handlers."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


class EaseOfUseMarkup(unittest.TestCase):
    def setUp(self):
        self.html = read("static/index.html")
        self.js = read("static/app.js")

    def test_bottom_nav_has_waivers_not_nfl_games(self):
        nav = block(self.html, 'id="bottom-nav"', "</nav>")
        self.assertIn('data-go="waivers"', nav)
        self.assertIn("<span>Waivers</span>", nav)
        self.assertNotIn('data-go="live"', nav)
        self.assertNotIn("NFL Games</span>", nav)
        # still reachable from the More drawer (the sidebar nav it opens)
        side = block(self.html, 'class="sidebar-nav"', '<div class="sidebar-middle">')
        self.assertIn('data-tab="live"', side)
        self.assertIn('<span class="nav-label">NFL Games</span>', side)

    def test_big_board_sits_below_the_decision_tabs(self):
        side = block(self.html, 'class="sidebar-nav"', '<div class="sidebar-middle">')
        for tab in ("myteam", "startsit", "trade", "waivers"):
            self.assertLess(side.index(f'data-tab="{tab}"'), side.index('data-tab="board"'))

    def test_api_errors_never_show_the_url(self):
        api = block(self.js, "async function api(path, opts)", "\n}\n")
        self.assertNotIn("-> ${", api)
        self.assertIn("Can't reach Lineup Lab", api)
        self.assertIn("err.status = res.status", api)

    def test_modals_get_dialog_semantics_in_one_place(self):
        helper = block(self.js, "function decorateModalRoot(root)", "\n}\n")
        self.assertIn('setAttribute("role", "dialog")', helper)
        self.assertIn('setAttribute("aria-modal", "true")', helper)
        self.assertIn("aria-label", helper)

    def test_no_inline_event_handlers(self):
        for rel in ("static/index.html", "static/app.js"):
            self.assertIsNone(re.search(r"\sonclick\s*=", read(rel)), rel)

    def test_gate_sends_the_platform(self):
        gate = block(self.js, "function renderGateConnectLeague()", "\nasync function main()")
        self.assertIn('data-platform="espn"', gate)
        self.assertIn("platform: connectPlatform", gate)


if __name__ == "__main__":
    unittest.main()
