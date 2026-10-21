import unittest
from engine import league_trades as T

TX = {"type": "trade", "status": "complete", "transaction_id": "t1", "leg": 6, "status_updated": 1000,
      "roster_ids": [1, 2], "adds": {"A": 1, "B": 2}, "drops": {"A": 2, "B": 1},
      "draft_picks": [{"season": "2027", "round": 2, "owner_id": 1, "previous_owner_id": 2}]}
NAMES = {1: "Alpha", 2: "Bravo"}


def nm(pid):
    return {"A": "Player A", "B": "Player B"}.get(pid, pid)


class TradeTests(unittest.TestCase):
    def test_two_sided_summary(self):
        t = T.parse_trade(TX, NAMES, nm)
        a = next(s for s in t["sides"] if s["roster_id"] == 1)
        b = next(s for s in t["sides"] if s["roster_id"] == 2)
        self.assertEqual([x["name"] for x in a["receives"]], ["Player A", "2027 round 2 pick"])
        self.assertEqual([x["name"] for x in a["gives"]], ["Player B"])
        self.assertEqual([x["name"] for x in b["gives"]], ["Player A", "2027 round 2 pick"])
        self.assertEqual(t["week"], 6)

    def test_ignores_waivers_and_unfinished(self):
        self.assertIsNone(T.parse_trade({**TX, "type": "waiver"}, NAMES, nm))
        self.assertIsNone(T.parse_trade({**TX, "status": "failed"}, NAMES, nm))

    def test_new_trades_filter(self):
        t = T.parse_trade(TX, NAMES, nm)
        self.assertEqual(T.new_trades([t], []), [t])
        self.assertEqual(T.new_trades([t], ["t1"]), [])


class EspnTradeTests(unittest.TestCase):
    class _Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def act(self, date, actions):
        return self._Obj(date=date, actions=actions)

    def test_two_team_trade_fills_both_sides(self):
        ta, tb = self._Obj(team_id=1, team_name="A"), self._Obj(team_id=2, team_name="B")
        p1, p2 = self._Obj(playerId=11, name="One"), self._Obj(playerId=22, name="Two")
        trades = T.parse_espn_trades([self.act(5, [(ta, "TRADED", p2, 0), (tb, "TRADED", p1, 0)])])
        self.assertEqual(len(trades), 1)
        a = next(s for s in trades[0]["sides"] if s["roster_id"] == 1)
        self.assertEqual([x["name"] for x in a["receives"]], ["Two"])
        self.assertEqual([x["name"] for x in a["gives"]], ["One"])

    def test_ignores_non_trades_and_one_sided(self):
        ta = self._Obj(team_id=1, team_name="A")
        p = self._Obj(playerId=1, name="X")
        self.assertEqual(T.parse_espn_trades([self.act(1, [(ta, "FA ADDED", p, 0)])]), [])
        self.assertEqual(T.parse_espn_trades([self.act(1, [(ta, "TRADED", p, 0)])]), [])

    def test_three_team_trade_does_not_guess_gives(self):
        teams = [self._Obj(team_id=i, team_name=str(i)) for i in (1, 2, 3)]
        acts = [(t, "TRADED", self._Obj(playerId=i, name=f"P{i}"), 0) for i, t in enumerate(teams)]
        trade = T.parse_espn_trades([self.act(1, acts)])[0]
        self.assertTrue(all(s["gives"] == [] for s in trade["sides"]))


class EspnPendingTests(unittest.TestCase):
    PENDING = [{"id": "x1", "type": "TRADE_ACCEPT", "acceptedDate": 5, "processDate": 9,
                "teamActions": {"12": "ACCEPTED", "11": "ACCEPTED", "10": "VETOED", "6": "APPROVED", "1": "VETOED", "2": "APPROVED"},
                "items": [{"type": "TRADE", "playerId": 1, "fromTeamId": 12, "toTeamId": 11},
                          {"type": "TRADE", "playerId": 2, "fromTeamId": 11, "toTeamId": 12}]}]

    def test_sides_and_votes(self):
        (t,) = T.parse_espn_pending(self.PENDING, {11: "Eleven", 12: "Twelve"}, lambda pid: f"P{pid}")
        a = next(s for s in t["sides"] if s["roster_id"] == 11)
        self.assertEqual([x["name"] for x in a["receives"]], ["P1"])
        self.assertEqual([x["name"] for x in a["gives"]], ["P2"])
        self.assertEqual(t["status"], "Under league review")
        self.assertEqual(t["votes"], {"approved": 2, "vetoed": 2, "accepted": 2})

    def test_unaccepted_proposal_has_no_votes(self):
        p = [{**self.PENDING[0], "type": "TRADE_PROPOSAL"}]
        (t,) = T.parse_espn_pending(p, {}, str)
        self.assertEqual(t["status"], "Proposed")
        self.assertIsNone(t["votes"])

    def test_ignores_non_trades(self):
        self.assertEqual(T.parse_espn_pending([{"type": "WAIVER", "items": []}], {}, str), [])


if __name__ == "__main__":
    unittest.main()
