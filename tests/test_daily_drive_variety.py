"""Easy -> hard days (owner, 2026-11-17): questions 1-3 are warm-ups anyone can answer, 4-5 medium, 6-7 deep cuts; every
question has at least 10 answers and at least one in every tier; warm-ups may have hundreds; round lines only; no
"name a player who scored a TD this season" lists."""
import datetime as dt
import os
import re
import tempfile
import unittest

import pandas as pd

from engine import daily_drive as dd
from engine import daily_drive_classics as cl
from engine import daily_drive_history_pool as hp
from engine import daily_drive_history_snapshot as hs
from engine import daily_drive_pool as pool

DAY = "2026-11-20"


def _answers(n):
    return [{"id": f"a{i}", "name": f"Player {i} Last{i}", "tier": dd.tier_for_rank(i, n)} for i in range(n)]


def _cand(key, kind, band, n, cat=None, pos=None, shape=None, group=None):
    return {"id": f"{kind[0]}:{key}", "template": key, "kind": kind, "text": key, "category": "x", "cat": cat or key,
            "answers": _answers(n), "group": group or key, "band": band, "pos_tag": pos, "shape": shape}


def _pool():
    out = []
    for kind, per in (("fantasy", 6), ("history", 12)):
        for band, n in (("easy", 150), ("medium", 35), ("hard", 14)):
            for i in range(per):
                out.append(_cand(f"{kind}-{band}-{i}", kind, band, n + i, pos=("QB", "RB", "WR", "TE", None)[i % 5]))
    out.append(_cand("draft-medium", "history", "medium", 40, cat="NFL Draft"))
    return out


class RuleTests(unittest.TestCase):
    def test_every_tier_from_ten_answers(self):
        self.assertTrue(dd.playable(_answers(10)))
        self.assertFalse(dd.playable(_answers(9)))
        self.assertTrue(dd.playable(_answers(400)))
        no_gold = [dict(a, tier=min(a["tier"], 5)) for a in _answers(40)]
        self.assertFalse(dd.playable(no_gold))

    def test_round_lines(self):
        for t in (1, 2, 4.5, 10, 25, 40, 60, 80, 100, 150, 300, 1000, 1200, 4000):
            self.assertTrue(dd.round_line(t), t)
        for t in (4.3, 12, 45, 55, 64, 85, 110, 175, 1250):
            self.assertFalse(dd.round_line(t), t)

    def test_easy_band_only_uses_hand_picked_lines(self):
        per = pd.DataFrame({"val": list(range(1, 301))})
        got = dd.band_rungs(per, ladder=(1, 100, 200, 250, 280, 290), easy_lines=(200,))
        self.assertEqual(got["easy"], [200])                    # 101 answers: easy; rung 1 (300 answers) is never a warm-up
        self.assertNotIn(1, got["easy"])
        self.assertIn(250, got["medium"])                        # 51 answers
        self.assertEqual(dd.band_rungs(per, ladder=(1, 100), easy_lines=())["easy"], [])

    def test_bands_ordered_and_disjoint(self):
        lo_prev = None
        for b in reversed(dd.BAND_ORDER):
            lo, hi, target = dd.BANDS[b]
            self.assertLessEqual(lo, target)
            self.assertLessEqual(target, hi)
            if lo_prev is not None:
                self.assertGreater(lo, lo_prev)
            lo_prev = hi
        self.assertEqual(dd.BANDS["hard"][0], dd.FLOOR)
        self.assertEqual(dd.FLOOR, 10)
        self.assertGreaterEqual(dd.BANDS["easy"][1], 300)        # a warm-up may have hundreds of answers


