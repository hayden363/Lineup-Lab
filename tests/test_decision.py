import datetime as dt
import unittest

import numpy as np
import pandas as pd

from engine import decision as D, weather as W
from engine.scoring import ScoringSettings, compute_fantasy_points


class OutcomeTest(unittest.TestCase):
    def test_quantiles_ordered_and_mean_kept(self):
        o = D.outcomes(15, 0.6, seed=1)
        self.assertLess(o["p10"], o["p50"])
        self.assertLess(o["p50"], o["p90"])
        self.assertAlmostEqual(float(o["_samples"].mean()), 15, delta=0.6)
        self.assertGreater(o["p_10plus"], o["p_20plus"])

    def test_shrinkage_toward_position(self):
        self.assertAlmostEqual(D.shrunk_cv(None, 0, 0.5), 0.5 * D.CV_SCALE)
        few = D.shrunk_cv(1.2, 2, 0.5)
        many = D.shrunk_cv(1.2, 16, 0.5)
        self.assertLess(few, many)

    def test_ruled_out_is_zero(self):
        o = D.ruled_out()
        self.assertEqual((o["p90"], o["p_10plus"]), (0.0, 0))


def P(name, proj, cv, seed):
    return {"player_id": name, "player_display_name": name, "outcomes": D.outcomes(proj, cv, seed)}


class VerdictTest(unittest.TestCase):
    def test_steady_vs_volatile_pivots_by_mode(self):
        steady, boom = P("Steady", 12, 0.3, 1), P("Boom", 11.5, 0.9, 2)
        self.assertEqual(D.verdict([steady, boom], "safe")["pick"], "Steady")
        self.assertEqual(D.verdict([steady, boom], "upside")["pick"], "Boom")
        self.assertIn("if you need a ceiling", D.verdict([steady, boom], "balanced")["line"])

    def test_clear_better_player_wins_every_mode(self):
        v = D.verdict([P("Star", 22, 0.45, 1), P("Scrub", 6, 0.6, 2)], "balanced")
        self.assertEqual(v["archetype"], "Best in every scenario")
        self.assertIn(v["confidence"], ("High", "Slam dunk"))

    def test_confidence_bands(self):
        self.assertEqual([D.confidence(p) for p in (50, 58, 65, 80)], ["Low", "Moderate", "High", "Slam dunk"])


class TrendAndSplitTest(unittest.TestCase):
    def test_one_odd_game_is_not_a_trend(self):
        # Week 4's 20% (left hurt) is outweighed by the 89% that followed:
        # only the smaller drop counts, well short of the 15-point flag.
        self.assertEqual(D.snap_trend([94, 88, 100, 20, 89]), -5.0)
        self.assertEqual(D.snap_trend([60, 62, 58, 90, 40]), 0.0)
        self.assertEqual(D.snap_trend([90, 88, 92, 60, 65]), -25.0)
        self.assertIsNone(D.snap_trend([90, 80, 70]))

    def test_script_split_counts_only_his_games(self):
        rows = []
        for wk in (1, 2):
            for i in range(60):
                rows.append({"posteam": "AAA", "play_type": "run", "week": wk, "score_differential": 10 if i % 2 else -10,
                             "rusher_player_id": "p" if wk == 1 else "x", "receiver_player_id": None})
        pbp = pd.DataFrame(rows)
        self.assertEqual(D.script_split(pbp, "p", "AAA", weeks={1})["leading"], 100.0)
        self.assertEqual(D.script_split(pbp, "p", "AAA")["leading"], 50.0)
        self.assertIsNone(D.script_split(pbp.drop(columns=["score_differential"]), "p", "AAA"))


