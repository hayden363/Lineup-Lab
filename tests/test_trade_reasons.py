import unittest
from engine import trade_reasons as R


def P(name, pos, value, **kw):
    return {"name": name, "position": pos, "value": value, **kw}


class ReasonTests(unittest.TestCase):
    def test_need_and_surplus_both_sides(self):
        give = [P("Spare RB", "RB", 12)]
        get = [P("Needed WR", "WR", 13)]
        out = R.build_reasons(give, get, {"RB": 2, "WR": 2}, {"RB": 4, "WR": 2},
                              {"RB": 2, "WR": 2}, {"RB": 2, "WR": 4}, None, None, "Them")
        self.assertTrue(any("Fills a need at WR" in s for s in out["you"]))
        self.assertTrue(any("depth you don't use" in s for s in out["you"]))
        self.assertTrue(any("Fills a need at RB" in s for s in out["them"]))
        self.assertTrue(any("depth Them doesn't use" in s for s in out["them"]))

    def test_value_wording(self):
        a = R.build_reasons([P("A", "RB", 10)], [P("B", "WR", 10.5)], {}, {}, {}, {}, None, None, "T")
        self.assertTrue(any("Close in value" in s for s in a["you"]))
        b = R.build_reasons([P("A", "RB", 10)], [P("B", "WR", 15)], {}, {}, {}, {}, None, None, "T")
        self.assertTrue(any("come out ahead" in s for s in b["you"]))
        self.assertTrue(any("T gives up" in s for s in b["them"]))

    def test_form_injury_bye_standings(self):
        out = R.build_reasons([P("Old", "RB", 12, form=-15, bye=7)], [P("Hot", "WR", 12, form=14, bye=9, injury_status="Questionable")],
                              {}, {}, {}, {}, (1, 4), (4, 1), "T")["you"]
        self.assertTrue(any("trending up" in s for s in out))
        self.assertTrue(any("cooling off" in s for s in out))
        self.assertTrue(any("Questionable" in s for s in out))
        self.assertTrue(any("bye from week 7 to week 9" in s for s in out))
        self.assertTrue(any("1-4" in s and "future" in s for s in out))

    def test_wording_names_the_other_team_and_rounds_needs(self):
        out = R.build_reasons([P("A", "RB", 10)], [P("B", "WR", 10)], {"WR": 2.6667, "RB": 2}, {"WR": 1, "RB": 2},
                              {"WR": 2, "RB": 1.6667}, {"WR": 2, "RB": 1}, (1, 3), (3, 1), "Bravo")
        self.assertTrue(any("you start 2.7 and carry 1" in s for s in out["you"]))
        self.assertTrue(any("Bravo starts" in s for s in out["them"]))
        self.assertFalse(any(" you " in f" {s.lower()} " for s in out["them"]))
        self.assertFalse(any("1.6666" in s or "2.6666" in s for s in out["you"] + out["them"]))

    def test_quiet_when_nothing_applies(self):
        out = R.build_reasons([], [], {}, {}, {}, {}, None, None, "T")
        self.assertEqual(out, {"you": [], "them": []})


if __name__ == "__main__":
    unittest.main()
