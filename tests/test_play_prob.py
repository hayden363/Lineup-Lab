"""Questionable/Doubtful players: the weekly projection multiplier policy, and what it does to the outcome range."""

import unittest
from datetime import date

from engine import decision, play_prob


class PlayProbTests(unittest.TestCase):
    """The weekly policy: Doubtful x0.25; Questionable x0.92, or x0.60 after a FRIDAY did-not-practice."""
    today = date(2026, 10, 23)          # a Friday

    def note(self, text, updated):
        return {"note": text, "updated": updated}

    WED, THU, FRI = "2026-10-21T18:00Z", "2026-10-22T18:00Z", "2026-10-23T18:00Z"
    DNP = "Smith (hamstring) was a non-participant in practice."

    def test_only_questionable_and_doubtful(self):
        self.assertIsNone(play_prob.play_probability("WR", "Out"))
        self.assertIsNone(play_prob.play_probability("WR", "IR"))
        self.assertIsNone(play_prob.play_probability("WR", None))

    def test_doubtful_is_a_quarter_whatever_the_practice_wording(self):
        self.assertEqual(play_prob.play_probability("RB", "Doubtful")["p_play"], 0.25)
        r = play_prob.play_probability("RB", "Doubtful", self.note(self.DNP, self.FRI), self.today)
        self.assertEqual(r["p_play"], 0.25)

    def test_questionable_is_never_halved_for_routine_reasons(self):
        for rep in (None, self.note("Smith was a full participant in practice.", self.THU),
                    self.note("Smith was limited in practice.", self.THU),
                    self.note(self.DNP, self.WED),                       # Wednesday non-participant: maintenance
                    self.note(self.DNP, self.THU)):
            r = play_prob.play_probability("WR", "Questionable", rep, self.today)
            self.assertEqual(r["p_play"], 0.92, rep)

    def test_only_a_friday_did_not_practice_drops_questionable_to_sixty_percent(self):
        r = play_prob.play_probability("WR", "Questionable", self.note(self.DNP, self.FRI), self.today)
        self.assertEqual((r["p_play"], r["practice"]), (0.60, "dnp"))
        self.assertIn("Friday", r["basis"])

    def test_friday_is_judged_in_eastern_time(self):
        late_friday_et = "2026-10-24T01:00Z"                              # 9pm Friday ET, already Saturday in UTC
        saturday_et = "2026-10-24T18:00Z"
        today = date(2026, 10, 24)
        self.assertEqual(play_prob.play_probability("WR", "Questionable", self.note(self.DNP, late_friday_et), today)["p_play"], 0.60)
        self.assertEqual(play_prob.play_probability("WR", "Questionable", self.note(self.DNP, saturday_et), today)["p_play"], 0.92)

    def test_friday_without_a_did_not_practice_stays_at_ninety(self):
        r = play_prob.play_probability("WR", "Questionable", self.note("Smith was limited in practice.", self.FRI), self.today)
        self.assertEqual(r["p_play"], 0.92)

    def test_a_dnp_note_with_no_timestamp_cannot_be_called_friday(self):
        r = play_prob.play_probability("WR", "Questionable", {"note": self.DNP}, self.today)
        self.assertEqual(r["p_play"], 0.92)

    def test_expected_to_miss_the_game_is_ruled_out_but_expected_to_miss_practice_is_not(self):
        game = play_prob.play_probability("WR", "Questionable", self.note("Turpin (ribs) is expected to miss the Week 7 matchup.", self.FRI), self.today)
        self.assertEqual((game["p_play"], game["practice"]), (0.05, "out"))
        for text in ("Smith (knee) is expected to miss practice Wednesday.", "Smith is expected to miss Thursday's practice."):
            r = play_prob.play_probability("WR", "Questionable", self.note(text, self.WED), self.today)
            self.assertEqual(r["p_play"], 0.92, text)

    def test_measured_history_is_reported_but_does_not_drive_the_number(self):
        r = play_prob.play_probability("WR", "Questionable", self.note(self.DNP, self.WED), self.today)
        self.assertLess(r["p_history"], 0.6)          # the data says ~46-49% of non-practising WRs played
        self.assertEqual(r["p_play"], 0.92)           # the policy is what scales the projection

    def test_stale_or_past_game_notes_are_ignored(self):
        old = {"note": "Smith was a full participant in practice.", "updated": "2026-10-01T10:00Z"}
        self.assertIsNone(play_prob.play_probability("WR", "Questionable", old, self.today)["practice"])
        past = self.note("McConkey won't return to Sunday's game due to a concussion.", self.THU)
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
