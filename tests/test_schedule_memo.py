"""injuries.timeline/_games_left and profile.team_schedule_cached remember a team's schedule per schedule table.
They must answer exactly like the original code and must never serve an answer from an outdated table."""
import unittest
from datetime import date

import numpy as np
import pandas as pd

from engine import injuries, profile


# ---- the original implementations, kept verbatim as references ----------------------------------------------------
def ref_timeline(return_date, schedule, team, today=None):
    out = {"return_date": return_date, "return_week": None, "games_out": None, "days_out": None, "games_left": None}
    if not return_date:
        return out
    today = today or date.today()
    try:
        back = date.fromisoformat(str(return_date)[:10])
    except ValueError:
        return out
    out["days_out"] = (back - today).days
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    s = s[(s["home_team"] == team) | (s["away_team"] == team)]
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    games = []
    for r in s.sort_values("week").itertuples(index=False):
        try:
            games.append((int(r.week), date.fromisoformat(str(r.gameday)[:10])))
        except (TypeError, ValueError):
            continue
    out["games_left"] = len(games)
    missed = [w for w, d in games if d < back]
    out["games_out"] = len(missed)
    later = [w for w, d in games if d >= back]
    out["return_week"] = later[0] if later else None
    return out


def ref_games_left(schedule, team):
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    s = s[(s["home_team"] == team) | (s["away_team"] == team)]
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    return int(len(s))


def ref_team_schedule(schedule, team):
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    s = s[(s["home_team"] == team) | (s["away_team"] == team)]
    out = {}
    for r in s.itertuples(index=False):
        home = r.home_team == team
        out[int(r.week)] = {
            "opponent": r.away_team if home else r.home_team, "home": bool(home),
            "gameday": getattr(r, "gameday", None), "gametime": getattr(r, "gametime", None),
            "played": bool(pd.notna(getattr(r, "home_score", np.nan))),
        }
    return out


TEAMS = ["KC", "BUF", "DAL", "PHI", "SF", "MIA", "NYJ", "DET"]


def schedule_frame(seed=0, played_through=6):
    rng = np.random.default_rng(seed)
    rows = []
    for week in range(1, 19):
        order = list(rng.permutation(TEAMS))
        for i in range(0, len(order), 2):
            if week % 9 == 0 and i == 0:
                continue                                                  # a couple of byes
            home, away = order[i], order[i + 1]
            rows.append({"game_type": "REG", "week": week, "home_team": home, "away_team": away,
                         "gameday": f"2026-{9 + (week - 1) // 5:02d}-{1 + (week * 3) % 27:02d}", "gametime": "13:00",
                         "home_score": float(rng.integers(3, 40)) if week <= played_through else np.nan})
    rows.append({"game_type": "POST", "week": 19, "home_team": "KC", "away_team": "BUF", "gameday": "2027-01-20",
                 "gametime": "16:00", "home_score": np.nan})                # playoff games must be ignored
    rows.append({"game_type": "REG", "week": 18, "home_team": "KC", "away_team": "DAL", "gameday": "not-a-date",
                 "gametime": "13:00", "home_score": np.nan})                # an unreadable date is skipped by timeline
    return pd.DataFrame(rows)


RETURNS = [None, "", "2026-10-01", "2026-11-15T00:00:00Z", "2026-12-25", "2027-02-01", "garbage", "2026-09-01"]


