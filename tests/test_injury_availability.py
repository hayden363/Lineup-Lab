"""A long injury cuts rest-of-season value by the games ESPN says he'll miss."""

import unittest
from datetime import date

import pandas as pd

from engine import injuries


def _schedule(n=10, team="WAS"):
    return pd.DataFrame({
        "game_type": ["REG"] * n, "week": range(1, n + 1), "home_team": [team] * n, "away_team": ["XXX"] * n,
        "home_score": [None] * n, "gameday": [f"2026-11-{d:02d}" for d in range(1, n + 1)],
    })


def _row(status, ret):
    return {"injury_status": status, "recent_team": "WAS",
            "injury_report": {"return_date": ret} if ret else None}


class AvailabilityTests(unittest.TestCase):
    today = date(2026, 10, 25)

    def test_season_ending_is_zero(self):
        self.assertEqual(injuries.availability(_row("Out", "2027-02-15"), _schedule(), self.today), 0.0)

    def test_partial_absence_scales(self):
        a = injuries.availability(_row("IR", "2026-11-06"), _schedule(), self.today)  # misses 5 of 10
        self.assertEqual(a, 0.5)

    def test_no_return_date_for_a_healthy_or_questionable_player_is_neutral(self):
        self.assertEqual(injuries.availability(_row("Questionable", None), _schedule(), self.today), 1.0)
        self.assertEqual(injuries.availability(_row(None, None), _schedule(), self.today), 1.0)

    def test_out_and_ir_without_a_return_date_still_get_an_assumed_discount(self):
        # 10 games left: Out is assumed to miss the next game, IR/PUP the NFL's 4-game minimum
        self.assertEqual(injuries.availability(_row("Out", None), _schedule(), self.today), 0.9)
        self.assertEqual(injuries.availability(_row("IR", None), _schedule(), self.today), 0.6)
        self.assertEqual(injuries.availability(_row("PUP", None), _schedule(), self.today), 0.6)

    def test_assumed_absence_is_capped_by_the_games_left(self):
        self.assertEqual(injuries.availability(_row("IR", None), _schedule(3), self.today), 0.0)
        self.assertEqual(injuries.availability(_row("IR", None), _schedule(0), self.today), 1.0)    # no games left: nothing to discount

    def test_unknown_length_statuses_are_not_guessed(self):
        self.assertEqual(injuries.availability(_row("Sus", None), _schedule(), self.today), 1.0)

    def test_an_espn_return_date_beats_the_assumption(self):
        self.assertEqual(injuries.availability(_row("IR", "2026-11-03"), _schedule(), self.today), 0.8)   # back after 2 of 10

    def test_out_long(self):
        self.assertTrue(injuries.out_long(_row("Out", "2027-02-15"), _schedule(), self.today))
        self.assertTrue(injuries.out_long(_row("IR", None), _schedule(), self.today))
        self.assertFalse(injuries.out_long(_row("Out", "2026-11-02"), _schedule(), self.today))
        self.assertFalse(injuries.out_long(_row("Questionable", None), _schedule(), self.today))


if __name__ == "__main__":
    unittest.main()
