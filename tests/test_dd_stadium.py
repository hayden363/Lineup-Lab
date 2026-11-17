"""The favorite-team stadium on the Daily Drive field (owner, 2026-11-16): real starters' numbers, this week's real
opponent on defense, only for a signed-in player."""
import datetime
import json
import os
import re
import unittest
from unittest import mock

from engine import dd_stadium as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _themes():
    src = open(os.path.join(ROOT, "static", "team-themes.js"), encoding="utf-8").read()
    return json.loads(re.search(r"window\.TEAM_THEMES = (\{.*?\n\});", src, re.S).group(1))


class SnapshotTests(unittest.TestCase):
    def test_every_team_has_a_full_lineup_of_real_numbers(self):
        teams = st.load()["teams"]
        self.assertEqual(sorted(teams), st.TEAMS)
        need = {"qb": 1, "rb": 1, "wr": 2, "te": 1, "ol": 5, "dl": 4, "lb": 2, "cb": 2, "s": 2}
        for code, t in teams.items():
            for k, n in need.items():
                self.assertEqual(len(t[k]), n, f"{code} {k}")
            offense = t["qb"] + t["rb"] + t["wr"] + t["te"] + t["ol"]
            defense = t["dl"] + t["lb"] + t["cb"] + t["s"]
            for nums in (offense, defense):
                self.assertEqual(len(nums), len(set(nums)), f"{code} repeats a number")
                self.assertTrue(all(0 <= n <= 99 for n in nums))
            self.assertGreaterEqual(len(t["bench"]), 10)
            self.assertIn(t["roof"], ("dome", "open", "outdoors"))
            self.assertIn(t["surface"], ("grass", "turf"))
            self.assertTrue(t["stadium"])
            self.assertGreaterEqual(len(t["games"]), 16)

    def test_uniforms_cover_the_settings_team_codes(self):
        self.assertEqual(sorted(_themes()), st.TEAMS)
        for code, row in st.UNIFORMS.items():
            self.assertEqual(len(row), 6, code)
            for c in row:
                self.assertRegex(c, r"^(#[0-9A-F]{6})?$", code)


class OpponentTests(unittest.TestCase):
    TEAMS = {"SEA": {"games": [[11, "2026-11-16", "LV"], [12, "2026-11-26", "SF"]], "rival": "ARI"},
             "LV": {"games": [], "rival": "KC"}, "SF": {"games": [], "rival": "SEA"}, "ARI": {"games": [], "rival": "SEA"}}

    def test_this_weeks_game_tuesday_to_monday(self):
        self.assertEqual(st.opponent("SEA", datetime.date(2026, 11, 10), self.TEAMS), "LV")      # Tuesday, game Monday
        self.assertEqual(st.opponent("SEA", datetime.date(2026, 11, 16), self.TEAMS), "LV")      # game day
        self.assertEqual(st.opponent("SEA", datetime.date(2026, 11, 24), self.TEAMS), "SF")      # Thanksgiving week

    def test_bye_week_falls_back_to_a_division_rival(self):
        self.assertEqual(st.opponent("SEA", datetime.date(2026, 11, 17), {**self.TEAMS, "SEA": {
            "games": [[11, "2026-11-16", "LV"], [13, "2026-11-29", "SF"]], "rival": "ARI"}}), "ARI")

    def test_stadium_unknown_team_or_missing_snapshot_is_none(self):
        self.assertIsNone(st.stadium("XYZ", datetime.date(2026, 11, 16)))
        self.assertIsNone(st.stadium("", datetime.date(2026, 11, 16)))
        self.assertIsNone(st.stadium("SEA", datetime.date(2026, 11, 16), path="/nonexistent/x.json"))

    def test_stadium_shape(self):
        sk = st.stadium("sea", datetime.date(2026, 11, 16))
        self.assertEqual(sk["home"]["code"], "SEA")
        self.assertEqual(set(sk["home"]["numbers"]), {"qb", "rb", "wr", "te", "ol"})  # the QB wears his real number
        self.assertEqual(set(sk["away"]["numbers"]), {"dl", "lb", "cb", "s"})
        self.assertNotEqual(sk["away"]["code"], "SEA")
        self.assertNotIn("name", json.dumps(sk["home"]["numbers"]))                   # numbers only, no names


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        cls.s = server
        cls.client = TestClient(server.app)

    def test_signed_out_gets_no_stadium(self):
        with mock.patch.object(self.s, "_play_user", return_value=None):
            for url in ("/api/play/stadium", "/api/play/stadium?team=SEA"):
                self.assertEqual(self.client.get(url).json(), {"signed_in": False, "stadium": None})

    def test_signed_in_uses_this_browsers_team_then_the_account_team(self):
        with mock.patch.object(self.s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(self.s.db, "get_settings", return_value={"theme": "GB"}) as gs:
            r = self.client.get("/api/play/stadium?team=SEA").json()
            self.assertTrue(r["signed_in"])
            self.assertEqual(r["stadium"]["home"]["code"], "SEA")
            gs.assert_not_called()
            r = self.client.get("/api/play/stadium").json()
            self.assertEqual(r["stadium"]["home"]["code"], "GB")
        with mock.patch.object(self.s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(self.s.db, "get_settings", return_value={"theme": None}):
            self.assertEqual(self.client.get("/api/play/stadium").json(), {"signed_in": True, "stadium": None})
        with mock.patch.object(self.s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(self.s.db, "get_settings", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get("/api/play/stadium").json(), {"signed_in": True, "stadium": None})

    def test_demo_preview_needs_no_account(self):
        with mock.patch.object(self.s, "_play_user", return_value=None):
            r = self.client.get("/api/play/stadium?preview=1&team=DET").json()
        self.assertEqual(r["stadium"]["home"]["code"], "DET")
        self.assertEqual(r["stadium"]["home"]["roof"], "dome")


class ClientTests(unittest.TestCase):
    def test_page_skins_the_field_only_for_a_signed_in_player(self):
        js = open(os.path.join(ROOT, "static", "play.js"), encoding="utf-8").read()
        self.assertIn("function loadStadium", js)
        self.assertIn("r.signed_in || previewCode != null", js)
        self.assertIn("preview=1", js)
        field = open(os.path.join(ROOT, "static", "play-field.js"), encoding="utf-8").read()
        self.assertIn("setTeam: function", field)
        self.assertIn("TU && TU.qbNum != null ? TU.qbNum : S.number", field)            # team field: real QB number; default: question number


if __name__ == "__main__":
    unittest.main()
