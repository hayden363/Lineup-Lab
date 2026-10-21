import unittest

from engine import trade_engine as T

SLOTS = ["QB", "RB", "WR"]


def P(pid, pos, value, trade, bye=None):
    return {"player_id": pid, "name": f"{pid} Player", "position": pos, "value": value, "trade": trade,
            "injury_status": None, "usage": None, "bye": bye}


class GradeMatrixTest(unittest.TestCase):
    def test_elite_win_win(self):
        self.assertEqual(T.grade_trade(100, 2.5, 2.2, []), "A+")

    def test_strong_upgrade(self):
        self.assertEqual(T.grade_trade(100, 1.8, 1.6, []), "A")
        self.assertEqual(T.grade_trade(100, 1.8, 1.1, []), "A-")

    def test_viable_one_side_modest(self):
        self.assertEqual(T.grade_trade(100, 0.6, 1.4, []), "B")
        self.assertEqual(T.grade_trade(100, 0.9, 1.2, []), "B+")

    def test_lateral_churn_is_c(self):
        self.assertEqual(T.grade_trade(100, 0.1, 0.2, []), "C")

    def test_lopsided_paper_value_is_d(self):
        self.assertEqual(T.grade_trade(150, 2.0, 2.0, []), "D")   # TBR 0.67
        self.assertEqual(T.grade_trade(70, 2.0, 2.0, []), "D")    # TBR 1.43

    def test_tier_break_or_opponent_loss_is_f(self):
        self.assertEqual(T.grade_trade(100, 3.0, 3.0, ["tier"]), "F")
        self.assertEqual(T.grade_trade(100, 3.0, -0.5, []), "F")
        self.assertEqual(T.grade_trade(100, 3.0, 3.0, ["insult"]), "F")


class ByeCrashTest(unittest.TestCase):
    def test_trade_that_creates_a_bye_hole_is_caught(self):
        before = [P("q", "QB", 20, 40), P("r1", "RB", 15, 60), P("w1", "WR", 14, 50), P("w2", "WR", 8, 20)]
        # after: their WR depth is traded away and the only WR left is on bye in week 9
        after = [P("q", "QB", 20, 40), P("r1", "RB", 15, 60), P("w1", "WR", 14, 50, bye=9)]
        self.assertEqual(T.bye_crash(before, after, SLOTS, week=5), 9)

    def test_past_bye_is_ignored(self):
        before = [P("q", "QB", 20, 40), P("r1", "RB", 15, 60), P("w1", "WR", 14, 50), P("w2", "WR", 8, 20)]
        after = [P("q", "QB", 20, 40), P("r1", "RB", 15, 60), P("w1", "WR", 14, 50, bye=3)]
        self.assertIsNone(T.bye_crash(before, after, SLOTS, week=5))

    def test_no_new_hole_no_flag(self):
        roster = [P("q", "QB", 20, 40, bye=9), P("r1", "RB", 15, 60), P("w1", "WR", 14, 50)]
        self.assertIsNone(T.bye_crash(roster, roster, SLOTS, week=5))   # already short in week 9 before the trade


class InsultGateTest(unittest.TestCase):
    def test_asking_for_their_best_for_scraps_fails(self):
        me = {"name": "Me", "players": [P("q", "QB", 20, 40), P("r", "RB", 12, 40), P("w", "WR", 12, 35),
                                        P("w2", "WR", 6, 18)], "weak": [], "strong": [], "record": None}
        them = {"name": "Them", "players": [P("Q", "QB", 19, 38), P("R", "RB", 18, 85), P("W", "WR", 10, 30),
                                            P("W2", "WR", 9, 22)], "weak": [], "strong": [], "record": None}
        ctx = {"slots": SLOTS, "profile": "standard", "teams": 12}
        a = T.assess([me["players"][3]], [them["players"][1]], me, them, ctx)
        self.assertFalse(a["gate_audit"]["insult_passed"])
        self.assertIn(a["verdict"]["fairness_grade"], ("D", "F"))
        self.assertEqual(a["verdict"]["status"], "VETOED")


if __name__ == "__main__":
    unittest.main()
