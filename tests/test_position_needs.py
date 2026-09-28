"""engine.tools._position_needs — starting-slot demand per position.

This feeds the Trade Finder's need multipliers, so a miscount silently
re-ranks every trade suggestion. The first test pins behaviour on a REAL
league's roster_positions (read from data_cache/, not typed in by hand), so
adding superflex support provably leaves standard leagues untouched.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import json
import unittest
from pathlib import Path

from engine.tools import _position_needs

CACHE = Path(__file__).resolve().parent.parent / "data_cache"


def _real_roster_positions():
    """roster_positions from a real Sleeper league cached by the app, or None
    if no cached league exists on this machine (e.g. a fresh clone)."""
    for f in sorted(CACHE.glob("sleeper_league_*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        rp = data.get("roster_positions") if isinstance(data, dict) else None
        if rp:
            return rp
    return None


class PositionNeeds(unittest.TestCase):
    def test_real_standard_league_is_unchanged(self):
        rp = _real_roster_positions()
        if rp is None:
            self.skipTest("no cached Sleeper league in data_cache/")
        # Real leagues here are QB, RB x2, WR x2, TE, FLEX x2 (+ K/DEF/bench):
        # 1 QB, and the two FLEX split a third each onto RB/WR/TE.
        needs = _position_needs(rp)
        qb = rp.count("QB")
        flex = rp.count("FLEX")
        self.assertEqual(needs["QB"], qb)
        self.assertAlmostEqual(needs["RB"], rp.count("RB") + flex / 3)
        self.assertAlmostEqual(needs["WR"], rp.count("WR") + flex / 3)
        self.assertAlmostEqual(needs["TE"], rp.count("TE") + flex / 3)

    def test_superflex_counts_as_an_extra_qb(self):
        needs = _position_needs(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"])
        self.assertEqual(needs["QB"], 2.0)
        # Superflex must not leak into the RB/WR/TE flex split.
        self.assertAlmostEqual(needs["RB"], 2 + 1 / 3)

    def test_espn_op_slot_counts_as_an_extra_qb(self):
        self.assertEqual(_position_needs(["QB", "OP"])["QB"], 2.0)

    def test_unknown_and_non_offense_slots_are_ignored(self):
        needs = _position_needs(["QB", "K", "DEF", "BN", "IR", "IDP_FLEX", "SOMETHING_NEW"])
        self.assertEqual(needs, {"QB": 1.0, "RB": 0.0, "WR": 0.0, "TE": 0.0})

    def test_empty_or_missing_roster(self):
        zero = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
        self.assertEqual(_position_needs([]), zero)
        self.assertEqual(_position_needs(None), zero)


if __name__ == "__main__":
    unittest.main()
