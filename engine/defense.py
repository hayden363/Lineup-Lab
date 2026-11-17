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

Next Gen Stats, defense side: real player-tracking data attributed to
whichever defense was on the field, not just the play-by-play boxscore.
NGS is published per player per week with no opponent column, so
`build_ngs_defense_profile` derives "who did this player face that week"
from the schedule and aggregates from there — average separation
allowed (the literal "coverage separation allowed" example from the
roadmap), YAC-over-expectation allowed (tackling in space, isolated from
how far downfield the catch was), CPOE allowed (completion rate allowed,
adjusted for throw difficulty instead of raw), and rush yards over
expected allowed (run-defense quality isolated from box-count/blocking
context). Two of these replace a less-specific play-by-play category for
the same SCORE metric (see METRIC_TO_DEFENSE); two blend with a
play-by-play category into a composite rather than replacing it, since
EPA already captures real game-situation value that a tracking-only stat
doesn't.
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

    out = pass_profile.join(run_profile, how="outer")
    out["qb_rush_ypg_allowed"] = qb_rush_allowed(pbp).reindex(out.index)
    return out


# ---- what a defense gives up to EACH position (owner 2026-11-17: our own position-specific metrics) ---------------
# Team-wide "yards per target allowed" mixes WRs, TEs and RBs; a defense can smother WRs and leak to TEs. Every
# target/carry is tagged with the receiving/rushing player's position (nflverse weekly roster) and each stat is shrunk
# toward the league mean with pseudo-observations, since a few games per defense are noisy.
# analysis/pos_matchup_backtest.py picked these over the team-wide stats for RB, WR and TE (2021-2025, walk-forward).
POS_SHRINK_TARGETS, POS_SHRINK_CARRIES, POS_SHRINK_GAMES = 60.0, 60.0, 4.0


def position_allowed(pbp, pos_of):
    """DataFrame (index = defense) of per-position allowed stats: ypt/catch/td/yac_allowed_{WR,TE,RB},
    tgt_pg_allowed_{WR,TE,RB}, ypc_allowed_RB, rush_td_allowed_RB, touch_pg_allowed_RB. `pos_of` maps player_id to
    position. Empty frame when the inputs can't support it."""
    need = {"defteam", "week", "play_type", "receiver_player_id", "rusher_player_id", "yards_gained", "complete_pass",
            "pass_touchdown", "rush_touchdown", "yards_after_catch", "sack"}
    if pbp is None or not len(pbp) or not need <= set(pbp.columns) or pos_of is None or not len(pos_of):
        return pd.DataFrame()
    idx = sorted(pbp["defteam"].dropna().unique())
    out = pd.DataFrame(index=idx)
    games = pbp.groupby("defteam")["week"].nunique().reindex(idx).fillna(0)

    def shrunk(num, den, k):
        league = num.sum() / den.sum() if den.sum() else 0.0
        return (num + k * league) / (den + k)

    z = lambda s_: s_.reindex(idx).fillna(0.0)
    tg = pbp[(pbp["play_type"] == "pass") & (pbp["sack"] == 0) & pbp["receiver_player_id"].notna()]
    rpos = tg["receiver_player_id"].map(pos_of)
    rb_targets = None
    for P in ("WR", "TE", "RB"):
        t = tg[rpos == P]
        g = t.groupby("defteam")
        n, yds = z(g.size()), z(g["yards_gained"].sum())
        cat, td = z(g["complete_pass"].sum()), z(g["pass_touchdown"].sum())
        yac = z(t[t["complete_pass"] == 1].groupby("defteam")["yards_after_catch"].sum())
        out[f"ypt_allowed_{P}"] = shrunk(yds, n, POS_SHRINK_TARGETS)
        out[f"catch_allowed_{P}"] = shrunk(cat, n, POS_SHRINK_TARGETS)
        out[f"td_allowed_{P}"] = shrunk(td, n, POS_SHRINK_TARGETS)
        out[f"yac_allowed_{P}"] = shrunk(yac, cat, POS_SHRINK_TARGETS / 2)
        out[f"tgt_pg_allowed_{P}"] = shrunk(n, games, POS_SHRINK_GAMES)
        if P == "RB":
            rb_targets = n
    ru = pbp[(pbp["play_type"] == "run") & pbp["rusher_player_id"].notna()]
    ru = ru[ru["rusher_player_id"].map(pos_of) == "RB"]
    g = ru.groupby("defteam")
    n, yds, td = z(g.size()), z(g["yards_gained"].sum()), z(g["rush_touchdown"].sum())
    out["ypc_allowed_RB"] = shrunk(yds, n, POS_SHRINK_CARRIES)
    out["rush_td_allowed_RB"] = shrunk(td, n, POS_SHRINK_CARRIES)
    out["touch_pg_allowed_RB"] = shrunk(n + rb_targets, games, POS_SHRINK_GAMES)
    return out


