"""engine.tools._trade_recommendation — the end-to-end trade headline and per-side verdicts.

test_trade_verdict.py only calls _side_verdict directly. This wires the whole path
(_team_needs -> _fit_score -> _side_verdict -> headline) for both sides with league_ctx dicts shaped like the
real ones, and pins the properties that must hold: swapping the sides mirrors the result, each headline branch is
reachable, and players carrying an 'error' key are left out.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest

from engine.tools import _trade_recommendation

STANDARD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K", "BN", "BN"]


def pl(*positions):
    return [{"position": p} for p in positions]


# Team RB_HEAVY: 5 RB (deep, 0.82), 1 WR (hole, 1.25).  Team WR_HEAVY: 5 WR (deep), 1 RB (hole).
RB_HEAVY = pl("QB", "TE", "RB", "RB", "RB", "RB", "RB", "WR")
WR_HEAVY = pl("QB", "TE", "WR", "WR", "WR", "WR", "WR", "RB")


def ctx(roster_a, roster_b):
    return {"roster_a": {"players": roster_a}, "roster_b": {"players": roster_b}, "roster_positions": STANDARD}


class Headline(unittest.TestCase):
    def test_each_side_receives_what_it_is_missing(self):
        # A (RB-heavy) gives an RB and gets a WR; B (WR-heavy) gives a WR and gets an RB; equal value.
        r = _trade_recommendation(pl("RB"), pl("WR"), 10.0, 10.0, ctx(RB_HEAVY, WR_HEAVY))
        self.assertEqual(r["headline"], "Roughly even on value — fills a real need for both sides.")
        self.assertEqual((r["side_a"]["fit_score"], r["side_b"]["fit_score"]), (0.43, 0.43))
        self.assertEqual(r["side_a"]["tier"], "smart")
        self.assertEqual(r["side_b"]["tier"], "smart")

    def test_both_sides_receive_what_they_are_already_deep_in(self):
        # A gives a WR (its hole) for an RB (its glut); B does the mirror image.
        r = _trade_recommendation(pl("WR"), pl("RB"), 10.0, 10.0, ctx(RB_HEAVY, WR_HEAVY))
        self.assertEqual(r["headline"], "Roughly even on value — doesn't really address either side's needs.")
        self.assertEqual((r["side_a"]["fit_score"], r["side_b"]["fit_score"]), (-0.43, -0.43))
        self.assertEqual(r["side_a"]["tier"], "questionable")

    def test_only_one_side_helped(self):
        both_rb_heavy = ctx(RB_HEAVY, RB_HEAVY)
        r = _trade_recommendation(pl("RB"), pl("WR"), 10.0, 10.0, both_rb_heavy)
        self.assertEqual(r["side_a"]["fit_score"], 0.43)
        self.assertEqual(r["side_b"]["fit_score"], -0.43)
        self.assertIn("clearly helps Side A's roster more", r["headline"])

    def test_a_wash_on_fit(self):
        r = _trade_recommendation(pl("RB"), pl("RB"), 10.0, 10.0, ctx(RB_HEAVY, WR_HEAVY))
        self.assertEqual(r["headline"], "Roughly even on value — roughly a wash on roster fit.")
        self.assertEqual(r["side_a"]["tier"], "fair")

    def test_value_lean_text_follows_the_totals(self):
        c = ctx(RB_HEAVY, WR_HEAVY)
        self.assertTrue(_trade_recommendation(pl("RB"), pl("RB"), 10.0, 14.0, c)["headline"].startswith("Leans toward Side A on value"))
        self.assertTrue(_trade_recommendation(pl("RB"), pl("RB"), 14.0, 10.0, c)["headline"].startswith("Leans toward Side B on value"))
        self.assertTrue(_trade_recommendation(pl("RB"), pl("RB"), 10.0, 11.5, c)["headline"].startswith("Roughly even on value"))   # exactly the 1.5 threshold


class Symmetry(unittest.TestCase):
    def test_swapping_the_sides_mirrors_the_result(self):
        a_out, b_out = pl("RB"), pl("WR")
        r = _trade_recommendation(a_out, b_out, 10.0, 14.0, ctx(RB_HEAVY, WR_HEAVY))
        s = _trade_recommendation(b_out, a_out, 14.0, 10.0, ctx(WR_HEAVY, RB_HEAVY))
        self.assertEqual(r["side_a"]["net_value"], 4.0)
        self.assertEqual(r["side_b"]["net_value"], -4.0)
        self.assertEqual(s["side_a"], r["side_b"])
        self.assertEqual(s["side_b"], r["side_a"])
        self.assertIn("Side A on value", r["headline"])
        self.assertIn("Side B on value", s["headline"])

    def test_net_values_are_opposites(self):
        r = _trade_recommendation(pl("RB"), pl("WR"), 7.3, 12.9, ctx(RB_HEAVY, WR_HEAVY))
        self.assertEqual(r["side_a"]["net_value"], -r["side_b"]["net_value"])


class ErrorPlayers(unittest.TestCase):
    def test_players_carrying_an_error_do_not_count_toward_fit(self):
        c = ctx(RB_HEAVY, WR_HEAVY)
        clean = _trade_recommendation(pl("RB"), pl("WR"), 10.0, 10.0, c)
        noisy = _trade_recommendation(pl("RB") + [{"position": "WR", "error": "not found"}], pl("WR") + [{"position": "RB", "error": "x"}], 10.0, 10.0, c)
        self.assertEqual(noisy["side_a"]["fit_score"], clean["side_a"]["fit_score"])
        self.assertEqual(noisy["side_b"]["fit_score"], clean["side_b"]["fit_score"])


if __name__ == "__main__":
    unittest.main()
