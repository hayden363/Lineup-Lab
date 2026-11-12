"""The week the app calls "this week" changes on Wednesdays (profile.active_week), and upcoming_week /
waivers.target_week both follow it.

    .venv/bin/python -m unittest tests.test_week_rule -v
"""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine import profile, tools, waivers

ET = ZoneInfo("America/New_York")


def at(y, m, d, hh=12, mm=0, tz=ET):
    return dt.datetime(y, m, d, hh, mm, tzinfo=tz)


def make_schedule(scored_through=0, with_dates=True):
    """Six weeks. W1-W3 start Thursday (Sep 10, 17, 24), W4 on a Sunday (Oct 4), W5 on a Saturday (Oct 10),
    W6 on a Wednesday (Oct 14). Every week has a Sunday game and a Monday game."""
    firsts = {1: "2026-09-10", 2: "2026-09-17", 3: "2026-09-24", 4: "2026-10-04", 5: "2026-10-10", 6: "2026-10-14"}
    rows = []
    for wk, first in firsts.items():
        d0 = pd.Timestamp(first)
        for i, off in enumerate([0, 3, 3, 4]):
            day = d0 + pd.Timedelta(days=off if off else 0) if wk in (1, 2, 3) else d0 + pd.Timedelta(days=i)
            rows.append({"week": wk, "game_type": "REG", "gameday": day.strftime("%Y-%m-%d"),
                         "home_score": float(20 + i) if wk <= scored_through else np.nan,
                         "away_score": float(10 + i) if wk <= scored_through else np.nan})
    # a playoff row that must never count
    rows.append({"week": 19, "game_type": "WC", "gameday": "2027-01-16", "home_score": np.nan, "away_score": np.nan})
    df = pd.DataFrame(rows)
    return df if with_dates else df.drop(columns=["gameday"])


class ActiveWeek(unittest.TestCase):
    def test_before_the_first_week_it_is_the_first_week(self):
        self.assertEqual(profile.active_week(make_schedule(), at(2026, 9, 1)), 1)

    def test_a_thursday_week_starts_the_wednesday_before_at_midnight_eastern(self):
        s = make_schedule()
        self.assertEqual(profile.active_week(s, at(2026, 9, 15, 23, 59)), 1)       # Tue night: still week 1
        self.assertEqual(profile.active_week(s, at(2026, 9, 16, 0, 0)), 2)         # Wed 00:00 ET: week 2
        self.assertEqual(profile.active_week(s, at(2026, 9, 16, 9, 0)), 2)

    def test_the_week_does_not_change_while_games_are_being_played(self):
        s = make_schedule()
        for day in (10, 11, 12, 13, 14, 15):                                       # Thu through Tue
            self.assertEqual(profile.active_week(s, at(2026, 9, day, 15)), 1, day)

    def test_scores_do_not_move_the_week(self):
        for scored in (0, 1, 3):
            self.assertEqual(profile.active_week(make_schedule(scored), at(2026, 9, 14, 23)), 1)

    def test_a_week_whose_first_game_is_sunday_starts_the_wednesday_before(self):
        s = make_schedule()
        self.assertEqual(profile.active_week(s, at(2026, 9, 29, 23, 59)), 3)
        self.assertEqual(profile.active_week(s, at(2026, 9, 30, 0, 0)), 4)

    def test_a_week_whose_first_game_is_saturday_starts_the_wednesday_before(self):
        s = make_schedule()
        self.assertEqual(profile.active_week(s, at(2026, 10, 6, 23)), 4)
        self.assertEqual(profile.active_week(s, at(2026, 10, 7, 0, 30)), 5)

    def test_a_week_whose_first_game_is_wednesday_starts_that_wednesday(self):
        s = make_schedule()
        self.assertEqual(profile.active_week(s, at(2026, 10, 13, 12)), 5)
        self.assertEqual(profile.active_week(s, at(2026, 10, 14, 0, 0)), 6)

    def test_after_the_last_week_it_stays_the_last_week_and_playoff_rows_never_count(self):
        self.assertEqual(profile.active_week(make_schedule(6), at(2027, 1, 20)), 6)

    def test_other_time_zones_are_converted_to_eastern(self):
        utc = ZoneInfo("UTC")
        s = make_schedule()
        self.assertEqual(profile.active_week(s, dt.datetime(2026, 9, 16, 3, 59, tzinfo=utc)), 1)   # 23:59 ET Tue
        self.assertEqual(profile.active_week(s, dt.datetime(2026, 9, 16, 4, 0, tzinfo=utc)), 2)    # 00:00 ET Wed
        pacific = ZoneInfo("America/Los_Angeles")
        self.assertEqual(profile.active_week(s, at(2026, 9, 15, 21, 30, tz=pacific)), 2)           # 00:30 ET Wed

    def test_a_naive_now_is_read_as_eastern(self):
        self.assertEqual(profile.active_week(make_schedule(), dt.datetime(2026, 9, 16, 0, 5)), 2)

    def test_daylight_saving_change_does_not_shift_the_flip(self):
        # Week 10 of the 2026 season starts the day after DST ends (Nov 1); the flip is still midnight local.
        s = pd.DataFrame([{"week": 9, "game_type": "REG", "gameday": "2026-10-29", "home_score": 1.0},
                          {"week": 10, "game_type": "REG", "gameday": "2026-11-05", "home_score": np.nan}])
        self.assertEqual(profile.active_week(s, at(2026, 11, 3, 23, 59)), 9)
        self.assertEqual(profile.active_week(s, at(2026, 11, 4, 0, 0)), 10)

    def test_no_dates_means_no_answer(self):
        self.assertIsNone(profile.active_week(make_schedule(with_dates=False), at(2026, 9, 14)))
        s = make_schedule()
        s["gameday"] = None
        self.assertIsNone(profile.active_week(s, at(2026, 9, 14)))

    def test_unparseable_and_missing_dates_are_ignored(self):
        s = make_schedule()
        s.loc[s["week"] == 2, "gameday"] = "TBD"                                   # week 2 has no usable dates at all
        self.assertEqual(profile.active_week(s, at(2026, 9, 20)), 1)                # skipped, still week 1
        self.assertEqual(profile.active_week(s, at(2026, 9, 30)), 4)                # later weeks unaffected

    def test_only_regular_season_games_count(self):
        s = make_schedule()
        self.assertEqual(profile.active_week(s, at(2027, 1, 14)), 6)


