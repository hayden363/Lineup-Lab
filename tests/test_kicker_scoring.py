"""engine.kicker_scoring — kicker points from play-by-play.

nflverse doesn't publish kicker fantasy points, but it does publish official
per-kicker weekly counting stats (FGs made per distance bucket, misses, PATs).
build_kicker_weekly derives the same counts from play-by-play, so the anchor
test holds those derived counts to the official ones: on the cached 2025 season
all 562 kicker-weeks match on all nine counts. Distance-bucket edges are the
classic off-by-one spot, so they're pinned separately too.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import glob
import json
import os
import unittest

import pandas as pd

from engine.kicker_scoring import (DEFAULT_K_SCORING, FG_BUCKETS, _fg_bucket,
                                   build_kicker_weekly, k_scoring_from_sleeper,
                                   score_kicker_weekly)

ROOT = os.path.join(os.path.dirname(__file__), "..")
OFFICIAL_SUFFIX = dict(zip(FG_BUCKETS, ["0_19", "20_29", "30_39", "40_49", "50_59", "60_"]))


class GroundTruth(unittest.TestCase):
    def test_derived_counts_match_nflverse_official_kicker_stats(self):
        seasons = [p.split("_")[-1].split(".")[0] for p in glob.glob(os.path.join(ROOT, "data_cache", "pbp_*.parquet"))]
        seasons = [s for s in seasons if os.path.exists(os.path.join(ROOT, "data_cache", f"weekly_{s}.parquet"))]
        if not seasons:
            self.skipTest("no cached season with both pbp and weekly data")
        for season in sorted(seasons):
            pbp = pd.read_parquet(os.path.join(ROOT, "data_cache", f"pbp_{season}.parquet"))
            wk = pd.read_parquet(os.path.join(ROOT, "data_cache", f"weekly_{season}.parquet"))
            ours = build_kicker_weekly(pbp)
            k = wk[(wk["fg_att"].fillna(0) > 0) | (wk["pat_att"].fillna(0) > 0)]
            official = pd.DataFrame({
                "player_id": k["player_id"], "week": k["week"],
                **{b: k[f"fg_made_{s}"].fillna(0) for b, s in OFFICIAL_SUFFIX.items()},
                # the app counts blocked kicks as misses, so compare against both
                "fg_miss": k["fg_missed"].fillna(0) + k["fg_blocked"].fillna(0),
                "xp_made": k["pat_made"].fillna(0),
                "xp_miss": k["pat_missed"].fillna(0) + k["pat_blocked"].fillna(0),
            })
            m = ours.merge(official, on=["player_id", "week"], how="outer",
                           suffixes=("_ours", "_nfl"), indicator=True)
            with self.subTest(season=season):
                self.assertEqual(int((m["_merge"] != "both").sum()), 0, "kicker-weeks present on only one side")
                for col in list(FG_BUCKETS) + ["fg_miss", "xp_made", "xp_miss"]:
                    bad = int((m[f"{col}_ours"].fillna(0) != m[f"{col}_nfl"].fillna(0)).sum())
                    self.assertEqual(bad, 0, f"{col}: {bad} kicker-weeks differ from nflverse")


class Buckets(unittest.TestCase):
    def test_every_bucket_edge(self):
        cases = {18: "fgm_0_19", 19: "fgm_0_19", 20: "fgm_20_29", 29: "fgm_20_29",
                 30: "fgm_30_39", 39: "fgm_30_39", 40: "fgm_40_49", 49: "fgm_40_49",
                 50: "fgm_50_59", 59: "fgm_50_59", 60: "fgm_60p", 66: "fgm_60p"}
        for distance, bucket in cases.items():
            with self.subTest(distance=distance):
                self.assertEqual(_fg_bucket(distance), bucket)


class Points(unittest.TestCase):
    def _row(self, **counts):
        base = {b: 0 for b in FG_BUCKETS}
        base.update(fg_miss=0, xp_made=0, xp_miss=0)
        base.update(counts)
        return pd.DataFrame([base])

    def test_hand_computed_week(self):
        # one 50-59 make (5) + two PATs (2) + one missed FG (-1) = 6
        row = self._row(fgm_50_59=1, xp_made=2, fg_miss=1)
        self.assertEqual(score_kicker_weekly(row, DEFAULT_K_SCORING).iloc[0], 6.0)

    def test_distance_is_rewarded(self):
        short = score_kicker_weekly(self._row(fgm_20_29=1), DEFAULT_K_SCORING).iloc[0]
        long = score_kicker_weekly(self._row(fgm_60p=1), DEFAULT_K_SCORING).iloc[0]
        self.assertGreater(long, short)


class SleeperSettings(unittest.TestCase):
    def test_known_keys_override_and_unknown_keys_are_ignored(self):
        s = k_scoring_from_sleeper({"fgm_50_59": "7", "fgmiss": 0, "not_a_key": 99})
        self.assertEqual((s["fgm_50_59"], s["fgmiss"]), (7.0, 0.0))
        self.assertNotIn("not_a_key", s)
        self.assertEqual(s["xpm"], DEFAULT_K_SCORING["xpm"])

    def test_real_cached_leagues_apply_their_kicker_values(self):
        files = sorted(glob.glob(os.path.join(ROOT, "data_cache", "sleeper_league_*.json")))
        if not files:
            self.skipTest("no cached Sleeper league in data_cache/")
        for path in files:
            raw = json.load(open(path)).get("scoring_settings") or {}
            s = k_scoring_from_sleeper(raw)
            with self.subTest(league=os.path.basename(path)):
                for key in DEFAULT_K_SCORING:
                    if key in raw:
                        self.assertEqual(s[key], float(raw[key]))


if __name__ == "__main__":
    unittest.main()
