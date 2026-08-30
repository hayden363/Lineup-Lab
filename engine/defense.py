"""
DEFENSIVE PROFILE ENGINE — granular, multi-stat matchup adjustment
======================================================================
The old matchup model (engine/matchup.py) was one number per (defense,
position): total fantasy points allowed vs league average. That blends
everything together — a defense could allow average RB fantasy points
while actually being elite against the run and leaky against
check-downs, and the blanket number hides that.

This module builds a real defensive profile per team from play-by-play —
run defense, pass defense, and pressure, each broken into several
categories (yards/carry allowed, completion % allowed, sack rate
generated, explosive-play rate allowed, EPA allowed, etc.) — computed the
same honest way as everything else in this app: real per-play results,
not proprietary grades.

Every one of a player's own value metrics (the same metrics SCORE is
built from, in engine/metrics.py) gets mapped to the defensive category
that actually predicts it, and adjusted by that category's real,
opponent-specific factor. A blanket "how many points did this defense
allow" model can't tell you a run-stuffing defense should specifically
hurt a between-the-tackles runner more than a pass-catching one; this
one can, because it's connecting the specific stat to the specific
metric instead of averaging everything into one number.

Next Gen Stats (separation, cushion, CPOE, etc.) aren't part of this
matchup layer yet — deliberately left for a follow-up, per your note.
"""

import numpy as np
import pandas as pd

from .metrics import WEIGHTS

# ----------------------------------------------------------------------
# Build the profile: one row per defense (defteam), many stat categories.
# ----------------------------------------------------------------------
def build_defense_profile(pbp):
    passes = pbp[pbp["play_type"] == "pass"].copy()
    runs = pbp[pbp["play_type"] == "run"].copy()

    passes["pressured"] = ((passes["sack"] == 1) | (passes["qb_hit"] == 1)).astype(int)
    thrown = passes[passes["sack"] == 0]  # a sack isn't a pass attempt

    pg = passes.groupby("defteam")
    tg = thrown.groupby("defteam")
    rg = runs.groupby("defteam")

    pass_profile = pd.DataFrame({
        "pass_plays": pg.size(),
        "comp_pct_allowed": tg["complete_pass"].mean() * 100,
        "ypa_allowed": tg["yards_gained"].mean(),
        "pass_td_rate_allowed": tg["pass_touchdown"].mean() * 100,
        "int_rate_forced": tg["interception"].mean() * 100,
        "sack_rate_generated": pg["sack"].mean() * 100,
        "pressure_rate_generated": pg["pressured"].mean() * 100,
        "explosive_pass_rate_allowed": pg.apply(lambda d: (d["yards_gained"] >= 20).mean() * 100),
        "yac_per_completion_allowed": thrown[thrown["complete_pass"] == 1].groupby("defteam")["yards_after_catch"].mean(),
        "epa_per_pass_allowed": pg["epa"].mean(),
    })

    run_profile = pd.DataFrame({
        "run_plays": rg.size(),
        "ypc_allowed": rg["yards_gained"].mean(),
        "rush_td_rate_allowed": rg["rush_touchdown"].mean() * 100,
        "explosive_run_rate_allowed": rg.apply(lambda d: (d["yards_gained"] >= 10).mean() * 100),
        "stuff_rate": rg.apply(lambda d: (d["yards_gained"] <= 0).mean() * 100),
        "epa_per_rush_allowed": rg["epa"].mean(),
    })

    # target-based receiving stats need a per-target denominator, not per-completion
    ypt = thrown.groupby("defteam").apply(lambda d: d["yards_gained"].sum() / max(len(d), 1))
    pass_profile["ypt_allowed"] = ypt

    return pass_profile.join(run_profile, how="outer")


