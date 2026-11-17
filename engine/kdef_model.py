"""
KICKER AND DEF/ST PROJECTIONS — the betting market, not recent form
====================================================================
The old projection was the history-blended per-game rate x (1 + FORM) [x the opposing
offense's factor for a defense]. Replayed game by game on 2024-25 regular seasons
(scripts/backtest_kdef.py, each prediction made from only the games before it) that was WORSE
than giving every defense or kicker the league average:

                          RMSE   weekly rank corr   avg pts of each week's top-20% picks
    DEF  league average    5.66        --                 --
    DEF  old formula       5.93       0.24                8.0
    DEF  this model        5.34       0.34                8.8
    K    league average    4.85        --                 --
    K    old formula       4.97       0.10                9.3
    K    this model        4.77       0.20                9.3

(Walk-forward fits of the same model, i.e. truly out of sample, score 5.35 and 4.81.)
A defense is a real improvement: about 10% less error and a much better weekly ranking. A
kicker is a small one: kickers are close to a coin flip week to week, and the model's honest
claim is "no worse than the average, a little better at ordering them", not a sharp forecast.

Recent form and the opposing offense's results so far are mostly noise for these two
positions: a defense's output is driven by how many points its opponent is expected to
score, and a kicker's by how many his own offense is expected to score (and a dome).
Both come straight from the game's betting lines, which the schedule already carries.
The rest of the signal, the player's own history-blended rate, is real but small, so it
is a minor term.

    DEF  ratio = 0.9993 + 0.0844 (rate/pool - 1) - 0.0747 (opponent implied total - 22)
    K    ratio = 0.9656 + 0.1709 (rate/pool - 1) + 0.0174 (own implied total - 22) + 0.0934 (dome)
    projection = pool x ratio

`pool` is the league-wide average rate of the same board, so the model is a RATIO and works
under any scoring: a league that pays differently for sacks, points allowed or long field
goals rescales both `rate` and `pool` together. The coefficients were fit on 2023-25 under
default Sleeper scoring, regular season only (scripts/backtest_kdef.py prints the fit's
out-of-sample score). With no betting line yet (a far-off week) the market terms go neutral
and the projection is the shrunk rate alone.
"""

import numpy as np
import pandas as pd

NEUTRAL_ITT = 22.0           # the league's average implied team total (2023-25 mean 22.0)
NEUTRAL_INDOOR = 0.33        # share of kicker games played under a roof (2023-25: 0.329)
ITT_RANGE = (14.0, 31.0)     # implied totals outside this are clamped; the fit saw ~15-29.5
RATIO_RANGE = (0.25, 2.0)    # keeps a freak line from projecting a defense below -75% or past 2x the average

# opp_sack added 2026-11-17 (analysis/kdef_adv_backtest.py): the opposing offense's sack rate allowed, from this season's
# play-by-play, is the one play-by-play stat that beat the market model out of sample (2024-25: RMSE 5.351 -> 5.339,
# weekly rank 0.338 -> 0.343, top-20% picks 9.01 -> 9.14 pts). Giveaway rate, red-zone rate and wind did not; kickers stay
# as they were. Refit on 2023-25 with the new term (`--fit`).
DEF_COEF = {"base": 0.9976, "rate": 0.1188, "itt_opp": -0.0685, "opp_sack": 0.2472}
SACK_SHRINK_DROPBACKS = 75.0     # pseudo-dropbacks of league-average sack rate mixed into each offense
SACK_RANGE = (0.6, 1.6)
K_COEF = {"base": 0.9656, "rate": 0.1709, "itt": 0.0174, "indoor": 0.0934}


def _clean(x, default):
    return default if x is None or pd.isna(x) else float(x)


def game_context(schedule, team, week=None):
    """{itt, itt_opp, indoor} for `team`'s game in `week` (default: its next unplayed game), from the
    schedule's betting lines. A value is None when the line isn't posted yet; None for no game."""
    sched = schedule[(schedule["home_team"] == team) | (schedule["away_team"] == team)]
    if week is None:
        if "home_score" in sched:
            sched = sched[sched["home_score"].isna()]
        if sched.empty:
            return None
        row = sched.sort_values("week").iloc[0]
    else:
        sched = sched[sched["week"] == week]
        if sched.empty:
            return None
        row = sched.iloc[0]
    spread, total = row.get("spread_line"), row.get("total_line")
    itt = itt_opp = None
    if spread is not None and total is not None and not pd.isna(spread) and not pd.isna(total):
        home = row["home_team"] == team
        sgn = 1.0 if home else -1.0           # spread_line is the HOME team's margin
        itt, itt_opp = (total + sgn * spread) / 2, (total - sgn * spread) / 2
    roof = row.get("roof")
    indoor = None if roof is None or pd.isna(roof) else (1.0 if str(roof) in ("dome", "closed") else 0.0)
    opp = row["away_team"] if row["home_team"] == team else row["home_team"]
    return {"itt": itt, "itt_opp": itt_opp, "indoor": indoor, "opp": opp}


def _ratio(x):
    return float(np.clip(x, *RATIO_RANGE))


def offense_sack_ratio(pbp, team):
    """The offense's sack rate allowed (sacks per dropback) this season as a ratio to the league (1.0 = average),
    shrunk with SACK_SHRINK_DROPBACKS pseudo-dropbacks. None when there's no play-by-play to read."""
    if pbp is None or not len(pbp) or not team or not {"qb_dropback", "sack", "posteam"} <= set(pbp.columns):
        return None
    d = pbp[pbp["qb_dropback"] == 1]
    if d.empty:
        return None
    league = float(d["sack"].fillna(0).mean())
    if league <= 0:
        return None
    mine = d[d["posteam"] == team]
    rate = (float(mine["sack"].fillna(0).sum()) + SACK_SHRINK_DROPBACKS * league) / (len(mine) + SACK_SHRINK_DROPBACKS)
    return float(np.clip(rate / league, *SACK_RANGE))


def defense_projection(rate, pool, itt_opp=None, opp_sack=None):
    """Points this defense is expected to score against an offense implied for `itt_opp` that allows sacks at
    `opp_sack` times the league rate (None = average)."""
    if not pool or pool <= 0:
        return float(rate)
    itt = float(np.clip(_clean(itt_opp, NEUTRAL_ITT), *ITT_RANGE))
    sk = float(np.clip(_clean(opp_sack, 1.0), *SACK_RANGE))
    c = DEF_COEF
    return round(pool * _ratio(c["base"] + c["rate"] * (rate / pool - 1) + c["itt_opp"] * (itt - NEUTRAL_ITT)
                               + c["opp_sack"] * (sk - 1)), 1)


def kicker_projection(rate, pool, itt=None, indoor=None):
    """Points this kicker is expected to score with his offense implied for `itt`."""
    if not pool or pool <= 0:
        return float(rate)
    t = float(np.clip(_clean(itt, NEUTRAL_ITT), *ITT_RANGE))
    c = K_COEF
    return round(pool * _ratio(c["base"] + c["rate"] * (rate / pool - 1) + c["itt"] * (t - NEUTRAL_ITT)
                               + c["indoor"] * _clean(indoor, NEUTRAL_INDOOR)), 1)
