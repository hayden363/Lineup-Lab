import unittest
from datetime import datetime
import pandas as pd
from engine import locks as L


def sched():
    rows = [("2026-10-22", "20:15", "DEN", "LV"), ("2026-10-25", "13:00", "SF", "WAS"), ("2026-10-26", "20:15", "KC", "BUF")]
    return pd.DataFrame([{"week": 7, "game_type": "REG", "gameday": d, "gametime": t, "home_team": h, "away_team": a}
                         for d, t, h, a in rows])


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=L.ET)


class LockTests(unittest.TestCase):
    def test_thursday_locks_thursday_sunday_waits(self):
        now = at("2026-10-22 21:00")
        self.assertTrue(L.is_locked(sched(), "DEN", 7, now))
        self.assertTrue(L.is_locked(sched(), "LV", 7, now))
        self.assertFalse(L.is_locked(sched(), "SF", 7, now))
        self.assertFalse(L.is_locked(sched(), "KC", 7, now))

    def test_exact_kickoff_locks_minute_before_does_not(self):
        self.assertFalse(L.is_locked(sched(), "SF", 7, at("2026-10-25 12:59")))
        self.assertTrue(L.is_locked(sched(), "SF", 7, at("2026-10-25 13:00")))

    def test_bye_never_locks(self):
        st = L.lock_status(sched(), "SEA", 7, at("2026-11-30 00:00"))
        self.assertTrue(st["bye"])
        self.assertFalse(st["locked"])

    def test_missing_time_is_unlocked(self):
        s = sched(); s.loc[0, "gametime"] = None
        self.assertFalse(L.is_locked(s, "DEN", 7, at("2026-10-30 00:00")))


if __name__ == "__main__":
    unittest.main()
