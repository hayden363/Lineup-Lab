"""The daily mix: from MIX_START a day is 2 this-season prompts + 5 NFL history prompts (owner, 2026-11-16)."""
import gzip
import json
import os
import tempfile
import unittest

from engine import daily_drive as dd
from engine import daily_drive_history_pool as hp
from engine import daily_drive_history_snapshot as snap


def _ans(n=dd.MIN_ANSWERS):
    return [{"id": f"a{i}", "name": f"P {i}", "tier": 6 if i == 0 else 1} for i in range(n)]


def _cands(kind, n, prefix):
    return [{"id": f"{prefix}{k}", "template": f"{prefix}{k}", "kind": kind, "cat": f"{prefix}cat{k}", "answers": _ans(), "text": "x"}
            for k in range(n)]


class MixTests(unittest.TestCase):
    def test_counts_switch_on_mix_start(self):
        self.assertEqual(dd.day_counts("2026-11-16"), (7, 0))
        self.assertEqual(dd.day_counts(dd.MIX_START), (2, 5))
        self.assertEqual(dd.day_size(), 7)

    def test_pick_day_takes_two_current_and_five_history(self):
        day = dd.pick_day("2026-11-20", _cands("fantasy", 20, "f") + _cands("history", 40, "h"))
        self.assertEqual([p["kind"] for p in day].count("fantasy"), 2)
        self.assertEqual([p["kind"] for p in day].count("history"), 5)

    def test_short_history_is_filled_with_current_prompts(self):
        day = dd.pick_day("2026-11-20", _cands("fantasy", 20, "f") + _cands("history", 2, "h"))
        self.assertEqual(len(day), 7)
        self.assertEqual([p["kind"] for p in day].count("history"), 2)
        day = dd.pick_day("2026-11-20", _cands("fantasy", 20, "f"))
        self.assertEqual(len(day), 7)

    def test_days_before_mix_start_are_all_current(self):
        day = dd.pick_day("2026-11-16", _cands("fantasy", 20, "f") + _cands("history", 40, "h"))
        self.assertEqual({p["kind"] for p in day}, {"fantasy"})


class SnapshotTests(unittest.TestCase):
    def test_shipped_snapshot_loads_and_covers_the_pool(self):
        body = snap.load()
        self.assertGreaterEqual(body["last"], 2025)
        keys = {t["key"] for t in hp.HISTORY_POOL}
        self.assertTrue(set(body["prompts"]) <= keys)
        self.assertGreaterEqual(len(body["prompts"]), 150)
        day = snap.snapshot_candidates("2026-11-17")
        self.assertGreaterEqual(len(day), 150)
        for p in day:
            self.assertEqual(p["kind"], "history")
            self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
            self.assertTrue(dd.has_hall_of_famer(p["answers"]))
            self.assertNotRegex(p["text"], r"\b19[0-9]{2}\b")          # nothing scoped before 2000

    def test_scoped_template_uses_the_dates_first_passing_variant(self):
        tpl = next(t for t in hp.HISTORY_POOL if t.get("scope") and len(hp.scope_options(t, 2025)) >= 6)
        order = hp.scope_order(tpl, "2026-12-01", 2025)
        fake = {"last": 2025, "prompts": {tpl["key"]: {str(order[2]): {"id": "two", "template": tpl["key"]},
                                                        str(order[5]): {"id": "five", "template": tpl["key"]}}}}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json.gz")
            with gzip.open(path, "wt") as f:
                json.dump(fake, f)
            got = snap.snapshot_candidates("2026-12-01", path=path)
        self.assertEqual([p["id"] for p in got], ["two"])

    def test_missing_snapshot_fails_soft(self):
        self.assertEqual(snap.snapshot_candidates("2026-12-01", path="/nonexistent/x.json.gz"), [])


if __name__ == "__main__":
    unittest.main()
