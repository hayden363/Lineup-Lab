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


if __name__ == "__main__":
    unittest.main()
