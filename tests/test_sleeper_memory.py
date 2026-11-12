"""The Sleeper player list is kept slim in memory and not re-downloaded within one forced refresh.

Nothing a user sees may change: every reader must give the same answer from the slim copy as from the full record.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import pandas as pd

from engine import sleeper

FULL = {
    "100": {"first_name": "Pat", "last_name": "Mahomes", "full_name": "Pat Mahomes", "position": "QB", "team": "KC",
            "injury_status": "Questionable", "injury_body_part": "Ankle", "depth_chart_order": 1,
            "birth_date": "1995-09-17", "search_full_name": "patmahomes", "fantasy_positions": ["QB"], "age": 31},
    "200": {"first_name": "Old", "last_name": "Timer", "full_name": "Old Timer", "position": "RB", "team": None,
            "injury_status": None, "age": 38, "metadata": {"a": 1}},
    "PHI": {"first_name": "Philadelphia", "last_name": "Eagles", "position": "DEF", "team": "PHI"},
}
CROSSWALK = {"100": "00-0033873", "200": "00-0011111", "PHI": "PHI"}


class SlimShape(unittest.TestCase):
    def test_keeps_only_read_fields_and_leaves_absent_ones_absent(self):
        slim = sleeper._slim_players(FULL)
        self.assertEqual(set(slim), set(FULL))
        self.assertEqual(slim["100"], {"first_name": "Pat", "last_name": "Mahomes", "full_name": "Pat Mahomes",
                                       "position": "QB", "team": "KC", "injury_status": "Questionable",
                                       "injury_body_part": "Ankle", "depth_chart_order": 1})
        self.assertNotIn("full_name", slim["PHI"])           # missing stays missing, so .get() still returns None
        self.assertIsNone(slim["200"]["team"])               # an explicit None is kept as None
        self.assertNotIn("birth_date", slim["100"])

    def test_every_reader_gives_the_same_answer_from_slim_as_from_full(self):
        def run(players):
            with mock.patch.object(sleeper, "all_players", return_value=players), \
                 mock.patch.object(sleeper, "id_crosswalk", return_value=CROSSWALK):
                sleeper._INACTIVE_GSIS_IDS = None
                out = {
                    "status": sleeper.live_injury_statuses(),
                    "body": sleeper.live_injury_body_parts(),
                    "inactive": sleeper.inactive_gsis_ids(),
                    "players": {pid: sleeper.resolve_unscored_player(pid) for pid in FULL},
                    "missing": sleeper.resolve_unscored_player("nope"),
                }
                sleeper._INACTIVE_GSIS_IDS = None
                return out
        self.assertEqual(run(FULL), run(sleeper._slim_players(FULL)))


class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class ForcedRefreshDownloadsOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(sleeper._MEM.clear)
        sleeper._MEM.clear()
        p = mock.patch.object(sleeper, "_json_cache_path", lambda name: os.path.join(self.tmp, f"{name}.json"))
        p.start(); self.addCleanup(p.stop)

    def test_player_list_is_fetched_once_for_three_forced_calls_and_disk_copy_stays_full(self):
        with mock.patch.object(sleeper.requests, "get", return_value=_Resp(FULL)) as get:
            a = sleeper.all_players(force=True)
            b = sleeper.all_players(force=True)
            c = sleeper.all_players(force=True)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(a, b); self.assertEqual(b, c)
        self.assertEqual(a, sleeper._slim_players(FULL))
        with open(os.path.join(self.tmp, "all_players.json")) as f:
            self.assertEqual(json.load(f), FULL)             # nothing was dropped from the file on disk

    def test_a_forced_call_after_the_window_fetches_again(self):
        with mock.patch.object(sleeper.requests, "get", return_value=_Resp(FULL)) as get:
            sleeper.all_players(force=True)
            later = sleeper._MEM["all_players"][0] + sleeper.FORCE_REUSE_SECONDS + 1
            with mock.patch.object(sleeper.time, "time", return_value=later):
                sleeper.all_players(force=True)
        self.assertEqual(get.call_count, 2)

    def test_loading_from_the_disk_cache_is_also_slim(self):
        with open(os.path.join(self.tmp, "all_players.json"), "w") as f:
            json.dump(FULL, f)
        with mock.patch.object(sleeper.requests, "get", side_effect=AssertionError("must not fetch")):
            self.assertEqual(sleeper.all_players(), sleeper._slim_players(FULL))

    def test_crosswalk_downloads_once_for_three_forced_calls(self):
        df = pd.DataFrame({"sleeper_id": [100.0, 200.0], "gsis_id": ["00-0033873", "00-0011111"]})
        fake = types.SimpleNamespace(import_ids=mock.Mock(return_value=df))
        sleeper._CROSSWALK, sleeper._CROSSWALK_AT = None, 0.0
        self.addCleanup(setattr, sleeper, "_CROSSWALK", None)
        with mock.patch.object(sleeper, "CACHE_DIR", self.tmp), \
             mock.patch.dict(sys.modules, {"nfl_data_py": fake}), \
             mock.patch.object(pd.DataFrame, "to_parquet", lambda self_, p: None):
            a = sleeper.id_crosswalk(force=True)
            b = sleeper.id_crosswalk(force=True)
            c = sleeper.id_crosswalk(force=True)
        self.assertEqual(fake.import_ids.call_count, 1)
        self.assertEqual(a, {"100": "00-0033873", "200": "00-0011111"})
        self.assertIs(a, c)

    def test_a_crosswalk_loaded_from_an_old_disk_file_does_not_block_a_forced_download(self):
        """After a restart the crosswalk comes from the (possibly day-old) parquet; Refresh must still download."""
        df = pd.DataFrame({"sleeper_id": [100.0], "gsis_id": ["00-0033873"]})
        fake = types.SimpleNamespace(import_ids=mock.Mock(return_value=df))
        sleeper._CROSSWALK, sleeper._CROSSWALK_AT = None, 0.0
        self.addCleanup(setattr, sleeper, "_CROSSWALK", None)
        self.addCleanup(setattr, sleeper, "_CROSSWALK_AT", 0.0)
        with mock.patch.object(sleeper, "CACHE_DIR", self.tmp), \
             mock.patch.dict(sys.modules, {"nfl_data_py": fake}), \
             mock.patch.object(pd, "read_parquet", return_value=df), \
             mock.patch.object(os.path, "exists", return_value=True), \
             mock.patch.object(os.path, "getmtime", return_value=sleeper.time.time() - 3600):
            sleeper.id_crosswalk()                       # first use after a restart: read from disk, no download
            self.assertEqual(fake.import_ids.call_count, 0)
            with mock.patch.object(pd.DataFrame, "to_parquet", lambda self_, p: None):
                sleeper.id_crosswalk(force=True)         # an immediate forced call must still download
        self.assertEqual(fake.import_ids.call_count, 1)


if __name__ == "__main__":
    unittest.main()
