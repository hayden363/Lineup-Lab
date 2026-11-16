"""The Daily Drive (engine/daily_drive.py + /api/play/*). No network: every table here is a few hand-built rows,
and the live loaders are replaced by synthetic prompts."""

import collections
import datetime as dt
import os
import re
import tempfile
import unittest
from unittest import mock

import pandas as pd

from engine import daily_drive as dd


def _answers(n, prefix="Player"):
    names = [f"{prefix}{chr(65 + i // 26)}{chr(65 + i % 26)} Smith{i}" for i in range(n)]
    return dd.rank_and_tier([(f"id{i}", nm, (i,)) for i, nm in enumerate(names)])


def _prompt(pid, template, kind, n=14):
    return {"id": pid, "template": template, "kind": kind, "text": f"text {pid}", "category": "cat", "answers": _answers(n)}


def _pool():
    return ([_prompt(f"f:{t}:{w}", t, "fantasy") for t in "abcdef" for w in (1, 2)]
            + [_prompt(f"h:{t}", t, "history") for t in "uvwxyz"])


class TierTests(unittest.TestCase):
    def test_all_six_tiers_present_from_twelve_answers(self):
        self.assertEqual(set(a["tier"] for a in _answers(12)), {1, 2, 3, 4, 5, 6})

    def test_percentile_cuts_on_a_hundred(self):
        c = collections.Counter(a["tier"] for a in _answers(100))
        self.assertEqual([c[t] for t in range(1, 7)], [20, 20, 20, 15, 15, 10])

    def test_most_popular_is_easiest(self):
        a = _answers(20)
        self.assertEqual(a[0]["tier"], 1)
        self.assertEqual(a[-1]["tier"], 6)

    def test_same_name_keeps_the_more_popular_player(self):
        a = dd.rank_and_tier([("x", "Josh Allen", (5,)), ("y", "Josh Allen", (1,)), ("z", "Other Guy", (3,))])
        self.assertEqual([(r["id"], r["name"]) for r in a], [("y", "Josh Allen"), ("z", "Other Guy")])


