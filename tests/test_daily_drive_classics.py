"""The curated classic prompts (engine/daily_drive_classics.py + engine/dd_classics/*.json). No network."""

import json
import os
import re
import tempfile
import unittest

from engine import daily_drive as dd
from engine import daily_drive_classics as cl


def _banks():
    return cl.load_banks()


def _bank(key):
    return next(b for b in _banks() if b["key"] == key)


def _ans(bank):
    return [cl._answer(a) for a in bank["answers"]]


class BankShape(unittest.TestCase):
    def test_banks_load_and_have_a_sane_count(self):
        n = len(_banks())
        self.assertGreaterEqual(n, 25)
        self.assertEqual(n, len([f for f in os.listdir(cl.BANK_DIR) if f.endswith(".json")]))

    def test_every_bank_meets_the_game_rules(self):
        keys = set()
        for b in _banks():
            self.assertNotIn(b["key"], keys)
            keys.add(b["key"])
            self.assertIn(b["era"], cl.ERAS)
            a = _ans(b)
            self.assertGreaterEqual(len(a), dd.MIN_ANSWERS, b["key"])
            self.assertTrue(dd.has_hall_of_famer(a), b["key"] + " needs a tier-6 answer")
            ids = [x["id"] for x in a]
            self.assertEqual(len(ids), len(set(ids)), b["key"] + " duplicate answer ids")
            names = [dd.norm_name(x["name"]) for x in a]
            self.assertEqual(len(names), len(set(names)), b["key"] + " duplicate normalized names")
            self.assertTrue(b["sources"], b["key"])

    def test_every_answer_has_a_source_url(self):
        for b in _banks():
            for a in b["answers"]:
                self.assertTrue(re.match(r"https://", a.get("source", "")), (b["key"], a["name"]))
            for s in b["sources"]:
                self.assertTrue(s.startswith("https://"), b["key"])
            self.assertGreaterEqual(len(b["sources"]), 2, b["key"] + " should cite two sources")

    def test_tiers_are_not_a_single_bucket(self):
        for b in _banks():
            self.assertGreaterEqual(len({a["tier"] for a in b["answers"]}), 4, b["key"])

    def test_pre2000_share_is_small(self):
        banks = _banks()
        self.assertLessEqual(sum(1 for b in banks if b["era"] == "pre2000"), 10)

    def test_no_defunct_franchise_prompt(self):
        for b in _banks():
            self.assertNotIn("defunct", b["text"].lower())
            self.assertNotIn("defunct", b["key"])

    def test_aliases_do_not_point_at_two_answers_in_one_bank_by_accident(self):
        for b in _banks():
            seen = {}
            for a in b["answers"]:
                for al in a.get("aliases", []):
                    k = dd.norm_name(al)
                    if k in seen and seen[k] != a["id"]:
                        # only the franchise bank has deliberate shared words, and those are last names (not whole aliases)
                        self.fail("%s: alias %r on both %s and %s" % (b["key"], al, seen[k], a["id"]))
                    seen[k] = a["id"]


class Candidates(unittest.TestCase):
    def test_shape_matches_the_pool(self):
        c = cl.classics_candidates("2026-11-20")
        self.assertEqual(len(c), len(_banks()))
        for p in c:
            for k in ("id", "template", "kind", "text", "category", "cat", "answers", "threshold", "group"):
                self.assertIn(k, p)
            self.assertEqual(p["kind"], "history")
            self.assertTrue(p["id"].startswith("c:"))
            self.assertIsNone(p["threshold"])
            for a in p["answers"]:
                self.assertTrue({"id", "name", "tier"} <= set(a))
                for k in dd.ANSWER_EXTRAS:
                    self.assertIn(k, a)
        self.assertEqual(len({p["id"] for p in c}), len(c))

    def test_pick_day_accepts_them(self):
        saved = dd.HISTORY_ENABLED
        dd.HISTORY_ENABLED = True
        try:
            day = dd.pick_day("2026-11-20", cl.classics_candidates())
        finally:
            dd.HISTORY_ENABLED = saved
        self.assertEqual(len(day), dd.N_HISTORY)
        self.assertEqual(len({p["group"] for p in day}), len(day))

    def test_reveal_view_works(self):
        p = cl.classics_candidates()[0]
        rv = dd.reveal_view(p)
        self.assertEqual(rv["id"], p["id"])
        self.assertEqual(sum(len(t["answers"]) for t in rv["tiers"]), len(p["answers"]))

    def test_fails_soft(self):
        self.assertEqual(cl.classics_candidates("2026-11-20", bank_dir=os.path.join(tempfile.gettempdir(), "nope-dd-classics")), [])
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "bad.json"), "w").write("{not json")
            json.dump({"key": "x", "cat": "c", "text": "t", "era": "all", "answers": [{"id": "a", "name": "A", "tier": 9}]},
                      open(os.path.join(d, "bad2.json"), "w"))
            self.assertEqual(cl.classics_candidates(bank_dir=d), [])


