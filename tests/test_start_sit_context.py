import unittest
import pandas as pd
from engine import context as C


def sched(spread, total, home="SF", away="WAS", wind=None, roof="outdoors"):
    return pd.DataFrame([{"week": 6, "game_type": "REG", "home_team": home, "away_team": away,
                          "spread_line": spread, "total_line": total, "roof": roof, "wind": wind,
                          "temp": None, "gameday": "2026-10-19", "gametime": "20:15"}])


class ContextTests(unittest.TestCase):
    def test_implied_totals(self):
        h = C.game_context(sched(7.5, 52.5), "SF", 6)
        a = C.game_context(sched(7.5, 52.5), "WAS", 6)
        self.assertEqual(h["implied_total"], 30.0)
        self.assertEqual(a["implied_total"], 22.5)
        self.assertEqual(a["margin"], -7.5)

    def test_missing_lines_no_adjustment(self):
        ctx = C.game_context(sched(None, None), "SF", 6)
        self.assertIsNone(ctx["implied_total"])
        self.assertEqual(C.environment_factor("WR", ctx)[0], 1.0)
        self.assertEqual(C.environment_factor("WR", None)[0], 1.0)

    def test_factor_capped(self):
        ctx = C.game_context(sched(20, 80), "SF", 6)
        for pos in ("QB", "RB", "WR", "TE"):
            self.assertLessEqual(C.environment_factor(pos, ctx)[0], 1.10)
        self.assertGreaterEqual(C.environment_factor("RB", C.game_context(sched(20, 30), "WAS", 6))[0], 0.90)

    def test_script_direction(self):
        ctx = C.game_context(sched(10, 45), "WAS", 6)  # WAS big underdog
        self.assertGreater(C.environment_factor("WR", ctx)[0], C.environment_factor("RB", ctx)[0])
        self.assertGreater(C.environment_factor("RB", ctx, 5)[0], C.environment_factor("RB", ctx, 20)[0] - 1)  # sanity
        self.assertGreater(C.environment_factor("RB", ctx, 20)[0], C.environment_factor("RB", ctx, 5)[0])

    def test_wind(self):
        ctx = C.game_context(sched(0, 45, wind=25), "SF", 6)
        self.assertLess(C.environment_factor("QB", ctx)[0], C.environment_factor("RB", ctx)[0])

    def test_modes(self):
        self.assertEqual(C.rank_value(10, 4, 20, "balanced"), 10)
        self.assertEqual(C.rank_value(10, 4, 20, "safe"), 7)
        self.assertEqual(C.rank_value(10, 4, 20, "upside"), 15)

    def test_usage_trend(self):
        rows = [{"player_id": "a", "week": w, "targets": t, "carries": 0, "attempts": 0}
                for w, t in enumerate([4, 4, 5, 9, 10, 11], 1)]
        u = C.usage_trend(pd.DataFrame(rows), "a", "WR")
        self.assertEqual(u["label"], "rising")
        self.assertIsNone(C.usage_trend(pd.DataFrame(rows[:3]), "a", "WR"))

    def test_reasons_and_summary(self):
        r = {"opponent": "WAS", "matchup_tag": "soft", "matchup_factor": 1.1, "PROJ": 10, "floor": 8, "ceiling": 14,
             "environment": {"notes": ["Indoors"]}, "usage": None}
        out = C.build_reasons(r)
        self.assertTrue(out[0].startswith("Soft matchup"))
        self.assertIn("Safe floor (8.0)", out)
        a = {"player_display_name": "A", "PROJ": 12, "rank_value": 12}
        b = {"player_display_name": "B", "PROJ": 10, "rank_value": 10}
        self.assertIn("12.0 vs 10.0", C.comparison_reason(a, [b], "balanced"))


if __name__ == "__main__":
    unittest.main()
