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


if __name__ == "__main__":
    unittest.main()