class MatchesTheOriginal(unittest.TestCase):
    def test_timeline_and_games_left_for_every_team_date_and_today(self):
        for seed in range(3):
            sched = schedule_frame(seed, played_through=4 + seed * 3)
            for team in TEAMS + ["XXX", None, float("nan")]:
                for rd in RETURNS:
                    for today in (None, date(2026, 10, 20), date(2027, 3, 1)):
                        with self.subTest(seed=seed, team=team, rd=rd, today=today):
                            self.assertEqual(injuries.timeline(rd, sched, team, today),
                                             ref_timeline(rd, sched, team, today))
                with self.subTest(seed=seed, team=team, what="games_left"):
                    self.assertEqual(injuries._games_left(sched, team), ref_games_left(sched, team))

    def test_availability_and_out_long_use_the_same_numbers(self):
        sched = schedule_frame(1)
        for team in TEAMS:
            for status in ("Out", "IR", "PUP", "Questionable", None):
                for rec in (None, {"return_date": "2026-11-20"}, {"return_date": None}):
                    row = {"injury_status": status, "injury_report": rec, "recent_team": team}
                    with self.subTest(team=team, status=status, rec=rec):
                        got = injuries.availability(row, sched, date(2026, 10, 20))
                        # the original availability, written out against the reference helpers
                        if not isinstance(status, str):
                            want = 1.0
                        elif isinstance(rec, dict) and rec.get("return_date"):
                            tl = ref_timeline(rec["return_date"], sched, team, date(2026, 10, 20))
                            want = 1.0 if not tl["games_left"] else max(0.0, 1.0 - tl["games_out"] / tl["games_left"])
                        else:
                            out = injuries.ASSUMED_GAMES_OUT.get(status)
                            left = ref_games_left(sched, team) if out else 0
                            want = 1.0 if (not out or not left) else max(0.0, 1.0 - min(out, left) / left)
                        self.assertEqual(got, want)

    def test_a_schedule_missing_a_column_fails_the_same_way(self):
        sched = schedule_frame().drop(columns=["gameday"])
        with self.assertRaises(AttributeError):
            ref_timeline("2026-11-20", sched, "KC", date(2026, 10, 20))
        with self.assertRaises(AttributeError):
            injuries.timeline("2026-11-20", sched, "KC", date(2026, 10, 20))
        self.assertEqual(injuries._games_left(sched, "KC"), ref_games_left(sched, "KC"))   # never needed gameday

    def test_team_schedule_cached_equals_team_schedule(self):
        sched = schedule_frame(2)
        for team in TEAMS + ["XXX", None, float("nan")]:
            with self.subTest(team=team):
                self.assertEqual(profile.team_schedule_cached(sched, team), ref_team_schedule(sched, team))
                self.assertEqual(profile.team_schedule_cached(sched, team), profile.team_schedule(sched, team))


class NeverServesAnOutdatedTable(unittest.TestCase):
    def test_a_new_schedule_object_replaces_the_memo(self):
        a, b = schedule_frame(0, 4), schedule_frame(0, 10)
        self.assertEqual(injuries._games_left(a, "KC"), ref_games_left(a, "KC"))
        self.assertEqual(injuries._games_left(b, "KC"), ref_games_left(b, "KC"))
        self.assertNotEqual(ref_games_left(a, "KC"), ref_games_left(b, "KC"))
        self.assertEqual(injuries._games_left(a, "KC"), ref_games_left(a, "KC"))      # and back again

    def test_a_game_finishing_inside_the_same_table_is_noticed(self):
        sched = schedule_frame(0, 4)
        before = injuries._games_left(sched, "KC"); tl_before = injuries.timeline("2026-11-20", sched, "KC", date(2026, 10, 1))
        first_open = sched.index[(sched["home_score"].isna()) & (sched["game_type"] == "REG")
                                 & ((sched["home_team"] == "KC") | (sched["away_team"] == "KC"))][0]
        sched.loc[first_open, "home_score"] = 20.0                                    # filled in place, same object
        self.assertEqual(injuries._games_left(sched, "KC"), before - 1)
        self.assertEqual(injuries._games_left(sched, "KC"), ref_games_left(sched, "KC"))
        self.assertEqual(injuries.timeline("2026-11-20", sched, "KC", date(2026, 10, 1)),
                         ref_timeline("2026-11-20", sched, "KC", date(2026, 10, 1)))
        self.assertNotEqual(injuries.timeline("2026-11-20", sched, "KC", date(2026, 10, 1)), tl_before)

    def test_team_schedule_cache_follows_a_new_table_and_an_in_place_score(self):
        sched = schedule_frame(0, 4)
        first = profile.team_schedule_cached(sched, "KC")
        self.assertIs(first, profile.team_schedule_cached(sched, "KC"))               # a real hit
        g = sched.index[(sched["game_type"] == "REG") & sched["home_score"].isna()
                        & ((sched["home_team"] == "KC") | (sched["away_team"] == "KC"))][0]
        sched.loc[g, "home_score"] = 17.0
        self.assertEqual(profile.team_schedule_cached(sched, "KC"), ref_team_schedule(sched, "KC"))
        other = schedule_frame(5, 12)
        self.assertEqual(profile.team_schedule_cached(other, "KC"), ref_team_schedule(other, "KC"))

    def test_the_memo_stays_small(self):
        sched = schedule_frame(0)
        for i in range(500):
            injuries._games_left(sched, float("nan")); injuries.timeline("2026-11-20", sched, None, date(2026, 10, 1))
            injuries._games_left(sched, TEAMS[i % len(TEAMS)])
            profile.team_schedule_cached(sched, float("nan"))
        self.assertLessEqual(len(injuries._REMAINING.left), len(TEAMS))
        self.assertLessEqual(len(injuries._REMAINING.games), len(TEAMS))
        self.assertLessEqual(len(profile._TEAM_SCHEDULES.by_team), len(TEAMS))


