"""
PLAYER PROFILE — the raw numbers behind a rating, laid out for the player card
=================================================================================
Four things the card needs that the ranked board doesn't carry:

  * season_totals     plain box-score totals (attempts, yards, TDs, ints...)
  * consistency       how steady a player is week to week, and how often he
                      has a big week or a dud
  * ngs_profile       every Next Gen Stats number the NFL publishes for his
                      position, each with its percentile among peers
  * weekly_status     every week of the schedule, tagged played / BYE / missed
                      (team played, he did not) / upcoming

Everything here is computed from the tables engine/board.py already loads.
"""

import numpy as np
import pandas as pd

TOTAL_COLUMNS = {
    "QB": ["completions", "attempts", "passing_yards", "passing_tds", "interceptions", "sacks",
           "carries", "rushing_yards", "rushing_tds"],
    "RB": ["carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds"],
    "WR": ["targets", "receptions", "receiving_yards", "receiving_tds", "carries", "rushing_yards", "rushing_tds"],
    "TE": ["targets", "receptions", "receiving_yards", "receiving_tds"],
}
_FUMBLE_LOST_COLS = ["rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"]


def season_totals(wk, position):
    """Box-score totals per player_id for one position: a DataFrame with a
    `games` column, the position's TOTAL_COLUMNS, `fumbles_lost`, and the
    per-game and per-attempt rates people read off a stat line."""
    sub = wk[wk["position"] == position]
    g = sub.groupby("player_id")
    cols = [c for c in TOTAL_COLUMNS[position] if c in sub.columns]
    out = g[cols].sum()
    out.insert(0, "games", g.size())
    lost = [c for c in _FUMBLE_LOST_COLS if c in sub.columns]
    out["fumbles_lost"] = g[lost].sum().sum(axis=1) if lost else 0
    out = out.astype(float)
    if position == "QB":
        out["completion_pct"] = (out["completions"] / out["attempts"].replace(0, np.nan) * 100).round(1)
        out["yards_per_attempt"] = (out["passing_yards"] / out["attempts"].replace(0, np.nan)).round(2)
    elif position == "RB":
        out["yards_per_carry"] = (out["rushing_yards"] / out["carries"].replace(0, np.nan)).round(2)
    else:
        out["yards_per_reception"] = (out["receiving_yards"] / out["receptions"].replace(0, np.nan)).round(1)
    return out


# A "big week" is a top-N finish at the position that week; a "dud" is a game
# he played that landed outside the startable range. Rank-based so it holds
# under any scoring system.
BOOM_RANK = {"QB": 6, "RB": 12, "WR": 12, "TE": 6}
BUST_RANK = {"QB": 20, "RB": 36, "WR": 36, "TE": 18}


def consistency(wk_scored, position):
    """Per-player week-to-week profile for one position from a scored weekly
    table (needs fpts_active). Returns a DataFrame by player_id:
    mean, std, cv (std/mean, lower = steadier), boom_rate, bust_rate (percent
    of his games), best, worst, and top_finishes (count of boom weeks)."""
    sub = wk_scored[wk_scored["position"] == position].copy()
    sub["wk_rank"] = sub.groupby("week")["fpts_active"].rank(ascending=False, method="min")
    g = sub.groupby("player_id")
    mean = g["fpts_active"].mean()
    std = g["fpts_active"].std(ddof=0)
    boom = sub["wk_rank"] <= BOOM_RANK[position]
    bust = sub["wk_rank"] > BUST_RANK[position]
    out = pd.DataFrame({
        "games": g.size(),
        "mean": mean.round(1),
        "std": std.round(1),
        "cv": (std / mean.where(mean > 0)).round(2),
        "boom_rate": (boom.groupby(sub["player_id"]).mean() * 100).round(0),
        "bust_rate": (bust.groupby(sub["player_id"]).mean() * 100).round(0),
        "best": g["fpts_active"].max().round(1),
        "worst": g["fpts_active"].min().round(1),
        "top_finishes": boom.groupby(sub["player_id"]).sum().astype(int),
    })
    return out


