"""ESPN starting slots -> the roster_positions list _position_needs reads.

The slot counts go through espn_api's real Settings class (not a hand-made
dict), so these tests break if the library's label order or pairing ever
changes underneath engine/espn.roster_positions.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from types import SimpleNamespace

from espn_api.football.settings import Settings

from engine import espn
from engine.tools import _position_needs


def _settings(slot_counts):
    """espn_api Settings built from the smallest payload its __init__
    accepts. slot_counts maps ESPN slot id -> count; ids missing from it
    are sent as 0, so lineupSlotCounts lists every id 0-25 in order."""
    data = {
        "scheduleSettings": {"matchupPeriodCount": 14, "matchupPeriods": {},
                             "playoffTeamCount": 4, "playoffSeedingRule": "TOTAL_POINTS_SCORED"},
        "tradeSettings": {"vetoVotesRequired": 4},
        "size": 10,
        "draftSettings": {"keeperCount": 0},
        "name": "Test League",
        "scoringSettings": {"matchupTieRule": "NONE", "playoffMatchupTieRule": "NONE", "scoringItems": []},
        "acquisitionSettings": {"isUsingAcquisitionBudget": False},
        "rosterSettings": {"lineupSlotCounts": {str(i): slot_counts.get(i, 0) for i in range(26)}},
    }
    return Settings(data)


def _league(slot_counts):
    return SimpleNamespace(settings=_settings(slot_counts))


# ESPN slot ids, from espn_api.football.constant.POSITION_MAP.
QB, TQB, RB, RB_WR, WR, WR_TE, TE, OP, DST, K, BE, IR, FLEX = 0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 20, 21, 23


class RosterPositions(unittest.TestCase):
    def test_standard_league_expands_one_entry_per_slot(self):
        league = _league({QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, DST: 1, K: 1, BE: 7, IR: 1})
        self.assertEqual(sorted(espn.roster_positions(league)),
                         sorted(["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE", "D/ST", "K"]))

    def test_bench_and_ir_are_not_starting_slots(self):
        league = _league({QB: 1, BE: 6, IR: 2})
        self.assertEqual(espn.roster_positions(league), ["QB"])

    def test_league_without_settings_counts_is_empty_not_an_error(self):
        self.assertEqual(espn.roster_positions(SimpleNamespace(settings=SimpleNamespace())), [])


class PositionNeedsFromEspn(unittest.TestCase):
    def needs(self, slot_counts):
        return _position_needs(espn.roster_positions(_league(slot_counts)))

    def test_rb_wr_te_flex_spreads_like_sleeper_flex(self):
        espn_needs = self.needs({QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1})
        sleeper_needs = _position_needs(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"])
        self.assertEqual(espn_needs, sleeper_needs)

    def test_rb_wr_flex_splits_between_rb_and_wr_only(self):
        n = self.needs({QB: 1, RB: 2, WR: 2, TE: 1, RB_WR: 1})
        self.assertEqual(n, {"QB": 1.0, "RB": 2.5, "WR": 2.5, "TE": 1.0})

    def test_wr_te_flex_splits_between_wr_and_te_only(self):
        n = self.needs({QB: 1, RB: 2, WR: 2, TE: 1, WR_TE: 1})
        self.assertEqual(n, {"QB": 1.0, "RB": 2.0, "WR": 2.5, "TE": 1.5})

    def test_op_counts_as_a_full_extra_qb(self):
        self.assertEqual(self.needs({QB: 1, OP: 1})["QB"], 2.0)

    def test_team_qb_slot_is_not_an_individual_qb_need(self):
        # A TQB slot is filled by a team's QB unit (position "TQB"), never
        # by a "QB" player, so it must not create QB need.
        self.assertEqual(self.needs({TQB: 1, RB: 2, WR: 2, TE: 1})["QB"], 0.0)

    def test_dst_and_kicker_create_no_skill_position_need(self):
        self.assertEqual(self.needs({DST: 1, K: 1}), {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0})


if __name__ == "__main__":
    unittest.main()