def league_relative_factors(profile):
    """Every raw stat -> a factor centered on 1.0. >1 always means 'more of
    this happened' — direction (good/bad for the offense) is handled later,
    when a metric's sign decides whether more is good.

    Rate/yardage columns (always positive, rarely near zero) use a plain
    ratio to league average. EPA columns cross zero and sit near it, where
    a ratio blows up (a defense at -0.01 EPA/play vs a league average of
    -0.002 is "a bit better than average," not a 5x factor) — those get a
    bounded z-score-based factor instead: same idea (above/below average),
    scaled sanely."""
    league_avg = profile.mean()
    league_std = profile.std().replace(0, np.nan)

    factors = pd.DataFrame(index=profile.index)
    for col in profile.columns:
        if "epa" in col:
            z = (profile[col] - league_avg[col]) / league_std[col]
            factors[col] = (1 + (z.fillna(0) / 2).clip(-0.3, 0.3)).round(3)
        else:
            factors[col] = (profile[col] / league_avg[col]).round(3) if league_avg[col] else 1.0
    return factors, league_avg


# ----------------------------------------------------------------------
# Map each position's own SCORE metrics to the defensive category that
# actually predicts it. `None` = no real defensive analog -> left neutral
# (usage/volume metrics like target_share are opportunity, not matchup).
# ----------------------------------------------------------------------
METRIC_TO_DEFENSE = {
    "QB": {
        "yards_per_attempt": "ypa_allowed",
        "completion_pct": "comp_pct_allowed",
        "td_rate": "pass_td_rate_allowed",
        "int_rate": "int_rate_forced",
        "sack_rate": "sack_rate_generated",
        "rush_yards_per_game": "ypc_allowed",
        "dakota": "epa_per_pass_allowed",
    },
    "RB": {
        "yards_per_carry": "ypc_allowed",
        "td_rate": "rush_td_rate_allowed",
        "touches_per_game": None,
        "yards_per_target": "ypt_allowed",
        "target_share": None,
        "rushing_epa_per_carry": "epa_per_rush_allowed",
    },
    "WR": {
        "target_share": None,
        "yards_per_target": "ypt_allowed",
        "td_rate_targets": "pass_td_rate_allowed",
        "catch_rate": "comp_pct_allowed",
        "air_yards_share": None,
        "wopr": None,
        "yac_per_reception": "yac_per_completion_allowed",
    },
}
METRIC_TO_DEFENSE["TE"] = METRIC_TO_DEFENSE["WR"]


def matchup_breakdown(position, opponent, factors):
    """Per-metric factor breakdown for one player's position vs one
    defense — what the UI shows as 'why this projection moved'."""
    mapping = METRIC_TO_DEFENSE.get(position, {})
    weights = WEIGHTS[position]
    rows = []
    for metric, weight in weights.items():
        def_col = mapping.get(metric)
        if def_col is None or opponent not in factors.index or def_col not in factors.columns:
            factor = 1.0
            category = None
        else:
            factor = float(factors.loc[opponent, def_col])
            category = def_col
        rows.append({"metric": metric, "weight": weight, "category": category, "factor": round(factor, 3)})
    return rows


def league_average_composite(position, factors):
    """Mean matchup multiplier across every real defense — used for the
    no-specific-opponent 'rest of season' blend instead of a specific
    matchup's number."""
    vals = [composite_multiplier(position, opp, factors) for opp in factors.index]
    return round(sum(vals) / len(vals), 3) if vals else 1.0


def composite_multiplier(position, opponent, factors):
    """Single blended matchup multiplier for PROJ: a weight-magnitude
    weighted average of every metric's real defensive factor. Metrics with
    no defensive analog count as neutral (1.0) but still weigh into the
    average, so a position dominated by volume metrics doesn't get
    over-swung by the one or two matchup-sensitive ones."""
    rows = matchup_breakdown(position, opponent, factors)
    total_w = sum(abs(r["weight"]) for r in rows)
    if total_w == 0:
        return 1.0
    blended = sum(abs(r["weight"]) * r["factor"] for r in rows) / total_w
    return round(float(blended), 3)