# (column, label, higher_is_better) — None means "context, not good or bad".
NGS_SPECS = {
    "passing": [
        ("completion_percentage_above_expectation", "Completion % over expected", True),
        ("expected_completion_percentage", "Expected completion %", None),
        ("avg_time_to_throw", "Time to throw (s)", None),
        ("aggressiveness", "Aggressiveness %", None),
        ("avg_intended_air_yards", "Intended air yards", None),
        ("avg_completed_air_yards", "Completed air yards", None),
        ("avg_air_yards_differential", "Air yards differential", None),
        ("avg_air_yards_to_sticks", "Air yards to the sticks", True),
        ("max_completed_air_distance", "Longest completed air distance", True),
        ("passer_rating", "Passer rating", True),
    ],
    "rushing": [
        ("rush_yards_over_expected_per_att", "Rush yards over expected / att", True),
        ("rush_pct_over_expected", "Rushes over expected %", True),
        ("efficiency", "Efficiency (lower = more north-south)", False),
        ("avg_time_to_los", "Time to line of scrimmage (s)", None),
        ("percent_attempts_gte_eight_defenders", "Stacked-box rate %", None),
        ("avg_rush_yards", "Avg rush yards", True),
    ],
    "receiving": [
        ("avg_separation", "Separation (yds)", True),
        ("avg_cushion", "Cushion (yds)", None),
        ("avg_yac_above_expectation", "YAC over expected", True),
        ("avg_yac", "YAC / reception", True),
        ("avg_expected_yac", "Expected YAC", None),
        ("avg_intended_air_yards", "Intended air yards", None),
        ("percent_share_of_intended_air_yards", "Air yards share %", True),
        ("catch_percentage", "Catch %", True),
    ],
}

# Plain-English meaning of each stat, shown under its name on the card.
NGS_TIPS = {
    "completion_percentage_above_expectation": "Completion rate beyond what the throws' difficulty predicts. Higher = more accurate than the average QB on the same throws.",
    "expected_completion_percentage": "How often an average QB would complete his throws, based on distance, coverage and pressure. A difficulty gauge, not a skill score.",
    "avg_time_to_throw": "Seconds from snap to release. Low = quick release; high = holds the ball or throws deep.",
    "aggressiveness": "Share of throws into tight windows (defender within 1 yard). High = gunslinger.",
    "avg_intended_air_yards": "How far downfield his throws are aimed on average. A style measure, not good or bad.",
    "avg_completed_air_yards": "How far downfield his completed passes travel before the catch.",
    "avg_air_yards_differential": "Completed minus intended air yards. Near zero or positive = completes deep throws; very negative = deep throws fall incomplete.",
    "avg_air_yards_to_sticks": "Air yards relative to the first-down marker. Positive = throws past the sticks; negative = throws short of them.",
    "max_completed_air_distance": "The longest completed pass he has thrown this season, measured in the air.",
    "passer_rating": "Standard NFL passer rating (max 158.3).",
    "rush_yards_over_expected_per_att": "Yards per carry beyond what the blocking and box predict. Higher = creating yards on his own.",
    "rush_pct_over_expected": "Share of carries that beat the expected gain.",
    "efficiency": "Distance traveled per yard gained. Lower = runs straight ahead; higher = dancing behind the line.",
    "avg_time_to_los": "Seconds from handoff to reaching the line of scrimmage. Low = decisive; high = patient.",
    "percent_attempts_gte_eight_defenders": "Share of carries into a box of 8+ defenders. High = defenses are loading up to stop him.",
    "avg_rush_yards": "Average yards per carry.",
    "avg_separation": "Yards of space from the nearest defender at the catch. More = easier to get open.",
    "avg_cushion": "Yards of room defenders give him at the snap. Large = respected less; small = pressed.",
    "avg_yac_above_expectation": "Yards after the catch beyond what the situation predicts. Higher = makes defenders miss.",
    "avg_yac": "Average yards gained after the catch per reception.",
    "avg_expected_yac": "Yards after the catch an average receiver would get on his catches.",
    "percent_share_of_intended_air_yards": "His share of the team's total targeted air yards. High = the offense throws downfield to him.",
    "catch_percentage": "Share of his targets he catches.",
}
NGS_MIN_VOLUME = {"passing": ("attempts", 40), "rushing": ("rush_attempts", 20), "receiving": ("targets", 10)}


def _season_rows(ngs):
    """NGS ships one season-aggregate row per player (week == 0) plus one row
    per week. Season numbers must come from the aggregate row; averaging all
    rows would count the aggregate as an extra week."""
    if ngs is None or ngs.empty:
        return ngs
    return ngs[ngs["week"] == 0]