class Aliases(unittest.TestCase):
    def setUp(self):
        self.fr = _ans(_bank("nfl-franchise"))

    def _ok(self, typed, name):
        r = dd.check_answer(self.fr, typed)
        self.assertTrue(r["ok"], (typed, r))
        self.assertEqual(r["answer"]["name"], name)

    def test_franchise_accepts_current_names_and_old_names(self):
        for typed in ("Las Vegas Raiders", "Raiders", "raiders", "LV Raiders", "Oakland Raiders", "Los Angeles Raiders"):
            self._ok(typed, "Las Vegas Raiders")
        for typed in ("Commanders", "Washington", "Redskins", "Washington Redskins", "Football Team"):
            self._ok(typed, "Washington Commanders")
        self._ok("Houston Oilers", "Tennessee Titans")
        self._ok("St. Louis Rams", "Los Angeles Rams")
        self._ok("Baltimore Colts", "Indianapolis Colts")
        self._ok("Decatur Staleys", "Chicago Bears")
        self._ok("Niners", "San Francisco 49ers")

    def test_franchise_accepts_a_defunct_team(self):
        for typed, name in (("Frankford Yellow Jackets", "Frankford Yellow Jackets"), ("Frankford Yellowjackets", "Frankford Yellow Jackets"),
                            ("Providence Steam Roller", "Providence Steam Roller"), ("Steamroller", "Providence Steam Roller"),
                            ("Canton Bulldogs", "Canton Bulldogs"), ("Pottsville Maroons", "Pottsville Maroons"),
                            ("Dayton Triangles", "Dayton Triangles"), ("Triangles", "Dayton Triangles")):
            self._ok(typed, name)

    def test_franchise_tiers_put_current_teams_low_and_defunct_high(self):
        t = {a["name"]: a["tier"] for a in self.fr}
        self.assertEqual(t["Dallas Cowboys"], 1)
        self.assertLessEqual(max(t[n] for n in t if n in {"Cincinnati Bengals", "Houston Texans", "Washington Commanders"}), 4)
        self.assertEqual(t["Dayton Triangles"], 6)
        self.assertGreaterEqual(t["Canton Bulldogs"], 5)
        self.assertEqual(sum(1 for a in self.fr if a["tier"] <= 4), 32)

    def test_rare_alias_is_exact_but_a_typo_is_not(self):
        r = dd.check_answer(self.fr, "Frankford Yellowjackets")
        self.assertTrue(r["ok"])
        r = dd.check_answer(self.fr, "Frankfurd Yellow Jackets")      # tier-6: typo is only a suggestion
        self.assertFalse(r["ok"])
        self.assertEqual(r["suggestions"], ["Frankford Yellow Jackets"])
        r = dd.check_answer(self.fr, "Dalas Cowboys")                  # tier-1: typo auto-accepts
        self.assertTrue(r["ok"] and r["answer"]["name"] == "Dallas Cowboys")

    def test_ambiguous_word_asks_which_one(self):
        r = dd.check_answer(self.fr, "Maroons")
        self.assertFalse(r["ok"])
        self.assertGreaterEqual(len(r["suggestions"]), 2)

    def test_alias_matches_player_short_names(self):
        a = _ans(_bank("sb-mvp-2000"))
        self.assertEqual(dd.check_answer(a, "Eli")["answer"]["name"], "Eli Manning")
        self.assertEqual(dd.check_answer(a, "Peyton")["answer"]["name"], "Peyton Manning")
        self.assertFalse(dd.check_answer(a, "Manning")["ok"])         # two Mannings: ask which
        self.assertEqual(dd.check_answer(a, "Kenneth Walker")["answer"]["name"], "Kenneth Walker III")
        a = _ans(_bank("sb-winning-qb-2000"))
        self.assertEqual(dd.check_answer(a, "Big Ben")["answer"]["name"], "Ben Roethlisberger")
        self.assertEqual(dd.check_answer(a, "Matt Stafford")["answer"]["name"], "Matthew Stafford")

    def test_used_answer_via_alias_is_still_once_only(self):
        r = dd.check_answer(self.fr, "Raiders")
        again = dd.check_answer(self.fr, "Oakland Raiders", used={r["answer"]["id"]})
        self.assertFalse(again["ok"])
        self.assertEqual(again["reason"], "already used")

    def test_stadium_old_names(self):
        a = _ans(_bank("current-stadium"))
        self.assertEqual(dd.check_answer(a, "Heinz Field")["answer"]["name"], "Acrisure Stadium")
        self.assertEqual(dd.check_answer(a, "Reliant Stadium")["answer"]["name"], "NRG Stadium")
        self.assertEqual(dd.check_answer(a, "FedExField")["answer"]["name"], "Northwest Stadium")


class CheckAnswerBackCompat(unittest.TestCase):
    def test_answers_without_aliases_behave_as_before(self):
        a = [{"id": str(i), "name": n, "tier": t} for i, (n, t) in enumerate(
            [("Tom Brady", 1), ("Peyton Manning", 1), ("Eli Manning", 2), ("Kurt Warner", 5)])]
        self.assertTrue(dd.check_answer(a, "tom brady")["ok"])
        self.assertTrue(dd.check_answer(a, "Brady")["ok"])
        self.assertFalse(dd.check_answer(a, "Manning")["ok"])
        self.assertTrue(dd.check_answer(a, "Tom Bardy")["ok"])
        self.assertFalse(dd.check_answer(a, "Kurt Warnar")["ok"])
        self.assertEqual(dd.check_answer(a, "nobody")["reason"], "not in the answer bank")


if __name__ == "__main__":
    unittest.main()
