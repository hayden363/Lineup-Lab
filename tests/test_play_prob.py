"""Questionable/Doubtful players keep their upside but lose their floor."""

import unittest
from datetime import date

from engine import decision, play_prob


class PlayProbTests(unittest.TestCase):
    today = date(2026, 10, 22)

    def note(self, text):
        return {"note": text, "updated": "2026-10-21T10:00Z"}

    def test_only_questionable_and_doubtful(self):
        self.assertIsNone(play_prob.play_probability("WR", "Out"))
        self.assertIsNone(play_prob.play_probability("WR", None))

    def test_doubtful_almost_never_plays(self):
        self.assertLess(play_prob.play_probability("RB", "Doubtful")["p_play"], 0.05)

    def test_questionable_is_not_a_killer(self):
        self.assertGreater(play_prob.play_probability("WR", "Questionable")["p_play"], 0.6)

    def test_practice_wording_moves_the_rate(self):
        f = play_prob.play_probability("WR", "Questionable", self.note("Smith (hamstring) was a full participant in practice."), self.today)
        d = play_prob.play_probability("WR", "Questionable", self.note("Smith (hamstring) was a non-participant in practice."), self.today)
        self.assertGreater(f["p_play"], 0.8)
        self.assertLess(d["p_play"], 0.55)
        self.assertEqual((f["practice"], d["practice"]), ("full", "dnp"))

    def test_expected_to_miss(self):
        r = play_prob.play_probability("WR", "Questionable", self.note("Turpin (ribs) is expected to miss the Week 7 matchup."), self.today)
        self.assertLessEqual(r["p_play"], 0.05)

    def test_stale_or_past_game_notes_are_ignored(self):
        old = {"note": "Smith was a full participant in practice.", "updated": "2026-10-01T10:00Z"}
        self.assertIsNone(play_prob.play_probability("WR", "Questionable", old, self.today)["practice"])
        past = self.note("McConkey won't return to Sunday's game due to a concussion.")
        self.assertIsNone(play_prob.play_probability("WR", "Questionable", past, self.today)["practice"])


class OutcomesTests(unittest.TestCase):
    def test_zero_mass_lowers_floor_and_mean_but_not_ceiling(self):
        healthy = decision.outcomes(14, 0.5, seed=1)
        q = decision.outcomes(14, 0.5, seed=1, p_play=0.7)
        self.assertEqual(q["p10"], 0.0)
        self.assertAlmostEqual(q["mean"], 9.8, places=1)
        self.assertGreater(q["p90"], healthy["p90"] * 0.9)

    def test_healthy_is_unchanged(self):
        self.assertEqual(decision.outcomes(14, 0.5, seed=1)["p10"], decision.outcomes(14, 0.5, seed=1, p_play=1.0)["p10"])


if __name__ == "__main__":
    unittest.main()
