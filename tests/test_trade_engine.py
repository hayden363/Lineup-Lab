import unittest

from engine import trade_engine as T

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
CTX = {"slots": SLOTS, "profile": "standard", "teams": 12}


def P(pid, pos, value, trade, injury=None):
    return {"player_id": pid, "name": f"{pid} Player", "position": pos, "value": value, "trade": trade,
            "injury_status": injury, "usage": None, "bye": None}


def team(players, wins=2, losses=2, weak=None):
    g = wins + losses
    return {"name": "Them", "players": players, "weak": weak or [], "strong": [],
            "record": {"wins": wins, "losses": losses, "ties": 0, "pct": wins / g if g else None, "text": f"{wins}-{losses}"}}


class MathTest(unittest.TestCase):
    def test_tiers_are_the_shared_pvs_bands(self):
        from engine import pvs
        self.assertEqual([T.tier(v) for v in (95, 80, 79.9, 60, 45, 30, 10)], [1, 1, 2, 2, 3, 4, 5])
        for v in range(0, 101, 5):
            self.assertEqual(T.tier(v), pvs.tier_number(v))

    def test_package_weights_by_league_depth(self):
        self.assertEqual(T.package_weights(2, "standard"), [1.0, 0.8])
        self.assertEqual(T.package_weights(3, "standard"), [1.0, 0.7, 0.5])
        self.assertEqual(T.package_weights(2, "deep"), [1.0, 0.9])
        self.assertAlmostEqual(T.package_weights(2, "shallow")[1], 0.68)

    def test_no_dollar_bill_fallacy_and_cut_cost(self):
        two = [P("a", "WR", 10, 50), P("b", "WR", 10, 50)]
        self.assertEqual(T.effective_value(two, "standard"), 90.0)
        self.assertEqual(T.effective_value(two, "standard", extra_bodies=1, v_cut=6), 84.0)

    def test_fairness_bands(self):
        self.assertEqual([T.fairness_band(x) for x in (80, 90, 100, 110, 120)],
                         ["underpay", "slight_underpay", "fair", "slight_overpay", "overpay"])

    def test_depth_profile(self):
        self.assertEqual(T.depth_profile({"teams": 12, "starters": 10}), "deep")
        self.assertEqual(T.depth_profile({"teams": 10, "starters": 9}), "shallow")

    def test_script_length_caps(self):
        self.assertTrue(T._cap("word " * 50, 30).count(" ") <= 30)
        self.assertEqual(T._last("Kenneth Walker III"), "Walker")


class AssessTest(unittest.TestCase):
    def setUp(self):
        # Me: deep at WR, weak at TE. Them: weak WR2, spare TE on the bench.
        self.me = team([P("q", "QB", 20, 40), P("r1", "RB", 15, 70), P("r2", "RB", 13, 55), P("w1", "WR", 16, 75),
                        P("w2", "WR", 14, 60), P("w3", "WR", 13, 52), P("w4", "WR", 12, 35), P("t", "TE", 5, 8),
                        P("bn", "RB", 4, 3)], 1, 3)
        self.them = team([P("Q", "QB", 19, 38), P("R1", "RB", 16, 72), P("R2", "RB", 14, 58), P("W1", "WR", 15, 66),
                          P("W2", "WR", 6, 12), P("T", "TE", 17, 70), P("T2", "TE", 12, 50), P("R3", "RB", 12, 30),
                          P("BN", "WR", 3, 2)], 2, 2, weak=["WR2"])

    def test_mutual_upgrade_approved(self):
        a = T.assess([self.me["players"][5]], [self.them["players"][6]], self.me, self.them, CTX)
        self.assertEqual(a["verdict"]["status"], "APPROVED", a["verdict"]["summary_reason"])
        self.assertGreaterEqual(float(a["quantitative_breakdown"]["opponent_starting_delta_ppg"]), 1.5)
        self.assertTrue(all(a["gate_audit"].values()))
        self.assertEqual(set(a["negotiation_scripts"]), {"casual_manager", "quantitative_analyst",
                                                         "skeptical_manager", "desperate_manager"})

    def test_star_for_scrub_is_dead(self):
        a = T.assess([P("bn", "RB", 4, 3)], [self.them["players"][5]], self.me, self.them, CTX)
        self.assertEqual(a["verdict"]["status"], "VETOED")
        self.assertFalse(a["gate_audit"]["fairness_passed"])
        self.assertIn("fairness index", a["verdict"]["summary_reason"])

    def test_tier_break_two_mids_for_a_star(self):
        star = P("S", "RB", 22, 95)
        them = team(self.them["players"] + [star], 1, 3)
        a = T.assess([P("m1", "WR", 12, 45), P("m2", "WR", 12, 45)], [star],
                     team(self.me["players"] + [P("m1", "WR", 12, 45), P("m2", "WR", 12, 45)], 1, 3), them, CTX)
        self.assertFalse(a["gate_audit"]["tier_break_passed"])

    def test_opponent_must_gain_starting_points(self):
        # Their bench TE for my WR4, who wouldn't start for them either.
        a = T.assess([self.me["players"][6]], [self.them["players"][7]], self.me, self.them, CTX)
        self.assertFalse(a["gate_audit"]["lineup_delta_passed"])

    def test_contender_wont_sell_stud_for_depth(self):
        them = dict(self.them, record={"wins": 4, "losses": 0, "ties": 0, "pct": 1.0, "text": "4-0"})
        a = T.assess([self.me["players"][5], self.me["players"][6]], [self.them["players"][5]], self.me, them, CTX)
        self.assertFalse(a["gate_audit"]["incentive_passed"])

    def test_extra_body_cuts_a_bench_player(self):
        roster, cut = T.after_trade(self.them["players"], {"T"}, [self.me["players"][4], self.me["players"][5]], SLOTS)
        self.assertEqual([p["player_id"] for p in cut], ["BN"])
        self.assertEqual(len(roster), len(self.them["players"]))

    def test_three_for_one_blocked_in_small_league(self):
        give = self.me["players"][4:7]
        a = T.assess(give, [self.them["players"][5]], self.me, self.them, dict(CTX, teams=10))
        self.assertFalse(a["gate_audit"]["roster_fit_passed"])


