"""Live (in-game) projection: the rules of engine/live_proj.live_projection and the shipped params."""
import json
import os
import unittest

from engine import live_proj as lp

POSITIONS = ("QB", "RB", "WR", "TE")


class LiveProjTests(unittest.TestCase):
    def test_params_json_loads_and_is_well_formed(self):
        path = os.path.join(os.path.dirname(lp.__file__), "live_proj_params.json")
        with open(path) as fh:
            p = json.load(fh)
        self.assertTrue(p["ship_model"])
        self.assertEqual(len(p["diff_labels"]), len(p["diff_cuts"]) + 1)
        for pos in POSITIONS:
            self.assertEqual(len(p["f"][pos]), len(p["diff_labels"]))
            for row in p["f"][pos]:
                self.assertEqual(len(row), len(p["ts"]))
                self.assertTrue(all(0.0 <= v <= 1.2 for v in row))

    def test_final_game_is_points_so_far(self):
        r = lp.live_projection("WR", 15.0, 9.4, 1200, -3, final=True)
        self.assertEqual(r["live_proj"], 9.4)
        self.assertEqual(r["rog"], 0.0)

    def test_no_time_left_is_points_so_far(self):
        for t in (0, -5):
            self.assertEqual(lp.live_projection("RB", 12.0, 7.0, t, 0)["live_proj"], 7.0)

    def test_never_below_points_so_far(self):
        for pos in POSITIONS + ("K", "DEF", None):
            for so_far in (0.0, 3.0, 40.0):
                for t in (3600, 1800, 300, 1):
                    for d in (-30, 0, 30, None):
                        r = lp.live_projection(pos, 10.0, so_far, t, d)
                        self.assertGreaterEqual(r["live_proj"], so_far)
                        self.assertGreaterEqual(r["rog"], 0.0)

    def test_unknown_position_uses_naive_time_scaling(self):
        for pos in ("K", "DEF", "XYZ", None):
            r = lp.live_projection(pos, 9.0, 2.0, 1800, 7)
            self.assertEqual(r["method"], "naive")
            self.assertAlmostEqual(r["rog"], 4.5)
            self.assertAlmostEqual(r["live_proj"], 6.5)

    def test_missing_pregame_does_not_invent_points(self):
        for pre in (None, 0, -1, float("nan")):
            r = lp.live_projection("WR", pre, 6.0, 1800, 0)
            self.assertEqual(r["method"], "naive")
            self.assertEqual(r["live_proj"], 6.0)

    def test_none_inputs_do_not_raise(self):
        r = lp.live_projection(None, None, None, None, None)
        self.assertEqual(r["live_proj"], 0.0)
        r = lp.live_projection("WR", 12.0, None, 1500, None, quarter=None)
        self.assertEqual(r["method"], "model")
        self.assertGreater(r["live_proj"], 0.0)
        r = lp.live_projection("WR", "abc", "x", "y", "z")
        self.assertEqual(r["live_proj"], 0.0)

    def test_model_is_used_for_skill_positions(self):
        for pos in POSITIONS:
            self.assertEqual(lp.live_projection(pos, 12.0, 4.0, 1800, 0)["method"], "model")
            self.assertEqual(lp.live_projection(pos.lower(), 12.0, 4.0, 1800, 0)["method"], "model")

    def test_more_time_left_never_shrinks_rog(self):
        times = [3600, 3300, 3000, 2700, 2400, 2100, 1800, 1500, 1200, 900, 600, 450, 300, 150, 30, 1]
        for pos in POSITIONS:
            for d in (-20, -10, -5, 0, 5, 10, 20):
                for pre in (6.0, 14.0, 24.0):
                    for so_far in (0.0, 0.5 * pre, 2.0 * pre):
                        rogs = [lp.live_projection(pos, pre, so_far, t, d)["rog"] for t in times]
                        for a, b in zip(rogs, rogs[1:]):    # times run from most to least time left
                            self.assertGreaterEqual(a + 1e-9, b, (pos, d, pre, so_far))

    def test_trailing_wr_late_scores_more_than_leading_wr(self):
        trailing = lp.live_projection("WR", 15.0, 8.0, 300, -9)["rog"]
        leading = lp.live_projection("WR", 15.0, 8.0, 300, 16)["rog"]
        self.assertGreater(trailing, leading)


if __name__ == "__main__":
    unittest.main()
