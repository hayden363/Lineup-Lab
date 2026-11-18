"""Daily Drive answer matching: initials (ARSB, JSN, OBJ), curated nicknames (CMC, Megatron), multi-word surnames
(Smith-Njigba, St. Brown), and decade questions that spell out their years."""
import unittest

from engine import daily_drive as dd
from engine import daily_drive_history_pool as hp
from engine import daily_drive_history_snapshot as snap


def A(i, name, tier=2):
    return {"id": i, "name": name, "tier": tier}


WRS = [A("00-0036963", "Amon-Ra St. Brown"), A("00-0038543", "Jaxon Smith-Njigba"), A("00-0031235", "Odell Beckham Jr."),
       A("00-0033280", "Christian McCaffrey"), A("00-0025389", "Calvin Johnson", tier=6), A("x1", "Mike Evans"),
       A("x2", "Marvin Jones")]


class InitialsTests(unittest.TestCase):
    def ok(self, typed, answers=WRS):
        r = dd.check_answer(answers, typed)
        return r["answer"]["name"] if r["ok"] else None

    def test_initials_match(self):
        self.assertEqual(self.ok("ARSB"), "Amon-Ra St. Brown")
        self.assertEqual(self.ok("jsn"), "Jaxon Smith-Njigba")
        self.assertEqual(self.ok("O.B.J."), "Odell Beckham Jr.")

    def test_two_letter_initials_are_not_auto_accepted(self):
        self.assertIsNone(self.ok("ME"))           # Mike Evans: too short to be safe

    def test_initials_shared_by_two_answers_are_not_auto_accepted(self):
        twins = [A("a", "Jamal Jay Smith"), A("b", "Jordan James Simms")]
        self.assertIsNone(self.ok("jjs", twins))

    def test_curated_nicknames(self):
        self.assertEqual(self.ok("CMC"), "Christian McCaffrey")
        self.assertEqual(self.ok("Megatron"), "Calvin Johnson")   # tier 6: a nickname counts as exact

    def test_nickname_only_counts_for_its_own_player(self):
        self.assertIsNone(self.ok("CMC", [A("x9", "Chris Moore")]))

    def test_multi_word_surname(self):
        self.assertEqual(self.ok("Smith-Njigba"), "Jaxon Smith-Njigba")
        self.assertEqual(self.ok("St. Brown"), "Amon-Ra St. Brown")

    def test_existing_matching_unchanged(self):
        self.assertEqual(self.ok("Evans"), "Mike Evans")
        self.assertEqual(self.ok("C. McCaffrey"), "Christian McCaffrey")
        r = dd.check_answer(WRS, "Odell Beckham")
        self.assertTrue(r["ok"])
        self.assertEqual(dd.check_answer(WRS, "Jalen Reagor")["reason"], "not in the answer bank")


class DecadeYearsTests(unittest.TestCase):
    def test_decade_text_spells_out_years(self):
        self.assertEqual(hp.decade_years("Name a WR taken in the first round of the 2010s drafts", "2010s"),
                         "Name a WR taken in the first round of the 2010s (2010–2019) drafts")
        self.assertEqual(hp.decade_years("Name a QB who ran for 400+ yards in a season of the 2020s", "2020s"),
                         "Name a QB who ran for 400+ yards in a season of the 2020s (since 2020)")

    def test_idempotent_and_ignores_non_decades(self):
        once = hp.decade_years("of the 2000s", "2000s")
        self.assertEqual(hp.decade_years(once, "2000s"), once)
        self.assertEqual(hp.decade_years("since 2000", None), "since 2000")

    def test_snapshot_prompts_get_years(self):
        q = {"id": "hh:x:2025:t0:2010s", "text": "Name a WR taken in the first round of the 2010s drafts", "scope": "2010s",
             "stat_label": "Pro Bowls", "rows": []}
        self.assertIn("(2010–2019)", snap._unpack(q, [])["text"])


if __name__ == "__main__":
    unittest.main()
