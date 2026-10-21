import unittest
from unittest import mock

import pandas as pd

from engine import contingency as c
from engine import ros_projection as ros


def _row(season, week, team, pid, pos, tgt=0, car=0):
    return {"season": season, "week": week, "recent_team": team, "player_id": pid, "position": pos,
            "targets": float(tgt), "carries": float(car)}


def _league(n_teams=6):
    """Each team: WR1 (10 tgt) misses week 5; WR2 6, WR3 4, TE 5, RB 3 tgt + 15 car.
    In week 5 WR2 takes +6, WR3 +2 and a no-role WR4 +2 of WR1's 10 targets."""
    rows = []
    for t in range(n_teams):
        team = f"T{t}"
        for wk in range(1, 7):
            absent = wk == 5
            if not absent:
                rows.append(_row(2025, wk, team, f"{team}w1", "WR", 10))
            rows.append(_row(2025, wk, team, f"{team}w2", "WR", 6 + (6 if absent else 0)))
            rows.append(_row(2025, wk, team, f"{team}w3", "WR", 4 + (2 if absent else 0)))
            if absent:
                rows.append(_row(2025, wk, team, f"{team}w4", "WR", 2))
            rows.append(_row(2025, wk, team, f"{team}te", "TE", 5))
            rows.append(_row(2025, wk, team, f"{team}rb", "RB", 3, 15))
    return pd.DataFrame(rows)


class AbsorptionTests(unittest.TestCase):
    def test_vacated_targets_land_where_they_went(self):
        tab = c.measure_absorption(_league())
        cell = tab[("WR", "targets")]
        self.assertAlmostEqual(cell["WR"], 0.8, places=2)
        self.assertAlmostEqual(cell["new"], 0.2, places=2)
        self.assertAlmostEqual(cell["TE"], 0.0, places=2)
        self.assertEqual(cell["events"], 6)

    def test_fractions_sum_to_one(self):
        cell = c.measure_absorption(_league())[("WR", "targets")]
        self.assertAlmostEqual(sum(cell[k] for k in ("RB", "WR", "TE", "QB", "new")), 1.0, places=6)

    def test_too_few_events_gives_no_cell(self):
        self.assertEqual(c.measure_absorption(_league(n_teams=3)), {})

    def test_two_regulars_missing_is_skipped(self):
        df = _league()
        both = df[~((df["week"] == 5) & df["player_id"].str.endswith("w2"))]
        self.assertNotIn(("WR", "targets"), c.measure_absorption(both))


def _wk():
    rows = []
    for wk in (1, 2, 3, 4):
        if wk != 4:
            rows.append(_row(2026, wk, "AAA", "w1", "WR", 10))
        rows.append(_row(2026, wk, "AAA", "w2", "WR", 6))
        rows.append(_row(2026, wk, "AAA", "w3", "WR", 4))
    return pd.DataFrame(rows)


TABLE = {("WR", "targets"): {"RB": 0.0, "WR": 0.8, "TE": 0.0, "QB": 0.0, "new": 0.2},
         ("WR", "carries"): {"RB": 0.0, "WR": 0.8, "TE": 0.0, "QB": 0.0, "new": 0.2}}
PPO = {"WR": (2.0, 0.5), "TE": (2.0, 0.5)}


class UpliftTests(unittest.TestCase):
    def _go(self, **kw):
        args = dict(wk=_wk(), scoring=None, team="AAA", season=2026, target_id="w2", target_pos="WR",
                    absent_id="w1", absent_pos="WR", baseline=20.0)
        args.update(kw)
        with mock.patch.object(c, "absorption", return_value=TABLE), \
                mock.patch.object(c, "points_per_opportunity", return_value=PPO):
            return c.uplift(**args)

    def test_uplift_matches_hand_calculation(self):
        # w1 share over the last 4 team games with a zero for the missed one = 0.375
        # w2 is 0.375 / (0.375 + 0.25) = 60% of the surviving WR share; 17.5 team targets a game
        # 0.8 x 0.375 x 0.6 x 17.5 = 3.15 targets x 2.0 points
        u = self._go()
        self.assertAlmostEqual(u["targets"], 3.15, places=2)
        self.assertAlmostEqual(u["points"], 6.3, places=2)

    def test_capped_at_half_the_baseline(self):
        self.assertAlmostEqual(self._go(baseline=8.0)["points"], 4.0, places=2)

    def test_different_position_group_gets_nothing_without_share(self):
        self.assertIsNone(self._go(target_id="w9", target_pos="TE"))

    def test_qb_target_or_absent_is_not_modelled(self):
        self.assertIsNone(self._go(target_pos="QB"))
        self.assertIsNone(self._go(absent_pos="QB"))

    def test_absent_player_with_no_recent_role_adds_nothing(self):
        wk = _wk()
        wk = wk[wk["player_id"] != "w1"]
        wk = pd.concat([wk, pd.DataFrame([_row(2026, 4, "AAA", "w1", "WR", 0)])])   # on the roster, never targeted
        self.assertIsNone(self._go(wk=wk))


class ProbabilityTests(unittest.TestCase):
    def test_known_outs_are_certain(self):
        for s in ("Out", "IR", "PUP", "Sus"):
            self.assertEqual(c.p_out(s, None), 1.0)

    def test_questionable_uses_play_chance(self):
        self.assertAlmostEqual(c.p_out("Questionable", 0.7), 0.3)
        self.assertEqual(c.p_out("Questionable", None), 0.0)
        self.assertEqual(c.p_out(None, 0.5), 0.0)


class BlockTests(unittest.TestCase):
    def test_nothing_contingent_gives_none(self):
        self.assertIsNone(ros._contingency_block(0, [], 0.0, None, 10, 1, 1, 1, 1, None))
        self.assertIsNone(ros._contingency_block(1, [{"p_out": 1, "points": 2}], 2.0, None, 10, 1, 1, 1, 1, None))

    def test_dual_numbers(self):
        mate = {"player_id": "x", "name": "X", "position": "WR", "status": "Out", "p_out": 1.0, "points": 2.0}
        pp = {"p_play": 0.6, "basis": "60% played"}
        b = ros._contingency_block(0, [mate], 2.0, pp, 10.0, 1.0, 1.0, 1.0, 1.0, "Questionable")
        self.assertEqual(b["teammates_out"][0]["proj_if_out"], 12.0)
        self.assertEqual(b["teammates_out"][0]["proj_if_plays"], 10.0)
        self.assertEqual(b["self"]["proj_if_out"], 0.0)
        self.assertEqual(b["self"]["proj_if_plays"], 12.0)

    def test_waterfall_carries_teammate_uplift_through_the_multipliers(self):
        w = ros.waterfall(10.0, 1.1, 1.0, 1.0, 1.0, teammates_out=2.0)
        self.assertEqual(w["teammates_out"], 2.0)
        self.assertAlmostEqual(w["final"], 13.2)


if __name__ == "__main__":
    unittest.main()