QB_RUSH_SHRINK_GAMES = 4.0   # pseudo-games of league-average QB rushing mixed into each defense (small, noisy samples)
QB_MIN_DROPBACKS = 10        # a "QB" here = anyone with 10+ dropbacks in the data (keeps trick-play passers out)


def qb_rush_allowed(pbp):
    """QB rushing yards per game a defense allows: scrambles and designed QB runs (nflverse records both as run plays),
    QBs identified from the same play-by-play as passers. Owner 2026-11-17: a QB's rushing should be graded against how
    a defense handles QB runs, not its yards per carry against running backs. The backtest
    (analysis/qb_matchup_backtest.py) found this the best way to grade it. Shrunk toward the league mean with
    QB_RUSH_SHRINK_GAMES pseudo-games, since a few games of QB runs are noisy."""
    if pbp is None or not len(pbp) or "rusher_player_id" not in pbp.columns:
        return pd.Series(dtype=float)
    drop = pbp[pbp["qb_dropback"] == 1] if "qb_dropback" in pbp.columns else pbp[pbp["play_type"] == "pass"]
    counts = drop["passer_player_id"].value_counts()
    qbs = set(counts[counts >= QB_MIN_DROPBACKS].index)
    games = pbp.groupby("defteam")["week"].nunique()
    runs = pbp[(pbp["play_type"] == "run") & pbp["rusher_player_id"].isin(qbs)]
    yds = runs.groupby("defteam")["yards_gained"].sum().reindex(games.index).fillna(0.0)
    league = yds.sum() / games.sum() if games.sum() else 0.0
    return (yds + QB_RUSH_SHRINK_GAMES * league) / (games + QB_RUSH_SHRINK_GAMES)


def _team_week_opponent_map(schedule):
    """(team, week) -> the opponent it actually played that week, both
    directions of every game. NGS's weekly tables are keyed by the
    player's own team, not the defense they faced — this is what lets us
    attribute a receiver's tracking numbers to the defense on the other
    side of the ball."""
    home = schedule[["week", "home_team", "away_team"]].rename(
        columns={"home_team": "team", "away_team": "opponent"})
    away = schedule[["week", "away_team", "home_team"]].rename(
        columns={"away_team": "team", "home_team": "opponent"})
    both = pd.concat([home, away], ignore_index=True)
    return both.set_index(["team", "week"])["opponent"]


def build_ngs_defense_profile(ngs_pass, ngs_rush, ngs_rec, schedule):
    """Defense-side Next Gen Stats: real player-tracking data (not
    proprietary grades) attributed to the defense that was actually on
    the field, via the schedule's (team, week) -> opponent map. Week 0
    rows in NGS are season-long aggregates, not a real game — dropped so
    a full season isn't double-counted as if it were one more week."""
    opp_map = _team_week_opponent_map(schedule)

    def with_defteam(df):
        df = df[df["week"] >= 1].copy()
        df["defteam"] = opp_map.reindex(list(zip(df["team_abbr"], df["week"]))).values
        return df.dropna(subset=["defteam"])

    def wavg(df, value_col, weight_col):
        """Weighted average of a per-player-week NGS stat, grouped by the
        defense that faced it — weighted by the same volume (targets/
        receptions/attempts) the stat itself is already an average over,
        so one busy game doesn't count the same as one three-target
        cameo."""
        w = df[weight_col].clip(lower=0)
        num = (df[value_col] * w).groupby(df["defteam"]).sum()
        den = w.groupby(df["defteam"]).sum().replace(0, np.nan)
        return num / den

    rec = with_defteam(ngs_rec)
    pas = with_defteam(ngs_pass)
    rus = with_defteam(ngs_rush)

    return pd.DataFrame({
        "sep_allowed": wavg(rec, "avg_separation", "targets"),
        "yac_oe_allowed": wavg(rec, "avg_yac_above_expectation", "receptions"),
        "cpoe_allowed": wavg(pas, "completion_percentage_above_expectation", "attempts"),
        "rush_yards_oe_allowed": wavg(rus, "rush_yards_over_expected_per_att", "rush_attempts"),
    })


