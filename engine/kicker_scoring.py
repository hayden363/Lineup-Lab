"""
KICKER SCORING
==============
Real fantasy points for a K roster slot, built from play-by-play — field
goals by distance bucket, misses, extra points — the same approach
engine/defense_scoring.py uses for DEF/ST. Kickers were never in
nflverse's weekly player-stats table (see engine/data.load_weekly), which
is the only reason this was unscored before: a kicker's Sleeper id
already resolves to a real gsis_id through the same crosswalk QB/RB/WR/TE
use, no team-code juggling needed here (contrast engine/defense_scoring's
Rams alias) — see engine/tools.py's K handling.

Scored with the real league's own Sleeper scoring settings when given —
per-distance-bucket FG values, miss penalty, XP make/miss — falling back
to Sleeper's own common defaults otherwise.

Projection is FORM-adjusted average, same shape as everything else in
this app (a kicker's own real game log, not one blanket number) — not a
defense-adjusted matchup model. Unlike a skill-position player, a
kicker's output is driven by his own team's scoring efficiency (how often
a drive stalls into a field-goal try vs. a touchdown) far more than by
the opponent's defensive quality, so grafting on an opponent factor the
way engine/defense.py does for offense would manufacture a signal that
isn't really there.
"""

import numpy as np
import pandas as pd

from .metrics import _recency_weighted_pct

DEFAULT_K_SCORING = dict(
    fgm_0_19=3.0, fgm_20_29=3.0, fgm_30_39=3.0, fgm_40_49=4.0,
    fgm_50_59=5.0, fgm_60p=6.0, fgmiss=-1.0, xpm=1.0, xpmiss=-1.0,
)

FG_BUCKETS = ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgm_60p")


def k_scoring_from_sleeper(scoring_settings):
    """Sleeper's own kicker scoring keys already match ours 1:1 (fgm_0_19,
    fgmiss, xpm, ...) — no translation table needed, unlike the offense/
    DEF mappings."""
    out = dict(DEFAULT_K_SCORING)
    for key in DEFAULT_K_SCORING:
        if key in (scoring_settings or {}):
            out[key] = float(scoring_settings[key])
    return out


def _fg_bucket(distance):
    if distance < 20:
        return "fgm_0_19"
    if distance < 30:
        return "fgm_20_29"
    if distance < 40:
        return "fgm_30_39"
    if distance < 50:
        return "fgm_40_49"
    if distance < 60:
        return "fgm_50_59"
    return "fgm_60p"


def build_kicker_weekly(pbp):
    """One row per (player_id, week): real makes by distance bucket,
    misses (missed or blocked — both count against the kicker the same
    way in standard scoring), and extra points made/missed."""
    needed = ("kicker_player_id", "week", "field_goal_attempt", "field_goal_result",
              "kick_distance", "extra_point_attempt", "extra_point_result")
    missing = [c for c in needed if c not in pbp.columns]
    if missing:
        raise ValueError(f"pbp is missing columns kicker scoring needs: {missing} "
                          "(engine/data.load_pbp's `keep` list must include them)")

    fg = pbp[pbp["field_goal_attempt"] == 1].dropna(subset=["kicker_player_id", "kick_distance"]).copy()
    xp = pbp[pbp["extra_point_attempt"] == 1].dropna(subset=["kicker_player_id"]).copy()

    fg["bucket"] = fg["kick_distance"].apply(_fg_bucket)
    made = (fg[fg["field_goal_result"] == "made"]
            .groupby(["kicker_player_id", "week", "bucket"]).size().unstack(fill_value=0))
    for col in FG_BUCKETS:
        if col not in made.columns:
            made[col] = 0
    miss = (fg[fg["field_goal_result"] != "made"]
            .groupby(["kicker_player_id", "week"]).size().rename("fg_miss"))
    xp_made = (xp[xp["extra_point_result"] == "good"]
               .groupby(["kicker_player_id", "week"]).size().rename("xp_made"))
    xp_miss = (xp[xp["extra_point_result"] != "good"]
               .groupby(["kicker_player_id", "week"]).size().rename("xp_miss"))

    weekly = made.join([miss, xp_made, xp_miss], how="outer").fillna(0).reset_index()
    return weekly.rename(columns={"kicker_player_id": "player_id"})


def score_kicker_weekly(weekly, k_settings):
    s = k_settings
    fpts = pd.Series(0.0, index=weekly.index)
    for bucket in FG_BUCKETS:
        fpts += weekly[bucket] * s[bucket]
    fpts += weekly["fg_miss"] * s["fgmiss"] + weekly["xp_made"] * s["xpm"] + weekly["xp_miss"] * s["xpmiss"]
    return fpts.round(2)


