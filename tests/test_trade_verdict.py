"""engine.tools._side_verdict — trade verdict tier classification.

The bad_value tier was unreachable: a trade losing >1.5 value with a neutral
fit (|fit| <= 0.15) was labelled 'bad' instead of 'bad_value'. The fix adds a
real_fit guard to the bad branch, mirroring the good_value_bad_fit
logic above it, so trades with |fit| <= 0.15 fall through to bad_value
("Loses on value; roster fit is close to a wash either way"). static/app.js
renders a 'Bad Value' label for bad_value verdicts, so the UI now correctly
shows the intended tier.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from engine.tools import _side_verdict


class TradeVerdict(unittest.TestCase):
    def test_verdict_tiers(self):
        """Verify _side_verdict returns correct tier labels for (value_delta, fit) pairs."""
        cases = [
            ((2, 0.2), "great"),
            ((2, -0.2), "good_value_bad_fit"),
            ((2, 0), "good_value"),
            ((-2, 0.2), "worth_it"),
            ((-2, -0.2), "bad"),
            ((-2, 0), "bad_value"),
            ((0, 0.2), "smart"),
            ((0, -0.2), "questionable"),
            ((0, 0), "fair"),
            ((1.5, 0.15), "fair"),
        ]
        for (value_delta, fit), expected_verdict in cases:
            with self.subTest(value_delta=value_delta, fit=fit):
                actual_verdict, _ = _side_verdict(value_delta, fit)
                self.assertEqual(actual_verdict, expected_verdict)

    def test_losing_value_with_neutral_fit_is_bad_value_not_bad(self):
        """Regression: losing >1.5 value with neutral fit is 'bad_value', not 'bad'."""
        verdict, _ = _side_verdict(-2, 0)
        self.assertEqual(verdict, "bad_value")


if __name__ == "__main__":
    unittest.main()
