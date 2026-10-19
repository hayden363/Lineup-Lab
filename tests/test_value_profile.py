"""Cross-position value (engine/value.py), the consensus name matching, and the
player profile pieces (engine/profile.py). Pure pandas: no network, no cache.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest

import numpy as np
import pandas as pd

from engine import consensus, profile, value


def frame(rows, pos):
    """rows: [(player_id, name, proj)] -> a position board stand-in."""
    return pd.DataFrame(
        [{"player_id": i, "player_display_name": n, "recent_team": "AAA", "PROJ": p} for i, n, p in rows]
    ).set_index("player_id")


class ReplacementRanks(unittest.TestCase):
    def test_default_twelve_team_league(self):
        # 12 x (starters + flex share): QB 12, RB 12*(2+.4)=28.8, WR 12*(2+.5)=30, TE 12*(1+.1)=13.2
        self.assertEqual(value.replacement_ranks(), {"QB": 12, "RB": 29, "WR": 30, "TE": 13})

    def test_superflex_pulls_quarterback_replacement_down(self):
        sf = value.replacement_ranks({"teams": 12, "slots": {"SUPERFLEX": 1}})
        self.assertEqual(sf["QB"], 20)
        self.assertGreater(sf["QB"], value.replacement_ranks()["QB"])


class ComputeValue(unittest.TestCase):
    def setUp(self):
        qbs = [(f"q{i}", f"Quarterback {i}", 25.0 - i * 0.5) for i in range(20)]
        # a thin tight-end position: two stars, then a cliff to ~8
        tes = [("t0", "Tight Star One", 22.0), ("t1", "Tight Star Two", 21.0)] + \
              [(f"t{i}", f"Tight End {i}", 9.0 - i * 0.2) for i in range(2, 20)]
        rbs = [(f"r{i}", f"Back {i}", 20.0 - i * 0.6) for i in range(40)]
        wrs = [(f"w{i}", f"Receiver {i}", 18.0 - i * 0.4) for i in range(45)]
        self.frames = {"QB": frame(qbs, "QB"), "RB": frame(rbs, "RB"),
                       "WR": frame(wrs, "WR"), "TE": frame(tes, "TE")}

    def test_best_quarterback_does_not_top_the_list_just_for_scoring_more(self):
        out = value.compute_value(self.frames)
        # QB1 projects 25 (highest raw) but QBs are deep, so his edge is small.
        self.assertNotEqual(out.iloc[0]["position"], "QB")
        top = out.set_index("player_display_name")
        self.assertGreater(top.loc["Tight Star One", "VOR"], top.loc["Quarterback 0", "VOR"])

    def test_tight_end_scarcity_shows_in_vor(self):
        out = value.compute_value(self.frames).set_index("player_display_name")
        # Star TE: 22 - replacement(9ish) is a big edge; a mid TE is near zero.
        self.assertGreater(out.loc["Tight Star One", "VOR"], 10)
        self.assertLess(abs(out.loc["Tight End 12", "VOR"]), 1.5)

    def test_superflex_raises_quarterbacks(self):
        base = value.compute_value(self.frames).set_index("player_display_name")
        sf = value.compute_value(self.frames, league={"teams": 12, "slots": {"SUPERFLEX": 1}}).set_index("player_display_name")
        self.assertLess(sf.loc["Quarterback 0", "overall_rank"], base.loc["Quarterback 0", "overall_rank"])

    def test_consensus_nudges_but_does_not_decide(self):
        plain = value.compute_value(self.frames)
        # Experts rank everyone exactly as we do, except they love Back 5.
        order = list(plain["player_display_name"])
        pos = dict(zip(plain["player_display_name"], plain["position"]))
        ecr = {consensus.match_key(n, pos[n]): {"ecr": float(i + 2), "ecr_sd": 0.0, "bye_week": 9}
               for i, n in enumerate(n for n in order if n != "Back 5")}
        ecr[consensus.match_key("Back 5", "RB")] = {"ecr": 1.0, "ecr_sd": 0.0, "bye_week": 9}
        before = plain.set_index("player_display_name").loc["Back 5", "overall_rank"]
        nudged = value.compute_value(self.frames, ecr=ecr).set_index("player_display_name")
        self.assertEqual(nudged.loc["Back 5", "bye_week"], 9)
        self.assertEqual(nudged.loc["Back 5", "ecr"], 1.0)
        self.assertLess(nudged.loc["Back 5", "overall_rank"], before)  # lifted by the experts...
        self.assertGreater(nudged.loc["Back 5", "overall_rank"], 1)    # ...but not handed #1

    def test_ranks_are_unique_and_complete(self):
        out = value.compute_value(self.frames)
        self.assertEqual(sorted(out["overall_rank"]), list(range(1, len(out) + 1)))
        self.assertTrue((out["VALUE"].between(0, 100)).all())

    def test_tiers_break_on_big_drops(self):
        self.assertEqual(list(value.assign_tiers([30, 29, 20, 19, 10, 9.5, 2, 1])), [1, 1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(len(value.assign_tiers([])), 0)


class Consensus(unittest.TestCase):
    def test_name_normalization(self):
        self.assertEqual(consensus.normalize_name("Kenneth Walker III"), "kenneth walker")
        self.assertEqual(consensus.normalize_name("Ja'Marr Chase"), "jamarr chase")
        self.assertEqual(consensus.normalize_name("Amon-Ra St. Brown"), "amon ra st brown")
        self.assertEqual(consensus.match_key("Marvin Harrison Jr.", "wr"), "marvin harrison|WR")

    def test_lookup_reads_only_the_overall_list(self):
        ecr = pd.DataFrame([
            {"page_type": "redraft-overall", "player": "A B", "pos": "RB", "team": "X", "ecr": 3.0,
             "sd": 1.0, "best": 2, "worst": 5, "bye": 7.0, "scrape_date": "2026-10-16"},
            {"page_type": "weekly-rb", "player": "A B", "pos": "RB", "team": "X", "ecr": 9.0,
             "sd": 1.0, "best": 2, "worst": 5, "bye": 7.0, "scrape_date": "2026-10-16"},
        ])
        got = consensus.overall_lookup(ecr)
        self.assertEqual(got[consensus.match_key("A B", "RB")]["ecr"], 3.0)
        self.assertEqual(consensus.weekly_lookup("rb", ecr)[consensus.match_key("A B", "RB")], 9.0)


class Profile(unittest.TestCase):
    def weekly(self):
        rows = []
        for week in range(1, 6):
            for pid, pts in (("a", [30, 10, 25, 12, 28][week - 1]), ("b", 15), ("c", 8), ("d", 6)):
                rows.append({"player_id": pid, "position": "RB", "week": week, "fpts_active": float(pts),
                             "carries": 10, "rushing_yards": 50, "rushing_tds": 1, "targets": 2,
                             "receptions": 2, "receiving_yards": 10, "receiving_tds": 0,
                             "rushing_fumbles_lost": 0, "receiving_fumbles_lost": 0, "sack_fumbles_lost": 0})
        return pd.DataFrame(rows)

    def test_totals_sum_and_rates(self):
        t = profile.season_totals(self.weekly(), "RB").loc["a"]
        self.assertEqual(t["carries"], 50)
        self.assertEqual(t["rushing_yards"], 250)
        self.assertEqual(t["yards_per_carry"], 5.0)

    def test_volatile_player_has_higher_cv_than_steady_one(self):
        c = profile.consistency(self.weekly(), "RB")
        self.assertGreater(c.loc["a", "cv"], c.loc["b", "cv"])
        self.assertEqual(c.loc["b", "std"], 0.0)
        self.assertGreaterEqual(c.loc["a", "boom_rate"], 0)

    def test_stat_line_per_position(self):
        self.assertEqual(profile.stat_line({"carries": 105, "rushing_yards": 504, "rushing_tds": 7,
                                            "receptions": 27, "receiving_yards": 243}, "RB"),
                         "105 car, 504 yds, 7 TD, 27 rec, 243 rec yds")
        self.assertIn("1,794 yds", profile.stat_line({"attempts": 249, "completions": 164, "passing_yards": 1794,
                                                      "passing_tds": 11, "interceptions": 6}, "QB"))


class WeeklyStatus(unittest.TestCase):
    def schedule(self):
        games = [(1, "AAA", "BBB", 10.0), (2, "CCC", "AAA", 20.0), (3, "AAA", "DDD", 7.0),
                 (5, "AAA", "EEE", np.nan)]  # week 4 is AAA's BYE; week 5 not played yet
        return pd.DataFrame([{"game_type": "REG", "week": w, "home_team": h, "away_team": a,
                              "home_score": s, "gameday": f"2026-10-{w:02d}", "gametime": "13:00"}
                             for w, h, a, s in games] +
                            [{"game_type": "REG", "week": 4, "home_team": "BBB", "away_team": "CCC",
                              "home_score": 3.0, "gameday": "2026-10-04", "gametime": "13:00"}])

    def test_played_dnp_bye_upcoming(self):
        played = pd.DataFrame([{"week": 1, "fpts": 12.0}, {"week": 3, "fpts": 9.0}])  # missed week 2
        rows = profile.weekly_status(played, self.schedule(), "AAA", final_week=5)
        self.assertEqual([r["status"] for r in rows], ["played", "dnp", "played", "bye", "upcoming"])
        self.assertEqual(rows[0]["fpts"], 12.0)
        self.assertEqual(rows[1]["opponent"], "CCC")
        self.assertFalse(rows[1]["home"])

    def test_bye_week_found(self):
        self.assertEqual(profile.bye_weeks(self.schedule())["AAA"], 4)


class NgsProfile(unittest.TestCase):
    def table(self):
        rows = []
        for i in range(8):
            season = {"player_gsis_id": f"p{i}", "week": 0, "targets": 50, "avg_separation": 2.0 + i * 0.2,
                      "avg_cushion": 6.0, "avg_yac_above_expectation": 0.0, "avg_yac": 4.0,
                      "avg_expected_yac": 4.0, "avg_intended_air_yards": 10.0,
                      "percent_share_of_intended_air_yards": 20.0, "catch_percentage": 65.0}
            rows.append(season)
            rows.append({**season, "week": 1, "avg_separation": 1.0})  # must not leak into the season value
        return pd.DataFrame(rows)

    def test_season_value_comes_from_aggregate_row_and_percentile_ranks_peers(self):
        stats = {s["key"]: s for s in profile.ngs_profile(self.table(), "receiving", "p7")}
        self.assertAlmostEqual(stats["avg_separation"]["value"], 3.4)
        self.assertGreater(stats["avg_separation"]["percentile"], 85)
        self.assertEqual(len(stats["avg_separation"]["weekly"]), 1)

    def test_unknown_player_returns_nothing(self):
        self.assertEqual(profile.ngs_profile(self.table(), "receiving", "nobody"), [])


if __name__ == "__main__":
    unittest.main()
