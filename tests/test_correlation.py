import unittest

import numpy as np
import pandas as pd

from engine import correlation as cr
from engine import decision


def _rank_corr(a, b):
    r = lambda x: np.argsort(np.argsort(x))  # noqa: E731
    return float(np.corrcoef(r(a), r(b))[0, 1])


def _draws(n=4, proj=(20, 14, 11, 19), cv=0.6, p_play=None):
    return [decision.outcomes(p, cv, i, (p_play or {}).get(i, 1.0))["_samples"] for i, p in enumerate(proj[:n])]


TAB = {"same": {("QB", "WR"): 0.4, ("WR", "WR"): 0.13, ("RB", "RB"): -0.07}, "opp": {("QB", "QB"): 0.13}, "n": 100}


class CorrelateTests(unittest.TestCase):
    def test_each_players_distribution_is_unchanged(self):
        s = _draws()
        c = cr.correlate(s, cr.matrix([{"team": "A", "position": "QB"}, {"team": "A", "position": "WR"},
                                       {"team": "A", "position": "WR"}, {"team": "B", "position": "RB"}], TAB), 1)
        for a, b in zip(s, c):
            self.assertTrue(np.array_equal(np.sort(a), np.sort(b)))

    def test_target_correlation_is_reached(self):
        s = _draws(2)
        c = cr.correlate(s, np.array([[1, 0.4], [0.4, 1]]), 1)
        self.assertAlmostEqual(_rank_corr(c[0], c[1]), 0.4, delta=0.04)

    def test_unrelated_players_stay_unrelated(self):
        s = _draws(2)
        c = cr.correlate(s, np.eye(2), 1)
        self.assertTrue(np.array_equal(c[0], s[0]))

    def test_missed_games_do_not_correlate_with_teammates(self):
        s = _draws(2, p_play={0: 0.5})
        c = cr.correlate(s, np.array([[1, 0.4], [0.4, 1]]), 2)
        zero = c[0] == 0
        self.assertAlmostEqual(float(zero.mean()), 0.5, delta=0.03)
        # his teammate scores the same on the games he misses as on the ones he plays
        self.assertAlmostEqual(float(c[1][zero].mean()), float(c[1][~zero].mean()), delta=0.7)
        self.assertGreater(_rank_corr(c[0][~zero], c[1][~zero]), 0.3)

    def test_stack_widens_lineup_range(self):
        s = _draws(3)
        c = cr.correlate(s, cr.matrix([{"team": "A", "position": "QB"}, {"team": "A", "position": "WR"},
                                       {"team": "A", "position": "WR"}], TAB), 1)
        r = cr.lineup_range(c)
        self.assertGreater(r["widening"], 0)
        self.assertAlmostEqual(r["mean"], sum(float(x.mean()) for x in s), places=0)

    def test_negative_pair_narrows_it(self):
        s = _draws(2)
        c = cr.correlate(s, np.array([[1, -0.5], [-0.5, 1]]), 1)
        self.assertLess(cr.lineup_range(c)["widening"], 0)

    def test_constants_shift_the_range(self):
        s = _draws(2)
        a, b = cr.lineup_range(s), cr.lineup_range(s, constants=10.0)
        self.assertAlmostEqual(b["p50"] - a["p50"], 10.0, places=1)

    def test_empty_lineup(self):
        self.assertIsNone(cr.lineup_range([]))


class MatrixTests(unittest.TestCase):
    def test_same_team_and_opposing_pairs(self):
        c = cr.matrix([{"team": "A", "position": "QB", "opponent": "B"}, {"team": "A", "position": "WR"},
                       {"team": "B", "position": "QB", "opponent": "A"}, {"team": "C", "position": "WR"}], TAB)
        self.assertAlmostEqual(c[0, 1], 0.4, places=2)
        self.assertAlmostEqual(c[0, 2], 0.13, places=2)
        self.assertEqual(c[0, 3], 0.0)
        self.assertTrue(np.allclose(c, c.T))

    def test_inconsistent_pairs_are_repaired_to_a_valid_matrix(self):
        bad = np.array([[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]])
        fixed = cr.nearest_correlation(bad)
        self.assertGreater(np.linalg.eigvalsh(fixed).min(), 0)
        self.assertTrue(np.allclose(np.diag(fixed), 1.0))


class ApplyTests(unittest.TestCase):
    def _rows(self):
        mk = lambda pid, team, pos, i: {"player_id": pid, "recent_team": team, "position": pos,  # noqa: E731
                                        "outcomes": decision.outcomes(15 + i, 0.6, i, 1.0)}
        return [mk("a", "AAA", "QB", 0), mk("b", "AAA", "WR", 1), mk("c", "ZZZ", "RB", 2)]

    def test_apply_links_teammates_only(self):
        rows = self._rows()
        orig = [r["outcomes"]["_samples"].copy() for r in rows]
        with unittest_mock_table():
            self.assertTrue(cr.apply(rows, pd.DataFrame()))
        self.assertGreater(_rank_corr(rows[0]["outcomes"]["_samples"], rows[1]["outcomes"]["_samples"]), 0.3)
        # the other team's player keeps his distribution and stays unrelated to the stack
        self.assertTrue(np.array_equal(np.sort(rows[2]["outcomes"]["_samples"]), np.sort(orig[2])))
        self.assertLess(abs(_rank_corr(rows[0]["outcomes"]["_samples"], rows[2]["outcomes"]["_samples"])), 0.06)
        self.assertAlmostEqual(rows[0]["outcomes"]["p50"], decision.outcomes(15, 0.6, 0, 1.0)["p50"])

    def test_apply_does_nothing_for_unrelated_players(self):
        rows = self._rows()[1:]
        with unittest_mock_table():
            self.assertFalse(cr.apply(rows, pd.DataFrame()))

    def test_ruled_out_players_are_skipped(self):
        rows = self._rows()
        rows[1]["outcomes"] = decision.ruled_out()
        with unittest_mock_table():
            self.assertFalse(cr.apply(rows, pd.DataFrame()))


def unittest_mock_table():
    from unittest import mock
    return mock.patch.object(cr, "table", return_value=TAB)


if __name__ == "__main__":
    unittest.main()
