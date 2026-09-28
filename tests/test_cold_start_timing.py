"""engine.board._timed — the cold-start instrumentation around load_bundle.

The logs it writes are the point, but the part that can actually break the app
is the wrapping: it must hand back the fetched table unchanged, and it must NOT
swallow a failure — load_bundle's contract is that the required core tables
(weekly/pbp/ngs/schedule) raise on failure, and a timing wrapper that caught
exceptions would quietly turn a failed fetch into a half-built board.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import io
import re
import unittest
from contextlib import redirect_stdout

import pandas as pd

from engine.board import _timed


class Timed(unittest.TestCase):
    def test_returns_the_fetched_table_unchanged(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        with redirect_stdout(io.StringIO()):
            out = _timed("weekly", lambda: df)
        self.assertIs(out, df)

    def test_logs_one_greppable_line_with_label_seconds_and_rows(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _timed("pbp", lambda: pd.DataFrame({"x": range(42)}))
        line = buf.getvalue().strip()
        self.assertRegex(line, r"^\[cold-start\] table=pbp seconds=\d+\.\d{2} rows=42$")

    def test_does_not_swallow_a_failed_fetch(self):
        def fetch():
            raise RuntimeError("nflverse 404")
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                _timed("weekly", fetch)

    def test_handles_a_result_without_len(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = _timed("odd", lambda: 7)
        self.assertEqual(out, 7)
        self.assertTrue(re.search(r"rows=\?$", buf.getvalue().strip()))


if __name__ == "__main__":
    unittest.main()