class BuilderTests(unittest.TestCase):
    def _wk(self):
        rows = []
        for i in range(15):                              # 15 RBs: odd ones score a rushing TD in week 3, all rush for 90 in week 2
            rows.append(dict(player_id=f"r{i}", player_display_name=f"Runner{i} Back", position="RB", week=3,
                             rushing_tds=1 if i % 2 == 0 else 0, rushing_yards=90, fantasy_points_ppr=10.0 + i))
            rows.append(dict(player_id=f"r{i}", player_display_name=f"Runner{i} Back", position="RB", week=2,
                             rushing_tds=0, rushing_yards=90, fantasy_points_ppr=5.0))
        rows.append(dict(player_id="w1", player_display_name="Wide Out", position="WR", week=3, rushing_tds=1,
                         rushing_yards=0, fantasy_points_ppr=30.0))
        return pd.DataFrame(rows)

    def test_week_prompt_matches_source_rows(self):
        wk = self._wk()
        tpl = dict(key="rb_rush_td", scope="week", pos=("RB",), stat="rushing_tds", min=1, text="Name a RB who scored a rushing TD")
        self.assertIsNone(dd.build_fantasy_prompt(tpl, wk, 2026, 3))      # only 8 qualify: below MIN_ANSWERS
        tpl2 = dict(tpl, key="rb_90", stat="rushing_yards", min=90)
        p = dd.build_fantasy_prompt(tpl2, wk, 2026, 2)
        self.assertEqual(len(p["answers"]), 15)                            # the WR is not an RB
        self.assertEqual(p["text"], "Name a RB who scored a rushing TD in Week 2")
        src = set(wk[(wk.week == 2) & (wk.position == "RB") & (wk.rushing_yards >= 90)]["player_display_name"])
        self.assertEqual({a["name"] for a in p["answers"]}, src)

    def test_consensus_rank_orders_popularity_and_unlisted_is_least_popular(self):
        wk = self._wk()
        tpl = dict(key="k", scope="week", pos=("RB",), stat="rushing_yards", min=90, text="t")
        ecr = {"runner5 back|RB": 1.0, "runner6 back|RB": 2.0}
        p = dd.build_fantasy_prompt(tpl, wk, 2026, 3, ecr)
        self.assertEqual([a["name"] for a in p["answers"][:2]], ["Runner5 Back", "Runner6 Back"])
        self.assertEqual(p["answers"][-1]["tier"], 6)
        self.assertNotIn(p["answers"][-1]["name"], ("Runner5 Back", "Runner6 Back"))

    def test_season_scope_sums_weeks_through_the_cutoff(self):
        wk = self._wk()
        tpl = dict(key="s", scope="season", pos=("RB",), stat="rushing_yards", min=180, text="t")
        self.assertEqual(len(dd.build_fantasy_prompt(tpl, wk, 2026, 3)["answers"]), 15)
        self.assertIsNone(dd.build_fantasy_prompt(tpl, wk, 2026, 2))       # only one week counted: 90 < 180

    def test_history_prompt(self):
        hist = pd.DataFrame([dict(player_id=f"p{i}", player_display_name=f"Wideout{i} X", position="WR", season=2010 + i % 5,
                                  receiving_yards=1400 if i < 13 else 900, fantasy_points_ppr=200.0 - i) for i in range(15)])
        career = dd.career_points(hist)
        tpl = dict(key="h", pos=("WR",), stat="receiving_yards", min=1300, text="t")
        p = dd.build_history_prompt(tpl, hist, career)
        self.assertEqual(len(p["answers"]), 13)
        self.assertEqual(p["answers"][0]["name"], "Wideout0 X")            # most career points = most famous = easiest tier
        self.assertEqual(p["answers"][0]["tier"], 1)

    def test_draft_prompt_uses_pick_filters(self):
        rows = [dict(season=2005 + i, round=1, pick=i + 1, gsis_id=f"g{i}", pfr_player_id=f"x{i}", pfr_player_name=f"Qb{i} Name",
                     position="QB", car_av=float(i)) for i in range(14)]
        rows.append(dict(season=1990, round=1, pick=1, gsis_id="old", pfr_player_id="o", pfr_player_name="Too Old", position="QB", car_av=1.0))
        rows.append(dict(season=2010, round=3, pick=70, gsis_id="r3", pfr_player_id="r", pfr_player_name="Round Three", position="QB", car_av=1.0))
        picks = pd.DataFrame(rows)
        tpl = dict(key="d", since=2000, rnd=1, pick=None, pos=("QB",), text="t")
        p = dd.build_draft_prompt(tpl, picks, pd.Series(dtype=float), 2026)
        names = {a["name"] for a in p["answers"]}
        self.assertEqual(len(names), 14)
        self.assertNotIn("Too Old", names)
        self.assertNotIn("Round Three", names)
        self.assertEqual(p["answers"][0]["name"], "Qb13 Name")             # no career points: higher career AV ranks as more famous

    def test_eligible_weeks_need_scores_and_a_past_date(self):
        sched = pd.DataFrame([
            dict(week=1, game_type="REG", gameday="2026-09-10", home_score=20.0),
            dict(week=1, game_type="REG", gameday="2026-09-13", home_score=17.0),
            dict(week=2, game_type="REG", gameday="2026-09-17", home_score=10.0),
            dict(week=2, game_type="REG", gameday="2026-09-20", home_score=None),
            dict(week=3, game_type="REG", gameday="2026-09-27", home_score=9.0)])
        self.assertEqual(dd.eligible_weeks(sched, dt.date(2026, 10, 1)), [1, 3])
        self.assertEqual(dd.eligible_weeks(sched, dt.date(2026, 9, 27)), [1])


