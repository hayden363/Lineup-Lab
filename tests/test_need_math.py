"""engine.tools Trade Finder need math — _need_multiplier, _team_position_counts, _team_needs, _fit_score.

_position_needs is covered in test_position_needs.py and is not re-tested here. These functions turn a roster
into the 1.25 / 1.0 / 0.82 multipliers that decide whether a trade "fills a real need", so a wrong boundary
silently re-ranks every trade suggestion. Boundaries are exercised exactly (filled == need, filled == need * 1.75).

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest

from engine.tools import _fit_score, _need_multiplier, _position_needs, _team_needs, _team_position_counts

STANDARD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K", "BN", "BN"]


def pl(*positions):
    return [{"position": p} for p in positions]


class NeedMultiplier(unittest.TestCase):
    def test_thresholds_with_a_whole_number_need(self):
        needs = {"RB": 2.0}
        self.assertEqual(_need_multiplier("RB", 0, needs), 1.25)
        self.assertEqual(_need_multiplier("RB", 1, needs), 1.25)
        self.assertEqual(_need_multiplier("RB", 2, needs), 1.0)      # filled == need is NOT a hole
        self.assertEqual(_need_multiplier("RB", 3, needs), 1.0)      # 3 < 3.5
        self.assertEqual(_need_multiplier("RB", 3.5, needs), 0.82)   # filled == need * 1.75 is already deep
        self.assertEqual(_need_multiplier("RB", 4, needs), 0.82)

    def test_fractional_flex_need_from_a_standard_league(self):
        rb_need = _position_needs(STANDARD)["RB"]                    # 2 + 1/3
        self.assertAlmostEqual(rb_need, 2 + 1 / 3)
        needs = {"RB": rb_need}                                      # deep line is 4.083...
        self.assertEqual(_need_multiplier("RB", 2, needs), 1.25)     # 2 < 2.33: still short of the flex share
        self.assertEqual(_need_multiplier("RB", 3, needs), 1.0)
        self.assertEqual(_need_multiplier("RB", 4, needs), 1.0)      # 4 < 4.083
        self.assertEqual(_need_multiplier("RB", 5, needs), 0.82)

    def test_position_absent_from_needs_defaults_to_one_starter(self):
        self.assertEqual(_need_multiplier("K", 0, {}), 1.25)
        self.assertEqual(_need_multiplier("K", 1, {}), 1.0)
        self.assertEqual(_need_multiplier("K", 2, {}), 0.82)         # 2 >= 1 * 1.75


class TeamPositionCounts(unittest.TestCase):
    def test_counts_only_qb_rb_wr_te(self):
        c = _team_position_counts(pl("QB", "RB", "RB", "WR", "TE", "DEF", "K", "TQB"))
        self.assertEqual(c, {"QB": 1, "RB": 2, "WR": 1, "TE": 1})

    def test_players_without_a_position_are_ignored(self):
        self.assertEqual(_team_position_counts([{"name": "x"}, {"position": None}]), {"QB": 0, "RB": 0, "WR": 0, "TE": 0})


class TeamNeeds(unittest.TestCase):
    def test_hole_adequate_and_deep_in_one_roster(self):
        roster = pl("QB", "RB", "RB", "RB", "RB", "RB", "WR")        # RB 5 (deep), WR 1 (hole), QB 1 (ok), TE 0 (hole)
        n = _team_needs(roster, STANDARD)
        self.assertEqual(n, {"QB": 1.0, "RB": 0.82, "WR": 1.25, "TE": 1.25})

    def test_no_roster_positions_still_returns_every_position(self):
        self.assertEqual(set(_team_needs([], None)), {"QB", "RB", "WR", "TE"})


class FitScore(unittest.TestCase):
    NEEDS = {"QB": 1.0, "RB": 0.82, "WR": 1.25, "TE": 1.25}

    def test_like_for_like_swap_is_zero(self):
        self.assertEqual(_fit_score(pl("RB"), pl("RB"), self.NEEDS), 0.0)

    def test_receiving_a_thin_position_for_a_deep_one_is_positive(self):
        self.assertEqual(_fit_score(pl("RB"), pl("WR"), self.NEEDS), 0.43)

    def test_the_reverse_is_negative(self):
        self.assertEqual(_fit_score(pl("WR"), pl("RB"), self.NEEDS), -0.43)

    def test_def_and_k_do_not_move_the_score(self):
        self.assertEqual(_fit_score(pl("DEF"), pl("K"), self.NEEDS), 0.0)
        self.assertEqual(_fit_score(pl("RB", "DEF"), pl("WR", "K"), self.NEEDS), 0.43)

    def test_an_unbalanced_def_or_k_add_or_drop_does_not_move_the_score(self):
        # a balanced DEF-for-K swap cancels even if they were counted; an unbalanced one only stays 0.0 if they are filtered out
        self.assertEqual(_fit_score(pl("DEF"), [], self.NEEDS), 0.0)
        self.assertEqual(_fit_score([], pl("K"), self.NEEDS), 0.0)
        self.assertEqual(_fit_score(pl("RB"), pl("WR", "K", "DEF"), self.NEEDS), 0.43)

    def test_multi_player_sides_are_summed(self):
        self.assertEqual(_fit_score(pl("RB", "RB"), pl("WR", "TE"), self.NEEDS), round(1.25 + 1.25 - 0.82 - 0.82, 2))


if __name__ == "__main__":
    unittest.main()
