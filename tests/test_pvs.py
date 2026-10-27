"""Player Value Score (engine/pvs.py): cross-position, replacement-anchored."""
import unittest

import numpy as np
import pandas as pd

from engine import pvs, value as value_layer


def _frames(rows):
    """rows: [(pid, pos, proj, ceiling)] -> {pos: board-like frame} for compute_value."""
    frames = {}
    for pid, pos, proj, ceil in rows:
        frames.setdefault(pos, []).append({
            "player_id": pid, "player_display_name": pid, "recent_team": "AAA", "PROJ": proj,
            "ceiling": ceil, "snap_pct": 0.85, "cv": 0.3, "FORM": 0.0, "games": 6,
        })
    return {p: pd.DataFrame(r).set_index("player_id") for p, r in frames.items()}


def _league_rows(allen_proj=24.0):
    """A 12-team pool: 15 QBs, 35 RBs, 35 WRs, 15 TEs on a smooth curve, plus a
    star RB (21.5) and star QB (allen_proj)."""
    rows = []
    for i in range(15):
        rows.append((f"qb{i}", "QB", 22.0 - i * 0.4, 28.0 - i * 0.5))
    for i in range(35):
        rows.append((f"rb{i}", "RB", 17.0 - i * 0.28, 24.0 - i * 0.3))
    for i in range(35):
        rows.append((f"wr{i}", "WR", 17.0 - i * 0.25, 24.0 - i * 0.3))
    for i in range(15):
        rows.append((f"te{i}", "TE", 12.0 - i * 0.5, 17.0 - i * 0.5))
    rows.append(("gibbs", "RB", 21.5, 34.0))
    rows.append(("allen", "QB", allen_proj, 35.0))
    return rows


def _scored(league=None, allen_proj=24.0):
    allp = value_layer.compute_value(_frames(_league_rows(allen_proj)), ecr=None, league=league)
    return pvs.add_pvs(allp, league=league)


