import unittest
from unittest import mock

from engine import lineup_advisor as la


def P(name, pos, proj, p10=None, p90=None, team="AAA", out=False):
    o = {"mean": proj, "p10": p10 if p10 is not None else proj * 0.5, "p50": proj,
         "p90": p90 if p90 is not None else proj * 1.5}
    if out:
        o["out"] = True
    return {"name": name, "position": pos, "team": team, "PROJ": proj, "outcomes": o}


class AdvisorTests(unittest.TestCase):
    def run_advise(self, slots, starters, players, mode="balanced", locked=(), no_game=()):
        with mock.patch.object(la.locks, "kickoff", side_effect=lambda s, team, wk: None if team in no_game else 1), \
             mock.patch.object(la.locks, "is_locked", side_effect=lambda s, team, wk, now=None: team in locked):
            return la.advise(slots, starters, players, None, 1, mode)

    def test_flex_overlap_that_greedy_gets_wrong(self):
        # WRRB_FLEX and REC_FLEX: the exact solver puts the RB in the first flex
        # and the second-best WR in the second, instead of burning a WR on flex one.
        slots = ["WR", "WRRB_FLEX", "REC_FLEX"]
        players = {
            "w1": P("W1", "WR", 20), "w2": P("W2", "WR", 15), "r1": P("R1", "RB", 12),
            "t1": P("T1", "TE", 4),
        }
        out = self.run_advise(slots, ["w1", "w2", "t1"], players)
        self.assertEqual(sorted(x for x in out["chosen"] if x), ["r1", "w1", "w2"])
        self.assertEqual(len(set(out["chosen"])), 3)

    def test_no_player_started_twice(self):
        slots = ["QB", "SUPER_FLEX", "RB"]
        players = {"q1": P("Q1", "QB", 22), "q2": P("Q2", "QB", 18), "r1": P("R1", "RB", 14)}
        out = self.run_advise(slots, ["q1", "r1", None], players)
        self.assertEqual(len(set(out["chosen"])), 3)
        self.assertIn("q2", out["chosen"])

    def test_locked_slot_keeps_occupant(self):
        slots = ["WR", "WR"]
        players = {"a": P("A", "WR", 5, team="LCK"), "b": P("B", "WR", 9), "c": P("C", "WR", 12)}
        out = self.run_advise(slots, ["a", "b"], players, locked={"LCK"})
        self.assertEqual(out["chosen"][0], "a")
        self.assertEqual(out["chosen"][1], "c")

    def test_out_and_bye_players_are_worth_zero(self):
        slots = ["RB", "RB"]
        players = {"hurt": P("Hurt", "RB", 18, out=True), "bye": P("Bye", "RB", 17, team="BYE"),
                   "a": P("A", "RB", 8), "b": P("B", "RB", 7)}
        out = self.run_advise(slots, ["hurt", "bye"], players, no_game={"BYE"})
        self.assertEqual(sorted(out["chosen"]), ["a", "b"])
        self.assertGreater(out["best_mean"], out["current_mean"])

    def test_safe_mode_prefers_the_higher_floor(self):
        slots = ["WR"]
        players = {"boom": P("Boom", "WR", 12, p10=2, p90=30), "steady": P("Steady", "WR", 11, p10=8, p90=15)}
        self.assertEqual(self.run_advise(slots, ["boom"], players, mode="safe")["chosen"], ["steady"])
        self.assertEqual(self.run_advise(slots, ["steady"], players, mode="upside")["chosen"], ["boom"])

    def test_defense_without_outcomes_uses_proj(self):
        slots = ["DEF"]
        players = {"d1": {"name": "D1", "position": "DEF", "team": "AAA", "PROJ": 8.0},
                   "d2": {"name": "D2", "position": "DEF", "team": "AAA", "PROJ": 5.0}}
        self.assertEqual(self.run_advise(slots, ["d2"], players)["chosen"], ["d1"])

    def test_already_best_has_no_changes(self):
        slots = ["QB", "RB"]
        players = {"q": P("Q", "QB", 20), "r": P("R", "RB", 10), "b": P("B", "RB", 3)}
        out = self.run_advise(slots, ["q", "r"], players)
        self.assertEqual(out["changes"], [])
        self.assertEqual(out["current_mode_value"], out["best_mode_value"])


if __name__ == "__main__":
    unittest.main()
