import datetime as dt
import unittest

from engine import waivers as w

ET = w.ET


def P(pid, pos, value, team="AAA", status=None):
    return {"player_id": pid, "position": pos, "value": value, "team": team, "injury_status": status, "week0": 7, "name": pid}


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


class WaiverRunTest(unittest.TestCase):
    def test_weekly_run_is_next_wednesday_3am_et(self):
        mon = dt.datetime(2026, 10, 19, 14, 0, tzinfo=ET)
        run = w.next_waiver_run({"waiver_day_of_week": 2}, mon)
        self.assertEqual((run.strftime("%a"), run.hour, run.day), ("Wed", 3, 21))

    def test_after_the_run_rolls_to_next_week(self):
        after = dt.datetime(2026, 10, 21, 4, 0, tzinfo=ET)
        self.assertEqual(w.next_waiver_run({"waiver_day_of_week": 2}, after).day, 28)

    def test_daily_waivers(self):
        now = dt.datetime(2026, 10, 19, 14, 0, tzinfo=ET)
        run = w.next_waiver_run({"daily_waivers": 1, "daily_waivers_hour": 5}, now)
        self.assertEqual((run.day, run.hour), (20, 5))

    def test_faab_status(self):
        league = {"settings": {"waiver_type": 2, "waiver_budget": 100, "waiver_day_of_week": 2}}
        rosters = [{"roster_id": 1, "settings": {"waiver_position": 4, "waiver_budget_used": 37}}, {"roster_id": 2}]
        st = w.league_status(league, rosters, 1, dt.datetime(2026, 10, 19, tzinfo=ET))
        self.assertEqual((st["faab_remaining"], st["faab_remaining_pct"], st["priority"], st["teams"]), (63.0, 63.0, 4, 2))

    def test_rolling_has_no_faab(self):
        st = w.league_status({"settings": {"waiver_type": 0}}, [{"roster_id": 1, "settings": {}}], 1)
        self.assertFalse(st["is_faab"])
        self.assertNotIn("faab_remaining", st)


class LineupTest(unittest.TestCase):
    def test_flex_takes_best_leftover(self):
        roster = [P("q", "QB", 20), P("r1", "RB", 15), P("r2", "RB", 12), P("r3", "RB", 11),
                  P("w1", "WR", 14), P("w2", "WR", 9), P("t", "TE", 7)]
        self.assertAlmostEqual(w.lineup_total(SLOTS, roster), 20 + 15 + 12 + 14 + 9 + 7 + 11)

    def test_swap_drops_least_costly_and_reports_gain(self):
        roster = [P("q", "QB", 20), P("r1", "RB", 15), P("r2", "RB", 12), P("r3", "RB", 3),
                  P("w1", "WR", 14), P("w2", "WR", 9), P("t", "TE", 7), P("w3", "WR", 5)]
        drop, gain, _ = w.best_swap(P("new", "TE", 12), roster, SLOTS, True, set(), {}, 7)
        self.assertEqual(drop["player_id"], "r3")
        # new TE starts (12 for 7) and the old TE takes the flex (7 for 5)
        self.assertAlmostEqual(gain, 7.0)

    def test_open_spot_means_no_drop(self):
        roster = [P("q", "QB", 20), P("t", "TE", 7)]
        drop, gain, _ = w.best_swap(P("new", "TE", 12), roster, ["QB", "TE"], False, set(), {}, 7)
        self.assertIsNone(drop)
        self.assertAlmostEqual(gain, 5.0)

    def test_protected_handcuff_not_dropped(self):
        roster = [P("q", "QB", 20), P("r1", "RB", 15), P("cuff", "RB", 2), P("w1", "WR", 4)]
        drop, _, _ = w.best_swap(P("new", "WR", 10), roster, ["QB", "RB", "WR"], True, {"cuff"}, {}, 7)
        self.assertEqual(drop["player_id"], "w1")

    def test_handcuffs_on_own_roster(self):
        depth = {"AAA": {"RB": ["r1", "cuff"]}, "BBB": {"RB": ["x", "y"]}}
        self.assertEqual(w.handcuffs_on([P("r1", "RB", 15), P("cuff", "RB", 2), P("y", "RB", 1)], depth), {"cuff"})


class NeedsTest(unittest.TestCase):
    def test_bye_week_shortage_this_week_is_urgent(self):
        roster = [P("q", "QB", 20), P("r1", "RB", 15, "BYE"), P("r2", "RB", 12), P("w1", "WR", 14), P("w2", "WR", 9),
                  P("w3", "WR", 8), P("t", "TE", 7)]
        n = w.needs(roster, SLOTS, [], 7, {"BYE": 7})
        self.assertEqual(n["RB"]["multiplier"], 1.5)
        self.assertIn("Week 7", n["RB"]["reasons"][0])

    def test_weak_starter_vs_league_median(self):
        mine = [P("q", "QB", 20), P("r1", "RB", 15), P("r2", "RB", 12), P("r3", "RB", 10), P("w1", "WR", 14), P("w2", "WR", 9),
                P("w3", "WR", 8), P("t", "TE", 4), P("t2", "TE", 3)]
        others = [[P("t", "TE", 10)] for _ in range(5)]
        n = w.needs(mine, SLOTS, others, 7, {})
        self.assertGreater(n["TE"]["multiplier"], 1.4)
        self.assertEqual(n["QB"]["multiplier"], 1.0)


class FlagTest(unittest.TestCase):
    def test_td_fluke_is_a_trap(self):
        weeks = [{"week": 1, "fpts": 4, "opp": 3, "td_pts": 0}, {"week": 2, "fpts": 18, "opp": 2, "td_pts": 12}]
        self.assertEqual(w.flag(weeks, {2: 25})[0], "trap")

    def test_volume_surge_with_quiet_box_score_is_breakout(self):
        weeks = [{"week": 1, "fpts": 6, "opp": 5, "td_pts": 0}, {"week": 2, "fpts": 7, "opp": 5, "td_pts": 0},
                 {"week": 3, "fpts": 6.5, "opp": 10, "td_pts": 0}]
        self.assertEqual(w.flag(weeks, {})[0], "breakout")

    def test_real_volume_big_game_is_not_a_trap(self):
        weeks = [{"week": 1, "fpts": 8, "opp": 8, "td_pts": 0}, {"week": 2, "fpts": 24, "opp": 12, "td_pts": 12}]
        self.assertIsNone(w.flag(weeks, {2: 80})[0])


class BidsTest(unittest.TestCase):
    STATUS = {"is_faab": True, "faab_budget": 100.0, "faab_remaining": 20.0}

    def test_tier_follows_score_and_caps_at_remaining(self):
        tiers = w.bid_tiers(85, 1.0, self.STATUS)
        rec = next(t for t in tiers if t["recommended"])
        self.assertEqual(rec["key"], "aggressive")
        self.assertEqual(rec["dollars"], [20.0, 20.0])
        self.assertEqual(next(t for t in w.bid_tiers(40, 1.0, self.STATUS) if t["recommended"])["key"], "floor")

    def test_desperate_need_bumps_tier(self):
        self.assertEqual(next(t for t in w.bid_tiers(66, 1.5, self.STATUS) if t["recommended"])["key"], "aggressive")

    def test_no_bids_without_faab(self):
        self.assertIsNone(w.bid_tiers(90, 1.0, {"is_faab": False}))


if __name__ == "__main__":
    unittest.main()
