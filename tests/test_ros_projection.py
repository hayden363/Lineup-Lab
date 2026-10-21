import unittest

from engine import ros_projection as ros


class RosMathTests(unittest.TestCase):
    def test_baseline_is_opportunity_not_the_rate(self):
        # a full window of opportunity data: the rate no longer pulls the baseline at all
        self.assertAlmostEqual(ros.blend_baseline(14.0, 30.0), 14.0)
        self.assertAlmostEqual(ros.blend_baseline(14.0, 5.0, efficiency=1.05), 14.7)

    def test_thin_opportunity_data_falls_back_to_rate(self):
        self.assertAlmostEqual(ros.blend_baseline(14.0, 10.0, 1.0, n_games=2), 0.5 * 14.0 + 0.5 * 10.0)
        self.assertAlmostEqual(ros.blend_baseline(14.0, 10.0, 1.0, n_games=0), 10.0)

    def test_efficiency_is_capped_five_percent(self):
        hot = ros.efficiency_multiplier(40.0, 10.0, 17)    # scoring 4x his opportunity
        cold = ros.efficiency_multiplier(2.0, 10.0, 17)
        self.assertEqual(hot, 1.05)
        self.assertEqual(cold, 0.95)

    def test_efficiency_regresses_with_few_games(self):
        small = ros.efficiency_multiplier(10.3, 10.0, 2)       # 3% over, 2 games
        big = ros.efficiency_multiplier(10.3, 10.0, 17)        # 3% over, 17 games
        self.assertLess(small, big)
        self.assertGreater(small, 1.0)
        self.assertLess(big, 1.05)

    def test_efficiency_neutral_when_unknown_or_normal(self):
        self.assertEqual(ros.efficiency_multiplier(None, 10.0, 5), 1.0)
        self.assertEqual(ros.efficiency_multiplier(10.0, 0, 5), 1.0)
        self.assertEqual(ros.efficiency_multiplier(10.0, 10.0, 5), 1.0)
        self.assertEqual(ros.efficiency_multiplier(10.6, 10.0, 5, pos_norm=1.06), 1.0)   # TE norm is above 1

    def test_three_td_outlier_cannot_move_projection_more_than_five_percent(self):
        base = ros.blend_baseline(12.0, 12.0, ros.efficiency_multiplier(12.0, 12.0, 6))
        after_fluke = ros.blend_baseline(12.0, 30.0, ros.efficiency_multiplier(30.0, 12.0, 6))
        self.assertLessEqual(after_fluke / base, 1.05 + 1e-9)

    def test_baseline_without_xfp_is_the_rate(self):
        self.assertEqual(ros.blend_baseline(None, 12.5), 12.5)

    def test_multipliers_stack(self):
        self.assertAlmostEqual(ros.combine(14.0, 1.15, 1.12), 14.0 * 1.15 * 1.12)

    def test_h2h_and_injury_default_neutral(self):
        self.assertEqual(ros.combine(10.0, 1.0, 1.0), 10.0)

    def test_defense_clamped(self):
        self.assertEqual(ros.clamp_defense(1.9), 1.2)
        self.assertEqual(ros.clamp_defense(0.2), 0.8)

    def test_grades_run_best_to_worst(self):
        self.assertEqual(ros.grade_for(1, 32), "A")
        self.assertEqual(ros.grade_for(16, 32), "C")
        self.assertEqual(ros.grade_for(32, 32), "F")
        self.assertIsNone(ros.grade_for(None, 32))


class MatchupHistoryTests(unittest.TestCase):
    def test_tiers_split_by_rank(self):
        self.assertEqual(ros.defense_tier(1, 32), "soft")
        self.assertEqual(ros.defense_tier(10, 32), "soft")
        self.assertEqual(ros.defense_tier(16, 32), "neutral")
        self.assertEqual(ros.defense_tier(23, 32), "tough")
        self.assertEqual(ros.defense_tier(32, 32), "tough")
        self.assertIsNone(ros.defense_tier(None, 32))

    def test_past_matchups_average_by_tier(self):
        ranks = {"AAA": (3, 32), "BBB": (30, 32), "CCC": (5, 32)}
        played = [{"week": 1, "opponent": "AAA", "points": 20.0},
                  {"week": 2, "opponent": "BBB", "points": 6.0},
                  {"week": 3, "opponent": "CCC", "points": 14.0}]
        games, by = ros.past_matchups(played, lambda o: ranks[o])
        self.assertEqual([g["tier"] for g in games], ["soft", "tough", "soft"])
        self.assertEqual(by["soft"], {"games": 2, "avg": 17.0})
        self.assertEqual(by["tough"], {"games": 1, "avg": 6.0})
        self.assertNotIn("neutral", by)

    def test_unknown_defense_is_left_out(self):
        games, by = ros.past_matchups([{"week": 1, "opponent": "ZZZ", "points": 9.0}], lambda o: (None, None))
        self.assertIsNone(games[0]["tier"])
        self.assertEqual(by, {})

    def test_waterfall_steps_multiply_in_order(self):
        w = ros.waterfall(10.0, 1.1, 0.8, 1.0, 0.5)
        self.assertEqual(w["baseline"], 10.0)
        self.assertEqual(w["after_environment"], 11.0)
        self.assertEqual(w["after_defense"], 8.8)
        self.assertEqual(w["after_history"], 8.8)
        self.assertEqual(w["final"], 4.4)


if __name__ == "__main__":
    unittest.main()
