"""The Daily Drive history pool (engine/daily_drive_history_pool.py). No network: small synthetic nflverse-shaped frames."""

import re
import unittest
from unittest import mock

import pandas as pd

from engine import daily_drive as dd
from engine import daily_drive_history_pool as h

KINDS = {"best", "career", "nseas", "game", "ngame", "post", "postn", "postsum", "draft"}


def _stat_row(pid, name, pos, team, season, **kw):
    row = {c: 0.0 for c in h._SUM_COLS}
    row.update(player_id=pid, name=name, pos=pos, team=team, season=season, headshot=None, games=16)
    row.update(kw)
    return row


def _frames():
    """24 QBs, 8 RBs, 8 WRs, 6 DEs, 2 Ks over 2001-2003 + a 2003 playoff / Super Bowl, plus a small draft table."""
    teams = ["BUF", "MIA", "NE", "NYJ"]
    ps = []
    for i in range(24):                                   # QBs: q0 is the biggest star
        for s in (2001, 2002):
            ps.append(_stat_row(f"q{i}", f"Qb Player{i:02d}", "QB", teams[i % 4], s, passing_yards=5000 - 60 * i - 100 * (s - 2001),
                                passing_tds=40 - i, attempts=500, completions=320, rushing_yards=100 + 20 * i, fantasy_points_ppr=300.0 - 5 * i))
    for i in range(8):
        for s in (2001, 2002, 2003):
            ps.append(_stat_row(f"r{i}", f"Rb Player{i}", "RB", teams[i % 4], s, rushing_yards=1500 - 60 * i, rushing_tds=12 - i,
                                carries=300, receptions=40, receiving_yards=300, fantasy_points_ppr=200.0 - 10 * i))
    for i in range(8):
        ps.append(_stat_row(f"w{i}", f"Wr Player{i}", "WR", teams[i % 4], 2002, receiving_yards=1500 - 90 * i, receiving_tds=10 - i,
                            receptions=100 - 5 * i, targets=150, fantasy_points_ppr=250.0 - 15 * i))
    for i in range(6):
        ps.append(_stat_row(f"d{i}", f"De Player{i}", "DE", teams[i % 4], 2002, def_sacks=18 - 2 * i, def_interceptions=i))
    for i in range(2):
        ps.append(_stat_row(f"k{i}", f"K Player{i}", "K", "NE", 2002, fg_made=36 - 4 * i, fg_long=58 - 4 * i, fg_att=40, pat_made=30))
    ps = h._derive(pd.DataFrame(ps))
    # one big game and one traded player-season (two stints)
    games = pd.DataFrame([dict(player_id="q0", name="Qb Player00", pos="QB", team="BUF", season=2002, week=5, headshot=None,
                               **{c: 0.0 for c in h._SUM_COLS if c not in ("passing_yards", "passing_tds")}, passing_yards=480.0, passing_tds=5.0)])
    games = h._derive(games)
    post = []
    for pid, name, pos, team, week, kw in [
        ("q0", "Qb Player00", "QB", "BUF", 20, dict(passing_yards=310.0, passing_tds=3.0, attempts=40.0)),
        ("q0", "Qb Player00", "QB", "BUF", 21, dict(passing_yards=280.0, passing_tds=1.0, attempts=38.0)),   # Super Bowl, BUF won
        ("q1", "Qb Player01", "QB", "MIA", 21, dict(passing_yards=200.0, passing_tds=1.0, attempts=30.0)),   # Super Bowl, MIA lost
        ("r0", "Rb Player0", "RB", "BUF", 21, dict(rushing_yards=110.0, rushing_tds=1.0, carries=22.0)),
        ("w0", "Wr Player0", "WR", "MIA", 21, dict(receiving_yards=95.0, receiving_tds=2.0, receptions=7.0)),
    ]:
        post.append(dict(_stat_row(pid, name, pos, team, 2003, **kw), week=week))
    post = h._derive(pd.DataFrame(post))
    games["week"] = games["week"].astype("int8")
    sbs = {2003: ("BUF", "MIA", 21)}
    picks = []
    colleges = ["Alabama", "Ohio St."]
    for i in range(40):
        picks.append(dict(season=2001 + i % 3, round=1 + i % 7, pick=1 + i, team=["GNB", "KAN", "OAK", "STL"][i % 4],
                          gsis_id=(f"q{i}" if i < 24 else f"x{i}"), pfr_player_id=f"P{i:04d}", pfr_player_name=f"Pick Player{i:02d}",
                          hof=i == 0, position=["QB", "RB", "WR", "DE", "T", "CB"][i % 6], side="O" if i % 6 < 3 else "D",
                          college=colleges[i % 2], allpro=2 if i < 3 else 0, probowls=max(0, 6 - i // 4), w_av=float(80 - i), car_av=None, seasons_started=5))
    picks = pd.DataFrame(picks)
    # a few rookies: q5 drafted 2001 played 2001 with big numbers (already in ps)
    return ps, games, post, sbs, picks


def _ctx():
    ps, games, post, sbs, picks = _frames()
    return h._prepare_ctx(h.assemble_context(ps, games, post, sbs, picks, 2003, {}))


def _tpl(key):
    return next(t for t in h.HISTORY_POOL if t["key"] == key)


def _custom(kind, **kw):
    base = dict(key="t", cat="x", kind=kind, text="Name a player since 2000", ladder=(1,), label="x")
    base.update(kw)
    return base


class PoolShapeTests(unittest.TestCase):
    def test_pool_size(self):
        self.assertGreaterEqual(len(h.HISTORY_POOL), 170)
        self.assertLessEqual(len(h.HISTORY_POOL), 200)

    def test_unique_keys_and_prefix(self):
        keys = [t["key"] for t in h.HISTORY_POOL]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(k.startswith("h_") for k in keys))

    def test_required_fields_and_known_kinds(self):
        for t in h.HISTORY_POOL:
            for f in ("key", "cat", "kind", "text", "ladder", "label"):
                self.assertIn(f, t, t["key"])
            self.assertIn(t["kind"], KINDS, t["key"])
            self.assertTrue(t["text"].startswith("Name a") or t["text"].startswith("Name {scope}"), t["key"])
            self.assertEqual(list(t["ladder"]), sorted(t["ladder"]), t["key"])
            self.assertTrue(t["ladder"], t["key"])

    def test_every_kind_is_used_and_enough_categories_for_a_five_prompt_day(self):
        self.assertEqual({t["kind"] for t in h.HISTORY_POOL}, KINDS)
        self.assertGreaterEqual(len({t["cat"] for t in h.HISTORY_POOL}), 10)

    def test_no_pre_2000_scope_in_any_template_text(self):
        """Owner rule: at most 5% of all questions may be pre-2000, so every template must say it is 2000-or-later."""
        for t in h.HISTORY_POOL:
            scopes = h.scope_options(t, 2025) or [None]
            for sc in scopes:
                for th in t["ladder"]:
                    txt = h.render_text(t, th, sc)
                    self.assertFalse(re.search(r"\b(19\d\d)\b", txt), txt)
                    self.assertFalse(re.search(r"\b(1980s|1990s)\b", txt), txt)
                    self.assertNotIn("{", txt)
                    self.assertTrue(re.search(r"since 2000|of the (2000s|2010s|2020s)|in the (2000s|2010s|2020s)|the \d{4} NFL Draft|2000s|2010s|2020s", txt), txt)
            self.assertGreaterEqual(t.get("since", 2000), 2000, t["key"])

    def test_scope_options_never_reach_before_2000(self):
        self.assertEqual(list(h.DECADES), ["2000s", "2010s", "2020s"])
        for t in h.HISTORY_POOL:
            if t.get("scope") == "year":
                self.assertGreaterEqual(min(h.scope_options(t, 2025)), 2000)
        self.assertEqual(h.FIRST_SEASON, 2000)

    def test_scoped_templates_have_a_scope_placeholder_and_unscoped_do_not(self):
        for t in h.HISTORY_POOL:
            self.assertEqual("{scope}" in t["text"], bool(t.get("scope")), t["key"])

    def test_game_templates_never_ask_below_the_stored_game_floor(self):
        for t in h.HISTORY_POOL:
            if t["kind"] == "game":
                self.assertIn(t["stat"], h.GAME_FLOORS, t["key"])
                self.assertGreaterEqual(min(t["ladder"]), h.GAME_FLOORS[t["stat"]], t["key"])
            if t["kind"] == "ngame":
                for col, op, v in t["cond"]:
                    self.assertEqual(op, ">=", t["key"])
                    self.assertIn(col, h.GAME_FLOORS, t["key"])
                    self.assertGreaterEqual(v, h.GAME_FLOORS[col], t["key"])

    def test_draft_templates_use_only_frozen_or_table_flags(self):
        for t in h.HISTORY_POOL:
            if t["kind"] == "draft":
                val = t.get("val", "probowls")
                self.assertTrue(val in ("probowls", "allpro") or val.startswith("career:"), t["key"])

    def test_scope_order_is_deterministic_and_complete(self):
        t = _tpl("h_dtm_pb")
        a, b = h.scope_order(t, "2026-11-17"), h.scope_order(t, "2026-11-17")
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), sorted(h.TEAMS))
        self.assertNotEqual(a, h.scope_order(t, "2026-11-18"))