class PickDayTests(unittest.TestCase):
    def test_easy_to_hard_two_current_five_history(self):
        day = dd.pick_day(DAY, _pool())
        self.assertEqual(len(day), 7)
        self.assertEqual([p["band"] for p in day], ["easy"] * 3 + ["medium"] * 2 + ["hard"] * 2)
        self.assertEqual(sum(p["kind"] == "fantasy" for p in day), 2)
        for i in range(len(day) - 1):                            # inside a band, the bigger answer set first
            if day[i]["band"] == day[i + 1]["band"]:
                self.assertGreaterEqual(len(day[i]["answers"]), len(day[i + 1]["answers"]))

    def test_same_date_same_day_and_rules_hold(self):
        a, b = dd.pick_day(DAY, _pool()), dd.pick_day(DAY, list(reversed(_pool())))
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        for p in a:
            self.assertTrue(dd.playable(p["answers"]))
        self.assertEqual(len({p["group"] for p in a}), 7)
        tags = [p["pos_tag"] for p in a if p["pos_tag"]]
        self.assertTrue(all(tags.count(t) <= dd.MAX_PER_POS for t in tags))
        self.assertTrue(any(p["cat"] in dd.BREADTH_CATS for p in a))   # at least one draft / team / awards question

    def test_one_single_game_and_one_season_total(self):
        cands = _pool() + [_cand(f"g{i}", "history", "easy", 200 + i, shape="game") for i in range(10)] + \
            [_cand(f"s{i}", "history", "easy", 220 + i, shape="season") for i in range(10)]
        day = dd.pick_day(DAY, cands)
        self.assertLessEqual(sum(p["shape"] == "game" for p in day), 1)
        self.assertLessEqual(sum(p["shape"] == "season" for p in day), 1)

    def test_unplayable_never_picked(self):
        thin = [_cand(f"thin{i}", "history", "easy", 9) for i in range(20)]
        for p in dd.pick_day(DAY, _pool() + thin):
            self.assertFalse(p["template"].startswith("thin"))

    def test_short_band_borrows_the_nearest_band(self):
        cands = [c for c in _pool() if not (c["kind"] == "history" and c["band"] == "hard")]
        day = dd.pick_day(DAY, cands)
        self.assertEqual(len(day), 7)
        self.assertEqual(sum(p["kind"] == "history" for p in day), 5)

    def test_days_before_variety_start_keep_the_old_picker(self):
        before = (dt.date.fromisoformat(dd.VARIETY_START) - dt.timedelta(days=1)).isoformat()
        self.assertEqual([p["id"] for p in dd.pick_day(before, _pool())], [p["id"] for p in dd.pick_day_legacy(before, _pool())])

    def test_a_template_rests_for_the_cooldown(self):
        cands = _pool()
        with tempfile.TemporaryDirectory() as d:
            days = [dd.get_puzzle((dt.date(2026, 11, 20) + dt.timedelta(days=i)).isoformat(), d, lambda _d: cands) for i in range(4)]
        easy = [[p["template"] for p in day["prompts"] if p["band"] == "easy"] for day in days]
        flat = [t for day in easy for t in day]
        self.assertEqual(len(flat), len(set(flat)))              # 12 warm-ups in 4 days, none repeated


class RealBankTests(unittest.TestCase):
    """The shipped data: the banded history snapshot and the hand-written banks."""

    @classmethod
    def setUpClass(cls):
        cls.hist = hs.banded_candidates(DAY)
        cls.classics = cl.classics_candidates(DAY, banded=True)

    def test_snapshot_ships(self):
        self.assertTrue(os.path.exists(hs.PATH_BANDED))
        self.assertGreater(len(self.hist), 150)
        self.assertGreater(sum(p["band"] == "easy" for p in self.hist), 15)

    def test_every_question_playable_and_in_its_band(self):
        for p in self.hist + self.classics:
            self.assertGreaterEqual(len(p["answers"]), dd.FLOOR, p["text"])
            self.assertTrue(dd.all_tiers(p["answers"]), p["text"])
        for p in self.hist:
            tpl = next(t for t in hp.HISTORY_POOL if t["key"] == p["template"])
            if p["band"] == "easy":
                self.assertIn(p["threshold"], tpl.get("easy_lines", ()), p["text"])
            else:
                self.assertTrue(dd.round_line(p["threshold"]), p["text"])

    def test_warmups_can_have_hundreds(self):
        self.assertTrue(any(len(p["answers"]) >= 100 for p in self.hist if p["band"] == "easy"))

    def test_no_bare_list_questions(self):
        """Owner 2026-11-17: "Name a player who scored a TD this season" is not a question."""
        pat = re.compile(r"(scored a (TD|touchdown)|with a touchdown|with a (rushing|receiving) TD)( this season)?$", re.I)
        for p in self.hist + self.classics:
            if p["band"] == "easy":
                self.assertFalse(pat.search(p["text"]), p["text"])
        for t in pool.POOL:
            self.assertNotIn(1, t.get("easy_lines", ()) if t["key"] != "qb_starts" else ())

    def test_answers_carry_their_card_details(self):
        p = next(p for p in self.hist if p["band"] == "easy")
        a = p["answers"][0]
        self.assertEqual(set(dd.ANSWER_EXTRAS) - set(a), set())
        self.assertTrue(a["stat_label"])


