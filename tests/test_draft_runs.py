import unittest
from unittest import mock

import pandas as pd

from engine import draft_runs, tools


def picks(*positions):
    return [{"position": p} for p in positions]


class RunPositionTests(unittest.TestCase):
    def test_four_of_last_eight_is_a_run(self):
        self.assertEqual(draft_runs.run_positions(picks("RB", "WR", "RB", "RB", "QB", "RB", "WR", "TE")), ["RB"])

    def test_three_is_not_a_run(self):
        self.assertEqual(draft_runs.run_positions(picks("RB", "WR", "RB", "RB", "QB", "WR", "WR", "TE")), [])

    def test_old_picks_age_out_of_the_window(self):
        # four RBs, then eight picks that aren't RBs: the run is over
        self.assertEqual(draft_runs.run_positions(picks("RB", "RB", "RB", "RB", "WR", "TE", "QB", "WR", "TE", "QB", "WR", "TE")), [])

    def test_two_positions_can_both_run(self):
        self.assertEqual(draft_runs.run_positions(picks("RB", "WR", "RB", "WR", "RB", "WR", "RB", "WR")), ["RB", "WR"])

    def test_short_draft_and_missing_position(self):
        self.assertEqual(draft_runs.run_positions([]), [])
        self.assertEqual(draft_runs.run_positions([{"position": None}] * 8), [])


def board(*rows):
    return pd.DataFrame(
        [{"player_display_name": n, "recent_team": "KC", "headshot_url": None, "SCORE": s, "fpts_per_game": 10.0}
         for _, n, s in rows], index=[pid for pid, _, _ in rows])


class DraftBoardRunTests(unittest.TestCase):
    def run_board(self, pick_positions):
        draft = {"league_id": None, "status": "drafting", "type": "snake", "season": "2026",
                 "settings": {"teams": 2, "rounds": 10}, "slot_to_roster_id": {"1": 1, "2": 2}}
        raw = [{"pick_no": i + 1, "round": 1, "roster_id": 1 + (i % 2), "player_id": f"x{i}",
                "metadata": {"position": pos, "first_name": "A", "last_name": str(i), "team": "KC"}}
               for i, pos in enumerate(pick_positions)]
        boards = {"QB": board(("q1", "Q", 50.0)), "RB": board(("r1", "R", 50.0)),
                  "WR": board(("w1", "W", 50.0)), "TE": board(("t1", "T", 50.0))}
        with mock.patch.object(tools.sleeper, "get_draft", return_value=draft), \
                mock.patch.object(tools.sleeper, "get_draft_picks", return_value=raw), \
                mock.patch.object(tools.sleeper, "id_crosswalk", return_value={}), \
                mock.patch.object(tools, "load_bundle", return_value={}), \
                mock.patch.object(tools, "build_board", side_effect=lambda pos, **k: boards[pos]):
            return tools.draft_board("d1")

    def test_position_in_a_run_gets_the_boost(self):
        out = self.run_board(["RB", "RB", "WR", "RB", "RB", "QB"])
        self.assertEqual(out["position_runs"], ["RB"])
        by_pos = {r["position"]: r for r in out["best_available"]}
        self.assertEqual(by_pos["RB"]["run_multiplier"], 1.25)
        self.assertEqual(by_pos["RB"]["ADJ_SCORE"], 62.5)
        self.assertEqual(by_pos["WR"]["run_multiplier"], 1.0)
        self.assertEqual(by_pos["WR"]["ADJ_SCORE"], 50.0)
        self.assertEqual(out["best_available"][0]["position"], "RB")

    def test_no_run_changes_nothing(self):
        out = self.run_board(["RB", "WR", "QB", "TE"])
        self.assertEqual(out["position_runs"], [])
        self.assertTrue(all(r["run_multiplier"] == 1.0 and r["ADJ_SCORE"] == 50.0 for r in out["best_available"]))


if __name__ == "__main__":
    unittest.main()