def ngs_profile(ngs, kind, player_id):
    """Every Next Gen Stat for this player: a list of
    {key, label, value, percentile, higher_is_better, weekly: [{week, value}]},
    percentile (0-100) among peers with enough volume. [] when he has no NGS."""
    season = _season_rows(ngs)
    if season is None or season.empty or player_id not in set(season["player_gsis_id"]):
        return []
    vol_col, vol_min = NGS_MIN_VOLUME[kind]
    peers = season[season[vol_col] >= vol_min] if vol_col in season else season
    mine = season[season["player_gsis_id"] == player_id].iloc[0]
    weekly = ngs[(ngs["player_gsis_id"] == player_id) & (ngs["week"] > 0)].sort_values("week")
    out = []
    for col, label, higher in NGS_SPECS[kind]:
        if col not in season.columns or pd.isna(mine[col]):
            continue
        vals = peers[col].dropna()
        pct = None
        if len(vals) >= 5:
            pct = float((vals < mine[col]).mean() * 100 + (vals == mine[col]).mean() * 50)
            if higher is False:
                pct = 100 - pct
        out.append({
            "key": col, "label": label, "tip": NGS_TIPS.get(col, ""), "value": round(float(mine[col]), 2),
            "percentile": None if pct is None else round(pct),
            "higher_is_better": higher,
            "weekly": [{"week": int(r.week), "value": round(float(v), 2)}
                       for r, v in zip(weekly.itertuples(), weekly[col]) if pd.notna(v)],
        })
    return out


def team_schedule(schedule, team):
    """{week: {opponent, home, gameday, gametime}} for a team's regular season."""
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


def weekly_status(player_weeks, schedule, team, final_week=18):
    """One row per week 1..final_week for a player:
        status  "played" | "bye" | "dnp" (team played, he didn't) | "upcoming"
        plus opponent/home and, when played, whatever stat columns the caller
        passed in player_weeks (a DataFrame with a `week` column).
    A week the team has no game is the BYE; a played game with no stat row is
    a miss, which is what the weekly breakdown needs to make obvious."""
    sched = team_schedule(schedule, team)
    by_week = {int(r["week"]): r for r in player_weeks.to_dict(orient="records")}
    rows = []
    for wk in range(1, final_week + 1):
        game = sched.get(wk)
        if game is None:
            rows.append({"week": wk, "status": "bye"})
            continue
        base = {"week": wk, "opponent": game["opponent"], "home": game["home"],
                "gameday": game["gameday"], "gametime": game["gametime"]}
        if wk in by_week:
            rows.append({**by_week[wk], **base, "status": "played"})
        elif game["played"]:
            rows.append({**base, "status": "dnp"})
        else:
            rows.append({**base, "status": "upcoming"})
    return rows


def bye_weeks(schedule):
    """{team: bye week} from the regular-season schedule: the one week in
    1..max a team has no game."""
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    if s.empty:
        return {}
    weeks = set(range(1, int(s["week"].max()) + 1))
    out = {}
    for team in set(s["home_team"]) | set(s["away_team"]):
        played = set(s[(s["home_team"] == team) | (s["away_team"] == team)]["week"].astype(int))
        missing = sorted(weeks - played)
        if len(missing) == 1:
            out[team] = missing[0]
    return out


def stat_line(row, position):
    """The one-line box score shown under a player: '249 att, 164 cmp, 1,794 yds, 11 TD, 6 INT'."""
    def n(key):
        v = row.get(key)
        return 0 if v is None or pd.isna(v) else int(round(float(v)))
    if position == "QB":
        parts = [f"{n('attempts')} att", f"{n('completions')} cmp", f"{n('passing_yards'):,} yds",
                 f"{n('passing_tds')} TD", f"{n('interceptions')} INT"]
        if n("rushing_yards"):
            parts.append(f"{n('rushing_yards')} rush yds")
    elif position == "RB":
        parts = [f"{n('carries')} car", f"{n('rushing_yards'):,} yds", f"{n('rushing_tds')} TD",
                 f"{n('receptions')} rec", f"{n('receiving_yards'):,} rec yds"]
        if n("receiving_tds"):
            parts.append(f"{n('receiving_tds')} rec TD")
    else:
        parts = [f"{n('targets')} tgt", f"{n('receptions')} rec", f"{n('receiving_yards'):,} yds",
                 f"{n('receiving_tds')} TD"]
        if n("rushing_yards"):
            parts.append(f"{n('rushing_yards')} rush yds")
    return ", ".join(parts)


def upcoming_week(schedule):
    """The next regular-season week with an unplayed game (what 'this week'
    means for BYE tags and lineups), or None once the season is over."""
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    return int(s["week"].min()) if len(s) else None
