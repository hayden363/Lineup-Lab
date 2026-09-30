"""engine.board._injury_multiplier_col / _injury_sample_col — the glue that feeds the injury adjustment into PROJ.

test_injury_impact.py covers the lookup itself. These two functions apply it row by row to a board DataFrame and
must degrade to neutral values (1.0 / None) when the injury columns are missing or a row has no usable designation.
The bucket used is read from engine/injury_impact_factors.json at test time, so a legitimate regeneration does
not break the suite.

Found while writing these: unadjusted rows of _injury_sample_col come back as NaN, not the None its docstring
promises (pandas turns None into NaN, here with or without the injury columns). Harmless today:
server._clean() maps NaN to JSON null and static/app.js only reads injury_sample_n when injury_factor != 1. So
the tests assert "missing" (None or NaN), not a specific sentinel.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest

import pandas as pd

from engine import injury_impact as ii
from engine.board import _injury_multiplier_col, _injury_sample_col


def _bucket(position="RB", status="Questionable"):
    for key, entry in ii._FACTORS.items():
        pos, part, st = key.split("|")
        if pos == position and st == status:
            return part, entry
    raise unittest.SkipTest(f"no {position}/{status} bucket in injury_impact_factors.json")


def _board():
    part, _ = _bucket()
    return pd.DataFrame(
        {
            "name": ["real bucket", "out", "no body part", "unknown body part", "healthy"],
            "injury_status": ["Questionable", "Out", "Questionable", "Questionable", None],
            "injury_body_part": [part, part, None, "Toenail", None],
        },
        index=[10, 11, 12, 13, 14],
    )


class MissingColumns(unittest.TestCase):
    def test_neutral_and_index_preserved_without_injury_columns(self):
        board = pd.DataFrame({"name": ["a", "b", "c"]}, index=[5, 7, 9])
        mult = _injury_multiplier_col(board, "RB")
        samp = _injury_sample_col(board, "RB")
        self.assertEqual(list(mult.index), [5, 7, 9])
        self.assertEqual(list(mult), [1.0, 1.0, 1.0])
        self.assertEqual(list(samp.index), [5, 7, 9])
        self.assertTrue(samp.isna().all())

    def test_either_column_missing_is_enough_to_go_neutral(self):
        for keep in ("injury_status", "injury_body_part"):
            board = pd.DataFrame({"name": ["a", "b"], keep: ["Questionable", "x"]}, index=[1, 2])
            self.assertEqual(list(_injury_multiplier_col(board, "RB")), [1.0, 1.0], keep)
            self.assertTrue(_injury_sample_col(board, "RB").isna().all(), keep)


class RowByRow(unittest.TestCase):
    def test_real_bucket_applies_its_multiplier_and_reports_its_sample_size(self):
        _, entry = _bucket()
        board = _board()
        mult = _injury_multiplier_col(board, "RB")
        samp = _injury_sample_col(board, "RB")
        self.assertEqual(mult[10], round(1.0 + entry["median_pct_change"], 4))
        self.assertLess(mult[10], 1.0)                      # an injury never raises a projection
        self.assertEqual(samp[10], entry["n"])

    def test_out_status_no_body_part_unknown_part_and_healthy_are_all_neutral(self):
        board = _board()
        mult = _injury_multiplier_col(board, "RB")
        samp = _injury_sample_col(board, "RB")
        for idx in (11, 12, 13, 14):
            self.assertEqual(mult[idx], 1.0, idx)
            self.assertTrue(pd.isna(samp[idx]), idx)

    def test_nan_body_part_is_neutral(self):
        part, _ = _bucket()
        board = pd.DataFrame({"injury_status": ["Questionable"], "injury_body_part": [float("nan")]}, index=[3])
        self.assertEqual(_injury_multiplier_col(board, "RB")[3], 1.0)
        self.assertTrue(pd.isna(_injury_sample_col(board, "RB")[3]))

    def test_position_without_a_bucket_is_neutral_even_with_a_real_body_part(self):
        part, _ = _bucket()
        board = pd.DataFrame({"injury_status": ["Questionable"], "injury_body_part": [part]}, index=[1])
        self.assertEqual(_injury_multiplier_col(board, "QB")[1], 1.0)     # QB has no bucket that clears the sample bar
        self.assertTrue(pd.isna(_injury_sample_col(board, "QB")[1]))

    def test_multiplier_and_sample_columns_agree_on_which_rows_were_adjusted(self):
        board = _board()
        adjusted = [i for i, m in _injury_multiplier_col(board, "RB").items() if m != 1.0]
        with_n = [i for i, n in _injury_sample_col(board, "RB").items() if not pd.isna(n)]
        self.assertEqual(adjusted, with_n)
        self.assertEqual(adjusted, [10])


if __name__ == "__main__":
    unittest.main()