class FlagsTest(unittest.TestCase):
    def test_vegas_and_trap_flags(self):
        r = {"position": "WR", "injury_status": None}
        ctx = {"implied_total": 17.5, "margin": -7, "weather": None}
        good, bad = D.player_flags(r, ctx, None, {"xfp_pg": 8.0, "diff": 5.0}, 50, -20)
        text = " ".join(bad)
        self.assertIn("17.5", text)
        self.assertIn("Running hot", text)
        self.assertIn("TD-dependent", text)
        self.assertIn("Snap share down 20", text)

    def test_matchup_flags_from_factors(self):
        f = pd.DataFrame({"ypt_allowed": [1.2, 1.0, 0.8], "pass_td_rate_allowed": [1.0, 1.0, 1.0]}, index=["AAA", "BBB", "CCC"])
        good, bad = D.matchup_flags("WR", "AAA", f)
        self.assertTrue(good and "20% above average" in good[0])
        good, bad = D.matchup_flags("WR", "CCC", f)
        self.assertTrue(bad and "20% below average" in bad[0])


class WeatherTest(unittest.TestCase):
    def test_degradation_index(self):
        self.assertEqual(W.degradation(5, 0, 0, 60)[1], "none")
        idx, label, why = W.degradation(22, 3.5, 0, 30)
        self.assertEqual((idx, label), (80, "severe"))
        self.assertIn("heavy rain", why)

    def test_no_forecast_indoors_or_far_out(self):
        self.assertIsNone(W.kickoff_forecast("DET00", "dome", "2026-10-25", "13:00"))
        self.assertIsNone(W.kickoff_forecast("CHI98", "outdoors", "2027-01-30", "13:00", today=dt.date(2026, 10, 19)))
        self.assertIsNone(W.kickoff_forecast("CHI98", "outdoors", "2026-10-01", "13:00", today=dt.date(2026, 10, 19)))


class ScoringBonusTest(unittest.TestCase):
    WK = pd.DataFrame([
        {"position": "TE", "receptions": 6, "receiving_yards": 105, "receiving_first_downs": 4},
        {"position": "WR", "receptions": 6, "receiving_yards": 99, "receiving_first_downs": 4},
        {"position": "RB", "rushing_yards": 210, "rushing_first_downs": 7},
    ])

    def test_defaults_unchanged(self):
        base = compute_fantasy_points(self.WK, ScoringSettings.from_preset("ppr")).tolist()
        self.assertEqual(base, [16.5, 15.9, 21.0])

    def test_te_premium_first_downs_and_milestones(self):
        s = ScoringSettings.from_dict({"te_reception": 0.5, "rec_fd": 0.5, "rush_fd": 0.5,
                                       "bonus_rec_100": 3, "bonus_rush_100": 3, "bonus_rush_200": 3})
        pts = compute_fantasy_points(self.WK, s).tolist()
        self.assertEqual(pts, [16.5 + 3 + 2 + 3, 15.9 + 2, 21.0 + 3.5 + 6])

    def test_preset_te_premium(self):
        s = ScoringSettings.from_preset("te_premium")
        self.assertEqual((s.reception, s.te_reception), (1.0, 0.5))


if __name__ == "__main__":
    unittest.main()


class RecentUsageTest(unittest.TestCase):
    def test_last_four_vs_season_and_role_shift(self):
        wk = pd.DataFrame([{"player_id": "p", "week": w, "target_share": ts, "targets": t}
                           for w, ts, t in [(1, .10, 3), (2, .10, 3), (3, .30, 9), (4, .30, 9), (5, .30, 9), (6, .30, 9)]])
        snaps = {w: 60 + w for w in range(1, 7)}
        xfp = {1: 4, 2: 4, 3: 12, 4: 12, 5: 12, 6: 12}
        r = D.recent_usage("p", "RB", wk, snaps, xfp, {3: 2, 4: 2})
        self.assertEqual(r["weeks"], [3, 4, 5, 6])
        self.assertEqual(r["target_share"], {"recent": 30.0, "season": 23.3})
        self.assertEqual(r["hvt_pg"]["recent"], 10.0)
        self.assertEqual(r["xfp_pg"], {"recent": 12.0, "season": 9.3})
        self.assertGreater(D.role_shift(r), 0)
        self.assertEqual(D.role_shift(None), 0.0)
        self.assertIsNone(D.recent_usage("p", "QB", wk, snaps, xfp, {})["xfp_pg"])
