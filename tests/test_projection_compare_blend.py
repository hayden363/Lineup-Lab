"""/api/player/{id}/projection-compare carries a `blend` next to our number
and the consensus: weighted by hours to kickoff, and never invented when the
expert number or the kickoff is missing.

    .venv/bin/python -m unittest tests.test_projection_compare_blend -v
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

import server


def consensus(proj):
    return {"configured": True, "source": "FantasyPros Consensus", "detail": "x", "proj": proj, "week": 7}


class ProjectionCompareBlend(unittest.TestCase):
    def call(self, proj, kickoff):
        detail = {"player_display_name": "Test Player", "position": "WR", "recent_team": "KC", "next_week": 7}
        with mock.patch.object(server, "player_detail", return_value=detail), \
                mock.patch.object(server, "load_bundle", return_value={"season": 2026, "schedule": None}), \
                mock.patch.object(server.tools, "real_proj_for_player", return_value=20.0), \
                mock.patch.object(server.locks, "kickoff", return_value=kickoff), \
                mock.patch.object(server.external_projections_layer, "projection_for_player",
                                  return_value=consensus(proj)):
            return TestClient(server.app).get("/api/player/abc/projection-compare").json()

    def test_blend_uses_hours_to_kickoff(self):
        far = datetime.now(timezone.utc) + timedelta(hours=120)
        near = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertEqual(self.call(12.0, far)["blend"]["blended"], 17.6)
        self.assertEqual(self.call(12.0, near)["blend"]["blended"], 14.0)

    def test_no_expert_number_means_no_blend(self):
        out = self.call(None, datetime.now(timezone.utc) + timedelta(hours=50))
        self.assertIsNone(out["blend"]["blended"])
        self.assertEqual(out["our_proj"], 20.0)

    def test_no_kickoff_means_no_blend(self):
        out = self.call(12.0, None)
        self.assertIsNone(out["blend"]["blended"])
        self.assertEqual(out["consensus"]["proj"], 12.0)


if __name__ == "__main__":
    unittest.main()
