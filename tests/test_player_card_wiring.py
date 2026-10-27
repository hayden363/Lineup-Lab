import re
import unittest


class PlayerCardWiringTests(unittest.TestCase):
    def test_hero_and_grades_are_wired(self):
        js = open("static/app.js").read()
        self.assertIn("beatProjChipHtml(p)", js)
        self.assertIn("scoutGrade(n.percentile)", js)
        self.assertTrue(re.search(r"function scoutGrade", js))

    def test_styles_exist(self):
        css = open("static/style.css").read()
        for sel in (".pcd-chip.beat.up", ".scs-grade"):
            self.assertIn(sel, css)

    def test_weekly_lineup_panel_is_gone(self):
        # the My Team "Set your lineup" panel and its /api/lineup endpoints were removed on purpose
        js, css = open("static/app.js").read(), open("static/style.css").read()
        for needle in ("loadLineupPanel", "renderLineupPanel", "lineup-panel", "/api/lineup/"):
            self.assertNotIn(needle, js)
        self.assertNotIn(".lu-row", css)
        self.assertIn("lk-open", css)   # the league-trades NEW badge still needs it

    def test_league_scoring_is_platform_aware(self):
        js = open("static/app.js").read()
        self.assertIn("function fetchLeagueScoring", js)
        self.assertEqual(js.count("api(`/api/sleeper/${"), 1)  # only the Sleeper-only draft tab

    def test_sidebar_rows_show_platform(self):
        self.assertIn("st-plat", open("static/app.js").read())


if __name__ == "__main__":
    unittest.main()
