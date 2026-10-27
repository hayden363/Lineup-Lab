"""POST /api/settings {"theme": ...}: only the 32 team codes (or empty to clear) are ever stored. No database."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import news

USER = {"id": 7, "username": "t"}


class ThemeSettingTests(unittest.TestCase):
    def setUp(self):
        server.app.dependency_overrides[server.require_user] = lambda: USER
        self.addCleanup(server.app.dependency_overrides.clear)
        self.client = TestClient(server.app)
        p = mock.patch.object(server.db, "update_settings", side_effect=lambda uid, updates: {"theme": updates.get("theme")})
        self.update = p.start()
        self.addCleanup(p.stop)

    def post(self, theme):
        return self.client.post("/api/settings", json={"theme": theme})

    def test_valid_code_is_stored(self):
        r = self.post("DET")
        self.assertEqual(r.status_code, 200)
        self.update.assert_called_once_with(7, {"theme": "DET"})

    def test_all_32_team_codes_are_accepted(self):
        self.assertEqual(len(news.TEAM_CODES), 32)
        for code in sorted(news.TEAM_CODES):
            self.assertEqual(self.post(code).status_code, 200, code)

    def test_empty_and_null_clear_it(self):
        for blank in ("", "   ", None):
            self.update.reset_mock()
            self.assertEqual(self.post(blank).status_code, 200, repr(blank))
            self.update.assert_called_once_with(7, {"theme": None})

    def test_lowercase_is_normalised_to_upper(self):
        self.assertEqual(self.post(" det ").status_code, 200)
        self.update.assert_called_once_with(7, {"theme": "DET"})

    def test_unknown_code_is_rejected_and_nothing_is_stored(self):
        for bad in ("XYZ", "WSH", "NFL", "DE"):
            r = self.post(bad)
            self.assertEqual(r.status_code, 422, bad)
        self.update.assert_not_called()

    def test_markup_and_overlong_values_are_rejected(self):
        for bad in ("<img onerror=x>", "DET; background:red", "DET'", "A" * 5000, 123, ["DET"], {"a": 1}):
            self.assertEqual(self.post(bad).status_code, 422, repr(bad)[:40])
        self.update.assert_not_called()

    def test_other_settings_are_unaffected(self):
        r = self.client.post("/api/settings", json={"scoring_preset": "ppr"})
        self.assertEqual(r.status_code, 200)
        self.update.assert_called_once_with(7, {"scoring_preset": "ppr"})

    def test_get_settings_returns_the_theme(self):
        with mock.patch.object(server.db, "get_settings", return_value={"theme": "GB", "scoring_preset": None}):
            self.assertEqual(self.client.get("/api/settings").json()["theme"], "GB")


if __name__ == "__main__":
    unittest.main()
