"""
DEFENSE / SPECIAL TEAMS SCORING
================================
Real fantasy points for a DEF/ST roster slot. Unlike a rookie with no NFL
games in our data yet, a defense's own real per-game production (sacks,
takeaways, defensive/return TDs, safeties, blocked kicks, points allowed)
is fully available in the same free, legal nflverse play-by-play and
schedule data everything else in this app already loads — there's no
reason a DEF slot should show a blank projection the way an unpriceable
player does.

Scored with the real Sleeper league's own scoring settings when given —
sack/INT/fumble-recovery/TD/safety/blocked-kick point values and the
points-allowed tier table — the same "custom to your exact league" pitch
as engine/scoring.py, extended to the categories offense-only
ScoringSettings never needed. Falls back to Sleeper's own common default
values for anything a league doesn't specify.
"""

import numpy as np
import pandas as pd

DEFAULT_DEF_SCORING = dict(
    def_sack=1.0, def_int=2.0, def_fumble_rec=2.0, def_td=6.0,
    def_safety=2.0, def_blocked_kick=2.0,
    pts_allow_0=10.0, pts_allow_1_6=7.0, pts_allow_7_13=4.0, pts_allow_14_20=1.0,
    pts_allow_21_27=0.0, pts_allow_28_34=-1.0, pts_allow_35p=-4.0,
)

# Sleeper's raw scoring_settings keys -> ours. `int` here is the DEFENSE
# forcing an interception (Sleeper scores the QB's own thrown pick
# separately, as `pass_int` — see engine/sleeper.SLEEPER_SCORING_MAP).
SLEEPER_DEF_SCORING_MAP = {
    "sack": "def_sack", "int": "def_int", "fum_rec": "def_fumble_rec",
    "def_td": "def_td", "safe": "def_safety", "blk_kick": "def_blocked_kick",
    "pts_allow_0": "pts_allow_0", "pts_allow_1_6": "pts_allow_1_6",
    "pts_allow_7_13": "pts_allow_7_13", "pts_allow_14_20": "pts_allow_14_20",
    "pts_allow_21_27": "pts_allow_21_27", "pts_allow_28_34": "pts_allow_28_34",
    "pts_allow_35p": "pts_allow_35p",
}

# The one real discrepancy found between Sleeper's team codes (what a DEF
# roster slot's id actually is) and nflverse's (what pbp/schedule use):
# the Rams. Every other code lines up exactly — see engine/tools.py's
# defense lookup for where this gets applied.
SLEEPER_TO_NFLVERSE_TEAM = {"LAR": "LA"}


def def_scoring_from_sleeper(scoring_settings):
    out = dict(DEFAULT_DEF_SCORING)
    for sleeper_key, our_key in SLEEPER_DEF_SCORING_MAP.items():
        if sleeper_key in (scoring_settings or {}):
            out[our_key] = float(scoring_settings[sleeper_key])
    return out


def _points_allowed_score(points, s):
    if pd.isna(points):
        return 0.0
    if points <= 0:
        return s["pts_allow_0"]
    if points <= 6:
        return s["pts_allow_1_6"]
    if points <= 13:
        return s["pts_allow_7_13"]
    if points <= 20:
        return s["pts_allow_14_20"]
    if points <= 27:
        return s["pts_allow_21_27"]
    if points <= 34:
        return s["pts_allow_28_34"]
    return s["pts_allow_35p"]


