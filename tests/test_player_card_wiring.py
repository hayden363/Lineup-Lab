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

    def test_lineup_panel_reports_best_lineup_gain(self):
        js = open("static/app.js").read()
        self.assertIn("L.bestNote", js)
        self.assertIn("lu-best-note", open("static/style.css").read())


if __name__ == "__main__":
    unittest.main()
