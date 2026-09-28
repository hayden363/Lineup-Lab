"""The security_headers middleware prints one [req] timing line per /api/ call.

Path only (never the query string — league ids must not reach logs), and
/healthz stays silent.

    .venv/bin/python -m unittest tests.test_request_timing -v
"""

import contextlib
import io
import unittest

from fastapi.testclient import TestClient

import server


class RequestTiming(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def _get(self, url):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = self.client.get(url)
        return r, buf.getvalue()

    def test_api_request_logs_req_line(self):
        r, out = self._get("/api/auth/me")
        self.assertEqual(r.status_code, 401)
        self.assertRegex(out, r"\[req\] method=GET path=/api/auth/me status=401 ms=\d+")

    def test_healthz_not_logged(self):
        _, out = self._get("/healthz")
        self.assertNotIn("[req]", out)

    def test_query_string_not_logged(self):
        _, out = self._get("/api/auth/me?league_id=123")
        self.assertNotIn("league_id", out)
        self.assertNotIn("?", out)


if __name__ == "__main__":
    unittest.main()
