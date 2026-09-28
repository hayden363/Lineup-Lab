"""engine.defense_scoring — team D/ST production from play-by-play.

nflverse records possession on kicking plays differently from scrimmage plays:
on a PUNT, posteam is the punting team (the returner's team is defteam); on a
KICKOFF, posteam is the RECEIVING team. build_defense_weekly used to treat both
like scrimmage plays, which dropped every kick-return TD (7 in 2025) and
inverted punt fumble recoveries (18 own-muff recoveries counted as takeaways,
13 real muffed-punt takeaways missed). The synthetic tests pin each possession
case; the real-data tests hold the result to nflverse's official per-player
stats on the cached 2025 season.

Known, documented residual: a punting team falling on its OWN fumble (e.g. a
bad snap) is still counted as a takeaway — telling it apart needs nflverse's
fumbled_1_team column, which data.load_pbp doesn't keep. One such play in 2025.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import os
import unittest

import pandas as pd

from engine.defense_scoring import DEFAULT_DEF_SCORING, _points_allowed_score, build_defense_weekly

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "data_cache")

PLAY = dict(week=1, sack=0, interception=0, fumble_recovery_1_team=None, safety=0,
            touchdown=0, td_team=None, punt_blocked=0, field_goal_result=None)
SCHEDULE = pd.DataFrame([{"week": 1, "home_team": "AAA", "away_team": "BBB", "home_score": 17, "away_score": 10}])


def _weekly(*plays):
    """Two teams, AAA and BBB, each with one ordinary snap so both have a row,
    plus whatever plays the test adds."""
    base = [dict(PLAY, play_type="pass", posteam="AAA", defteam="BBB"),
            dict(PLAY, play_type="pass", posteam="BBB", defteam="AAA")]
    pbp = pd.DataFrame(base + [dict(PLAY, **p) for p in plays])
    return build_defense_weekly(pbp, SCHEDULE).set_index("defteam")


class PossessionCases(unittest.TestCase):
    def test_kick_return_td_is_credited_to_the_receiving_team(self):
        # On a kickoff the RECEIVING team is posteam; its return TD must count.
        w = _weekly(dict(play_type="kickoff", posteam="AAA", defteam="BBB", touchdown=1, td_team="AAA"))
        self.assertEqual((w.loc["AAA", "def_tds"], w.loc["BBB", "def_tds"]), (1, 0))

    def test_kicking_team_scoring_on_a_kickoff_still_counts(self):
        w = _weekly(dict(play_type="kickoff", posteam="AAA", defteam="BBB", touchdown=1, td_team="BBB"))
        self.assertEqual(w.loc["BBB", "def_tds"], 1)

    def test_punt_return_td_is_credited_to_the_receiving_team(self):
        # On a punt the receiving team is defteam.
        w = _weekly(dict(play_type="punt", posteam="AAA", defteam="BBB", touchdown=1, td_team="BBB"))
        self.assertEqual(w.loc["BBB", "def_tds"], 1)

    def test_offensive_td_is_not_a_defensive_td(self):
        w = _weekly(dict(play_type="run", posteam="AAA", defteam="BBB", touchdown=1, td_team="AAA"))
        self.assertEqual((w.loc["AAA", "def_tds"], w.loc["BBB", "def_tds"]), (0, 0))

    def test_muffed_punt_recovered_by_punting_team_is_their_takeaway(self):
        w = _weekly(dict(play_type="punt", posteam="AAA", defteam="BBB", fumble_recovery_1_team="AAA"))
        self.assertEqual((w.loc["AAA", "fumble_rec"], w.loc["BBB", "fumble_rec"]), (1, 0))

    def test_returner_falling_on_his_own_muff_is_not_a_takeaway(self):
        w = _weekly(dict(play_type="punt", posteam="AAA", defteam="BBB", fumble_recovery_1_team="BBB"))
        self.assertEqual((w.loc["AAA", "fumble_rec"], w.loc["BBB", "fumble_rec"]), (0, 0))

    def test_kickoff_fumble_recovered_by_kicking_team_is_a_takeaway(self):
        # Kickoffs were already right: the kicking team is defteam there.
        w = _weekly(dict(play_type="kickoff", posteam="AAA", defteam="BBB", fumble_recovery_1_team="BBB"))
        self.assertEqual(w.loc["BBB", "fumble_rec"], 1)

    def test_scrimmage_fumble_recovered_by_defense_is_a_takeaway(self):
        w = _weekly(dict(play_type="run", posteam="AAA", defteam="BBB", fumble_recovery_1_team="BBB"))
        self.assertEqual(w.loc["BBB", "fumble_rec"], 1)


class PointsAllowed(unittest.TestCase):
    def test_every_tier_edge(self):
        s = DEFAULT_DEF_SCORING
        cases = {0: "pts_allow_0", 1: "pts_allow_1_6", 6: "pts_allow_1_6", 7: "pts_allow_7_13",
                 13: "pts_allow_7_13", 14: "pts_allow_14_20", 20: "pts_allow_14_20",
                 21: "pts_allow_21_27", 27: "pts_allow_21_27", 28: "pts_allow_28_34",
                 34: "pts_allow_28_34", 35: "pts_allow_35p", 52: "pts_allow_35p"}
        for pts, key in cases.items():
            with self.subTest(points=pts):
                self.assertEqual(_points_allowed_score(pts, s), s[key])

    def test_missing_score_is_neutral(self):
        self.assertEqual(_points_allowed_score(float("nan"), DEFAULT_DEF_SCORING), 0.0)


class GroundTruth2025(unittest.TestCase):
    """Real 2025 season from data_cache/, compared with nflverse's official
    per-player stats summed by team-week."""

    @classmethod
    def setUpClass(cls):
        paths = [os.path.join(CACHE, f) for f in ("pbp_2025.parquet", "weekly_2025.parquet", "schedule_2025.parquet")]
        if not all(os.path.exists(p) for p in paths):
            raise unittest.SkipTest("2025 pbp/weekly/schedule not all cached")
        cls.pbp, wk, sched = (pd.read_parquet(p) for p in paths)
        cls.weekly = build_defense_weekly(cls.pbp, sched).set_index(["defteam", "week"])
        cls.official = wk.groupby(["recent_team", "week"]).sum(numeric_only=True).rename_axis(["defteam", "week"])

    def _differing(self, ours, official):
        both = pd.concat([ours.rename("ours"), official.rename("official")], axis=1).dropna()
        return int((both["ours"] != both["official"]).sum())

    def test_interceptions_match_official(self):
        self.assertEqual(self._differing(self.weekly["ints"], self.official["def_interceptions"]), 0)

    def test_blocked_kicks_match_official(self):
        off = self.official["def_punt_blocks"] + self.official["def_fg_blocks"]
        self.assertEqual(self._differing(self.weekly["blocked_kicks"], off), 0)

    def test_special_teams_tds_match_official(self):
        # The kick-return fix: every special-teams TD, credited to the right
        # team, must equal nflverse's official special_teams_tds per team-week.
        p = self.pbp
        on_kick = p["play_type"].isin(["punt", "kickoff", "field_goal"])
        st = p[(p["touchdown"] == 1) & on_kick
               & ((p["td_team"] == p["defteam"]) | ((p["play_type"] == "kickoff") & (p["td_team"] == p["posteam"])))]
        ours = st.groupby([st["td_team"], st["week"]]).size().rename_axis(["defteam", "week"])
        both = pd.concat([ours.rename("ours"), self.official["special_teams_tds"].rename("official")], axis=1).fillna(0)
        self.assertEqual(int((both["ours"] != both["official"]).sum()), 0)

    def test_every_real_kick_return_td_reaches_the_receiving_team(self):
        # Checks build_defense_weekly's OUTPUT, not a re-derivation: each real
        # 2025 kick-return TD must show up in the receiving team's def_tds.
        # (The previous code credited none of the 7.)
        p = self.pbp
        ko = p[(p["play_type"] == "kickoff") & (p["touchdown"] == 1) & (p["td_team"] == p["posteam"])]
        self.assertGreater(len(ko), 0)
        need = ko.groupby([ko["td_team"], ko["week"]]).size().to_dict()
        have = self.weekly["def_tds"].to_dict()
        short = [key for key, n in need.items() if have.get(key, 0) < n]
        self.assertEqual(short, [], "kick-return TDs missing from the receiving team's D/ST")

    def test_no_credited_punt_recovery_is_an_official_own_recovery_only(self):
        p = self.pbp
        credited = p[(p["play_type"] == "punt") & (p["fumble_recovery_1_team"] == p["posteam"])]
        opp = self.official["fumble_recovery_opp"].to_dict()
        own_only = [(t, w) for t, w in zip(credited["fumble_recovery_1_team"], credited["week"])
                    if opp.get((t, w), 0) == 0]
        # One documented residual (a punting team recovering its own fumble).
        self.assertLessEqual(len(own_only), 1, f"punt recoveries with no official opponent recovery: {own_only}")


if __name__ == "__main__":
    unittest.main()
