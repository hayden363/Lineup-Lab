"""Regression tests for fixes from the Oct 19 full-code review."""
import unittest
from unittest import mock

from engine import defense_scoring, lineup, oauth, weekly_proj
from engine.scoring import ScoringSettings


class TeamCodeTest(unittest.TestCase):
    def test_sleeper_and_espn_codes_map_to_nflverse(self):
        self.assertEqual(defense_scoring.to_nflverse_team("LAR"), "LA")
        self.assertEqual(defense_scoring.to_nflverse_team("WSH"), "WAS")
        self.assertEqual(defense_scoring.to_nflverse_team("KC"), "KC")
        self.assertIsNone(defense_scoring.to_nflverse_team(None))


class EspnSlotTest(unittest.TestCase):
    def test_espn_slot_labels_are_eligible(self):
        self.assertTrue(lineup.eligible("RB/WR/TE", "TE"))
        self.assertTrue(lineup.eligible("D/ST", "DEF"))
        self.assertFalse(lineup.eligible("RB/WR", "TE"))
        self.assertTrue(lineup.eligible("OP", "QB"))


class ProjectionExtrasTest(unittest.TestCase):
    def test_te_premium_and_first_downs_in_projection(self):
        s = ScoringSettings.from_dict({"te_reception": 0.5, "rec_fd": 0.5})
        line = {"rec": 6, "rec_yd": 60, "rec_fd": 4}
        self.assertEqual(weekly_proj.points(line, s, "WR"), 14.0)
        self.assertEqual(weekly_proj.points(line, s, "TE"), 17.0)


class GoogleEmailVerifiedTest(unittest.TestCase):
    def _exchange(self, claims):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"id_token": "x"}
        with mock.patch.object(oauth.requests, "post", return_value=resp), \
             mock.patch.object(oauth, "_verify_id_token", return_value=claims):
            return oauth.google_exchange_code("code", "https://example.test/cb")

    def test_unverified_email_rejected(self):
        with self.assertRaises(oauth.OAuthError):
            self._exchange({"sub": "1", "email": "a@b.c", "email_verified": False})

    def test_verified_email_accepted_bool_or_string(self):
        self.assertEqual(self._exchange({"sub": "1", "email": "a@b.c", "email_verified": True})["provider_id"], "1")
        self.assertEqual(self._exchange({"sub": "2", "email": "a@b.c", "email_verified": "true"})["provider_id"], "2")


class StartSitSizeTest(unittest.TestCase):
    def test_request_size_bounds(self):
        import server
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            server._check_startsit_size(server.StartSitRequest(player_ids=["a"]))
        with self.assertRaises(HTTPException):
            server._check_startsit_size(server.StartSitRequest(player_ids=[str(i) for i in range(7)]))
        server._check_startsit_size(server.StartSitRequest(player_ids=["a", "b"]))


if __name__ == "__main__":
    unittest.main()
