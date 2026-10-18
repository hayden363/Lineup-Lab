"""/api/meta must not load the data bundle.

The frontend awaits /api/meta before it draws even the sign-in screen. When it
called load_bundle() (the ~25s nflverse fetch), a cold start left the whole UI
blank until that finished. It only needs the season and the team list, so it
must stay independent of the bundle.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server


class MetaColdStart(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_answers_without_loading_the_bundle(self):
        boom = mock.Mock(side_effect=RuntimeError("bundle must not load for /api/meta"))
        with mock.patch.object(server, "load_bundle", boom), \
             mock.patch.object(server.data_layer, "resolve_season", return_value=2026):
            r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        boom.assert_not_called()
        body = r.json()
        self.assertEqual(body["season"], 2026)
        self.assertEqual(body["teams"], server.NFL_TEAMS)
        self.assertEqual(len(body["teams"]), 32)
        self.assertEqual(len(set(body["teams"])), 32)

    def test_team_codes_are_nflverses_not_sleepers(self):
        # nflverse writes the Rams as LA; a Sleeper-style LAR here would make the
        # opponent dropdown pick a code the matchup data has no rows for.
        self.assertIn("LA", server.NFL_TEAMS)
        self.assertNotIn("LAR", server.NFL_TEAMS)


if __name__ == "__main__":
    unittest.main()
