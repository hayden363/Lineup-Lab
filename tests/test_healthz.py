"""/healthz must stay pure liveness.

Render uses it as healthCheckPath (render.yaml) on every fresh instance during a
deploy. If it ever starts depending on nflverse, the database or the data
bundle, an outage in any of those would read as this app being down and could
fail a deploy — which is the exact problem /api/health has. These tests make
that regression loud.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server


class Healthz(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_returns_plain_ok(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")

    def test_survives_nflverse_being_down(self):
        # Simulate the upstream outage /api/health is vulnerable to: any attempt
        # to resolve the season or load data now explodes. /healthz must not care.
        boom = mock.Mock(side_effect=RuntimeError("nflverse unreachable"))
        with mock.patch.object(server.data_layer, "resolve_season", boom), \
             mock.patch.object(server, "load_bundle", boom):
            r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")
        boom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
