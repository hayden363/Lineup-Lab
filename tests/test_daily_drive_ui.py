"""Daily Drive UI round 2 (owner, 2026-11-17): football emojis per play, a Wordle-style end screen with tabs, a podium
leaderboard with each player's spoiler-free drive, desktop side columns, and the Daily Drive first in the app sidebar
with a halo until today's game is played."""
import os
import re
import unittest

from engine import daily_drive as dd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _r(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()


class EmojiTests(unittest.TestCase):
    def test_owner_emojis(self):
        self.assertEqual(dd.TIERS[6][2], "\U0001F3C8")          # Highlight Reel TD: football
        self.assertEqual(dd.TIERS[5][2], "\U0001F4A3")          # Bomb: bomb
        self.assertEqual(dd.TIERS[3][2], "⛓️")        # Chain Mover: chains
        self.assertEqual(dd.SACKED_EMOJI, "❌")
        js = _r("static/play.js")
        for t in range(1, 7):
            self.assertIn('"%s"' % dd.TIERS[t][2], js)            # page and server agree
        self.assertIn('var SACK = "%s"' % dd.SACKED_EMOJI, js)


class EndScreenTests(unittest.TestCase):
    def test_wordle_top_and_tabs(self):
        js = _r("static/play.js")
        for s in ('"dd-emo"', '"Share result"', '"Leaderboard"', '"Answers"', '"My stats"', 'role: "tab"', "navigator.share"):
            self.assertIn(s, js)
        css = _r("static/play.css")
        self.assertIn('.dd[data-mode="result"] .dd-stage { width: min(1120px', css)     # desktop end screen uses the width
        self.assertIn(".dd-results { display: grid; grid-template-columns:", css)

    def test_podium_leaderboard(self):
        js = _r("static/play.js")
        self.assertIn("function podium(", js)
        self.assertIn("top.slice(0, 10)", js)
        self.assertIn("r.emoji", js)


class SidebarTests(unittest.TestCase):
    def test_daily_drive_is_first_and_glows_until_played(self):
        html = _r("static/index.html")
        nav = html[html.index('<div class="sidebar-nav">'):html.index('<div class="sidebar-middle">')]
        first = re.search(r'class="nav-item[^"]*"', nav).group(0)
        self.assertIn("nav-play", first)
        js = _r("static/app.js")
        self.assertIn("function markDailyDrive", js)
        self.assertIn('"dd.played." + day', js)                   # same key the /play page saves
        self.assertIn("America/New_York", js)                    # the Drive's day rolls over at midnight ET
        css = _r("static/style.css")
        self.assertIn(".nav-item.nav-play.fresh", css)
        self.assertIn("prefers-reduced-motion: reduce) { .nav-item.nav-play.fresh { animation: none; }", css)

    def test_play_page_saves_the_key_the_sidebar_reads(self):
        self.assertIn('lsSet("dd.played." + puzzle.date', _r("static/play.js"))


class LandingTests(unittest.TestCase):
    def test_launch_page_is_lineup_lab_with_one_daily_drive_door(self):
        """Owner 2026-11-17 (round 4): Lineup Lab first; the Daily Drive is one card (cover + Play), no question shown,
        no Daily Drive section; the rest of the page is Lineup Lab. The Daily Drive is the nav's second tab."""
        js = _r("static/landing.js")
        app = js[js.index("function App()"):]
        self.assertIn("<${BrandHero}/><${Hero}/>", app)
        for gone in ("DriveHero", "HowItPlays", "useDrive", "'/api/play/daily'"):
            self.assertNotIn(gone, js)                                              # no live question on the front door
        self.assertEqual(js.count("<h1 "), 1)
        self.assertIn('className="lab-h1"', js)
        nav = js[js.index("function Nav("):js.index("/* ---------- HERO")]
        links = re.findall(r"\['([^']+)','([#/][^']*)'\]", nav[:nav.index("];")])
        self.assertEqual(links[1], ("The Daily Drive", "/play"))                    # the second tab opens the game
        brand = js[js.index("function BrandHero"):js.index("function Hero(")]
        self.assertIn("The Daily Drive</h2>", brand)
        self.assertIn("Fantasy tools</h2>", brand)
        self.assertIn('href="/play">${Ico(\'Play\',{size:16})}Play today\'s drive', brand)
        html = _r("static/landing.html")
        self.assertIn("<title>Lineup Lab", html)
        self.assertNotIn(".dd-board", html)

    def test_front_door_has_no_emojis_a_real_logo_and_a_game_cover(self):
        """Owner 2026-11-17 (round 3): no emojis on the front door, the real app icon as the logo, a cover image of
        the actual game on the Daily Drive door, and the Krillion comparison (as a comparison, not our name)."""
        js = _r("static/landing.js")
        for e in ("\u2705", "\u26a1", "\u26d3", "\u274c", "\U0001F3C8", "\U0001F4A3", "\U0001F680"):
            self.assertNotIn(e, js)
        self.assertIn("'/icons/icon-512.png':'/icons/icon-192.png'", js)
        self.assertIn('src="/img/daily-drive-cover.webp"', js)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "static", "img", "daily-drive-cover.webp")))
        self.assertIn("Like Krillion, but for football", js)
        self.assertNotIn("krillion.io", js.lower())


if __name__ == "__main__":
    unittest.main()