class DailyPuzzleTests(unittest.TestCase):
    def test_deterministic_and_shaped(self):
        a = dd.pick_day("2026-11-16", _pool())
        b = dd.pick_day("2026-11-16", list(reversed(_pool())))
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertEqual(collections.Counter(p["kind"] for p in a), {"fantasy": 4, "history": 3})
        self.assertEqual(len({p["template"] for p in a if p["kind"] == "fantasy"}), 4)
        self.assertNotEqual([p["id"] for p in a], [p["id"] for p in dd.pick_day("2026-11-17", _pool())])

    def test_every_prompt_has_enough_answers_and_all_tiers(self):
        for p in dd.pick_day("2026-11-16", _pool() + [_prompt("f:tiny:1", "tiny", "fantasy", n=5)]):
            self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
            self.assertEqual({a["tier"] for a in p["answers"]}, {1, 2, 3, 4, 5, 6})

    def test_recent_prompts_are_avoided_when_the_pool_allows(self):
        first = dd.pick_day("2026-11-16", _pool())
        again = dd.pick_day("2026-11-16", _pool(), recent_ids={p["id"] for p in first})
        self.assertFalse({p["id"] for p in first} & {p["id"] for p in again})

    def test_puzzle_is_cached_to_disk_and_reused(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            def cands(date):
                calls.append(date)
                return _pool()
            one = dd.get_puzzle("2026-11-16", d, cands)
            two = dd.get_puzzle("2026-11-16", d, cands)
            self.assertEqual(len(calls), 1)
            self.assertEqual([p["id"] for p in one["prompts"]], [p["id"] for p in two["prompts"]])
            self.assertEqual(dd.recent_prompt_ids(d, "2026-11-17"), {p["id"] for p in one["prompts"]})

    def test_short_day_is_not_cached(self):
        with tempfile.TemporaryDirectory() as d:
            dd.get_puzzle("2026-11-16", d, lambda date: _pool()[:3])
            self.assertEqual(os.listdir(d), [])

    def test_public_view_has_no_answers(self):
        v = dd.public_view(_prompt("f:a:1", "a", "fantasy"))
        self.assertEqual(set(v), {"id", "text", "category", "count"})


def _bank(*rows):
    return [{"id": f"i{k}", "name": n, "tier": t} for k, (n, t) in enumerate(rows)]


class MatchingTests(unittest.TestCase):
    BANK = _bank(("Josh Allen", 2), ("Jalen Hurts", 3), ("Kenneth Walker III", 1), ("Patrick Mahomes II", 6),
                 ("Allen Robinson II", 4), ("Marvin Harrison Jr.", 5), ("Justin Jefferson", 5))

    def ok(self, typed, used=()):
        return dd.check_answer(self.BANK, typed, used)

    def test_full_name_any_case_punctuation_and_suffix(self):
        self.assertEqual(self.ok("josh allen")["answer"]["name"], "Josh Allen")
        self.assertEqual(self.ok("Kenneth Walker")["answer"]["name"], "Kenneth Walker III")
        self.assertEqual(self.ok("marvin harrison jr")["answer"]["name"], "Marvin Harrison Jr.")
        self.assertEqual(self.ok("  Patrick   Mahomes ")["answer"]["name"], "Patrick Mahomes II")

    def test_initial_and_last_name(self):
        self.assertEqual(self.ok("J. Hurts")["answer"]["name"], "Jalen Hurts")
        self.assertEqual(self.ok("Hurts")["answer"]["name"], "Jalen Hurts")

    def test_ambiguous_last_name_gives_suggestions(self):
        r = self.ok("J. Allen")                               # Josh Allen only (Allen Robinson is a first name): unique
        self.assertTrue(r["ok"])
        bank = self.BANK + _bank(("Jamal Allen", 1))
        r = dd.check_answer(bank, "allen", ())
        self.assertFalse(r["ok"])
        self.assertIn("Josh Allen", r["suggestions"])
        self.assertIn("Jamal Allen", r["suggestions"])

    def test_typo_limits_depend_on_tier(self):
        self.assertTrue(self.ok("Jalen Hurtz")["ok"])                       # tier 3, distance 1: auto-accepted
        r = self.ok("Patrik Mahomes")                                       # tier 6: a suggestion, never an auto-accept
        self.assertFalse(r["ok"])
        self.assertEqual(r["suggestions"], ["Patrick Mahomes II"])
        r = self.ok("Justin Jeffersn")                                      # tier 5: same
        self.assertFalse(r["ok"])
        self.assertEqual(r["suggestions"], ["Justin Jefferson"])
        self.assertFalse(self.ok("Jalen Hrts Xx")["ok"])                    # beyond the distance limit

    def test_short_names_allow_only_one_typo(self):
        bank = _bank(("Al Bo", 2), ("Xx Yy", 2))
        self.assertTrue(dd.check_answer(bank, "Al Bi", ())["ok"])           # distance 1
        self.assertFalse(dd.check_answer(bank, "Ol Bi", ())["ok"])          # distance 2 on a name under 6 letters

    def test_duplicate_answer_rejected(self):
        first = self.ok("Josh Allen")["answer"]
        r = self.ok("josh allen", used=[first["id"]])
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "already used")

    def test_not_in_bank_and_empty(self):
        self.assertEqual(self.ok("Tom Brady")["reason"], "not in the answer bank")
        self.assertFalse(self.ok("   ")["ok"])

    def test_share_card_is_spoiler_free(self):
        s = dd.share_text("2026-11-16", [6, 3, 0, 4, 2, 5, 3])
        self.assertEqual(s.splitlines()[0], "The Daily Drive · Nov 16 · 320 yds")
        self.assertEqual(s.splitlines()[1], "\U0001F3C6\U0001F7E2\U0001F7E5\U0001F535\U0001F7E1\U0001F7E3\U0001F7E2")
        self.assertTrue(s.endswith("/play"))


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        self.today = dd.today_et().isoformat()
        self.puzzle = {"date": self.today, "prompts": dd.pick_day(self.today, _pool())}
        self.server._PLAY_MEM.clear()
        patcher = mock.patch.object(self.server.daily_drive, "get_puzzle", lambda d, cache: {"date": d, "prompts": self.puzzle["prompts"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.server._PLAY_MEM.clear)
        self.server._RATE_BUCKETS.clear()

    def test_daily_never_leaks_answers(self):
        r = self.client.get("/api/play/daily")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertEqual(len(r.json()["prompts"]), 7)
        for p in self.puzzle["prompts"]:
            for a in p["answers"]:
                self.assertNotIn(a["name"], body)
                self.assertNotIn(a["id"] + '"', body)

    def test_check_accepts_and_does_not_echo_the_bank(self):
        p = self.puzzle["prompts"][0]
        a = p["answers"][3]
        r = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": a["name"], "used": []})
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertEqual((j["tier"], j["canonical"]), (a["tier"], a["name"]))
        self.assertEqual(j["yards"], dd.TIERS[a["tier"]][1])
        bad = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": "Nobody Atall", "used": []}).json()
        self.assertEqual(bad, {"ok": False, "reason": "not in the answer bank", "suggestions": []})
        again = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": a["name"], "used": [a["id"]]}).json()
        self.assertEqual(again["reason"], "already used")

    def test_future_and_malformed_dates_refused(self):
        future = (dd.today_et() + dt.timedelta(days=2)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={future}").status_code, 400)
        self.assertEqual(self.client.get("/api/play/daily?date=nonsense").status_code, 400)
        old = (dd.today_et() - dt.timedelta(days=dd.ARCHIVE_DAYS + 5)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={old}").status_code, 400)
        past = (dd.today_et() - dt.timedelta(days=3)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={past}").status_code, 200)

    def test_reveal_and_practice(self):
        p = self.puzzle["prompts"][0]
        j = self.client.get(f"/api/play/reveal?date={self.today}&prompt_id={p['id']}").json()
        self.assertEqual([t["tier"] for t in j["tiers"]], [6, 5, 4, 3, 2, 1])
        self.assertEqual(sum(len(t["answers"]) for t in j["tiers"]), len(p["answers"]))
        self.assertEqual(self.client.get(f"/api/play/reveal?date={self.today}&prompt_id=nope").status_code, 404)
        pr = self.client.get("/api/play/practice").json()
        self.assertLess(pr["date"], self.today)
        self.assertEqual(set(pr["prompt"]), {"id", "text", "category", "count"})

    def test_page_assets_are_served_and_csp_safe(self):
        page = self.client.get("/play")
        self.assertEqual(page.status_code, 200)
        self.assertIn("script-src 'self'", page.headers["content-security-policy"])
        scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", page.text, re.S)
        self.assertTrue(scripts)
        for attrs, inner in scripts:
            self.assertIn("src=", attrs)
            self.assertEqual(inner.strip(), "")                  # no inline JS
        self.assertNotRegex(page.text, r"\son\w+=")             # no inline event handlers
        self.assertEqual(self.client.get("/play.js").status_code, 200)
        self.assertEqual(self.client.get("/play.css").status_code, 200)


if __name__ == "__main__":
    unittest.main()


class FameTest(unittest.TestCase):
    """History rarity: the highest of career points, career AV and the current consensus rank."""

    def test_star_rookie_and_old_legend_are_not_rare(self):
        # rookie: few career points but a top consensus rank; legend: few 1999+ points but huge career AV
        fame = dd.fame_scores([900.0, 40.0, 30.0, 10.0], [None, None, 150.0, 2.0], [None, 8.0, None, None])
        self.assertGreater(fame[1], 0.9)     # consensus rank 8
        self.assertEqual(fame[2], 1.0)       # biggest AV in the set
        self.assertLess(fame[3], 0.5)        # obscure on every signal

    def test_unknown_signals_count_as_no_fame(self):
        self.assertEqual(dd.fame_scores([5.0], [None], [None]), [1.0])   # a set of one is trivially "most famous"
        self.assertEqual(dd.fame_scores([1.0, 2.0], [None, None], [400.0, None])[0], 0.0)
