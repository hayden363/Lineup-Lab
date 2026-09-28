"""engine.injury_impact — the historical injury adjustment to PROJ.

The factors come from engine/injury_impact_factors.json, which
injury_impact_tuner.py regenerates. So beyond the lookup behaviour, these tests
hold the regenerated file to the claims the module's docstring makes about it:
every bucket clears the sample-size bar, QB has no buckets, an injury never
raises a projection, Doubtful is never milder than Questionable for the same
position and body part, and every alias points at a bucket that really has
data. All true of the file as of 2026-09-28 (33 buckets, n 31-279,
multipliers 0.55-0.981); a bad regeneration would fail here.

Expected values are read from the file rather than hard-coded, so a
legitimate regeneration doesn't break the suite — only a wrong one does.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import json
import os
import unittest

from engine import injury_impact as ii

with open(ii._FACTORS_PATH) as fh:
    RAW = json.load(fh)
FACTORS = RAW["factors"]


class FactorFileInvariants(unittest.TestCase):
    def test_file_has_buckets(self):
        self.assertGreater(len(FACTORS), 0)

    def test_every_bucket_clears_its_own_sample_size_bar(self):
        min_n = RAW.get("min_n", 30)
        thin = {k: v["n"] for k, v in FACTORS.items() if v["n"] < min_n}
        self.assertEqual(thin, {}, f"buckets under min_n={min_n}")

    def test_no_quarterback_buckets(self):
        # Documented finding: no QB bucket reaches the sample-size bar.
        self.assertEqual([k for k in FACTORS if k.startswith("QB|")], [])

    def test_an_injury_never_raises_a_projection(self):
        up = {k: v["median_pct_change"] for k, v in FACTORS.items() if not -1.0 < v["median_pct_change"] <= 0.0}
        self.assertEqual(up, {}, "multipliers outside (0, 1]")

    def test_doubtful_is_never_milder_than_questionable(self):
        milder = []
        for key, v in FACTORS.items():
            pos, part, status = key.split("|")
            q = FACTORS.get(f"{pos}|{part}|Questionable")
            if status == "Doubtful" and q and v["median_pct_change"] > q["median_pct_change"]:
                milder.append(f"{pos}|{part}")
        self.assertEqual(milder, [])

    def test_every_alias_points_at_a_bucket_with_data(self):
        # An alias to a body part with no bucket would silently never adjust.
        parts = {k.split("|")[1] for k in FACTORS}
        dead = {src: dst for src, dst in ii._BODY_PART_ALIASES.items() if dst not in parts}
        self.assertEqual(dead, {})


class Lookup(unittest.TestCase):
    KEY = next(iter(FACTORS))                      # any real bucket, e.g. "WR|Ankle|Questionable"
    POS, PART, STATUS = KEY.split("|")

    def test_real_bucket_applies_its_median(self):
        expected = round(1.0 + FACTORS[self.KEY]["median_pct_change"], 4)
        self.assertEqual(ii.injury_multiplier(self.POS, self.STATUS, self.PART), expected)

    def test_neutral_without_a_qualifying_status(self):
        for status in (None, "", "Out", "IR", "Healthy"):
            with self.subTest(status=status):
                self.assertEqual(ii.injury_multiplier(self.POS, status, self.PART), 1.0)

    def test_neutral_without_a_body_part_or_bucket(self):
        self.assertEqual(ii.injury_multiplier(self.POS, self.STATUS, None), 1.0)
        self.assertEqual(ii.injury_multiplier(self.POS, self.STATUS, "Elbow-Nonexistent"), 1.0)
        self.assertEqual(ii.injury_multiplier("QB", "Questionable", "Ankle"), 1.0)

    def test_sub_type_aliases_resolve_to_the_general_bucket(self):
        knee = next((k for k in FACTORS if k.split("|")[1] == "Knee"), None)
        if knee is None:
            self.skipTest("no Knee bucket in this factors file")
        pos, _, status = knee.split("|")
        self.assertEqual(ii.injury_multiplier(pos, status, "Knee - ACL"), ii.injury_multiplier(pos, status, "Knee"))

    def test_detail_discloses_the_sample_and_agrees_with_the_multiplier(self):
        d = ii.injury_adjustment_detail(self.POS, self.STATUS, self.PART)
        self.assertIsNotNone(d)
        assert d is not None
        self.assertEqual(d["real_sample_size"], FACTORS[self.KEY]["n"])
        self.assertEqual(d["multiplier"], ii.injury_multiplier(self.POS, self.STATUS, self.PART))

    def test_detail_is_none_when_nothing_applies(self):
        self.assertIsNone(ii.injury_adjustment_detail(self.POS, "Out", self.PART))
        self.assertIsNone(ii.injury_adjustment_detail(self.POS, self.STATUS, "Elbow-Nonexistent"))


if __name__ == "__main__":
    unittest.main()