class UpcomingWeekAndTargetWeek(unittest.TestCase):
    def test_both_follow_the_wednesday_rule_and_agree(self):
        s = make_schedule(scored_through=1)
        for now, expected in ((at(2026, 9, 13, 16), 1), (at(2026, 9, 15, 22), 1), (at(2026, 9, 16, 1), 2),
                              (at(2026, 9, 18, 12), 2)):
            self.assertEqual(profile.upcoming_week(s, now), expected, now)
            self.assertEqual(waivers.target_week(s, now), expected, now)

    def test_target_week_no_longer_flips_on_sunday_afternoon(self):
        # More than half of week 1's games are scored by Sunday afternoon: the old rule moved on to week 2 here.
        s = make_schedule(scored_through=1)
        self.assertEqual(waivers.target_week(s, at(2026, 9, 13, 17)), 1)

    def test_upcoming_week_is_none_once_the_season_is_over(self):
        self.assertIsNone(profile.upcoming_week(make_schedule(6), at(2027, 1, 20)))

    def test_the_last_week_is_still_the_week_until_its_games_are_scored(self):
        self.assertEqual(profile.upcoming_week(make_schedule(5), at(2026, 10, 20)), 6)
        self.assertEqual(waivers.target_week(make_schedule(6), at(2027, 1, 20)), 6)

    def test_without_dates_the_old_score_based_rules_still_apply(self):
        s = make_schedule(scored_through=2, with_dates=False)
        self.assertEqual(profile.upcoming_week(s, at(2026, 9, 14)), 3)             # next week with an unplayed game
        self.assertEqual(waivers.target_week(s, at(2026, 9, 14)), 3)               # first week with most games unplayed

    def test_the_week_in_play_is_unchanged_by_the_new_rule_on_a_thursday(self):
        # same answer the old rules gave on a game day, so a visitor on Thursday notices nothing
        s = make_schedule(scored_through=0)
        self.assertEqual(profile.upcoming_week(s, at(2026, 9, 17, 12)), 2)


class ByeBeforeNextGame(unittest.TestCase):
    """Start/Sit marks a player on bye when the team's bye falls between the current week and its next game."""
    f = staticmethod(tools._bye_before_next_game)

    def test_a_team_playing_this_week_is_not_on_bye(self):
        self.assertIsNone(self.f(bye_week=7, slate_week=10, next_game_week=10))      # bye already past, plays now
        self.assertIsNone(self.f(bye_week=13, slate_week=10, next_game_week=10))     # bye later

    def test_a_team_on_bye_in_the_current_week_is_on_bye(self):
        self.assertEqual(self.f(bye_week=10, slate_week=10, next_game_week=11), 10)

    def test_sunday_to_tuesday_a_team_that_played_and_is_off_next_week_reads_as_on_bye(self):
        # current week 10 (already played), next game week 12: the idle week is 11
        self.assertEqual(self.f(bye_week=11, slate_week=10, next_game_week=12), 11)

    def test_a_bye_further_away_is_not_flagged(self):
        self.assertIsNone(self.f(bye_week=13, slate_week=10, next_game_week=11))

    def test_missing_pieces_never_flag(self):
        self.assertIsNone(self.f(None, 10, 11))
        self.assertIsNone(self.f(11, None, 12))
        self.assertIsNone(self.f(11, 10, None))


class Real2026Schedule(unittest.TestCase):
    def test_the_real_schedule_flips_on_wednesdays(self):
        try:
            from engine import data
            s = data.load_schedule()
        except Exception as e:                           # no cached data on this machine
            self.skipTest(f"schedule unavailable: {e}")
        if "gameday" not in s.columns or not (s["week"] == 11).any():
            self.skipTest("not the 2026 schedule")
        self.assertEqual(profile.active_week(s, at(2026, 11, 12, 10)), 10)         # Thursday of week 10
        self.assertEqual(profile.active_week(s, at(2026, 11, 17, 23, 30)), 10)     # Tuesday night
        self.assertEqual(profile.active_week(s, at(2026, 11, 18, 0, 1)), 11)       # Wednesday


if __name__ == "__main__":
    unittest.main()
