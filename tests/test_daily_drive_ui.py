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
    def test_launch_page_leads_with_the_daily_drive(self):
        js = _r("static/landing.js")
        app = js[js.index("function App()"):]
        # owner 2026-11-17 (round 2): Lineup Lab first, the Daily Drive second (the way in), then the fantasy tools
        self.assertLess(app.index("<${BrandHero}/>"), app.index("<${DriveHero}/>"))
        self.assertLess(app.index("<${DriveHero}/>"), app.index("<${Hero}/>"))
        self.assertEqual(js.count("<h1 "), 1)                                       # one h1: the Lineup Lab headline
        self.assertIn('className="lab-h1"', js)
        nav = js[js.index("function Nav("):js.index("/* ---------- HERO")]
        links = re.findall(r"\['([^']+)','#", nav[:nav.index("];")])
        self.assertEqual(links[1], "The Daily Drive")                               # the second tab
        brand = js[js.index("function BrandHero"):js.index("function DriveHero")]
        self.assertIn("The Daily Drive</h2>", brand)
        self.assertIn("Fantasy tools</h2>", brand)
        self.assertIn("fetch(u,{credentials:'same-origin'})", js)                  # live card reads the real endpoints
        self.assertIn("'/api/play/daily'", js)
        self.assertIn('href="/play">${Ico(\'Play\',{size:18})}Play today\'s drive', js)
        html = _r("static/landing.html")
        self.assertIn("<title>Lineup Lab", html)


if __name__ == "__main__":
    unittest.main()