class StartsTests(unittest.TestCase):
    def test_qb_starts_come_from_finished_games_only(self):
        sched = pd.DataFrame({"game_type": ["REG"] * 3, "week": [1, 2, 3], "home_score": [20, 17, None],
                              "home_qb_id": ["q1", "q1", "q1"], "away_qb_id": ["q2", "q3", "q2"]})
        st = pool.qb_starts(sched, through=3)
        self.assertEqual(st.to_dict(), {"q1": 2.0, "q2": 1.0, "q3": 1.0})
        self.assertEqual(len(pool.qb_starts(sched.drop(columns=["home_qb_id", "away_qb_id"]), 3)), 0)

    def test_text(self):
        tpl = next(t for t in pool.POOL if t["key"] == "qb_starts")
        self.assertEqual(pool.render_text(tpl, 1, 10), "Name a QB who has started a game this season")


class EasierDayTests(unittest.TestCase):
    """Owner 2026-11-22: a little easier. From EASIER_START: 4 easy, 2 medium, 1 hard, and nothing under 15 answers."""
    AFTER = "2026-11-24"

    def _big_pool(self):
        out = []
        for k in ("fantasy", "history"):
            for band, n in (("easy", 150), ("medium", 35), ("hard", 16)):
                out += [_cand(f"{k[0]}{band}{i}", k, band, n + i) for i in range(12)]
        return out

    def test_new_day_shape(self):
        day = dd.pick_day(self.AFTER, self._big_pool())
        self.assertEqual([p["band"] for p in day], ["easy"] * 4 + ["medium"] * 2 + ["hard"])
        self.assertEqual(sum(p["kind"] == "fantasy" for p in day), 2)

    def test_no_question_under_15_answers(self):
        thin = [_cand(f"thin{i}", "history", "hard", 11) for i in range(30)]
        day = dd.pick_day(self.AFTER, self._big_pool() + thin)
        self.assertGreaterEqual(min(len(p["answers"]) for p in day), dd.EASIER_MIN_ANSWERS)

    def test_days_already_played_keep_their_shape(self):
        before = (dt.date.fromisoformat(dd.EASIER_START) - dt.timedelta(days=1)).isoformat()
        day = dd.pick_day(before, self._big_pool())
        self.assertEqual([p["band"] for p in day], ["easy"] * 3 + ["medium"] * 2 + ["hard"] * 2)

    def test_a_recent_question_stays_out_even_if_categories_repeat(self):
        cands = [_cand(f"e{i}", "history", "easy", 150 + i, cat="same") for i in range(6)] + self._big_pool()
        avoid = {c["template"] for c in cands if c["template"].startswith("e") and c["template"][1:].isdigit()}
        day = dd.pick_day(self.AFTER, cands, avoid)
        self.assertFalse({p["template"] for p in day} & avoid)

    def test_cooldown_reads_the_frozen_days(self):
        frozen = {"prompts": [{"template": "frozen_tpl", "group": "frozen_group"}]}
        dd.set_puzzle_store(lambda d: frozen if d == "2026-11-23" else None)
        self.addCleanup(dd.set_puzzle_store, None)
        with tempfile.TemporaryDirectory() as tmp:
            got = dd.recent_templates(tmp, "2026-11-24", self._big_pool())
        self.assertTrue({"frozen_tpl", "frozen_group"} <= got)

    def test_stored_this_season_questions_say_so(self):
        from engine import daily_drive_pool as pp
        puzzle = {"prompts": [{"id": "p:x:2026:w11:t50", "text": "Name a player who has been targeted 50+ times"},
                              {"id": "p:y:2026:w11:t2", "text": "Name a RB with 2+ rushing TDs last week"},
                              {"id": "hh:z:2025:t3", "text": "Name a QB with 3+ playoff wins since 2000"}]}
        pp.say_when(pp.say_when(puzzle))                         # safe to run twice
        self.assertEqual([p["text"] for p in puzzle["prompts"]],
                         ["Name a player who has been targeted 50+ times this season",
                          "Name a RB with 2+ rushing TDs last week", "Name a QB with 3+ playoff wins since 2000"])


if __name__ == "__main__":
    unittest.main()