def build_defense_weekly(pbp, schedule):
    """One row per (defteam, week): real defensive/ST production — sacks,
    takeaways, defensive/return TDs, safeties, blocked kicks — plus points
    allowed that week (the actual final score, from the schedule, not
    derived from pbp)."""
    needed = ("defteam", "week", "sack", "interception", "fumble_recovery_1_team",
              "safety", "touchdown", "td_team", "punt_blocked", "field_goal_result")
    missing = [c for c in needed if c not in pbp.columns]
    if missing:
        raise ValueError(f"pbp is missing columns defense scoring needs: {missing} "
                          "(engine/data.load_pbp's `keep` list must include them)")

    g = pbp.groupby(["defteam", "week"])
    weekly = pd.DataFrame({"sacks": g["sack"].sum(), "ints": g["interception"].sum()})

    fumble_rec = (pbp[pbp["fumble_recovery_1_team"] == pbp["defteam"]]
                  .groupby(["defteam", "week"]).size())
    safeties = pbp[pbp["safety"] == 1].groupby(["defteam", "week"]).size()
    def_tds = (pbp[(pbp["touchdown"] == 1) & (pbp["td_team"] == pbp["defteam"])]
               .groupby(["defteam", "week"]).size())
    # Approximation, not exact: a blocked kick that's also recovered can
    # double-count against fumble_rec on the rare play where nflverse
    # marks both — an accepted small overcount on a low-weight category
    # rather than the added complexity of disambiguating it play by play.
    blocked = (pbp[(pbp["punt_blocked"] == 1) | (pbp["field_goal_result"] == "blocked")]
               .groupby(["defteam", "week"]).size())

    weekly["fumble_rec"] = fumble_rec
    weekly["safeties"] = safeties
    weekly["def_tds"] = def_tds
    weekly["blocked_kicks"] = blocked
    weekly = weekly.fillna(0).reset_index()

    # Points allowed: the opponent's real final score, from the schedule —
    # one row per (team, week) it actually played, both home and away.
    home = schedule[["week", "home_team", "away_score"]].rename(
        columns={"home_team": "team", "away_score": "points_allowed"})
    away = schedule[["week", "away_team", "home_score"]].rename(
        columns={"away_team": "team", "home_score": "points_allowed"})
    pa = pd.concat([home, away], ignore_index=True).dropna(subset=["points_allowed"])
    pa = pa.set_index(["team", "week"])["points_allowed"]

    weekly["points_allowed"] = pa.reindex(list(zip(weekly["defteam"], weekly["week"]))).values
    return weekly.dropna(subset=["points_allowed"])


def score_defense_weekly(weekly, def_settings):
    s = def_settings
    return (
        weekly["sacks"] * s["def_sack"]
        + weekly["ints"] * s["def_int"]
        + weekly["fumble_rec"] * s["def_fumble_rec"]
        + weekly["def_tds"] * s["def_td"]
        + weekly["safeties"] * s["def_safety"]
        + weekly["blocked_kicks"] * s["def_blocked_kick"]
        + weekly["points_allowed"].apply(lambda p: _points_allowed_score(p, s))
    ).round(2)


def build_defense_board(pbp, schedule, scoring_settings=None):
    """SCORE/FORM/floor/ceiling/fpts_per_game for every real defense,
    keyed by nflverse team code (see SLEEPER_TO_NFLVERSE_TEAM for the one
    place that differs from a Sleeper DEF roster slot's own id) — shaped
    like build_board()'s output so the rest of the app can treat a DEF
    slot the same way it treats a player."""
    def_settings = def_scoring_from_sleeper(scoring_settings)
    weekly = build_defense_weekly(pbp, schedule)
    weekly["fpts"] = score_defense_weekly(weekly, def_settings)

    g = weekly.groupby("defteam")
    board = pd.DataFrame({
        "games": g.size(),
        "fpts_per_game": g["fpts"].mean().round(2),
        "sacks_per_game": g["sacks"].mean().round(2),
        "takeaways_per_game": (g["ints"].mean() + g["fumble_rec"].mean()).round(2),
        "floor": g["fpts"].quantile(0.25).clip(lower=0).round(1),
        "ceiling": g["fpts"].quantile(0.75).round(1),
    })

    rng = board["fpts_per_game"].max() - board["fpts_per_game"].min()
    board["SCORE"] = (((board["fpts_per_game"] - board["fpts_per_game"].min()) / rng * 100)
                       if rng else pd.Series(50.0, index=board.index)).round(1)

    def _form(pdata):
        pdata = pdata.sort_values("week")
        season_avg = pdata["fpts"].mean()
        recent_avg = pdata["fpts"].tail(3).mean()
        if season_avg:
            return round(float(np.clip((recent_avg - season_avg) / season_avg, -0.4, 0.4)) * 100, 1)
        return 0.0

    board["FORM"] = pd.Series({team: _form(d) for team, d in weekly.groupby("defteam")})
    board.index.name = "player_id"
    return board.sort_values("SCORE", ascending=False)


def resolve_defense_row(team_code, defense_board):
    """defense_board is keyed by nflverse team code; a Sleeper DEF roster
    slot's own id is the Sleeper team code (identical for every team
    except the Rams — see SLEEPER_TO_NFLVERSE_TEAM)."""
    nflverse_code = SLEEPER_TO_NFLVERSE_TEAM.get(team_code, team_code)
    if nflverse_code not in defense_board.index:
        return None
    return defense_board.loc[nflverse_code].to_dict()
