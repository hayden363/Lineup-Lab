"""The 'this week' card: one number, its range, and what moved it."""

import unittest

from engine import profile, tools, waivers


class ExplainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = waivers.load_bundle()
        cls.slate = waivers.target_week(cls.bundle["schedule"])
        cls.pool, _ = waivers.cached_pool(None, cls.bundle)
        cls.byes = {t for t, w in profile.bye_weeks(cls.bundle["schedule"]).items() if w == cls.slate}

    def healthy_wr(self, on_bye):
        wr = self.pool[(self.pool["position"] == "WR") & self.pool["injury_status"].isna() & (self.pool["games"] >= 4)]
        wr = wr[wr["recent_team"].isin(self.byes) == on_bye].sort_values("value", ascending=False)
        return wr.index[0] if len(wr) else None

    def test_range_is_ordered_and_drivers_are_real(self):
        pid = self.healthy_wr(False)
        out = tools.projection_explain(pid)
        self.assertFalse(out["out"])
        self.assertLessEqual(out["floor"], out["typical"])
        self.assertLessEqual(out["typical"], out["ceiling"])
        self.assertGreaterEqual(out["expected"], 0)
        labels = {d["label"] for d in out["drivers"]}
        self.assertIn("Season scoring", labels)
        for d in out["drivers"]:
            self.assertIn(d["direction"], ("up", "down", "flat"))
            # a stated effect must be the model's own multiplier, never an invented one
            if d["label"] == "Usage vs results":
                self.assertIsNone(d["effect_pct"])
        self.assertGreater(out["backtest"]["games"], 10000)

    def test_bye_week_player_has_no_projection(self):
        pid = self.healthy_wr(True)
        if pid is None:
            self.skipTest("no WR on a bye this week")
        out = tools.projection_explain(pid)
        self.assertTrue(out["out"] and out["on_bye"])
        self.assertEqual(out["out_reason"], "bye")
        self.assertNotIn("expected", out)

    def test_unknown_player(self):
        self.assertIsNone(tools.projection_explain("00-0000000"))


if __name__ == "__main__":
    unittest.main()
