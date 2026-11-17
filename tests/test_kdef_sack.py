"""DEF/ST projection: the opposing offense's sack rate allowed (owner 2026-11-17; analysis/kdef_adv_backtest.py)."""
import unittest

import pandas as pd

from engine import kdef_model as K


def _pbp():
    rows = []
    for team, sacks in (("SACKY", 12), ("CLEAN", 2)):
        rows += [dict(posteam=team, qb_dropback=1, sack=1)] * sacks + [dict(posteam=team, qb_dropback=1, sack=0)] * (100 - sacks)
        rows += [dict(posteam=team, qb_dropback=0, sack=0)] * 50
    return pd.DataFrame(rows)


class SackTests(unittest.TestCase):
    def test_ratio_is_shrunk_and_ordered(self):
        p = _pbp()
        a, b = K.offense_sack_ratio(p, "SACKY"), K.offense_sack_ratio(p, "CLEAN")
        self.assertGreater(a, 1.0)
        self.assertLess(b, 1.0)
        self.assertLess(a, 12 / 7)                    # raw ratio is 12% vs 7% league: shrunk below that
        self.assertIsNone(K.offense_sack_ratio(None, "SACKY"))
        self.assertIsNone(K.offense_sack_ratio(p, ""))

    def test_more_sacks_allowed_means_more_defense_points(self):
        hi = K.defense_projection(7.0, 6.0, 22.0, 1.3)
        mid = K.defense_projection(7.0, 6.0, 22.0, None)
        lo = K.defense_projection(7.0, 6.0, 22.0, 0.7)
        self.assertGreater(hi, mid)
        self.assertGreater(mid, lo)
        self.assertEqual(mid, K.defense_projection(7.0, 6.0, 22.0, 1.0))   # missing = league average

    def test_context_names_the_opponent(self):
        sched = pd.DataFrame([dict(week=11, home_team="SEA", away_team="ARI", spread_line=3.0, total_line=44.0,
                                   roof="outdoors", home_score=None)])
        self.assertEqual(K.game_context(sched, "SEA", 11)["opp"], "ARI")
        self.assertEqual(K.game_context(sched, "ARI", 11)["opp"], "SEA")


if __name__ == "__main__":
    unittest.main()