class EditsInsideTheSameTableAreNoticed(unittest.TestCase):
    """The table object and its size stay the same; something inside it changes."""

    def kc_row(self, sched):
        return sched.index[(sched["game_type"] == "REG") & sched["home_score"].isna() & (sched["home_team"] == "KC")][0]

    def assert_all_match(self, sched):
        for team in TEAMS:
            self.assertEqual(injuries._games_left(sched, team), ref_games_left(sched, team))
            self.assertEqual(injuries.timeline("2026-11-20", sched, team, date(2026, 10, 1)),
                             ref_timeline("2026-11-20", sched, team, date(2026, 10, 1)))
            self.assertEqual(profile.team_schedule_cached(sched, team), ref_team_schedule(sched, team))

    def test_a_game_moved_to_another_day(self):
        sched = schedule_frame(0, 4); self.assert_all_match(sched)
        sched.loc[self.kc_row(sched), "gameday"] = "2027-01-03"
        self.assert_all_match(sched)

    def test_a_kickoff_time_change(self):
        sched = schedule_frame(0, 4); self.assert_all_match(sched)
        sched.loc[self.kc_row(sched), "gametime"] = "20:15"
        self.assert_all_match(sched)

    def test_teams_swapped_or_game_type_changed(self):
        sched = schedule_frame(0, 4); self.assert_all_match(sched)
        i = self.kc_row(sched); sched.loc[i, ["home_team", "away_team"]] = ["DET", "KC"]
        self.assert_all_match(sched)
        sched.loc[i, "game_type"] = "POST"
        self.assert_all_match(sched)

    def test_one_game_finishes_while_another_reopens(self):
        """Same number of unplayed games before and after, so a count of unplayed games alone cannot see it."""
        sched = schedule_frame(0, 4); self.assert_all_match(sched)
        open_rows = sched.index[sched["home_score"].isna() & (sched["game_type"] == "REG")]
        done_rows = sched.index[sched["home_score"].notna()]
        sched.loc[open_rows[0], "home_score"] = 24.0
        sched.loc[done_rows[0], "home_score"] = np.nan
        self.assert_all_match(sched)


class ThreadsOnDifferentTablesNeverMix(unittest.TestCase):
    def test_a_stale_writer_cannot_contaminate_the_current_table(self):
        x, y = schedule_frame(0, 4), schedule_frame(0, 18)            # y has every game played: KC has none left
        stale = injuries._memo(x, "KC")                               # a thread starts on table x ...
        self.assertEqual(injuries._games_left(y, "KC"), ref_games_left(y, "KC"))    # ... a refresh swaps in table y
        stale.left["KC"] = 99; stale.games["KC"] = [(1, date(2026, 9, 1))]          # ... then the old thread finishes
        self.assertEqual(injuries._games_left(y, "KC"), ref_games_left(y, "KC"))
        self.assertEqual(injuries.timeline("2026-11-20", y, "KC", date(2026, 10, 1)),
                         ref_timeline("2026-11-20", y, "KC", date(2026, 10, 1)))
        old = profile.team_schedule_cached(x, "KC"); profile._TEAM_SCHEDULES.by_team["KC"] = {"poison": 1}
        self.assertEqual(profile.team_schedule_cached(y, "KC"), ref_team_schedule(y, "KC"))
        self.assertNotEqual(old, ref_team_schedule(y, "KC"))

    def test_eight_threads_on_two_tables(self):
        import threading
        tables = [schedule_frame(0, 4), schedule_frame(0, 18)]
        want = [{t: (ref_games_left(s, t), ref_timeline("2026-11-20", s, t, date(2026, 10, 1)), ref_team_schedule(s, t))
                 for t in TEAMS} for s in tables]
        errors = []

        def work(k):
            for i in range(150):
                n = (k + i) % 2; s, t = tables[n], TEAMS[(k * 3 + i) % len(TEAMS)]
                got = (injuries._games_left(s, t), injuries.timeline("2026-11-20", s, t, date(2026, 10, 1)),
                       profile.team_schedule_cached(s, t))
                if got != want[n][t]:
                    errors.append((n, t))

        threads = [threading.Thread(target=work, args=(k,)) for k in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
