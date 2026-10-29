"""Tests for engine/data.py: cache TTL, season resolver, schedule helpers.

No network: _fetch_stats_player_week is patched, the cache dir is a tempdir,
and the schedule frames are built by hand.

    .venv/bin/python -m unittest tests.test_data_layer -v
"""
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from engine import data


class DiskCache(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        p = mock.patch.multiple(
            data,
            CACHE_DIR=self.td.name,
            _MANIFEST_PATH=os.path.join(self.td.name, "manifest.json"),
            _MEM={},
        )
        p.start()
        self.addCleanup(p.stop)
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return pd.DataFrame({"a": [1, 2, 3]})

    def test_second_call_is_served_from_memory(self):
        data._disk_cached("k", 2025, self.fetch)
        data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(self.calls, 1)

    def test_fresh_disk_copy_is_used_after_memory_is_cleared(self):
        data._disk_cached("k", 2025, self.fetch)
        data._MEM.clear()
        df = data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(self.calls, 1)
        self.assertEqual(list(df["a"]), [1, 2, 3])

    def test_stale_disk_copy_is_refetched(self):
        data._disk_cached("k", 2025, self.fetch)
        data._MEM.clear()
        m = data._load_manifest()
        m["k_2025"]["fetched_at"] -= data.CACHE_TTL_SECONDS + 1
        data._save_manifest(m)
        data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(self.calls, 2)

    def test_copy_just_inside_the_ttl_is_still_fresh(self):
        data._disk_cached("k", 2025, self.fetch)
        data._MEM.clear()
        m = data._load_manifest()
        m["k_2025"]["fetched_at"] -= data.CACHE_TTL_SECONDS - 60
        data._save_manifest(m)
        data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(self.calls, 1)

    def test_force_bypasses_memory_and_disk(self):
        data._disk_cached("k", 2025, self.fetch)
        data._disk_cached("k", 2025, self.fetch, force=True)
        self.assertEqual(self.calls, 2)

    def test_different_season_is_a_different_entry(self):
        data._disk_cached("k", 2024, self.fetch)
        data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(self.calls, 2)

    def test_a_write_failure_is_swallowed_and_the_data_still_returned(self):
        with mock.patch.object(pd.DataFrame, "to_parquet", side_effect=OSError("disk full")):
            df = data._disk_cached("k", 2025, self.fetch)
        self.assertEqual(len(df), 3)
        self.assertNotIn("k_2025", data._load_manifest())     # no manifest entry for a file that was not written

    def test_manifest_that_is_not_json_reads_as_empty(self):
        with open(data._MANIFEST_PATH, "w") as f:
            f.write("{not json")
        self.assertEqual(data._load_manifest(), {})


class ResolveSeason(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(data, "_resolved_season", None)
        p.start()
        self.addCleanup(p.stop)
        now = mock.patch.object(data.pd.Timestamp, "now", return_value=pd.Timestamp("2026-10-28"))
        now.start()
        self.addCleanup(now.stop)

    def probe(self, available):
        def f(year):
            if year in available:
                return pd.DataFrame({"x": range(3)})
            return pd.DataFrame()           # published but empty
        return f

    def test_uses_the_current_year_when_it_has_rows(self):
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe({2026})):
            self.assertEqual(data.resolve_season(), 2026)

    def test_falls_back_to_the_most_recent_season_with_rows(self):
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe({2025})):
            self.assertEqual(data.resolve_season(), 2025)

    def test_an_exception_for_a_year_moves_on_to_the_previous_year(self):
        def f(year):
            if year == 2026:
                raise OSError("404")
            return pd.DataFrame({"x": [1]})
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=f):
            self.assertEqual(data.resolve_season(), 2025)

    def test_the_result_is_cached_for_later_calls(self):
        fn = mock.Mock(side_effect=self.probe({2025}))
        with mock.patch.object(data, "_fetch_stats_player_week", fn):
            data.resolve_season()
            n = fn.call_count
            self.assertEqual(data.resolve_season(), 2025)
            self.assertEqual(fn.call_count, n)

    def test_force_re_probes_from_the_current_year(self):
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe({2025})):
            self.assertEqual(data.resolve_season(), 2025)
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe({2026, 2025})):
            self.assertEqual(data.resolve_season(force=True), 2026)

    def test_a_preferred_season_does_not_set_the_global(self):
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe({2023})):
            self.assertEqual(data.resolve_season(preferred=2023), 2023)
        self.assertIsNone(data._resolved_season)

    def test_raises_when_nothing_is_published_within_the_lookback(self):
        with mock.patch.object(data, "_fetch_stats_player_week", side_effect=self.probe(set())):
            with self.assertRaises(RuntimeError):
                data.resolve_season(lookback=2)

    def test_the_lookback_limits_how_far_back_it_goes(self):
        fn = mock.Mock(side_effect=self.probe(set()))
        with mock.patch.object(data, "_fetch_stats_player_week", fn):
            with self.assertRaises(RuntimeError):
                data.resolve_season(lookback=2)
        self.assertEqual([c.args[0] for c in fn.call_args_list], [2026, 2025, 2024])


def schedule():
    return pd.DataFrame({
        "week": [1, 2, 3, 3],
        "home_team": ["KC", "BUF", "KC", "DEN"],
        "away_team": ["BAL", "KC", "LV", "SEA"],
        "home_score": [27.0, 20.0, None, None],
        "away_score": [20.0, 17.0, None, None],
    })


class ScheduleHelpers(unittest.TestCase):
    def test_current_week_is_the_latest_played_week(self):
        self.assertEqual(data.current_week(schedule()), 2)

    def test_current_week_is_one_when_nothing_has_been_played(self):
        s = schedule()
        s["home_score"] = float("nan")
        self.assertEqual(data.current_week(s), 1)

    def test_current_week_is_one_without_a_score_column(self):
        self.assertEqual(data.current_week(schedule().drop(columns=["home_score"])), 1)

    def test_next_opponent_defaults_to_the_first_unplayed_week_at_home(self):
        self.assertEqual(data.next_opponent(schedule(), "KC"), ("LV", 3))

    def test_next_opponent_flips_for_an_away_game(self):
        self.assertEqual(data.next_opponent(schedule(), "KC", week=2), ("BUF", 2))
        self.assertEqual(data.next_opponent(schedule(), "KC", week=1), ("BAL", 1))

    def test_next_opponent_for_a_team_with_a_future_away_game(self):
        self.assertEqual(data.next_opponent(schedule(), "SEA"), ("DEN", 3))

    def test_next_opponent_is_none_when_the_team_has_no_game_that_week(self):
        self.assertEqual(data.next_opponent(schedule(), "KC", week=9), (None, None))

    def test_next_opponent_is_none_when_everything_has_been_played(self):
        s = schedule()
        s["home_score"] = 10.0
        self.assertEqual(data.next_opponent(s, "KC"), (None, None))

    def test_next_opponent_for_an_unknown_team(self):
        self.assertEqual(data.next_opponent(schedule(), "ZZZ"), (None, None))


if __name__ == "__main__":
    unittest.main()
