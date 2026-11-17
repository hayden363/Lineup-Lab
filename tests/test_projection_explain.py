"""The 'this week' card: one number, its range, and what moved it."""

import unittest

from engine import data, profile, tools, waivers


class ExplainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = waivers.load_bundle()
        cls.slate = waivers.target_week(cls.bundle["schedule"])
        cls.pool, _ = waivers.cached_pool(None, cls.bundle)
        # "On bye" uses the engine's own rule (tools._bye_before_next_game), not just bye == slate week. From
        # Sunday to Tuesday the app's week is one most teams already played, so a team whose bye is NEXT week
        # (next game two weeks out) is also idle: on Tue Nov 17 the "healthy" WR came from SEA (bye wk 11,
        # next game wk 12, slate wk 10) and projection_explain correctly called him out on a bye.
        sched = cls.bundle["schedule"]
        byes = profile.bye_weeks(sched)

        def idle(team):
            _, next_wk = data.next_opponent(sched, team)
            return next_wk is None or tools._bye_before_next_game(byes.get(team), cls.slate, next_wk) is not None
        cls.byes = {t for t in set(sched["home_team"]) | set(sched["away_team"]) if idle(t)}

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
