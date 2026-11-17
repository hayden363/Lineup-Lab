"""QB matchup grading (owner 2026-11-17, decided by analysis/qb_matchup_backtest.py): a QB's rushing is graded against the
QB runs a defense allows, not its yards per carry against running backs, and only MATCHUP_STRENGTH of the QB composite
reaches PROJ (full strength made the head-to-head probabilities worse than no matchup)."""
import unittest

import pandas as pd

from engine import defense


def _pbp():
    rows = []
    # qb1 drops back 12 times for team A against defense X and Y; rb1 runs against both
    for wk, d in ((1, "X"), (2, "Y")):
        rows += [dict(play_type="pass", qb_dropback=1, passer_player_id="qb1", rusher_player_id=None, defteam=d, week=wk, yards_gained=7)] * 12
        rows += [dict(play_type="run", qb_dropback=0, passer_player_id=None, rusher_player_id="rb1", defteam=d, week=wk, yards_gained=5)] * 20
    # X gives up 60 QB rushing yards, Y gives up none
    rows += [dict(play_type="run", qb_dropback=0, passer_player_id=None, rusher_player_id="qb1", defteam="X", week=1, yards_gained=10)] * 6
    # a trick-play passer (1 dropback) running is not counted as a QB run
    rows += [dict(play_type="pass", qb_dropback=1, passer_player_id="wr9", rusher_player_id=None, defteam="Y", week=2, yards_gained=30)]
    rows += [dict(play_type="run", qb_dropback=0, passer_player_id=None, rusher_player_id="wr9", defteam="Y", week=2, yards_gained=40)]
    return pd.DataFrame(rows)


class QbRushAllowedTests(unittest.TestCase):
    def test_counts_only_real_qbs_and_shrinks_to_the_mean(self):
        q = defense.qb_rush_allowed(_pbp())
        league = 60 / 2                                               # 60 QB yards over 2 defense-games
        k = defense.QB_RUSH_SHRINK_GAMES
        self.assertAlmostEqual(q["X"], (60 + k * league) / (1 + k))
        self.assertAlmostEqual(q["Y"], (0 + k * league) / (1 + k))       # the trick-play run is ignored
        self.assertGreater(q["X"], q["Y"])

    def test_empty_input_is_safe(self):
        self.assertEqual(len(defense.qb_rush_allowed(pd.DataFrame())), 0)


class MappingAndStrengthTests(unittest.TestCase):
    def test_qb_rushing_reads_qb_runs_not_rb_yards_per_carry(self):
        self.assertEqual(defense.METRIC_TO_DEFENSE["QB"]["rush_yards_per_game"], "qb_rush_ypg_allowed")
        self.assertEqual(defense.METRIC_TO_DEFENSE["RB"]["yards_per_carry"], "ypc_allowed_RB")   # RBs: run D vs RBs

    def test_qb_factor_is_scaled_and_the_label_reads_the_full_composite(self):
        f = pd.DataFrame({c: [1.3, 0.7] for c in set(defense.METRIC_TO_DEFENSE["QB"].values()) if c}, index=["SOFT", "HARD"])
        raw = defense.composite_multiplier("QB", "SOFT", f, full=True)
        used = defense.composite_multiplier("QB", "SOFT", f)
        k = defense.MATCHUP_STRENGTH["QB"]
        self.assertAlmostEqual(used, round(1 + k * (raw - 1), 3))
        self.assertLess(abs(used - 1), abs(raw - 1))
        self.assertEqual(set(defense.MATCHUP_STRENGTH), {"QB", "RB", "WR", "TE"})
        ranks = sorted(f.index, key=lambda t: -defense.composite_multiplier("QB", t, f))
        self.assertEqual(ranks, sorted(f.index, key=lambda t: -defense.composite_multiplier("QB", t, f, full=True)))

    def test_profile_carries_the_column(self):
        pbp = _pbp().assign(complete_pass=1, pass_touchdown=0, interception=0, sack=0, qb_hit=0, epa=0.1,
                            yards_after_catch=3, rush_touchdown=0)
        prof = defense.build_defense_profile(pbp)
        self.assertIn("qb_rush_ypg_allowed", prof.columns)



class PositionAllowedTests(unittest.TestCase):
    """RB / WR / TE read what a defense gives up to that position (analysis/pos_matchup_backtest.py)."""

    def _pbp(self):
        r = []
        for d in ("X", "Y"):
            for wk in (1, 2):
                # X lets WRs catch everything for 15; Y holds WRs to 5 a target; both the same against TEs
                r += [dict(defteam=d, week=wk, play_type="pass", sack=0, receiver_player_id="wr1", rusher_player_id=None,
                           yards_gained=15 if d == "X" else 5, complete_pass=1, pass_touchdown=0, rush_touchdown=0,
                           yards_after_catch=4)] * 8
                r += [dict(defteam=d, week=wk, play_type="pass", sack=0, receiver_player_id="te1", rusher_player_id=None,
                           yards_gained=8, complete_pass=1, pass_touchdown=0, rush_touchdown=0, yards_after_catch=3)] * 4
                r += [dict(defteam=d, week=wk, play_type="run", sack=0, receiver_player_id=None, rusher_player_id="rb1",
                           yards_gained=4, complete_pass=0, pass_touchdown=0, rush_touchdown=0, yards_after_catch=0)] * 10
        return pd.DataFrame(r)

    def test_splits_by_position_and_shrinks(self):
        pos_of = pd.Series({"wr1": "WR", "te1": "TE", "rb1": "RB"})
        a = defense.position_allowed(self._pbp(), pos_of)
        self.assertGreater(a.loc["X", "ypt_allowed_WR"], a.loc["Y", "ypt_allowed_WR"])
        self.assertLess(a.loc["X", "ypt_allowed_WR"], 15)                                   # shrunk toward the mean
        self.assertAlmostEqual(a.loc["X", "ypt_allowed_TE"], a.loc["Y", "ypt_allowed_TE"])     # same vs TEs
        self.assertAlmostEqual(a.loc["X", "ypc_allowed_RB"], 4.0)
        self.assertAlmostEqual(a.loc["X", "tgt_pg_allowed_WR"], 8.0)

    def test_every_rb_wr_te_metric_column_is_built(self):
        pos_of = pd.Series({"wr1": "WR", "te1": "TE", "rb1": "RB"})
        cols = set(defense.position_allowed(self._pbp(), pos_of).columns)
        for P in ("RB", "WR", "TE"):
            for c in defense.METRIC_TO_DEFENSE[P].values():
                self.assertIn(c, cols, (P, c))

    def test_missing_inputs_are_safe(self):
        self.assertTrue(defense.position_allowed(None, None).empty)
        self.assertTrue(defense.position_allowed(self._pbp(), pd.Series(dtype=object)).empty)


if __name__ == "__main__":
    unittest.main()