class TestPVS(unittest.TestCase):
    def test_back_outranks_higher_scoring_quarterback(self):
        out = _scored()
        self.assertGreater(out.loc["allen", "PROJ"], out.loc["gibbs", "PROJ"])
        self.assertGreater(out.loc["gibbs", "PVS"], out.loc["allen", "PVS"])

    def test_superflex_lifts_quarterbacks(self):
        one_qb = _scored()
        sf = _scored(league={"teams": 12, "slots": {"SUPERFLEX": 1}})
        # Allen is already past the elite reference in both leagues; a mid-pack QB is the one that moves
        self.assertGreater(sf.loc["qb6", "pvs_vorp"], one_qb.loc["qb6", "pvs_vorp"])
        self.assertGreater(sf.loc["qb6", "PVS"], one_qb.loc["qb6", "PVS"])
        self.assertGreaterEqual(sf.loc["allen", "PVS"], one_qb.loc["allen", "PVS"])
        qb12 = sf[sf["position"] == "QB"].sort_values("PROJ", ascending=False)
        self.assertGreater(qb12["PVS"].iloc[11], one_qb[one_qb["position"] == "QB"].sort_values("PROJ", ascending=False)["PVS"].iloc[11])

    def test_range_and_replacement_floor(self):
        out = _scored()
        self.assertTrue(out["PVS"].between(0, 100).all())
        self.assertLess(out["PVS"].max(), 100.0)     # absolute scale: the best player is not pinned at 100
        self.assertGreater(out["PVS"].max(), 70.0)
        worst = out.sort_values("PVS").iloc[0]
        self.assertLess(worst["PVS"], out["PVS"].max() / 2)
        self.assertIn(worst["PVS_tier"], ("Bench depth", "Flex / matchup play"))

    def test_one_outlier_does_not_flatten_the_rest(self):
        out = _scored()
        self.assertGreater((out["PVS"] >= 50).sum(), 3)
        # the star RB beats the next best by far less than his raw lead would suggest
        ranked = out["PVS"].sort_values(ascending=False)
        self.assertLess(ranked.iloc[0] - ranked.iloc[4], 15)

    def test_perfect_player_has_headroom_but_a_great_matchup_reaches_100(self):
        rows = [("star", "RB", 40.0, 60.0)] + [(f"rb{i}", "RB", 17.0 - i * 0.28, 24.0) for i in range(35)]
        allp = value_layer.compute_value(_frames(rows), ecr=None)
        neutral = pvs.add_pvs(allp).loc["star", "PVS"]
        great = pvs.add_pvs(allp, matchup={"star": 1.25}).loc["star", "PVS"]
        self.assertLessEqual(neutral, 96.0)
        self.assertGreater(great, neutral)

    def test_more_points_never_lowers_score_within_position(self):
        out = _scored()
        rb = out[out["position"] == "RB"].sort_values("PROJ", ascending=False)
        self.assertTrue(rb["PVS"].is_monotonic_decreasing)

    def test_pillars_exposed_and_unit_range(self):
        out = _scored()
        for c in ("pvs_vorp", "pvs_vol", "pvs_ceil", "pvs_perf", "pvs_match"):
            self.assertIn(c, out.columns)
        for c in ("pvs_vorp", "pvs_vol", "pvs_ceil", "pvs_perf"):
            self.assertTrue(out[c].between(0, 1).all(), c)

    def test_matchup_multiplier_clamped(self):
        self.assertEqual(pvs.matchup_multiplier(22.0, 1.0), 1.0)
        self.assertEqual(pvs.matchup_multiplier(40.0, 1.3), 1.25)
        self.assertEqual(pvs.matchup_multiplier(10.0, 0.7), 0.75)
        self.assertEqual(pvs.matchup_multiplier(None, None), 1.0)
        self.assertAlmostEqual(pvs.matchup_multiplier(None, 1.1), 1.1)

    def test_matchup_dial_moves_score(self):
        allp = value_layer.compute_value(_frames(_league_rows()), ecr=None)
        base = pvs.add_pvs(allp)
        boosted = pvs.add_pvs(allp, matchup={"rb10": 1.25})
        dimmed = pvs.add_pvs(allp, matchup={"rb10": 0.75})
        self.assertGreater(boosted.loc["rb10", "PVS"], base.loc["rb10", "PVS"])
        self.assertLess(dimmed.loc["rb10", "PVS"], base.loc["rb10", "PVS"])

    def test_missing_optional_columns_still_scores(self):
        allp = value_layer.compute_value(_frames(_league_rows()), ecr=None)
        slim = allp.drop(columns=["ceiling", "snap_pct", "cv", "FORM", "games"])
        out = pvs.add_pvs(slim)
        self.assertTrue(out["PVS"].notna().all())

    def test_input_not_modified_and_empty_ok(self):
        allp = value_layer.compute_value(_frames(_league_rows()), ecr=None)
        cols = list(allp.columns)
        pvs.add_pvs(allp)
        self.assertEqual(list(allp.columns), cols)
        self.assertTrue(pvs.add_pvs(pd.DataFrame()).empty)

    def test_tier_bands(self):
        for score, name in [(100, "Elite cornerstone"), (80, "Elite cornerstone"), (79.9, "High-end starter"),
                            (60, "High-end starter"), (59.9, "Every-week starter"), (40, "Every-week starter"),
                            (39.9, "Flex / matchup play"), (25, "Flex / matchup play"), (24.9, "Bench depth"),
                            (0, "Bench depth")]:
            self.assertEqual(pvs.tier_label(score), name, score)
        self.assertIsNone(pvs.tier_label(float("nan")))


class TestReorder(unittest.TestCase):
    def test_big_board_order_follows_pvs_and_ranks_agree(self):
        out = pvs.reorder(_scored())
        self.assertTrue(out["PVS"].is_monotonic_decreasing)
        self.assertEqual(list(out["overall_rank"]), list(range(1, len(out) + 1)))
        self.assertEqual(list(out["our_rank"]), [float(i) for i in range(1, len(out) + 1)])
        self.assertTrue(out["tier"].is_monotonic_increasing)
        self.assertGreaterEqual(out["tier"].iloc[-1], 4)
        self.assertEqual(pvs.tier_number(92), 1)
        self.assertEqual(pvs.tier_number(55), 3)
        self.assertEqual(pvs.tier_number(30), 4)


if __name__ == "__main__":
    unittest.main()