def league_relative_factors(profile):
    """Every raw stat -> a factor centered on 1.0. >1 always means 'more of
    this happened' — direction (good/bad for the offense) is handled later,
    when a metric's sign decides whether more is good.

    Rate/yardage columns (always positive, rarely near zero) use a plain
    ratio to league average. EPA and "over expectation" columns (EPA,
    CPOE, YAC-over-expectation, rush-yards-over-expected) cross zero and
    sit near it, where a ratio blows up (a defense at -0.01 EPA/play vs a
    league average of -0.002 is "a bit better than average," not a 5x
    factor) — those get a bounded z-score-based factor instead: same idea
    (above/below average), scaled sanely."""
    league_avg = profile.mean()
    league_std = profile.std().replace(0, np.nan)

    def is_centered(col):
        return "epa" in col or "cpoe" in col or "_oe_" in col

    factors = pd.DataFrame(index=profile.index)
    for col in profile.columns:
        if is_centered(col):
            z = (profile[col] - league_avg[col]) / league_std[col]
            factors[col] = (1 + (z.fillna(0) / 2).clip(-0.3, 0.3)).round(3)
        else:
            factors[col] = (profile[col] / league_avg[col]).round(3) if league_avg[col] else 1.0

    # Composite categories: blend a play-by-play z-scored factor with a
    # tracking-data one for the same underlying question, rather than
    # picking one and discarding the other. EPA already captures real
    # game-situation value (down/distance/score) that a tracking-only stat
    # doesn't, and the tracking stat isolates player-tracking skill
    # (separation, yards-over-expected) that EPA doesn't — averaging two
    # already-centered-on-1.0 factors keeps the result centered too.
    if "epa_per_pass_allowed" in factors and "cpoe_allowed" in factors:
        factors["pass_epa_cpoe_allowed"] = ((factors["epa_per_pass_allowed"] + factors["cpoe_allowed"]) / 2).round(3)
    if "epa_per_rush_allowed" in factors and "rush_yards_oe_allowed" in factors:
        factors["rush_efficiency_allowed"] = ((factors["epa_per_rush_allowed"] + factors["rush_yards_oe_allowed"]) / 2).round(3)

    return factors, league_avg


