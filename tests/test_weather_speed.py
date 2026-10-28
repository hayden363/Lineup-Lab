"""Weather must never make a page slow: failures are remembered, lookups run together, and the wait is short."""
import datetime as dt
import time
import unittest
from unittest import mock

import pandas as pd

from engine import sleeper, weather

TODAY = dt.date(2026, 11, 1)
DATA = {"hourly": {"time": ["2026-11-01T13:00", "2026-11-01T14:00", "2026-11-01T15:00"], "temperature_2m": [50, 50, 50],
                   "wind_speed_10m": [5, 5, 5], "wind_gusts_10m": [8, 8, 8], "precipitation": [0, 0, 0], "snowfall": [0, 0, 0]}}


def fresh():
    weather._FAILED.clear()
    sleeper._MEM.pop("wx_DET00_2026-11-01", None)


class FailureMemoryTests(unittest.TestCase):
    def setUp(self):
        fresh()
        self.addCleanup(fresh)

    def test_a_failed_lookup_is_not_retried_for_a_while(self):
        with mock.patch.object(sleeper, "_cached_get", side_effect=RuntimeError("down")) as g:
            for _ in range(5):
                self.assertIsNone(weather.kickoff_forecast("DET00", "outdoors", "2026-11-01", "13:00", TODAY))
        self.assertEqual(g.call_count, 1)

    def test_the_failure_expires(self):
        with mock.patch.object(sleeper, "_cached_get", side_effect=RuntimeError("down")) as g:
            weather.kickoff_forecast("DET00", "outdoors", "2026-11-01", "13:00", TODAY)
            weather._FAILED["wx_DET00_2026-11-01"] -= weather.FAIL_TTL + 1
            weather.kickoff_forecast("DET00", "outdoors", "2026-11-01", "13:00", TODAY)
        self.assertEqual(g.call_count, 2)

    def test_a_success_still_works_and_waits_only_a_few_seconds(self):
        with mock.patch.object(sleeper, "_cached_get", return_value=DATA) as g:
            out = weather.kickoff_forecast("DET00", "outdoors", "2026-11-01", "13:00", TODAY)
        self.assertEqual(out["temp"], 50)
        self.assertLessEqual(g.call_args.kwargs.get("timeout", 15), 5)


class PrefetchTests(unittest.TestCase):
    SCHED = pd.DataFrame([
        {"week": 8, "game_type": "REG", "home_team": "DET", "away_team": "GB", "stadium_id": "DET00", "roof": "outdoors", "gameday": "2026-11-01", "gametime": "13:00"},
        {"week": 8, "game_type": "REG", "home_team": "KC", "away_team": "BUF", "stadium_id": "KAN00", "roof": "outdoors", "gameday": "2026-11-01", "gametime": "16:25"},
        {"week": 8, "game_type": "REG", "home_team": "NO", "away_team": "ATL", "stadium_id": "NOR00", "roof": "dome", "gameday": "2026-11-01", "gametime": "13:00"},
        {"week": 9, "game_type": "REG", "home_team": "SF", "away_team": "SEA", "stadium_id": "SFO01", "roof": "outdoors", "gameday": "2026-11-08", "gametime": "13:00"}])

    def test_every_outdoor_game_of_the_week_is_fetched_once_and_together(self):
        seen = []

        def slow(stadium, roof, gameday, gametime, today=None):
            time.sleep(0.2)
            seen.append(stadium)
        t0 = time.time()
        with mock.patch.object(weather, "kickoff_forecast", side_effect=slow):
            n = weather.prefetch(self.SCHED, 8)
        self.assertEqual(sorted(seen), ["DET00", "KAN00"])          # the dome and next week's game are skipped
        self.assertEqual(n, 2)
        self.assertLess(time.time() - t0, 0.35)                     # in parallel, not 0.4 s in a row

    def test_prefetch_never_raises(self):
        with mock.patch.object(weather, "kickoff_forecast", side_effect=RuntimeError("boom")):
            self.assertEqual(weather.prefetch(self.SCHED, 8), 2)
        self.assertEqual(weather.prefetch(None, 8), 0)
        self.assertEqual(weather.prefetch(pd.DataFrame(), 8), 0)


if __name__ == "__main__":
    unittest.main()