class RenderTests(unittest.TestCase):
    def test_pro_bowl_and_all_pro_phrases(self):
        t = _tpl("h_d_r1_pos")
        self.assertEqual(h.render_text(t, 1, "QB"), "Name a QB taken in the first round since 2000 who made a Pro Bowl")
        self.assertEqual(h.render_text(t, 3, "OL"), "Name an offensive lineman taken in the first round since 2000 who made 3+ Pro Bowls")
        self.assertIn("who was an All-Pro 2+ times", h.render_text(_tpl("h_d_r1_ap"), 2))
        self.assertTrue(h.render_text(_tpl("h_d_first_overall"), 0).endswith("since 2000"))

    def test_scope_text(self):
        self.assertEqual(h.render_text(_tpl("h_dtm_r1"), 0, "GB"), "Name a first-round pick of the Packers since 2000")
        self.assertIn("from Ohio State", h.render_text(_tpl("h_dc_pb"), 0, "Ohio St."))
        self.assertIn("from Ole Miss", h.render_text(_tpl("h_dc_pb"), 0, "Mississippi"))
        self.assertIn("2010s", h.render_text(_tpl("h_dec_qb_yds"), 4000, "2010s"))
        self.assertIn("#3 overall", h.render_text(_tpl("h_d_slot"), 0, 3))
        self.assertIn("fifth-round", h.render_text(_tpl("h_d_round"), 2, 5))

    def test_numbers_use_commas(self):
        self.assertIn("4,500+", h.render_text(_tpl("h_qb_pass_yds"), 4500))


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _ctx()

    def _val(self, per, name):
        return float(per[per["name"] == name]["val"].iloc[0])

    def test_best_season_takes_the_best_not_the_sum(self):
        per = h.evaluate(_custom("best", pos="QB", stat="passing_yards"), self.ctx)
        self.assertEqual(len(per), 24)
        self.assertEqual(self._val(per, "Qb Player00"), 5000)              # 2001, not 2001+2002
        self.assertEqual(set(per.columns), {"player_id", "name", "pos", "team", "headshot", "val", "ppr"})

    def test_career_sums_seasons(self):
        per = h.evaluate(_custom("career", pos="QB", stat="passing_yards"), self.ctx)
        self.assertEqual(self._val(per, "Qb Player00"), 5000 + 4900)

    def test_nseas_counts_seasons_over_the_line(self):
        per = h.evaluate(_custom("nseas", pos="QB", stat="passing_yards", line=4900), self.ctx)
        self.assertEqual(self._val(per, "Qb Player00"), 2)
        self.assertEqual(self._val(per, "Qb Player01"), 1)                 # 4940 then 4840

    def test_position_filter_and_decade_scope(self):
        per = h.evaluate(_custom("best", pos="RB", stat="rushing_yards"), self.ctx)
        self.assertEqual(set(per["pos"]), {"RB"})
        t = _custom("best", pos="QB", stat="passing_yards", scope="decade")
        self.assertEqual(len(h.evaluate(t, self.ctx, "2000s")), 24)
        self.assertEqual(len(h.evaluate(t, self.ctx, "2010s")), 0)          # no 2010s data: the scope really filters seasons

    def test_team_scope_uses_that_teams_rows(self):
        per = h.evaluate(_custom("best", pos="QB", stat="passing_yards", scope="team"), self.ctx, "BUF")
        self.assertTrue(set(per["team"]) <= {"BUF"})
        self.assertEqual(len(per), 6)

    def test_game_and_ngame(self):
        per = h.evaluate(_custom("game", pos="QB", stat="passing_yards"), self.ctx)
        self.assertEqual(self._val(per, "Qb Player00"), 480)
        n = h.evaluate(_custom("ngame", pos="QB", cond=[("passing_tds", ">=", 5)]), self.ctx)
        self.assertEqual(self._val(n, "Qb Player00"), 1)

    def test_post_kinds_and_super_bowl_flags(self):
        po = h.evaluate(_custom("post", pos="QB", stat="passing_yards"), self.ctx)
        self.assertEqual(self._val(po, "Qb Player00"), 310)
        sb = h.evaluate(_custom("post", pos="QB", stat="passing_yards", sb=True), self.ctx)
        self.assertEqual(self._val(sb, "Qb Player00"), 280)
        won = h.evaluate(_custom("postn", pos="QB", sb=True, won_sb=True, cond=[("attempts", ">=", 1)]), self.ctx)
        self.assertEqual(list(won["name"]), ["Qb Player00"])
        lost = h.evaluate(_custom("postn", pos="QB", sb=True, lost_sb=True, cond=[("attempts", ">=", 1)]), self.ctx)
        self.assertEqual(list(lost["name"]), ["Qb Player01"])
        total = h.evaluate(_custom("postsum", pos="QB", stat="passing_yards"), self.ctx)
        self.assertEqual(self._val(total, "Qb Player00"), 590)

    def test_rookie_and_round_filters_need_a_draft_row(self):
        # q0 was drafted 2001 round 1, q1 in 2002; undrafted players (r*, w*) can never be rookies / round-filtered
        rk = h.evaluate(_custom("best", pos="QB", stat="passing_yards", rookie=True), self.ctx)
        self.assertEqual(self._val(rk, "Qb Player00"), 5000)
        self.assertTrue(set(rk["name"]) <= set(self.ctx["ps"][self.ctx["ps"]["pos"] == "QB"]["name"]))
        rd = h.evaluate(_custom("best", pos="RB", stat="rushing_yards", rd=(1, 7)), self.ctx)
        self.assertTrue(rd.empty)

    def test_draft_flags_scope_and_team_mapping(self):
        self.assertEqual(set(self.ctx["draft"]["dteam"]) , {"GB", "KC", "LV", "LA"})        # GNB/KAN/OAK/STL -> today's codes
        hof = h.evaluate(_custom("draft", hof=True), self.ctx)
        self.assertEqual(list(hof["name"]), ["Pick Player00"])
        top = h.evaluate(_custom("draft", pick=(1, 5)), self.ctx)
        self.assertEqual(len(top), 5)
        team = h.evaluate(_custom("draft", scope="team"), self.ctx, "GB")
        self.assertTrue(set(team["team"]) <= {"GB"})
        col = h.evaluate(_custom("draft", scope="college"), self.ctx, "Alabama")
        self.assertEqual(len(col), 20)
        pos = h.evaluate(_custom("draft", scope="pos"), self.ctx, "QB")
        self.assertEqual(len(pos), 7)
        pb = h.evaluate(_custom("draft", val="probowls", min_pb=5), self.ctx)
        self.assertTrue((pb["val"] >= 5).all())
        ap = h.evaluate(_custom("draft", val="allpro", min_ap=1), self.ctx)
        self.assertEqual(len(ap), 3)

    def test_draft_career_stat_comes_from_frozen_table(self):
        per = h.evaluate(_custom("draft", dpos="QB", val="career:passing_yards"), self.ctx)
        self.assertEqual(self._val(per, "Pick Player00"), 5000 + 4900)

    def test_draft_year_slot_and_round_scopes(self):
        self.assertEqual(len(h.evaluate(_custom("draft", scope="year"), self.ctx, 2001)), sum(1 for i in range(40) if i % 3 == 0))
        self.assertEqual(list(h.evaluate(_custom("draft", scope="slot"), self.ctx, 3)["name"]), ["Pick Player02"])
        self.assertTrue((h.evaluate(_custom("draft", scope="round"), self.ctx, 2)["val"] >= 0).all())


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _ctx()

    def test_prompt_shape_and_real_tiering(self):
        tpl = _custom("best", key="h_test", pos="QB", stat="passing_yards", ladder=(3000, 4000, 4800), text="Name a QB with {t}+ passing yards since 2000", label="pass yds")
        p = h.build_history_prompt(tpl, self.ctx)
        self.assertIsNotNone(p)
        for f in ("id", "template", "kind", "text", "category", "cat", "answers", "threshold", "group", "scope"):
            self.assertIn(f, p)
        self.assertEqual(p["kind"], "history")
        self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
        self.assertTrue(dd.has_hall_of_famer(p["answers"]))
        self.assertTrue(p["category"].startswith("NFL history"))
        self.assertEqual(p["answers"][0]["tier"], 1)
        for a in p["answers"]:
            for extra in ("team", "position", "headshot", "stat", "stat_label"):
                self.assertIn(extra, a)
        self.assertEqual({a["stat_label"] for a in p["answers"]}, {"pass yds"})
        # the ladder walk picks the highest rung that still leaves TARGET_MIN answers
        self.assertEqual(p["threshold"], 4000)

    def test_too_few_answers_means_no_prompt(self):
        tpl = _custom("best", pos="RB", stat="rushing_yards", ladder=(1400, 1500), label="rush yds")
        self.assertIsNone(h.build_history_prompt(tpl, self.ctx))

    def test_too_broad_prompt_is_dropped_not_widened(self):
        tpl = _custom("best", pos="QB", stat="passing_yards", ladder=(1000,), label="pass yds")
        with mock.patch.object(h, "HIST_MAX_ANSWERS", 10):
            self.assertIsNone(h.build_history_prompt(tpl, self.ctx))

    def test_scoped_template_falls_through_to_a_passing_scope(self):
        tpl = _custom("draft", key="h_scoped", scope="college", ladder=(0,), text="Name a player from {scope} drafted since 2000")
        tpl["colleges"] = ["Nowhere State", "Alabama"]                       # the first option has no answers
        with mock.patch.object(h, "scope_order", lambda t, d, last=2025: ["Nowhere State", "Alabama"]):
            p = h.build_any_scope(tpl, self.ctx, "2026-11-17")
        self.assertIsNotNone(p)
        self.assertEqual(p["scope"], "Alabama")
        self.assertIn("Alabama", p["text"])

    def test_history_candidates_builds_from_a_ctx_and_is_deterministic(self):
        tpls = [t for t in h.HISTORY_POOL if t["key"] in ("h_dc_pb", "h_dtm_pb", "h_d_first_overall")]
        a = h.history_candidates("2026-11-17", ecr_rank={}, templates=tpls, ctx=self.ctx)
        b = h.history_candidates("2026-11-17", ecr_rank={}, templates=tpls, ctx=self.ctx)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        ids = [p["id"] for p in a]
        self.assertEqual(len(ids), len(set(ids)))

    def test_candidates_feed_pick_day_unchanged(self):
        """The prompts are shaped for dd.pick_day (kind 'history', template, group, cat, answers)."""
        qb = _custom("best", key="h_qb", pos="QB", stat="passing_yards", ladder=(3000, 4000), text="Name a QB with {t}+ passing yards since 2000", label="pass yds", cat="Season marks")
        p = h.build_history_prompt(qb, self.ctx)
        with mock.patch.object(dd, "HISTORY_ENABLED", True), mock.patch.object(dd, "N_FANTASY", 0), mock.patch.object(dd, "N_HISTORY", 1):
            day = dd.pick_day("2026-11-17", [p])
        self.assertEqual([x["id"] for x in day], [p["id"]])


class FailSoftTests(unittest.TestCase):
    def test_unreadable_season_data_gives_no_prompts_not_an_exception(self):
        with mock.patch.object(h, "build_context", side_effect=RuntimeError("download failed")):
            self.assertEqual(h.history_candidates("2026-11-17", ecr_rank={}), [])

    def test_a_broken_template_is_skipped(self):
        ctx = _ctx()
        bad = _custom("best", key="h_bad", pos="QB", stat="no_such_column")
        good = _custom("draft", key="h_good", ladder=(0,))
        out = h.history_candidates("2026-11-17", ecr_rank={}, templates=[bad, good], ctx=ctx)
        self.assertEqual([p["template"] for p in out], ["h_good"])

    def test_missing_super_bowl_schedule_drops_only_super_bowl_prompts(self):
        ps, games, post, _sbs, picks = _frames()
        ctx = h._prepare_ctx(h.assemble_context(ps, games, post, {}, picks, 2003, {}))
        sb = _custom("postn", pos="QB", sb=True, cond=[("attempts", ">=", 1)])
        self.assertTrue(h.evaluate(sb, ctx).empty)


if __name__ == "__main__":
    unittest.main()