# ----------------------------------------------------------------------
# Map each position's own SCORE metrics to the defensive category that
# actually predicts it. `None` = no real defensive analog -> left neutral
# (usage/volume metrics like target_share are opportunity, not matchup).
#
# Four of these are NGS-informed (see build_ngs_defense_profile): catch_rate
# and yac_per_reception moved from a play-by-play category to a more
# specific tracking-data one (coverage separation allowed; YAC over
# expectation allowed, which isolates tackling-in-space skill from how far
# downfield the catch was); dakota and rushing_epa_per_carry moved to a
# composite that blends their existing EPA-based category with a tracking
# one instead of discarding either.
# ----------------------------------------------------------------------
METRIC_TO_DEFENSE = {
    "QB": {
        "yards_per_attempt": "ypa_allowed",
        "completion_pct": "comp_pct_allowed",
        "td_rate": "pass_td_rate_allowed",
        "int_rate": "int_rate_forced",
        "sack_rate": "sack_rate_generated",
        "rush_yards_per_game": "qb_rush_ypg_allowed",   # QB runs allowed, not RB yards per carry (owner 2026-11-17, backtested)
        "dakota": "pass_epa_cpoe_allowed",
    },
    # RB / WR / TE read what the defense allows to THAT position, plus how much volume it funnels to it
    # (owner 2026-11-17; analysis/pos_matchup_backtest.py "pos_vol" won on 2022-23 and held out on 2024-25).
    "RB": {
        "yards_per_carry": "ypc_allowed_RB",
        "td_rate": "rush_td_allowed_RB",
        "touches_per_game": "touch_pg_allowed_RB",
        "yards_per_target": "ypt_allowed_RB",
        "target_share": "tgt_pg_allowed_RB",
        "rushing_epa_per_carry": "ypc_allowed_RB",
    },
    "WR": {
        "target_share": "tgt_pg_allowed_WR",
        "yards_per_target": "ypt_allowed_WR",
        "td_rate_targets": "td_allowed_WR",
        "catch_rate": "catch_allowed_WR",
        "air_yards_share": "tgt_pg_allowed_WR",
        "wopr": "tgt_pg_allowed_WR",
        "yac_per_reception": "yac_allowed_WR",
    },
    "TE": {
        "target_share": "tgt_pg_allowed_TE",
        "yards_per_target": "ypt_allowed_TE",
        "td_rate_targets": "td_allowed_TE",
        "catch_rate": "catch_allowed_TE",
        "air_yards_share": "tgt_pg_allowed_TE",
        "wopr": "tgt_pg_allowed_TE",
        "yac_per_reception": "yac_allowed_TE",
    },
}


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


# How much of the matchup composite reaches PROJ, per position: factor = 1 + strength * (composite - 1).
# QB 0.35 from analysis/qb_matchup_backtest.py (2021-2025, walk-forward): the full-strength QB factor swung projections
# about +/-14% and made the head-to-head probabilities worse than no matchup at all; ~1/3 strength gave the lowest
# pairwise log loss, picked on 2022-23 and confirmed on held-out 2024-25. Positions not listed keep full strength.
# RB 0.5, WR 0.25, TE 0.25 from analysis/pos_matchup_backtest.py (same method, picked on 2022-23, held out 2024-25):
# RB clearly gains; WR matchups carry almost no signal (0.25 of the position-specific composite is no worse than none
# and better than the old full-strength team-wide one); TE is a tie with the old setting.
MATCHUP_STRENGTH = {"QB": 0.35, "RB": 0.5, "WR": 0.25, "TE": 0.25}


def composite_multiplier(position, opponent, factors, full=False):
    """The matchup multiplier PROJ uses: the raw composite (composite_raw) scaled by MATCHUP_STRENGTH for the
    position. full=True returns the raw composite (used for the soft/tough label, which describes the defense)."""
    raw = composite_raw(position, opponent, factors)
    if full:
        return raw
    k = MATCHUP_STRENGTH.get(position, 1.0)
    return round(float(1 + k * (raw - 1)), 3)


def composite_raw(position, opponent, factors):
    """Single blended matchup multiplier for PROJ: a weight-magnitude
    weighted average of every metric's real defensive factor. Metrics with
    no defensive analog count as neutral (1.0) but still weigh into the
    average, so a position dominated by volume metrics doesn't get
    over-swung by the one or two matchup-sensitive ones.

    A factor's raw reading is always "more of this happened," not "better
    for the offense" — for a metric whose own SCORE weight is negative
    (int_rate, sack_rate: more of these is BAD for the player), a defense
    forcing more than average (factor > 1) is a tougher matchup and must
    pull the blend down, not up. Reflecting the factor around 1.0
    (2 - factor) before blending gets that direction right without
    touching the raw factor `matchup_breakdown` returns for display."""
    rows = matchup_breakdown(position, opponent, factors)
    total_w = sum(abs(r["weight"]) for r in rows)
    if total_w == 0:
        return 1.0
    effective = [r["factor"] if r["weight"] >= 0 else (2 - r["factor"]) for r in rows]
    blended = sum(abs(r["weight"]) * f for r, f in zip(rows, effective)) / total_w
    return round(float(blended), 3)