class FinderTest(unittest.TestCase):
    def test_only_approved_spread_out_and_shopped(self):
        me = AssessTest()
        me.setUp()
        rosters = {1: dict(me.me, name="Me")}
        for rid in range(2, 6):
            t = team([dict(p, player_id=f"{p['player_id']}{rid}") for p in me.them["players"]], 2, 2, weak=["WR2"])
            rosters[rid] = dict(t, name=f"T{rid}")
        out = T.find_trades(rosters, 1, CTX, max_suggestions=10, fair_first=False)
        self.assertTrue(out)
        per_opp = {}
        for s in out:
            per_opp[s["opponent_roster_id"]] = per_opp.get(s["opponent_roster_id"], 0) + 1
            self.assertEqual(s["analysis"]["verdict"]["status"], "APPROVED")
        self.assertTrue(all(n <= 2 for n in per_opp.values()))
        shopped = T.find_trades(rosters, 1, CTX, give_ids=["w3"])
        self.assertTrue(all(any(p["player_id"] == "w3" for p in s["you_give"]) for s in shopped))
        # the fair-first list is every even trade, not capped per opponent
        mixed = T.find_trades(rosters, 1, CTX, max_suggestions=10)
        self.assertTrue(all(s["kind"] in ("fair", "approved") for s in mixed))


class AcquireTest(unittest.TestCase):
    """find_trades(want_ids=...): every suggestion lands the player you named, from the team that owns him."""

    def rosters(self):
        me = AssessTest()
        me.setUp()
        rosters = {1: dict(me.me, name="Me")}
        for rid in range(2, 5):
            t = team([dict(p, player_id=f"{p['player_id']}{rid}") for p in me.them["players"]], 2, 2, weak=["WR2"])
            rosters[rid] = dict(t, name=f"T{rid}")
        return rosters

    def test_every_suggestion_lands_the_wanted_player_from_his_owner(self):
        out = T.find_trades(self.rosters(), 1, CTX, want_ids=["T3"], max_suggestions=6)
        self.assertTrue(out)
        for s in out:
            self.assertEqual(s["opponent_roster_id"], 3)
            self.assertIn("T3", [p["player_id"] for p in s["you_get"]])

    def test_a_player_nobody_else_owns_returns_nothing(self):
        self.assertEqual(T.find_trades(self.rosters(), 1, CTX, want_ids=["ghost"]), [])

    def test_your_own_player_cannot_be_the_target(self):
        self.assertEqual(T.find_trades(self.rosters(), 1, CTX, want_ids=["w1"]), [])

    def test_a_target_outside_the_top_candidates_is_still_considered(self):
        rosters = self.rosters()
        rosters[2]["players"].append(P("deep", "WR", 9, 20))
        out = T.find_trades(rosters, 1, CTX, want_ids=["deep"], fair_first=False, max_suggestions=6)
        self.assertTrue(all("deep" in [p["player_id"] for p in s["you_get"]] for s in out))


