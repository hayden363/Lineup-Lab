"""static/team-themes.js: the 32-team palette table (and, in later tasks, the derivation engine and picker)."""
import json
import os
import re
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


if __name__ == "__main__":
    unittest.main()
