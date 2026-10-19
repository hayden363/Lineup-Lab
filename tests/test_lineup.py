import unittest
from datetime import datetime
import pandas as pd
from engine import lineup as L, locks


def sched():
    rows = [("2026-10-22", "20:15", "DEN", "LV"), ("2026-10-25", "13:00", "SF", "WAS"), ("2026-10-25", "16:25", "KC", "BUF")]
    df = pd.DataFrame([{"week": 7, "game_type": "REG", "gameday": d, "gametime": t, "home_team": h, "away_team": a}
                       for d, t, h, a in rows])
    return pd.concat([df, pd.DataFrame([{"week": 8, "game_type": "REG", "gameday": "2026-11-01", "gametime": "13:00",
                                          "home_team": "SEA", "away_team": "ARI"}])], ignore_index=True)


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=locks.ET)


P = {
    "qb1": {"name": "Q One", "position": "QB", "team": "DEN", "PROJ": 20},
    "rb1": {"name": "R One", "position": "RB", "team": "SF", "PROJ": 15},
    "rb2": {"name": "R Two", "position": "RB", "team": "KC", "PROJ": 12},
    "wr1": {"name": "W One", "position": "WR", "team": "WAS", "PROJ": 14},
    "te1": {"name": "T One", "position": "TE", "team": "SEA", "PROJ": 8},   # SEA: bye
}
SLOTS = ["QB", "RB", "WR", "FLEX"]


class LineupTests(unittest.TestCase):
    def v(self, proposed, previous, now="2026-10-21 12:00"):
        return L.validate(SLOTS, proposed, previous, P, sched(), 7, at(now))

    def test_legal_swap_before_kickoffs(self):
        r = self.v(["qb1", "rb2", "wr1", "rb1"], ["qb1", "rb1", "wr1", "rb2"])
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(r["total_proj"], 61.0)

    def test_cannot_bench_started_player(self):
        # Thursday: DEN's QB has kicked off
        r = self.v(["rb1", "rb2", "wr1", "rb1"], ["qb1", "rb1", "wr1", "rb2"], "2026-10-22 21:00")
        self.assertFalse(r["ok"])
        self.assertTrue(any("QB is locked" in e for e in r["errors"]))

    def test_cannot_move_started_player_in(self):
        prev = [None, "rb1", "wr1", "rb2"]
        r = self.v(["qb1", "rb1", "wr1", "rb2"], prev, "2026-10-22 21:00")
        self.assertFalse(r["ok"])
        self.assertTrue(any("already played" in e for e in r["errors"]))

    def test_unchanged_locked_slot_is_fine(self):
        same = ["qb1", "rb1", "wr1", "rb2"]
        self.assertTrue(self.v(same, same, "2026-10-26 00:00")["ok"])

    def test_position_eligibility(self):
        r = self.v(["rb1", "rb2", "wr1", "rb1"], ["qb1", "rb1", "wr1", "rb2"])
        self.assertFalse(r["ok"])
        self.assertTrue(any("can't play QB" in e for e in r["errors"]))

    def test_flex_takes_te_and_duplicates_rejected(self):
        r = self.v(["qb1", "rb1", "wr1", "te1"], ["qb1", "rb1", "wr1", "rb2"])
        self.assertTrue(r["ok"], r["errors"])
        self.assertTrue(any("bye" in w for w in r["warnings"]))
        dup = self.v(["qb1", "rb1", "wr1", "rb1"], ["qb1", "rb1", "wr1", "rb2"])
        self.assertTrue(any("twice" in e for e in dup["errors"]))

    def test_no_team_player_warns_but_isnt_called_bye(self):
        P["ghost2"] = {"name": "Retired Guy", "position": "RB", "team": "788", "PROJ": 0}
        try:
            r = self.v(["qb1", "ghost2", "wr1", "rb1"], ["qb1", "rb1", "wr1", "rb2"])
        finally:
            del P["ghost2"]
        self.assertTrue(any("no NFL team" in w for w in r["warnings"]))
        self.assertFalse(any("bye" in w for w in r["warnings"]))

    def test_unknown_player_rejected(self):
        r = self.v(["qb1", "rb1", "wr1", "ghost"], ["qb1", "rb1", "wr1", "rb2"])
        self.assertFalse(r["ok"])

    def test_best_lineup_respects_locks_and_byes(self):
        prev = ["qb1", "rb2", "wr1", "te1"]
        r = L.best_lineup(SLOTS, prev, P, sched(), 7, at("2026-10-22 21:00"))
        self.assertEqual(r["lineup"][0]["player_id"], "qb1")      # locked, kept
        self.assertEqual(r["lineup"][3]["player_id"], "rb2")      # beats bye TE for FLEX
        self.assertTrue(r["ok"], r["errors"])


if __name__ == "__main__":
    unittest.main()
