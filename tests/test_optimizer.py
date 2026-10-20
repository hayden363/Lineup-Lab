import itertools
import random
import unittest

from engine import lineup as L, optimizer


def P(pid, pos, v):
    return {"player_id": pid, "position": pos, "value": v}


def brute(slots, players):
    """Reference answer: try every way to give each slot a distinct player
    (or nobody), keep the best total among the fullest lineups."""
    best = (-1, float("-inf"))
    opts = [[None] + [p for p in players if L.eligible(s, p["position"])] for s in slots]
    for combo in itertools.product(*opts):
        ids = [c["player_id"] for c in combo if c]
        if len(ids) != len(set(ids)):
            continue
        best = max(best, (len(ids), sum(c["value"] for c in combo if c)))
    return best


def greedy(slots, players):
    order = sorted(slots, key=lambda s: len(L.ELIGIBLE.get(s, {s})))
    used, total = set(), 0.0
    for slot in order:
        pool = [p for p in players if p["player_id"] not in used and L.eligible(slot, p["position"])]
        if pool:
            b = max(pool, key=lambda p: p["value"])
            used.add(b["player_id"])
            total += b["value"]
    return total


class OptimizerTests(unittest.TestCase):
    def run_opt(self, slots, players):
        return optimizer.best_assignment(slots, players, L.eligible)

    def test_overlapping_flex_beats_greedy(self):
        # WR/RB flex and WR/TE flex overlap on WR: greedy gives the WR to the
        # first flex and leaves the TE flex with a 1-point TE.
        slots = ["WRRB_FLEX", "REC_FLEX"]
        players = [P("wr", "WR", 10), P("rb", "RB", 9), P("te", "TE", 1)]
        self.assertEqual(greedy(slots, players), 11)
        total, chosen = self.run_opt(slots, players)
        self.assertEqual(total, 19)
        self.assertEqual([c["player_id"] for c in chosen], ["rb", "wr"])

    def test_matches_brute_force_on_random_rosters(self):
        rng = random.Random(7)
        layouts = [
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
            ["QB", "RB", "WR", "TE", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"],
            ["RB", "WR", "WR", "FLEX", "FLEX", "TE"],
            ["QB", "RB/WR", "WR/TE", "OP"],
        ]
        for _ in range(150):
            slots = rng.choice(layouts)
            players = [P(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]), round(rng.uniform(0, 25), 1))
                       for i in range(rng.randint(3, 9))]
            fill, best = brute(slots, players)
            total, chosen = self.run_opt(slots, players)
            self.assertEqual(sum(1 for c in chosen if c), fill, (slots, players))
            self.assertAlmostEqual(total, best, places=6, msg=(slots, players))

    def test_never_worse_than_greedy(self):
        rng = random.Random(11)
        slots = ["QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX", "REC_FLEX"]
        for _ in range(100):
            players = [P(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]), round(rng.uniform(0, 25), 1))
                       for i in range(rng.randint(8, 20))]
            self.assertGreaterEqual(self.run_opt(slots, players)[0] + 1e-9, greedy(slots, players))

    def test_slot_with_no_eligible_player_stays_empty(self):
        total, chosen = self.run_opt(["QB", "RB"], [P("rb", "RB", 5)])
        self.assertEqual(chosen[0], None)
        self.assertEqual(chosen[1]["player_id"], "rb")
        self.assertEqual(total, 5)

    def test_zero_value_player_still_fills_a_slot(self):
        total, chosen = self.run_opt(["RB"], [P("rb", "RB", 0.0)])
        self.assertEqual(chosen[0]["player_id"], "rb")
        self.assertEqual(total, 0.0)

    def test_more_slots_than_players_and_empty_inputs(self):
        total, chosen = self.run_opt(["RB", "WR", "TE"], [P("rb", "RB", 4)])
        self.assertEqual([bool(c) for c in chosen], [True, False, False])
        self.assertEqual(self.run_opt([], [P("rb", "RB", 4)]), (0.0, []))
        self.assertEqual(self.run_opt(["RB"], []), (0.0, [None]))

    def test_player_used_once(self):
        _, chosen = self.run_opt(["RB", "FLEX"], [P("rb", "RB", 9), P("wr", "WR", 3)])
        ids = [c["player_id"] for c in chosen]
        self.assertEqual(sorted(ids), ["rb", "wr"])


if __name__ == "__main__":
    unittest.main()