if __name__ == "__main__":
    unittest.main()


class TradeValueTest(unittest.TestCase):
    """trade_values() must keep real gaps between players and follow the league's PVS."""

    @staticmethod
    def _pool():
        import pandas as pd
        rows = [("a", "RB", 20.0), ("b", "RB", 19.9), ("c", "WR", 14.0), ("d", "WR", 13.9), ("e", "QB", 18.0),
                ("f", "TE", 8.0),
                ("xr", "RB", 6.0), ("xw", "WR", 6.0), ("xq", "QB", 6.0), ("xt", "TE", 3.0)]   # free agents
        return pd.DataFrame({"player_display_name": [f"{r[0]} Player" for r in rows],
                             "position": [r[1] for r in rows], "value": [r[2] for r in rows]},
                            index=[r[0] for r in rows])

    ROSTERED = {"a", "b", "c", "d", "e", "f"}
    SHAPE = {"teams": 12, "slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 0}}

    def test_fallback_keeps_gaps_instead_of_flat_rank_steps(self):
        v = T.trade_values(self._pool(), self.SHAPE, self.ROSTERED, ecr={})
        # 0.1 PPG apart is nearly the same price, 6 PPG apart is not (a rank curve would charge the same step for both)
        self.assertLess(v["a"]["trade"] - v["b"]["trade"], 3)
        self.assertGreater(v["b"]["trade"] - v["c"]["trade"], 10)

    def test_uses_league_pvs_when_given(self):
        pvs = {"a": 90.0, "b": 70.0, "c": 50.0, "d": 30.0, "e": 85.0, "f": 10.0, "xr": 5.0, "xw": 4.0, "xq": 3.0, "xt": 2.0}
        v = T.trade_values(self._pool(), self.SHAPE, self.ROSTERED, ecr={}, pvs_by_id=pvs)
        self.assertEqual({k: x["trade"] for k, x in v.items()}, pvs)
        self.assertEqual(v["e"]["tier"], 1)
        self.assertEqual(v["f"]["tier"], 5)
        self.assertEqual(v["e"]["rank"], 2)

    def test_superflex_pvs_changes_the_quarterback_price(self):
        one_qb = T.trade_values(self._pool(), self.SHAPE, None, ecr={}, pvs_by_id={"a": 90, "b": 70, "c": 50, "d": 30, "e": 40, "f": 10, "xr": 5, "xw": 4, "xq": 3, "xt": 2})
        superflex = T.trade_values(self._pool(), self.SHAPE, None, ecr={}, pvs_by_id={"a": 90, "b": 70, "c": 50, "d": 30, "e": 75, "f": 10, "xr": 5, "xw": 4, "xq": 3, "xt": 2})
        self.assertGreater(superflex["e"]["trade"], one_qb["e"]["trade"])
        self.assertLess(superflex["e"]["rank"], one_qb["e"]["rank"])

    def test_missing_pvs_for_a_player_falls_back_not_crashes(self):
        v = T.trade_values(self._pool(), self.SHAPE, self.ROSTERED, ecr={}, pvs_by_id={"a": 90.0})
        self.assertEqual(set(v), {"a", "b", "c", "d", "e", "f", "xr", "xw", "xq", "xt"})
        self.assertTrue(all(0 <= x["trade"] <= 100 for x in v.values()))

    def test_expert_rank_nudges_by_thirty_percent(self):
        import pandas as pd
        pool = self._pool()
        pvs = {"a": 90.0, "b": 70.0, "c": 50.0, "d": 30.0, "e": 20.0, "f": 10.0, "xr": 5.0, "xw": 4.0, "xq": 3.0, "xt": 2.0}
        from engine import consensus
        key = consensus.match_key("f Player", "TE")
        v = T.trade_values(pool, self.SHAPE, self.ROSTERED, ecr={key: {"ecr": 1}}, pvs_by_id=pvs)
        # experts have him 1st -> blends toward the top slot's PVS (90): 0.7*10 + 0.3*90
        self.assertAlmostEqual(v["f"]["trade"], 34.0, places=1)
        self.assertEqual(v["a"]["trade"], 90.0)