def build_team_kicker_baseline(pbp, scoring_settings=None):
    """Real per-team kicking production (fpts/game), regardless of which
    individual did the kicking — the fallback for a kicker with a known
    CURRENT team (from Sleeper's live roster data, not our stale nflverse
    snapshot — see engine/tools._kicker_row) but no personal game log of
    his own, most commonly a rookie or a new signing.

    This is not a guess about his own leg. It's a real, sourced number —
    "this team's kicking operation produced about X points/game last
    season" — which is a reasonable thing to lean on precisely because a
    kicker's output is driven far more by his team's scoring environment
    (how often a drive stalls into a field-goal try) than by individual
    skill, the same reasoning build_kicker_board's docstring gives for
    NOT building an opponent-matchup adjustment. A team that changed
    kickers mid-season only makes this MORE representative of the team's
    real kicking opportunity level, not less."""
    k_settings = k_scoring_from_sleeper(scoring_settings)
    needed = ("posteam", "week", "field_goal_attempt", "field_goal_result",
              "kick_distance", "extra_point_attempt", "extra_point_result")
    missing = [c for c in needed if c not in pbp.columns]
    if missing:
        raise ValueError(f"pbp is missing columns the kicker team baseline needs: {missing}")

    fg = pbp[pbp["field_goal_attempt"] == 1].dropna(subset=["posteam", "kick_distance"]).copy()
    xp = pbp[pbp["extra_point_attempt"] == 1].dropna(subset=["posteam"]).copy()
    fg["bucket"] = fg["kick_distance"].apply(_fg_bucket)

    made = fg[fg["field_goal_result"] == "made"].groupby(["posteam", "week", "bucket"]).size().unstack(fill_value=0)
    for col in FG_BUCKETS:
        if col not in made.columns:
            made[col] = 0
    miss = fg[fg["field_goal_result"] != "made"].groupby(["posteam", "week"]).size().rename("fg_miss")
    xp_made = xp[xp["extra_point_result"] == "good"].groupby(["posteam", "week"]).size().rename("xp_made")
    xp_miss = xp[xp["extra_point_result"] != "good"].groupby(["posteam", "week"]).size().rename("xp_miss")

    weekly = made.join([miss, xp_made, xp_miss], how="outer").fillna(0).reset_index()
    weekly = weekly.rename(columns={"posteam": "team"})
    weekly["fpts"] = score_kicker_weekly(weekly, k_settings)
    return weekly.groupby("team")["fpts"].mean().round(2)


def build_kicker_board(pbp, scoring_settings=None, min_games=2):
    """SCORE/FORM/floor/ceiling/fpts_per_game for every real kicker who
    attempted a kick this season, keyed by gsis_id — same shape as
    build_board()'s offensive output and defense_scoring.build_defense_board,
    so the rest of the app can treat a K slot the same way."""
    k_settings = k_scoring_from_sleeper(scoring_settings)
    weekly = build_kicker_weekly(pbp)
    weekly["fpts"] = score_kicker_weekly(weekly, k_settings)
    weekly["fg_made"] = weekly[list(FG_BUCKETS)].sum(axis=1)

    g = weekly.groupby("player_id")
    board = pd.DataFrame({
        "games": g.size(),
        "fpts_per_game": g["fpts"].mean().round(2),
        "fg_made_per_game": g["fg_made"].mean().round(2),
        "fg_miss_per_game": g["fg_miss"].mean().round(2),
        "floor": g["fpts"].quantile(0.25).clip(lower=0).round(1),
        "ceiling": g["fpts"].quantile(0.75).round(1),
    })
    # same "don't rank someone off a one-game sample" bar the rest of the
    # app uses (engine/metrics.MIN_GAMES) — a single hot/cold game
    # shouldn't stand in for a kicker's real season.
    board = board[board["games"] >= min_games]

    rng = board["fpts_per_game"].max() - board["fpts_per_game"].min() if len(board) else 0
    board["SCORE"] = (((board["fpts_per_game"] - board["fpts_per_game"].min()) / rng * 100)
                       if rng else pd.Series(50.0, index=board.index)).round(1)

    def _form(pdata):
        # Same real recency-weighting + sample-size confidence shrinkage
        # as skill positions (engine.metrics.form_adjustment) and DEF/ST
        # (engine.defense_scoring — see that file's _form for the fuller
        # writeup) — this had the identical blunt "last 3 games vs season
        # average" gap DEF/ST used to have, same fix applies.
        pdata = pdata.sort_values("week")
        pct = _recency_weighted_pct(pdata["fpts"].to_numpy(), halflife=2.5, min_games_full_confidence=8)
        return round(float(np.clip(pct, -0.4, 0.4)) * 100, 1)

    board["FORM"] = pd.Series({pid: _form(d) for pid, d in weekly.groupby("player_id") if pid in board.index})
    board.index.name = "player_id"
    return board.sort_values("SCORE", ascending=False)
