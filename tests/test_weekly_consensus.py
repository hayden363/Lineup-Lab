"""Weekly expert consensus blended into Start/Sit and Waivers (engine/consensus.py)."""

import unittest
from unittest import mock

import pandas as pd

from engine import consensus, profile, tools, waivers


def _sched():
    return pd.DataFrame({"week": [5, 5, 6], "game_type": ["REG"] * 3,
                         "gameday": ["2026-10-08", "2026-10-11", "2026-10-15"]})


def _page(pos, rows, scrape):
    return pd.DataFrame([{"page_type": f"weekly-{pos.lower()}", "player": n, "pos": pos, "team": "X", "ecr": float(r),
                          "sd": 1.0, "best": 1, "worst": 9, "bye": 7.0, "scrape_date": scrape} for n, r in rows])


class Helpers(unittest.TestCase):
    def test_fresh_after_is_four_days_before_the_weeks_first_game(self):
        self.assertEqual(consensus.fresh_after(_sched(), 5), pd.Timestamp("2026-10-04"))
        self.assertIsNone(consensus.fresh_after(_sched(), 9))   # no games that week

    def test_stale_weekly_page_is_ignored(self):
        ecr = _page("RB", [("A B", 3)], "2026-10-01")
        key = consensus.match_key("A B", "RB")
        self.assertEqual(consensus.weekly_lookup("RB", ecr)[key], 3.0)                 # old callers unchanged
        self.assertEqual(consensus.weekly_lookup("RB", ecr, fresh_after=pd.Timestamp("2026-10-04")), {})
        self.assertEqual(consensus.weekly_lookup("RB", ecr, fresh_after=pd.Timestamp("2026-09-30"))[key], 3.0)

    def test_rank_maps_onto_our_points_scale(self):
        ref = [20.0, 15.0, 10.0, 5.0]
        self.assertEqual(consensus.points_for_rank(1, ref), 20.0)
        self.assertEqual(consensus.points_for_rank(2.6, ref), 10.0)    # fractional ranks round
        self.assertEqual(consensus.points_for_rank(99, ref), 5.0)      # past the end -> the last slot
        self.assertIsNone(consensus.points_for_rank(None, ref))
        self.assertIsNone(consensus.points_for_rank(1, []))

    def test_blend_uses_the_weight_and_falls_back_without_a_rank(self):
        ref = [20.0, 10.0]
        blended, pts = consensus.blend_with_rank(10.0, 1, ref, 0.8)
        self.assertEqual(pts, 20.0)
        self.assertAlmostEqual(blended, 18.0)                          # 0.8*20 + 0.2*10
        self.assertEqual(consensus.blend_with_rank(10.0, None, ref, 0.8), (10.0, None))

    def test_weights_are_the_backtested_ones(self):
        self.assertEqual(consensus.WEEKLY_WEIGHT, 0.80)
        self.assertLess(consensus.WAIVER_WEEKLY_WEIGHT, consensus.WEEKLY_WEIGHT)


class WaiverPool(unittest.TestCase):
    def pool(self):
        return pd.DataFrame({"position": ["RB"] * 3, "player_display_name": ["A One", "B Two", "C Three"],
                             "value": [20.0, 12.0, 4.0]}, index=["a", "b", "c"])

    def test_blends_only_listed_players_and_never_touches_the_cached_pool(self):
        pool = self.pool()
        ecr = _page("RB", [("C Three", 1), ("A One", 3)], "2026-10-08")   # experts flip C to the top
        with mock.patch.object(consensus, "load_ecr", return_value=ecr):
            out = waivers.with_weekly_consensus(pool, _sched(), 5, weight=0.5)
        self.assertEqual(list(pool["value"]), [20.0, 12.0, 4.0])          # input untouched
        self.assertAlmostEqual(out.loc["c", "value"], 0.5 * 20.0 + 0.5 * 4.0)
        self.assertEqual(out.loc["c", "value_model"], 4.0)
        self.assertAlmostEqual(out.loc["a", "value"], 0.5 * 4.0 + 0.5 * 20.0)   # rank 3 -> the 3rd slot (4.0)
        self.assertEqual(out.loc["b", "value"], 12.0)                      # not listed: our number stands

    def test_stale_page_changes_nothing(self):
        ecr = _page("RB", [("C Three", 1)], "2026-09-20")
        with mock.patch.object(consensus, "load_ecr", return_value=ecr):
            out = waivers.with_weekly_consensus(self.pool(), _sched(), 5)
        self.assertEqual(list(out["value"]), [20.0, 12.0, 4.0])


class StartSitUsesConsensus(unittest.TestCase):
    def test_a_fresh_weekly_rank_moves_proj_and_is_reported(self):
        bundle = waivers.load_bundle()
        week = waivers.target_week(bundle["schedule"])
        after = consensus.fresh_after(bundle["schedule"], week)
        if after is None:
            self.skipTest("no game dates for this week")
        byes = profile.bye_weeks(bundle["schedule"])
        pool, _ = waivers.cached_pool(None, bundle)
        qbs = pool[(pool["position"] == "QB") & pool["injury_status"].isna()
                   & ~pool["recent_team"].map(lambda t: byes.get(t) == week)].sort_values("value", ascending=False)
        if len(qbs) < 12:
            self.skipTest("not enough healthy QBs")
        low = qbs.iloc[10]      # a mid QB whom the (fake) experts put first
        none = pd.DataFrame(columns=["page_type", "player", "pos", "team", "ecr", "sd", "best", "worst", "bye", "scrape_date"])
        with mock.patch.object(consensus, "load_ecr", return_value=none):   # whatever the real cache holds is out of the picture
            base = tools.start_sit([low.name, qbs.index[0]])
        base_row = next(p for p in base["players"] if p["player_id"] == low.name)
        if base_row.get("on_bye") or not base_row["PROJ"]:
            self.skipTest("test player not playing")
        self.assertIsNone(base_row["consensus"])
        ecr = _page("QB", [(low["player_display_name"], 1)], (after + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        with mock.patch.object(consensus, "load_ecr", return_value=ecr):
            res = tools.start_sit([low.name, qbs.index[0]])
        row = next(p for p in res["players"] if p["player_id"] == low.name)
        self.assertEqual(row["consensus"]["rank"], 1)
        self.assertEqual(row["consensus"]["weight"], consensus.WEEKLY_WEIGHT)
        self.assertGreater(row["PROJ"], base_row["PROJ"])                  # pulled toward the top-QB number
        self.assertTrue(any("Experts rank him QB1" in r for r in row["reasons"]))
        other = next(p for p in res["players"] if p["player_id"] == qbs.index[0])
        self.assertIsNone(other["consensus"])                              # unlisted: our own number

    def test_stale_page_leaves_start_sit_unchanged(self):
        bundle = waivers.load_bundle()
        week = waivers.target_week(bundle["schedule"])
        after = consensus.fresh_after(bundle["schedule"], week)
        if after is None:
            self.skipTest("no game dates for this week")
        old = (after - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        ecr = _page("QB", [("Anyone", 1)], old)
        with mock.patch.object(consensus, "load_ecr", return_value=ecr):
            lookups, ref = tools._weekly_consensus_inputs(bundle, week, None)
        self.assertEqual((lookups, ref), ({}, {}))


if __name__ == "__main__":
    unittest.main()
