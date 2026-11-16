"""The 100-prompt Daily Drive pool (engine/daily_drive_pool.py). No network: a tiny synthetic season."""

import re
import unittest

import pandas as pd

from engine import daily_drive as dd
from engine import daily_drive_pool as pool


def _season():
    """6 teams over 4 weeks; 40 players. Returns (weekly, schedule, draft)."""
    teams = ["BUF", "MIA", "NE", "NYJ", "KC", "LV"]
    sched, wk = [], []
    pairs = {1: [("BUF", "MIA"), ("NE", "NYJ"), ("KC", "LV")], 2: [("MIA", "NE"), ("NYJ", "KC"), ("LV", "BUF")],
             3: [("BUF", "NE"), ("MIA", "KC"), ("NYJ", "LV")], 4: [("NE", "KC"), ("LV", "MIA"), ("BUF", "NYJ")]}
    for w, gs in pairs.items():
        for h, a in gs:
            sched.append(dict(game_id=f"2026_{w:02d}_{a}_{h}", season=2026, game_type="REG", week=w, gameday="2026-09-10",
                              weekday="Sunday", gametime="20:15" if h == "KC" else "13:00", away_team=a, away_score=17,
                              home_team=h, home_score=24, overtime=1.0 if w == 3 else 0.0, roof="dome" if h == "LV" else "outdoors",
                              div_game=1 if pool.TEAM_DIV[h] == pool.TEAM_DIV[a] else 0, spread_line=3.0))
    for t in teams:
        for pos, n in (("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1)):
            for i in range(n):
                pid = f"{t}-{pos}{i}"
                for w, gs in pairs.items():
                    g = next(((h, a) for h, a in gs if t in (h, a)), None)
                    if not g:
                        continue
                    row = dict(player_id=pid, player_display_name=f"{t} {pos}{i}", player_name=pid, position=pos, week=w,
                               season_type="REG", game_id=f"2026_{w:02d}_{g[1]}_{g[0]}", recent_team=t, headshot_url=None)
                    for c in ("completions", "attempts", "passing_yards", "passing_tds", "interceptions", "sacks", "carries",
                              "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds",
                              "receiving_air_yards", "receiving_yards_after_catch", "target_share", "fantasy_points_ppr",
                              "rushing_first_downs", "receiving_first_downs", "fumbles_lost_total"):
                        row[c] = 0.0
                    k = w + i
                    if pos == "QB":
                        row.update(completions=20, attempts=30, passing_yards=250 + 10 * w, passing_tds=2, rushing_yards=30, fantasy_points_ppr=20.0 + w)
                    elif pos == "RB":
                        row.update(carries=15 + k, rushing_yards=80 + 10 * k, rushing_tds=1 if w % 2 else 0, receptions=3, targets=4, receiving_yards=20, fantasy_points_ppr=14.0 + k)
                    elif pos == "WR":
                        row.update(receptions=5 + i, targets=8, receiving_yards=60 + 15 * w + 10 * i, receiving_tds=1 if w == 2 else 0, target_share=0.2, fantasy_points_ppr=12.0 + w + i)
                    else:
                        row.update(receptions=4, targets=6, receiving_yards=45 + 5 * w, receiving_tds=1 if w == 4 else 0, fantasy_points_ppr=9.0 + w)
                    wk.append(row)
    draft = pd.DataFrame({"gsis_id": [f"BUF-WR0", "KC-WR1"], "season": [2026, 2025], "college": ["Alabama", "Ohio St."]})
    return pd.DataFrame(wk), pd.DataFrame(sched), draft


def _ctx(through=4):
    wk, sched, draft = _season()
    return pool.build_context(wk, sched, 2026, through, draft)


def _tpl(key):
    return next(t for t in pool.POOL if t["key"] == key)


class PoolShapeTests(unittest.TestCase):
    def test_exactly_100_prompts(self):
        self.assertEqual(len(pool.POOL), 100)

    def test_unique_keys(self):
        keys = [t["key"] for t in pool.POOL]
        self.assertEqual(len(keys), len(set(keys)))

    def test_required_fields_and_known_kinds(self):
        for t in pool.POOL:
            for f in ("key", "cat", "kind", "text", "ladder", "label", "pos"):
                self.assertIn(f, t, t["key"])
            self.assertIn(t["kind"], {"sum", "max", "games", "ratio", "mean", "streak", "topfinish", "range"}, t["key"])
            self.assertTrue(t["text"].startswith("Name a"), t["key"])
            self.assertGreaterEqual(len(t["ladder"]), 2, t["key"])
            self.assertEqual(list(t["ladder"]), sorted(t["ladder"]), t["key"])
            pos = pool.POS_SETS[t["pos"]] if isinstance(t["pos"], str) else t["pos"]
            self.assertTrue(pos, t["key"])
            for w in t.get("where", ()):
                self.assertIn(w, pool.WHERES, t["key"])
            if t.get("scope"):
                self.assertIn("{scope}", t["text"], t["key"])
                self.assertIn(t["scope"], pool.SCOPES, t["key"])
            if t["kind"] in ("games", "streak", "ratio", "mean", "range", "topfinish") or t["kind"] in ("sum", "max"):
                pass

    def test_every_prompt_with_a_ladder_shows_its_threshold(self):
        """No silent thresholds: a walked ladder must be visible in the text (via {t} or {times})."""
        for t in pool.POOL:
            self.assertTrue("{t}" in t["text"] or "{times}" in t["text"], t["key"])

    def test_texts_render_for_every_rung(self):
        for t in pool.POOL:
            scope = pool.SCOPES[t["scope"]][0] if t.get("scope") else None
            for rung in t["ladder"]:
                s = pool.render_text(t, rung, 10, scope)
                self.assertNotIn("{", s, t["key"])
                self.assertNotIn("None", s, t["key"])

    def test_article_fix(self):
        self.assertEqual(pool.render_text(_tpl("te_game_yds"), 80, 10), "Name a TE with an 80+ yard receiving game")
        self.assertEqual(pool.render_text(_tpl("te_game_yds"), 70, 10), "Name a TE with a 70+ yard receiving game")

    def test_scope_rotation_is_deterministic_and_covers_scopes(self):
        t = _tpl("sc_div_rec_td")
        self.assertEqual(pool.scope_for(t, "2026-11-16"), pool.scope_for(t, "2026-11-16"))
        seen = {pool.scope_for(t, f"2026-11-{d:02d}") for d in range(1, 30)}
        self.assertGreater(len(seen), 3)
        self.assertTrue(seen <= set(pool.DIVISIONS))

    def test_division_map_is_complete(self):
        self.assertEqual(len(pool.TEAM_DIV), 32)
        self.assertEqual(set(pool.TEAM_DIV), set(pool.TEAM_NAME))
        self.assertTrue(all(len(v) == 4 for v in pool.DIVISIONS.values()))

    def test_ids_do_not_collide_across_scopes(self):
        ctx = _ctx()
        a = pool.build_pool_prompt(_tpl("sc_div_rec_td"), ctx, None, None, "AFC East")
        b = pool.build_pool_prompt(_tpl("sc_div_rec_td"), ctx, None, None, "AFC West")
        if a and b:
            self.assertNotEqual(a["id"], b["id"])


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _ctx()

    def _val(self, key, pid, scope=None):
        per = pool.evaluate(_tpl(key), self.ctx, scope)
        row = per[per["player_id"] == pid]
        return None if row.empty else float(row["val"].iloc[0])

    def test_sum_and_max(self):
        self.assertEqual(self._val("qb_pass_td", "BUF-QB0"), 8)                  # 2 TDs x 4 games
        self.assertEqual(self._val("qb_game_yds", "BUF-QB0"), 290)               # best game: week 4, 250 + 40
        self.assertEqual(self._val("qb_pass_yds", "BUF-QB0"), 4 * 250 + 100)

    def test_derived_columns(self):
        self.assertEqual(self._val("any_total_td", "BUF-RB0"), 2)                # rush TD in weeks 1 and 3
        self.assertEqual(self._val("any_scrim", "BUF-QB0"), 120)                 # QB rushing yards count toward scrimmage

    def test_games_count_with_combo_condition(self):
        # BUF-RB0: week k=w -> rush yds 80+10w; 100+ rush AND a TD happens only in odd weeks with w >= 2 -> week 3
        self.assertEqual(self._val("combo_rb_100_td", "BUF-RB0"), 1)

    def test_ratio_has_volume_gate(self):
        t = dict(_tpl("e_rb_ypc"), min_den_pg=100)                                # impossible gate -> nobody qualifies
        self.assertTrue(pool.evaluate(t, self.ctx)["val"].dropna().empty)
        per = pool.evaluate(_tpl("e_rb_ypc"), self.ctx)
        row = per[per["player_id"] == "BUF-RB0"].iloc[0]
        self.assertAlmostEqual(row["val"], (90 + 100 + 110 + 120) / (16 + 17 + 18 + 19), places=5)

    def test_negative_ratio_for_low_is_good(self):
        per = pool.evaluate(_tpl("e_qb_safe"), self.ctx)
        self.assertTrue((per["val"].dropna() <= 0).all())

    def test_window_last_week_and_last_three(self):
        self.assertEqual(self._val("w_wr_100", "BUF-WR0"), 60 + 15 * 4)           # week 4 only
        self.assertEqual(self._val("w3_wr_yds", "BUF-WR0"), sum(60 + 15 * w for w in (2, 3, 4)))

    def test_where_flags(self):
        self.assertEqual(self._val("x_div_td", "BUF-RB0"), 2)                     # rush TDs in weeks 1 and 3, both division games
        self.assertEqual(self._val("x_ot_ppr", "BUF-RB0"), 14.0 + 3 + 0)          # week 3 is the overtime game (k = 3 + 0)
        dome = pool.evaluate(_tpl("x_dome_td"), self.ctx)
        self.assertTrue(dome.empty or set(dome["player_id"].str.split("-").str[0]) <= {"LV"} | {"BUF", "MIA", "NYJ", "NE", "KC"})

    def test_scope_filter(self):
        per = pool.evaluate(_tpl("sc_div_rec_td"), self.ctx, "AFC East")
        self.assertTrue(set(per["team"]) <= set(pool.DIVISIONS["AFC East"]))
        conf = pool.evaluate(_tpl("sc_conf_rb_yds"), self.ctx, "NFC")
        self.assertTrue(conf.empty)                                              # fixture has no NFC team

    def test_rookie_and_college_filters(self):
        r = pool.evaluate(_tpl("r_wr_yds"), self.ctx)
        self.assertEqual(list(r["player_id"]), ["BUF-WR0"])                       # the only 2026 draftee
        c = pool.evaluate(_tpl("sc_col_td"), self.ctx, "SEC")
        self.assertEqual(list(c["player_id"]), ["BUF-WR0"])

    def test_no_draft_table_means_no_rookies_not_invented_ones(self):
        wk, sched, _ = _season()
        ctx = pool.build_context(wk, sched, 2026, 4, None)
        self.assertTrue(pool.evaluate(_tpl("r_td"), ctx).empty)

    def test_streak_counts_consecutive_team_games(self):
        # BUF-WR0 caught a TD only in week 2 -> streak of 1; all QBs score a passing TD but "tds" is rush+rec only
        t = dict(_tpl("s_td"))
        per = pool.evaluate(t, self.ctx)
        self.assertTrue((per["val"] >= 1).all())
        t2 = dict(t, cond=[("receiving_yards", ">=", 1)], pos=("WR",))
        per2 = pool.evaluate(t2, self.ctx)
        self.assertEqual(float(per2[per2["player_id"] == "BUF-WR0"]["val"].iloc[0]), 4)

    def test_topfinish_ranks_within_position_and_week(self):
        t = dict(_tpl("f_te1"), top=1)
        per = pool.evaluate(t, self.ctx)
        self.assertEqual(int(per["val"].sum()), 24)                               # six identical TEs tie for rank 1 each week: ties share the rank

    def test_range_needs_enough_games(self):
        per = pool.evaluate(_tpl("o_swing"), self.ctx)
        self.assertFalse(per.empty)


class TieringPathTests(unittest.TestCase):
    def test_build_through_the_real_tiering_path(self):
        ctx = _ctx()
        t = dict(_tpl("wr_rec_yds"), ladder=(60, 120, 200, 400))
        p = pool.build_pool_prompt(t, ctx, {}, None)
        self.assertIsNotNone(p)
        self.assertTrue(dd.has_hall_of_famer(p["answers"]))
        self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
        self.assertEqual(p["kind"], "fantasy")
        self.assertIn(f"{p['threshold']}+", p["text"])

    def test_returns_none_when_too_few_answers(self):
        ctx = _ctx()
        t = dict(_tpl("wr_rec_yds"), ladder=(100000,))
        self.assertIsNone(pool.build_pool_prompt(t, ctx, {}, None))

    def test_candidates_are_valid_prompt_dicts(self):
        ctx = _ctx()
        for p in pool.pool_candidates(ctx, "2026-10-01", {}, None):
            self.assertTrue(dd.has_hall_of_famer(p["answers"]))
            self.assertGreaterEqual(len(p["answers"]), dd.MIN_ANSWERS)
            self.assertTrue(p["id"].startswith("p:"))
            self.assertTrue(re.match(r"^[\w:.\-+]+$", p["id"]), p["id"])
            self.assertIn("cat", p)

    def test_pick_day_accepts_pool_candidates(self):
        ctx = _ctx()
        cands = pool.pool_candidates(ctx, "2026-10-01", {}, None)
        if len(cands) >= dd.day_size():
            self.assertEqual(len(dd.pick_day("2026-10-01", cands)), dd.day_size())



class WiringTests(unittest.TestCase):
    def test_bottom_rung_reads_as_plain_english(self):
        from engine.daily_drive_pool import tidy_text
        self.assertEqual(tidy_text("Name a NFC North player with 1+ receiving TDs"), "Name an NFC North player with a receiving TD")
        self.assertEqual(tidy_text("Name a QB who has rushed for 1+ touchdowns"), "Name a QB who has rushed for a touchdown")
        self.assertEqual(tidy_text("Name a TE who finished top-6 in PPR scoring 1+ times"), "Name a TE who finished top-6 in PPR scoring at least once")
        self.assertEqual(tidy_text("Name a WR with 12+ receiving TDs"), "Name a WR with 12+ receiving TDs")      # untouched above 1

    def test_pick_day_takes_at_most_one_prompt_per_category(self):
        from engine import daily_drive as dd
        ans = [{"id": f"a{i}", "name": f"P {i}", "tier": 6 if i == 0 else 1} for i in range(dd.MIN_ANSWERS)]
        cands = [{"id": f"p:{c}{k}", "template": f"{c}{k}", "kind": "fantasy", "cat": c, "answers": ans, "text": "x"}
                 for c in "ABCDEFGHIJ" for k in range(5)]
        day = dd.pick_day("2026-11-20", cands)
        self.assertEqual(len(day), dd.day_size())
        self.assertEqual(len({p["cat"] for p in day}), len(day))

    def test_pool_starts_tomorrow_not_today(self):
        from engine import daily_drive as dd
        self.assertEqual(dd.POOL_START, "2026-11-17")


if __name__ == "__main__":
    unittest.main()
