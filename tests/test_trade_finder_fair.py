"""The finder lists every dead-even trade first, even one that helps neither lineup."""

import unittest

from engine import trade_engine as T

SLOTS = ["QB", "RB", "WR"]


def P(pid, pos, value, trade):
    return {"player_id": pid, "name": f"{pid} Player", "position": pos, "value": value, "trade": trade,
            "injury_status": None, "usage": None, "bye": None}


def league():
    mine = [P("mq", "QB", 20, 70), P("mrb", "RB", 16, 60), P("mw", "WR", 12, 45), P("mw2", "WR", 9, 30)]
    theirs = [P("tq", "QB", 19, 66), P("trb", "RB", 11, 40), P("tw", "WR", 15, 60), P("tw2", "WR", 8, 28)]
    rosters = {1: {"name": "Me", "players": mine, "record": {"text": "3-3", "pct": 0.5}},
               2: {"name": "Them", "players": theirs, "record": {"text": "3-3", "pct": 0.5}}}
    T.annotate(rosters, SLOTS)
    ctx = {"slots": SLOTS, "profile": "balanced", "teams": 12, "starters": 3, "week": None}
    return rosters, ctx


class FairFirstTests(unittest.TestCase):
    def test_even_trade_that_helps_nobody_is_listed_first(self):
        rosters, ctx = league()
        found = T.find_trades(rosters, 1, ctx)
        fair = [f for f in found if f["kind"] == "fair"]
        self.assertTrue(fair, "a 60-for-60 swap is dead even and must be offered")
        self.assertEqual(found[0]["kind"], "fair")
        for f in fair:
            self.assertTrue(95 <= f["analysis"]["quantitative_breakdown"]["fairness_index"] <= 105)

    def test_uneven_trade_is_not_fair(self):
        rosters, ctx = league()
        me, opp = rosters[1], rosters[2]
        give, get = [me["players"][3]], [opp["players"][2]]   # 30 for 60
        self.assertIsNone(T.assess(give, get, me, opp, ctx, full=False, fair=True))

    def test_fair_mode_ignores_lineup_gate(self):
        rosters, ctx = league()
        me, opp = rosters[1], rosters[2]
        a = T.assess([me["players"][1]], [opp["players"][2]], me, opp, ctx, full=True, fair=True)
        self.assertNotIn("lineup", [k for k, v in a["gate_audit"].items() if v is False])
        self.assertIsNone(a["gate_audit"]["lineup_delta_passed"])   # shown as "not required", not as a pass

    def test_off_switch_restores_gated_results(self):
        rosters, ctx = league()
        self.assertFalse([f for f in T.find_trades(rosters, 1, ctx, fair_first=False) if f.get("kind") == "fair"])


if __name__ == "__main__":
    unittest.main()
