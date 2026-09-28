"""Activation recording in /api/trade-finder.

The server records trade_finder_result_viewed only for a signed-in user's own
league and only when suggestions come back non-empty. The part that could hurt
real users is the failure path: the activation_events table doesn't exist until
its migration is applied, so a failed insert must never turn a working Trade
Finder response into an error. Every external dependency is mocked here — no
network, no database, no nflverse.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import db

USER = {"id": 41, "username": "tester"}
SLEEPER_TEAM = {"platform": "sleeper", "league_id": "1392639173193633792", "roster_id": 3}


class TradeFinderActivation(unittest.TestCase):
    def setUp(self):
        server.app.dependency_overrides[server.require_user] = lambda: USER
        server.app.dependency_overrides[server.scoring_from_query] = lambda: None
        self.client = TestClient(server.app)
        patches = [
            mock.patch.object(server.db, "get_active_team", return_value=dict(SLEEPER_TEAM)),
            mock.patch.object(server, "_effective_scoring", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(server.app.dependency_overrides.clear)

    def _call(self, suggestions, record=None):
        result = {"season": 2025, "my_roster_id": 3, "suggestions": suggestions}
        record = record or mock.Mock()
        with mock.patch.object(server.tools, "trade_finder", return_value=result), \
             mock.patch.object(server.db, "record_activation_event", record):
            r = self.client.get("/api/trade-finder")
        return r, record

    def test_records_when_suggestions_come_back(self):
        r, record = self._call([{"give": ["a"], "get": ["b"]}])
        self.assertEqual(r.status_code, 200)
        record.assert_called_once_with(41, "trade_finder_result_viewed", SLEEPER_TEAM["league_id"])

    def test_does_not_record_an_empty_result(self):
        r, record = self._call([])
        self.assertEqual(r.status_code, 200)
        record.assert_not_called()

    def test_a_failed_insert_never_breaks_the_response(self):
        # What actually happens until the migration is applied.
        boom = mock.Mock(side_effect=RuntimeError('relation "activation_events" does not exist'))
        r, _ = self._call([{"give": ["a"], "get": ["b"]}], record=boom)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["suggestions"]), 1)
        boom.assert_called_once()

    def test_espn_league_is_rejected_before_anything_is_recorded(self):
        with mock.patch.object(server.db, "get_active_team",
                               return_value={"platform": "espn", "league_id": "9", "roster_id": 1}), \
             mock.patch.object(server.db, "record_activation_event") as record:
            r = self.client.get("/api/trade-finder")
        self.assertEqual(r.status_code, 400)
        record.assert_not_called()


class RecordActivationEvent(unittest.TestCase):
    def test_rejects_an_unknown_event_name_before_touching_the_db(self):
        with mock.patch.object(db, "_conn") as conn:
            with self.assertRaises(ValueError):
                db.record_activation_event(1, "made_up_event", "L1")
        conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
