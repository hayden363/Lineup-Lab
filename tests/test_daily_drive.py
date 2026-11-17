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
    return dd.rank_and_tier([(f"id{i}", nm, (i,), {"team": "SEA", "position": "WR", "headshot": f"https://img/{i}.png",
                                                    "stat": 500 + i, "stat_label": "rec yds"}) for i, nm in enumerate(names)])


def _prompt(pid, template, kind, n=14):
    return {"id": pid, "template": template, "kind": kind, "text": f"text {pid}", "category": "cat", "answers": _answers(n)}


def _pool():
    return ([_prompt(f"f:{t}:2026:w{w}:t100", t, "fantasy") for t in "abcdefghij" for w in (1, 2)]
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

    def _season_wk(self):
        """30 WRs: wr i has 100*(i+1)/... receiving yards over two weeks, a big game in week 2."""
        rows = []
        for i in range(30):
            for w, yds in ((1, 20 * (i + 1)), (2, 10 * (i + 1))):
                rows.append(dict(player_id=f"w{i}", player_display_name=f"Wide{i} Out", position="WR", week=w, recent_team="SEA" if w == 1 else "DEN",
                                 headshot_url=f"https://img/w{i}.png", receiving_yards=float(yds), receiving_tds=1.0 if i % 3 == 0 else 0.0,
                                 rushing_tds=0.0, rushing_yards=0.0, receptions=3.0, fantasy_points_ppr=float(yds) / 10))
        rows.append(dict(player_id="r1", player_display_name="Some Back", position="RB", week=1, recent_team="NE", headshot_url=None,
                         receiving_yards=900.0, receiving_tds=0.0, rushing_tds=0.0, rushing_yards=0.0, receptions=3.0, fantasy_points_ppr=9.0))
        return pd.DataFrame(rows)

    TPL = dict(key="wr_rec_yds", per="season", pos=("WR",), stat="receiving_yards", ladder=(300, 400, 500, 600, 700, 800, 1000),
               label="rec yds", text="Name a WR with {t}+ receiving yards this season")

    def test_threshold_ladder_picks_the_highest_rung_that_keeps_enough_answers(self):
        wk = self._season_wk()                            # season totals are 30*(i+1): 30..900; 15+ players need >= 480ish
        p = dd.build_season_prompt(self.TPL, wk, 2026, 2)
        # rungs: 500 -> players with 30*(i+1)>=500 (i>=16): 14 players; 400 -> i>=13: 17 players -> 400 is the highest with >= 15
        self.assertEqual(p["threshold"], 400)
        self.assertEqual(len(p["answers"]), 17)
        self.assertEqual(p["text"], "Name a WR with 400+ receiving yards this season")
        self.assertEqual(p["category"], "This season · through Week 2")
        self.assertEqual(p["id"], "f:wr_rec_yds:2026:w2:t400")
        src = set(wk[wk.position == "WR"].groupby("player_display_name")["receiving_yards"].sum().loc[lambda v: v >= 400].index)
        self.assertEqual({a["name"] for a in p["answers"]}, src)       # the RB with 900 is not a WR

    def test_answer_extras_come_from_the_data(self):
        p = dd.build_season_prompt(self.TPL, self._season_wk(), 2026, 2)
        a = next(x for x in p["answers"] if x["name"] == "Wide29 Out")
        self.assertEqual((a["team"], a["position"], a["stat"], a["stat_label"]), ("DEN", "WR", 900, "rec yds"))   # latest team
        self.assertEqual(a["headshot"], "https://img/w29.png")
        self.assertEqual(set(a), {"id", "name", "tier", "team", "position", "headshot", "stat", "stat_label"})

    def test_through_week_only_counts_finished_weeks(self):
        wk = self._season_wk()
        p1 = dd.build_season_prompt(dict(self.TPL, ladder=(100, 200, 300)), wk, 2026, 1)     # week 1 only: 20*(i+1) <= 600
        self.assertEqual(p1["threshold"], 300)                       # week 1 only: totals 20..600; 300+ leaves 16
        self.assertEqual(max(a["stat"] for a in p1["answers"]), 600)
        self.assertNotEqual(p1["id"], dd.build_season_prompt(dict(self.TPL, ladder=(100, 200, 300)), wk, 2026, 2)["id"])

    def test_new_week_makes_new_ids_and_rungs_climb(self):
        wk = self._season_wk()
        a = dd.build_season_prompt(self.TPL, wk[wk.week <= 1], 2026, 1)
        b = dd.build_season_prompt(self.TPL, wk, 2026, 2)
        self.assertNotEqual(a["id"], b["id"])
        self.assertLess(a["threshold"], b["threshold"] + 1)
        self.assertGreater(b["threshold"], a["threshold"])      # more weeks played -> a higher rung still has 15 answers

    def test_unreachable_ladder_returns_none_and_small_set_falls_back_above_floor(self):
        wk = self._season_wk()
        self.assertIsNone(dd.build_season_prompt(dict(self.TPL, ladder=(5000,)), wk, 2026, 2))
        p = dd.build_season_prompt(dict(self.TPL, ladder=(690, 450)), wk, 2026, 2)   # 690 -> 9 answers (below the floor), 450 -> 16 -> in band
        self.assertEqual(p["threshold"], 450)
        p = dd.build_season_prompt(dict(self.TPL, ladder=(690, 600, 5000)), wk, 2026, 2)   # 600 -> 11 answers: below MIN_ANSWERS
        self.assertIsNone(p)

    def test_single_game_templates_use_the_best_game_and_the_label(self):
        wk = self._season_wk()
        tpl = dict(self.TPL, key="wr_game_rec", per="game", ladder=(50, 100, 150, 200), label="rec yds in a game",
                   text="Name a WR with a {t}+ yard receiving game this season")
        p = dd.build_season_prompt(tpl, wk, 2026, 2)      # best game = week 1: 20*(i+1); 15+ players need >= 320 -> rung 200 has 21 players
        self.assertEqual(p["threshold"], 200)
        top = next(a for a in p["answers"] if a["name"] == "Wide29 Out")
        self.assertEqual((top["stat"], top["stat_label"]), (600, "rec yds in a game"))

    def test_tds_stat_adds_rushing_and_receiving(self):
        wk = self._season_wk().assign(rushing_tds=2.0)
        tpl = dict(key="any_td", per="season", pos=("WR",), stat="tds", ladder=(3, 4), label="total TD", text="Name a player with {t}+ total TDs this season")
        p = dd.build_season_prompt(tpl, wk, 2026, 2)      # 2 weeks x 2 rushing = 4, +2 for the 10 multiples-of-3 receivers
        self.assertEqual(p["threshold"], 4)
        self.assertEqual(len(p["answers"]), 30)

    def test_consensus_rank_orders_popularity_and_unlisted_is_least_popular(self):
        wk = self._season_wk()
        ecr = {"wide20 out|WR": 1.0, "wide21 out|WR": 2.0}
        p = dd.build_season_prompt(self.TPL, wk, 2026, 2, ecr)
        self.assertEqual([a["name"] for a in p["answers"][:2]], ["Wide20 Out", "Wide21 Out"])
        self.assertEqual(p["answers"][-1]["tier"], 6)
        self.assertNotIn(p["answers"][-1]["name"], ("Wide20 Out", "Wide21 Out"))
        self.assertEqual(p["answers"][2]["name"], "Wide29 Out")      # unlisted: tie-break by season PPR points

    def test_ladder_steps_down_until_a_hall_of_famer_exists(self):
        wk = self._season_wk()
        with mock.patch.object(dd, "has_hall_of_famer", side_effect=lambda ans: len(ans) >= 20):
            p = dd.build_season_prompt(self.TPL, wk, 2026, 2)
        self.assertGreaterEqual(len(p["answers"]), 20)
        self.assertEqual(p["threshold"], 300)

    def test_real_templates_are_season_scoped_with_ladders(self):
        self.assertGreaterEqual(len(dd.FANTASY_TEMPLATES), 14)
        self.assertEqual(len({t["key"] for t in dd.FANTASY_TEMPLATES}), len(dd.FANTASY_TEMPLATES))
        for t in dd.FANTASY_TEMPLATES:
            self.assertIn("this season", t["text"])
            self.assertNotRegex(t["text"], r"(?i)week")
            self.assertIn("{t}", t["text"])
            self.assertEqual(list(t["ladder"]), sorted(t["ladder"]))
            self.assertGreaterEqual(len(t["ladder"]), 3)
            self.assertIn(t["per"], ("season", "game"))

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
        self.assertEqual(collections.Counter(p["kind"] for p in a), {"fantasy": 7})     # history is off
        self.assertEqual(len({p["template"] for p in a}), 7)
        self.assertNotEqual([p["id"] for p in a], [p["id"] for p in dd.pick_day("2026-11-17", _pool())])

    def test_every_prompt_in_a_day_has_a_hall_of_famer(self):
        bad = dict(_prompt("f:bad:2026:w1:t1", "bad", "fantasy"), answers=[dict(a, tier=min(a["tier"], 5)) for a in _answers(14)])
        for d in range(1, 20):
            day = dd.pick_day(f"2026-11-{d:02d}", _pool() + [bad])
            self.assertEqual(len(day), 7)
            self.assertNotIn("bad", {p["template"] for p in day})
            for p in day:
                self.assertTrue(any(a["tier"] == 6 for a in p["answers"]), p["id"])

    def test_mix_is_two_current_plus_five_history_from_mix_start(self):
        a = dd.pick_day(dd.MIX_START, _pool())
        n_hist = sum(1 for c in _pool() if c["kind"] == "history")
        self.assertEqual(collections.Counter(p["kind"] for p in a), {"fantasy": 7 - min(5, n_hist), "history": min(5, n_hist)})
        self.assertEqual(dd.day_size(), 7)

    def test_every_prompt_has_enough_answers_and_all_tiers(self):
        for p in dd.pick_day("2026-11-16", _pool() + [_prompt("f:tiny:2026:w1:t5", "tiny", "fantasy", n=5)]):
            self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
            self.assertEqual({a["tier"] for a in p["answers"]}, {1, 2, 3, 4, 5, 6})

    def test_no_template_on_consecutive_days_when_the_pool_allows(self):
        day = dt.date(2026, 11, 1)
        prev = set()
        for i in range(40):
            big = [_prompt(f"f:t{k}:2026:w1:t1", f"t{k}", "fantasy") for k in range(16)]      # >= 14 templates: 7 fresh ones always exist
            picks = dd.pick_day((day + dt.timedelta(days=i)).isoformat(), big, avoid_templates=prev)
            cur = {p["template"] for p in picks}
            self.assertEqual(len(cur), 7)
            self.assertFalse(cur & prev, f"day {i} repeats {cur & prev}")
            prev = cur

    def test_variety_falls_back_when_the_pool_is_too_small(self):
        small = [_prompt(f"f:{t}:2026:w1:t1", t, "fantasy") for t in "abcdefgh"]    # 8 templates, yesterday used 7: only 1 fresh
        picks = dd.pick_day("2026-11-16", small, avoid_templates=set("abcdefg"))
        self.assertEqual(len(picks), 7)
        self.assertIn("h", {p["template"] for p in picks})

    def test_near_duplicate_groups_never_share_a_day(self):
        pool = [dict(_prompt(f"f:{t}:2026:w1:t1", t, "fantasy"), group="g1" if t in "ab" else t) for t in "abcdefghij"]
        for d in range(1, 15):
            ts = {p["template"] for p in dd.pick_day(f"2026-11-{d:02d}", pool)}
            self.assertFalse({"a", "b"} <= ts)

    def test_puzzle_is_cached_to_disk_and_reused(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            def cands(date):
                calls.append(date)
                return _pool()
            one = dd.get_puzzle("2026-11-15", d, cands)             # both before MIX_START: the all-current days
            two = dd.get_puzzle("2026-11-15", d, cands)
            self.assertEqual(len(calls), 1)
            self.assertEqual([p["id"] for p in one["prompts"]], [p["id"] for p in two["prompts"]])
            nxt = dd.get_puzzle("2026-11-16", d, cands)
            # 10 templates, 7 used yesterday: the 3 unused ones are all taken and only 4 repeats are forced
            self.assertEqual(len({p["template"] for p in one["prompts"]} & {p["template"] for p in nxt["prompts"]}), 4)

    def test_old_format_cache_is_regenerated(self):
        with tempfile.TemporaryDirectory() as d:
            import json
            with open(os.path.join(d, "puzzle_2026-11-16.json"), "w") as fh:
                json.dump({"date": "2026-11-16", "prompts": [{"id": "old"}] * 7}, fh)        # pre-v2 file: no "v"
            puz = dd.get_puzzle("2026-11-16", d, lambda date: _pool())
            self.assertEqual(puz["v"], dd.PUZZLE_VERSION)
            self.assertNotIn("old", [p["id"] for p in puz["prompts"]])

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
        self.assertEqual(s.splitlines()[1], "\U0001F3C8\u26D3\uFE0F\u274C\U0001F680\u26A1\U0001F4A3\u26D3\uFE0F")
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
        self.assertEqual(len(r.json()["prompts"]), dd.day_size())
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

    def test_check_returns_answer_extras_and_a_token_that_verifies(self):
        from engine import daily_drive_scores as dds
        p = self.puzzle["prompts"][0]
        a = p["answers"][3]
        with mock.patch.dict(os.environ, {"APP_SECRET_KEY": "extras-test-secret"}):
            j = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": a["name"], "used": []}).json()
            for k in ("team", "position", "headshot", "stat", "stat_label"):
                self.assertEqual(j[k], a[k], k)
            self.assertEqual(dds.verify_token(self.today, j["token"])[1:], (a["id"], a["tier"]))
            yards, tiers = dds.score_from_tokens(self.today, [j["token"]], self.puzzle["prompts"])
            self.assertEqual(yards, dd.TIERS[a["tier"]][1])

    def _finished_today(self):
        """Signed in with today's score saved: the only way today's answer sheets unlock."""
        s = self.server
        for pt in (mock.patch.object(s, "_play_user", return_value={"id": 7}),
                   mock.patch.object(s.db, "drive_my_day", return_value={"date": self.today, "yards": 300, "tiers": [3]})):
            pt.start(); self.addCleanup(pt.stop)

    def test_reveal_has_details_per_answer_matching_the_names(self):
        self._finished_today()
        p = self.puzzle["prompts"][0]
        j = self.client.get(f"/api/play/reveal?date={self.today}&prompt_id={p['id']}").json()
        bank = {a["name"]: a for a in p["answers"]}
        for t in j["tiers"]:
            self.assertEqual([d["name"] for d in t["details"]], t["answers"])
            for d in t["details"]:
                self.assertEqual({k: d[k] for k in ("team", "position", "headshot", "stat", "stat_label")},
                                 {k: bank[d["name"]][k] for k in ("team", "position", "headshot", "stat", "stat_label")})

    def test_daily_still_hides_extras(self):
        body = self.client.get("/api/play/daily").text
        for p in self.puzzle["prompts"]:
            for a in p["answers"]:
                self.assertNotIn(a["headshot"], body)

    def test_old_format_bank_rows_still_answer_with_null_extras(self):
        old = {"id": "x1", "name": "Old Row", "tier": 3}
        self.assertEqual(dd.answer_details(old), {"team": None, "position": None, "headshot": None, "stat": None, "stat_label": None})

    def test_future_and_malformed_dates_refused(self):
        future = (dd.today_et() + dt.timedelta(days=2)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={future}").status_code, 400)
        self.assertEqual(self.client.get("/api/play/daily?date=nonsense").status_code, 400)
        old = (dd.today_et() - dt.timedelta(days=dd.ARCHIVE_DAYS + 5)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={old}").status_code, 400)
        past = (dd.today_et() - dt.timedelta(days=3)).isoformat()
        self.assertEqual(self.client.get(f"/api/play/daily?date={past}").status_code, 200)

    def test_todays_reveal_is_locked_until_a_signed_in_player_has_finished(self):
        s = self.server
        p = self.puzzle["prompts"][0]
        url = f"/api/play/reveal?prompt_id={p['id']}"
        rare = [a["name"] for a in p["answers"] if a["tier"] == 6]
        # signed out (with or without the date): locked, and no answer leaks in the error
        for u in (url, url + f"&date={self.today}"):
            r = self.client.get(u)
            self.assertEqual(r.status_code, 403)
            self.assertIn("unlock", r.json()["detail"])
            for name in rare:
                self.assertNotIn(name, r.text)
        # signed in but no saved score today: locked
        with mock.patch.object(s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(s.db, "drive_my_day", return_value=None) as my_day:
            self.assertEqual(self.client.get(url).status_code, 403)
            my_day.assert_called_with(self.today, 7, None)       # looked up by account only, never a device id
        # signed in, DB down: fail closed
        with mock.patch.object(s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(s.db, "drive_my_day", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get(url).status_code, 403)
        # signed in with today's score saved: open
        with mock.patch.object(s, "_play_user", return_value={"id": 7}), \
             mock.patch.object(s.db, "drive_my_day", return_value={"date": self.today, "yards": 300, "tiers": [3]}):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_past_days_reveal_is_open_to_anyone(self):
        past = (dd.today_et() - dt.timedelta(days=1)).isoformat()
        p = self.puzzle["prompts"][0]
        r = self.client.get(f"/api/play/reveal?date={past}&prompt_id={p['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["tier"] for t in r.json()["tiers"]], [6, 5, 4, 3, 2, 1])

    def test_reveal_and_practice(self):
        self._finished_today()
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


# ---------------------------------------------------------------------------------------- saved scores (v2)
from engine import daily_drive_scores as ds   # noqa: E402

KEY = b"k" * 32


def _tokens_for(date, prompts, picks):
    """picks = {prompt index: answer index} -> signed tokens, exactly as /api/play/check would issue them."""
    return [ds.sign_token(date, prompts[i]["id"], prompts[i]["answers"][a]["id"], prompts[i]["answers"][a]["tier"], key=KEY)
            for i, a in picks.items()]


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.day = "2026-11-16"
        self.prompts = dd.pick_day(self.day, _pool())

    def test_round_trip(self):
        a = self.prompts[2]["answers"][4]
        tok = ds.sign_token(self.day, self.prompts[2]["id"], a["id"], a["tier"], key=KEY)
        self.assertEqual(ds.verify_token(self.day, tok, key=KEY), (self.prompts[2]["id"], a["id"], a["tier"]))

    def test_tampering_is_rejected(self):
        a = self.prompts[0]["answers"][0]
        tok = ds.sign_token(self.day, self.prompts[0]["id"], a["id"], a["tier"], key=KEY)
        left, right = tok.split(".")
        forged_payload = ds._b64(f"{self.prompts[0]['id']}|{a['id']}|6".encode())          # bump the tier to Highlight Reel TD
        for bad in (forged_payload + "." + right, left + "." + ds._b64(b"x" * 16), left, "", "a.b.c", None, 12, left + "." + right[:-2]):
            self.assertIsNone(ds.verify_token(self.day, bad, key=KEY), bad)
        self.assertIsNone(ds.verify_token("2026-11-15", tok, key=KEY))                      # a real token is bound to its date
        self.assertIsNone(ds.verify_token(self.day, tok, key=b"z" * 32))                    # and to the server's key

    def test_no_key_means_scoring_off(self):
        with mock.patch.dict(os.environ, {"APP_SECRET_KEY": ""}), mock.patch("engine.crypto._load_or_create_key", side_effect=OSError):
            self.assertFalse(ds.enabled())
            self.assertIsNone(ds.sign_token(self.day, "p", "a", 3))

    def test_env_secret_is_used(self):
        with mock.patch.dict(os.environ, {"APP_SECRET_KEY": "abc"}):
            self.assertTrue(ds.enabled())
            tok = ds.sign_token(self.day, "p", "a", 3)
            self.assertEqual(ds.verify_token(self.day, tok), ("p", "a", 3))

    def test_yards_are_recomputed_from_the_puzzle(self):
        toks = _tokens_for(self.day, self.prompts, {0: 0, 1: 5, 3: 13})         # tiers come from the bank, not the caller
        yards, tiers = ds.score_from_tokens(self.day, toks, self.prompts, key=KEY)
        want = [self.prompts[0]["answers"][0]["tier"], self.prompts[1]["answers"][5]["tier"], 0, self.prompts[3]["answers"][13]["tier"], 0, 0, 0]
        self.assertEqual(tiers, want)
        self.assertEqual(yards, sum(dd.TIERS[t][1] for t in want if t))

    def test_duplicate_prompt_tokens_count_once(self):
        toks = _tokens_for(self.day, self.prompts, {0: 13}) + _tokens_for(self.day, self.prompts, {0: 0})
        _, tiers = ds.score_from_tokens(self.day, toks, self.prompts, key=KEY)
        self.assertEqual(tiers[0], self.prompts[0]["answers"][13]["tier"])       # the first token wins, never the best

    def test_forged_unknown_or_inconsistent_tokens_fail_the_whole_submit(self):
        a = self.prompts[0]["answers"][0]
        with self.assertRaises(ValueError):
            ds.score_from_tokens(self.day, ["nonsense"], self.prompts, key=KEY)
        with self.assertRaises(ValueError):                                       # signed, but for a prompt not in today's puzzle
            ds.score_from_tokens(self.day, [ds.sign_token(self.day, "f:zz:9", a["id"], a["tier"], key=KEY)], self.prompts, key=KEY)
        with self.assertRaises(ValueError):                                       # signed with a tier the bank doesn't have
            ds.score_from_tokens(self.day, [ds.sign_token(self.day, self.prompts[0]["id"], a["id"], 6, key=KEY)], self.prompts, key=KEY)
        with self.assertRaises(ValueError):
            ds.score_from_tokens(self.day, [ds.sign_token(self.day, self.prompts[0]["id"], "no-such-id", 1, key=KEY)], self.prompts, key=KEY)

    def test_device_hash(self):
        h = ds.device_hash("a" * 32)
        self.assertEqual(len(h), 64)
        self.assertNotIn("a" * 32, h)
        for bad in (None, "", "short", "has space " * 4, "x" * 100, 5):
            self.assertIsNone(ds.device_hash(bad))


class StatsMathTests(unittest.TestCase):
    def test_distribution_buckets(self):
        d = ds.distribution([0, 99, 100, 199, 250, 599, 600, 700, 700])
        self.assertEqual([b["count"] for b in d], [2, 2, 1, 0, 0, 1, 3])
        self.assertEqual((d[0]["lo"], d[0]["hi"], d[-1]["lo"], d[-1]["hi"]), (0, 99, 600, 700))
        self.assertEqual(len(d), 7)

    def test_average_median_players(self):
        s = ds.day_stats([100, 200, 600, 400])
        self.assertEqual((s["players"], s["average_yards"], s["median_yards"]), (4, 325.0, 300.0))
        self.assertNotIn("percentile", s)
        e = ds.day_stats([])
        self.assertEqual((e["players"], e["average_yards"], e["median_yards"]), (0, None, None))

    def test_percentile_counts_strictly_lower_scores_among_the_others(self):
        ys = [100, 200, 300, 400, 500]
        self.assertEqual(ds.percentile_beaten(ys, 500), 100)
        self.assertEqual(ds.percentile_beaten(ys, 300), 50)
        self.assertEqual(ds.percentile_beaten(ys, 100), 0)
        self.assertEqual(ds.percentile_beaten([300, 300, 300], 300), 0)            # ties don't count as beaten
        self.assertIsNone(ds.percentile_beaten([300], 300))                        # alone: nobody to beat
        self.assertEqual(ds.day_stats(ys, 400)["percentile"], 75)

    def test_streaks(self):
        self.assertEqual(ds.streaks([], "2026-11-16"), (0, 0))
        run = ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-16"]
        self.assertEqual(ds.streaks(run, "2026-11-16"), (1, 3))                    # today only; the 12-14 run is the longest
        self.assertEqual(ds.streaks(run + ["2026-11-15"], "2026-11-16"), (5, 5))
        self.assertEqual(ds.streaks(["2026-11-14", "2026-11-15"], "2026-11-16"), (2, 2))   # not played today yet: still alive
        self.assertEqual(ds.streaks(["2026-11-13", "2026-11-14"], "2026-11-16"), (0, 2))   # a day was missed: broken
        self.assertEqual(ds.streaks(["2026-11-16", "2026-11-16"], "2026-11-16"), (1, 1))

    def test_my_history_payload(self):
        rows = [{"date": "2026-11-14", "yards": 300, "tiers": [3, 3, 3, 3, 3, 3, 3]},
                {"date": "2026-11-16", "yards": 100, "tiers": [1, 0, 0, 0, 0, 0, 0]},
                {"date": "2026-11-15", "yards": 500, "tiers": [6, 5, 4, 3, 2, 1, 0]}]
        h = ds.my_history(rows, "2026-11-16")
        self.assertEqual((h["games"], h["average_yards"], h["best_yards"], h["current_streak"], h["longest_streak"]), (3, 300.0, 500, 3, 3))
        self.assertEqual([g["date"] for g in h["history"]], ["2026-11-16", "2026-11-15", "2026-11-14"])
        self.assertEqual(h["history"][1]["emoji"], "\U0001F3C8\U0001F4A3\U0001F680\u26D3\uFE0F\u26A1\u2705\u274C")
        self.assertEqual(h["spark"], [300, 500, 100])                               # oldest to newest


class ScoreEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        s = self.server
        self.today = dd.today_et().isoformat()
        prompts = dd.pick_day(self.today, _pool())
        self.prompts = prompts
        s._PLAY_MEM.clear(); s._RATE_BUCKETS.clear(); s._PLAY_STATS_CACHE.clear()
        for p in (mock.patch.dict(os.environ, {"APP_SECRET_KEY": "endpoint-test-secret"}),
                  mock.patch.object(s.daily_drive, "get_puzzle", lambda d, cache: {"date": d, "prompts": prompts})):
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(s._PLAY_MEM.clear)
        self.db = {"scores": {}}                                                    # (date, who) -> row; one per device and per user
        self.user = None

        def save(game_date, yards, tiers, user_id=None, device_hash=None, now=None):
            for who in [("u", user_id)] * (user_id is not None) + [("d", device_hash)] * (device_hash is not None):
                if (game_date, who) in self.db["scores"]:
                    return self.db["scores"][(game_date, who)], False
            row = {"date": game_date, "yards": yards, "tiers": list(tiers)}
            for who in [("u", user_id)] * (user_id is not None) + [("d", device_hash)] * (device_hash is not None):
                self.db["scores"][(game_date, who)] = row
            return row, True

        def my_day(game_date, user_id=None, device_hash=None):
            return self.db["scores"].get((game_date, ("u", user_id))) or self.db["scores"].get((game_date, ("d", device_hash)))

        def day_yards(game_date):
            return [r["yards"] for r in {id(r): r for (d, _), r in self.db["scores"].items() if d == game_date}.values()]

        for p in (mock.patch.object(s.db, "save_drive_score", side_effect=save), mock.patch.object(s.db, "drive_my_day", side_effect=my_day),
                  mock.patch.object(s.db, "drive_day_yards", side_effect=day_yards),
                  mock.patch.object(s.db, "drive_history", side_effect=lambda uid, limit=1000: [
                      r for (d, who), r in sorted(self.db["scores"].items(), reverse=True) if who == ("u", uid)]),
                  mock.patch.object(s, "current_user", side_effect=lambda req: self.user)):
            p.start(); self.addCleanup(p.stop)

    def _check(self, i, a, date=None):
        p = self.prompts[i]
        r = self.client.post("/api/play/check", json={"date": date or self.today, "prompt_id": p["id"], "answer": p["answers"][a]["name"], "used": []})
        self.assertTrue(r.json()["ok"])
        return r.json()

    def _tokens(self, picks):
        return [self._check(i, a)["token"] for i, a in picks.items()]

    def test_check_returns_a_verifiable_token_and_failures_do_not(self):
        j = self._check(0, 3)
        self.assertEqual(ds.verify_token(self.today, j["token"])[1:], (j["answer_id"], j["tier"]))
        bad = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": self.prompts[0]["id"], "answer": "Nobody Atall", "used": []}).json()
        self.assertNotIn("token", bad)

    def test_score_is_recomputed_server_side_and_saved_once_per_device(self):
        toks = self._tokens({0: 0, 1: 4, 2: 13})
        dev = "d" * 24
        r = self.client.post("/api/play/score", json={"date": self.today, "device_id": dev, "tokens": toks, "yards": 9999}).json()
        want = sum(dd.TIERS[self.prompts[i]["answers"][a]["tier"]][1] for i, a in {0: 0, 1: 4, 2: 13}.items())
        self.assertTrue(r["available"] and r["saved"])
        self.assertEqual(r["yards"], want)
        self.assertEqual(r["stats"]["players"], 1)
        again = self.client.post("/api/play/score", json={"date": self.today, "device_id": dev, "tokens": self._tokens({0: 13, 1: 13}), "yards": 1}).json()
        self.assertFalse(again["saved"])
        self.assertEqual(again["yards"], want)                                       # the original score stands
        self.assertEqual(self.client.post("/api/play/score", json={"date": self.today, "device_id": "e" * 24, "tokens": []}).json()["yards"], 0)

    def test_one_score_per_signed_in_user_across_devices(self):
        self.user = {"id": 7}
        toks = self._tokens({0: 0})
        a = self.client.post("/api/play/score", json={"date": self.today, "device_id": "a" * 24, "tokens": toks}).json()
        b = self.client.post("/api/play/score", json={"date": self.today, "device_id": "b" * 24, "tokens": self._tokens({1: 0, 2: 0})}).json()
        self.assertTrue(a["saved"])
        self.assertFalse(b["saved"])
        self.assertEqual(b["yards"], a["yards"])

    def test_forged_tokens_wrong_day_and_missing_identity_are_refused(self):
        dev = "f" * 24
        post = lambda **kw: self.client.post("/api/play/score", json={"date": self.today, "device_id": dev, **kw})
        self.assertEqual(post(tokens=["abc.def"]).status_code, 400)
        good = self._tokens({0: 0})
        self.assertEqual(post(tokens=good + ["abc.def"]).status_code, 400)           # one bad token spoils the submit
        left, right = good[0].split(".")
        self.assertEqual(post(tokens=[ds._b64(ds._unb64(left) + b"0") + "." + right]).status_code, 400)
        self.assertEqual(self.client.post("/api/play/score", json={"date": self.today, "tokens": good}).status_code, 400)   # signed out, no device
        yesterday = (dd.today_et() - dt.timedelta(days=1)).isoformat()
        old = self.client.post("/api/play/score", json={"date": yesterday, "device_id": dev, "tokens": []})
        self.assertEqual(old.status_code, 400)                                       # only today's game is scored
        self.assertEqual(self.client.post("/api/play/score", json={"date": "2999-01-01", "device_id": dev, "tokens": []}).status_code, 400)
        self.assertEqual(self.db["scores"], {})

    def test_yesterdays_token_cannot_score_today(self):
        yesterday = (dd.today_et() - dt.timedelta(days=1)).isoformat()
        stale = self._check(0, 0, date=yesterday)["token"]
        r = self.client.post("/api/play/score", json={"date": self.today, "device_id": "g" * 24, "tokens": [stale]})
        self.assertEqual(r.status_code, 400)

    def test_score_is_rate_limited(self):
        codes = [self.client.post("/api/play/score", json={"date": self.today, "device_id": "h" * 24, "tokens": []}).status_code for _ in range(12)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10:], [429, 429])

    def test_stats_endpoint(self):
        for n, picks in enumerate(({0: 0}, {0: 0, 1: 0}, {0: 13, 1: 13, 2: 13})):
            self.client.post("/api/play/score", json={"date": self.today, "device_id": chr(97 + n) * 24, "tokens": self._tokens(picks)})
        anon = self.client.get(f"/api/play/stats?date={self.today}").json()
        self.assertTrue(anon["available"])
        self.assertEqual(anon["players"], 3)
        self.assertEqual(len(anon["distribution"]), 7)
        self.assertEqual(sum(b["count"] for b in anon["distribution"]), 3)
        self.assertNotIn("percentile", anon)
        mine = self.client.get(f"/api/play/stats?date={self.today}&device_id={'c' * 24}").json()   # the top scorer
        self.assertEqual(mine["percentile"], 100)
        self.assertEqual(mine["your_yards"], max(r["yards"] for r in {id(r): r for r in self.db["scores"].values()}.values()))

    def test_me_signed_out_and_signed_in(self):
        self.assertEqual(self.client.get("/api/play/me").json(), {"signed_in": False})
        self.user = {"id": 5}
        self.assertEqual(self.client.get("/api/play/me").json()["games"], 0)
        self.client.post("/api/play/score", json={"date": self.today, "device_id": "m" * 24, "tokens": self._tokens({0: 0, 1: 0})})
        j = self.client.get("/api/play/me").json()
        self.assertEqual((j["signed_in"], j["available"], j["games"], j["current_streak"], j["longest_streak"]), (True, True, 1, 1, 1))
        self.assertEqual(j["history"][0]["date"], self.today)
        self.assertEqual(len(j["history"][0]["emoji"]) > 0, True)
        self.assertEqual(j["best_yards"], j["average_yards"])

    def test_me_streak_over_several_days(self):
        self.user = {"id": 5}
        today = dd.today_et()
        for back in (0, 1, 2, 4):
            d = (today - dt.timedelta(days=back)).isoformat()
            self.db["scores"][(d, ("u", 5))] = {"date": d, "yards": 100 + back, "tiers": [1] * 7}
        j = self.client.get("/api/play/me").json()
        self.assertEqual((j["games"], j["current_streak"], j["longest_streak"]), (4, 3, 3))


class DegradedTests(unittest.TestCase):
    """The table is missing or the database is down: the game plays and nothing 500s."""

    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        s = self.server
        self.today = dd.today_et().isoformat()
        self.prompts = dd.pick_day(self.today, _pool())
        s._PLAY_MEM.clear(); s._RATE_BUCKETS.clear(); s._PLAY_STATS_CACHE.clear()
        boom = RuntimeError("relation daily_drive_scores does not exist")
        for p in (mock.patch.dict(os.environ, {"APP_SECRET_KEY": "endpoint-test-secret"}),
                  mock.patch.object(s.daily_drive, "get_puzzle", lambda d, cache: {"date": d, "prompts": self.prompts}),
                  mock.patch.object(s.db, "save_drive_score", side_effect=boom), mock.patch.object(s.db, "drive_my_day", side_effect=boom),
                  mock.patch.object(s.db, "drive_day_yards", side_effect=boom), mock.patch.object(s.db, "drive_history", side_effect=boom),
                  mock.patch.object(s, "current_user", side_effect=boom)):
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(s._PLAY_MEM.clear)

    def test_game_endpoints_still_work(self):
        self.assertEqual(self.client.get("/api/play/daily").status_code, 200)
        p = self.prompts[0]
        j = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": p["answers"][0]["name"], "used": []}).json()
        self.assertTrue(j["ok"] and j["token"])

    def test_score_stats_me_degrade_quietly(self):
        p = self.prompts[0]
        tok = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": p["answers"][0]["name"], "used": []}).json()["token"]
        r = self.client.post("/api/play/score", json={"date": self.today, "device_id": "z" * 24, "tokens": [tok]})
        self.assertEqual((r.status_code, r.json()), (200, {"available": False, "saved": False}))
        r = self.client.get(f"/api/play/stats?date={self.today}&device_id={'z' * 24}")
        self.assertEqual((r.status_code, r.json()), (200, {"available": False}))
        self.assertEqual(self.client.get("/api/play/me").json(), {"signed_in": False})    # even the session lookup failing is harmless

    def test_me_when_history_query_fails(self):
        with mock.patch.object(self.server, "current_user", return_value={"id": 1}):
            self.assertEqual(self.client.get("/api/play/me").json(), {"signed_in": True, "available": False})

    def test_no_signing_secret_switches_scoring_off_but_not_the_game(self):
        with mock.patch.dict(os.environ, {"APP_SECRET_KEY": ""}), mock.patch("engine.crypto._load_or_create_key", side_effect=OSError):
            p = self.prompts[0]
            j = self.client.post("/api/play/check", json={"date": self.today, "prompt_id": p["id"], "answer": p["answers"][0]["name"], "used": []}).json()
            self.assertTrue(j["ok"])
            self.assertNotIn("token", j)
            r = self.client.post("/api/play/score", json={"date": self.today, "device_id": "z" * 24, "tokens": []})
            self.assertEqual(r.json(), {"available": False, "saved": False})


class DbHelperTests(unittest.TestCase):
    """engine/db.py helpers against a fake cursor (no database)."""

    class Cur:
        def __init__(self, results):
            self.results, self.sql = list(results), []

        def execute(self, q, params=None):
            self.sql.append((" ".join(q.split()), params))

        def fetchone(self):
            return self.results.pop(0) if self.results else None

        def fetchall(self):
            return self.results.pop(0) if self.results else []

    def _patch(self, cur):
        from contextlib import contextmanager
        from engine import db

        @contextmanager
        def conn():
            yield cur
        return mock.patch.object(db, "_conn", conn)

    def test_save_inserts_with_do_nothing_and_reports_created(self):
        from engine import db
        row = {"game_date": dt.date(2026, 11, 16), "yards": 300, "tiers": [3] * 7}
        cur = self.Cur([row])
        with self._patch(cur):
            out, created = db.save_drive_score("2026-11-16", 300, [3] * 7, None, "h" * 64, now=1.0)
        self.assertTrue(created)
        self.assertEqual(out, {"date": "2026-11-16", "yards": 300, "tiers": [3] * 7})
        self.assertIn("ON CONFLICT DO NOTHING", cur.sql[0][0])

    def test_repeat_returns_the_original_and_attaches_a_signed_in_user(self):
        from engine import db
        row = {"game_date": dt.date(2026, 11, 16), "yards": 100, "tiers": [1] + [0] * 6}
        cur = self.Cur([None, None, row])                # insert conflicts; user lookup misses; device lookup finds the old row
        with self._patch(cur):
            out, created = db.save_drive_score("2026-11-16", 999, [6] * 7, 4, "h" * 64)
        self.assertFalse(created)
        self.assertEqual(out["yards"], 100)
        self.assertTrue(any(q.startswith("UPDATE daily_drive_scores SET user_id") for q, _ in cur.sql))


class NavigationAndMigrationTests(unittest.TestCase):
    def _read(self, path):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path), encoding="utf-8") as fh:
            return fh.read()

    def test_sidebar_entry_links_to_play(self):
        html = self._read("static/index.html")
        self.assertRegex(html, r'<a class="nav-item[^"]*"[^>]*href="/play"')
        self.assertIn("The Daily Drive", html)
        self.assertNotRegex(html, r'<a class="nav-item[^"]*"[^>]*data-tab')            # not a tab: the router must ignore it

    def test_sign_in_gate_links_to_play(self):
        js = self._read("static/app.js")
        gate = js[js.index("function renderGateAuth"):js.index("async function onGateAuthSuccess")]
        self.assertIn('href="/play"', gate)

    def test_landing_has_nav_and_hero_links(self):
        js = self._read("static/landing.js")
        nav = js[js.index("function Nav("):js.index("/* ---------- HERO")]
        self.assertGreaterEqual(nav.count('href="/play"'), 2)                           # desktop bar and the phone menu
        hero = js[js.index("/* ---------- HERO"):js.index("function Footer")]
        self.assertIn('href="/play"', hero)

    def test_play_page_has_back_link_and_no_inline_js(self):
        html, js = self._read("static/play.html"), self._read("static/play.js")
        self.assertIn('"ll-brand", href: "/"', js)                              # the Lineup Lab top bar links home on every screen
        self.assertIn('"Open app"', js)                                         # signed in: back into the app
        self.assertIn('href: "/?auth=login"', js)                               # signed out: the landing page's sign-in buttons
        self.assertIn('src="/play-field.js"', html)

    def test_migration_has_the_unique_constraints_and_rls(self):
        sql = self._read("migrations/20261116000000_daily_drive_scores.sql")
        self.assertIn("CREATE TABLE IF NOT EXISTS public.daily_drive_scores", sql)
        self.assertRegex(sql, r"UNIQUE INDEX[^;]*\(game_date, user_id\)\s+WHERE user_id IS NOT NULL")
        self.assertRegex(sql, r"UNIQUE INDEX[^;]*\(game_date, device_hash\)\s+WHERE device_hash IS NOT NULL")
        self.assertIn("REFERENCES public.users (id) ON DELETE CASCADE", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        for col in ("yards", "tiers", "device_hash", "created_at"):
            self.assertIn(col, sql)


class PlayVisualTest(unittest.TestCase):
    """The immersive /play front end: static checks only (no browser): CSP-safe, reduced motion, optional API fields."""

    def _r(self, p):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p), encoding="utf-8") as f:
            return f.read()

    def test_no_inline_script_and_no_external_assets(self):
        html = self._r("static/play.html")
        for attrs, inner in re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S):
            self.assertIn("src=", attrs)
            self.assertEqual(inner.strip(), "")
        self.assertIn('src="/team-themes.js"', html)
        self.assertIn('id="dd-live"', html)                       # aria-live region for results
        for f in ("static/play.js", "static/play-field.js", "static/play.css"):
            self.assertNotRegex(self._r(f), r"https?://(?!www\.w3\.org)")   # no CDNs or remote assets
        # the page loads only the app's own Google Fonts (same as index.html; the CSP allows exactly these hosts)
        self.assertNotRegex(html, r"https?://(?!fonts\.googleapis\.com|fonts\.gstatic\.com)")

    def test_reduced_motion_is_handled_in_css_and_js(self):
        self.assertIn("prefers-reduced-motion: reduce", self._r("static/play.css"))
        js = self._r("static/play.js")
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn("if (REDUCED", js)                          # particles, scan hold and count-ups skip when reduced
        self.assertEqual(js.count("requestAnimationFrame(loop)") >= 1, True)

    def test_optional_player_fields_degrade_gracefully(self):
        js = self._r("static/play.js")
        for key in ("r.team", "r.position", "r.headshot", "r.stat", "r.stat_label"):
            self.assertIn(key, js)
        self.assertIn('"/api/img?url="', js)                      # headshots go through the same-origin proxy
        self.assertIn("initials(", js)                            # fallback badge
        self.assertIn("tr.details", js)                           # reveal details are optional

    def test_tier_colors_emoji_and_leaderboard_wiring(self):
        js, css = self._r("static/play.js"), self._r("static/play.css")
        for e in ("\u2705", "\u26A1", "\u26D3\uFE0F", "\U0001F680", "\U0001F4A3", "\U0001F3C8", "\u274C"):
            self.assertIn(e, js)
        self.assertNotIn("\U0001F7E5", js)                       # old sacked square
        for t in ("--t1: #b3bccd", "--t2: #6fd0ff", "--t3: #ff4b55", "--t4: #b866ff", "--t5: #fff04d", "--t6: #ffab1a"):
            self.assertIn(t, css)                                 # grey, light blue, red, purple, yellow, gold
        self.assertIn("/api/play/leaderboard", js)
        for name in ("Checkdown", "Quick Slant", "Chain Mover", "Chunk Play", "Bomb", "Highlight Reel TD"):
            self.assertIn(name, js)                               # the six plays
        self.assertIn("DDField.create", js)                       # the field scene lives in play-field.js
        self.assertLess(len(js) + len(css) + len(self._r("static/play-field.js")), 215_000)              # stays light (190k -> 200k for the NFL field + pixel players Nov 16; 215k for the desktop columns, podium leaderboard and tabbed end screen Nov 17)


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


class SeasonFameTest(unittest.TestCase):
    """A star with a big career but a low current consensus rank must not be the rare (Highlight Reel TD) answer."""

    def test_career_star_is_not_rare(self):
        rows = [dict(player_id=f"p{i}", name=f"Player {i}", pos="QB", team="X", headshot=None, val=150.0 + i, ppr=50.0)
                for i in range(12)]
        rows[0].update(player_id="star", name="Star Qb")
        per = pd.DataFrame(rows)
        career = {"star": 3000.0, **{f"p{i}": 10.0 * i for i in range(1, 12)}}
        ans = dd._answers_at(per, 100, {}, "rush yds", fame=(career, {}))
        self.assertEqual({a["name"]: a["tier"] for a in ans}["Star Qb"], 1)


class LeaderboardTest(unittest.TestCase):
    def test_ranks_ties_and_my_rank_among_everyone(self):
        top = [{"name": "a", "yards": 500}, {"name": "b", "yards": 400}, {"name": "c", "yards": 400}, {"name": "d", "yards": 300}]
        body = ds.leaderboard_body(top, [500, 450, 400, 400, 300, 120], my_yards=400)
        self.assertEqual([r["rank"] for r in body["top"]], [1, 2, 2, 4])
        self.assertEqual(body["you"], {"rank": 3, "yards": 400})          # the anonymous 450 counts
        self.assertEqual(body["players"], 6)
        self.assertIsNone(ds.leaderboard_body([], [], None)["you"])

    def test_board_rows_carry_the_spoiler_free_drive(self):
        top = [{"name": "a", "yards": 185, "tiers": [6, 5, 0, 0, 0, 0, 0]}, {"name": "b", "yards": 10}]
        body = ds.leaderboard_body(top, [185, 10], my_yards=10, my_tiers=[1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(body["top"][0]["emoji"], ds.emoji_row([6, 5, 0, 0, 0, 0, 0]))
        self.assertNotIn("emoji", body["top"][1])                          # older rows without tiers still render
        self.assertEqual(body["you"]["emoji"], ds.emoji_row([1, 0, 0, 0, 0, 0, 0]))
        self.assertNotIn("name", body["you"])

    def test_tier_colors_follow_owner_order(self):
        self.assertEqual([dd.tier_info(t)["emoji"] for t in range(1, 7)],
                         ["\u2705", "\u26A1", "\u26D3\uFE0F", "\U0001F680", "\U0001F4A3", "\U0001F3C8"])


class LeaderboardEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        s = self.server
        s._RATE_BUCKETS.clear(); s._PLAY_STATS_CACHE.clear()
        today = dd.today_et().isoformat()
        p = mock.patch.object(s.daily_drive, "get_puzzle", lambda d, cache: {"date": d, "prompts": dd.pick_day(today, _pool())})
        p.start(); self.addCleanup(p.stop)

    def test_board_and_degraded(self):
        s = self.server
        with mock.patch.object(s.db, "drive_leaderboard", return_value=[{"name": "hayden", "yards": 455}]), \
             mock.patch.object(s.db, "drive_day_yards", return_value=[455, 300]), \
             mock.patch.object(s.db, "drive_my_day", return_value={"date": "x", "yards": 300, "tiers": [1]}):
            j = self.client.get("/api/play/leaderboard?device_id=0123456789abcdef0123456789abcdef").json()
        self.assertEqual(j["top"], [{"rank": 1, "name": "hayden", "yards": 455}])
        self.assertEqual(j["you"], {"rank": 2, "yards": 300, "emoji": "\u2705"})      # your own drive row, spoiler-free
        s._PLAY_STATS_CACHE.clear()
        with mock.patch.object(s.db, "drive_leaderboard", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get("/api/play/leaderboard").json(), {"available": False})
