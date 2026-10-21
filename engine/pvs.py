"""
PLAYER VALUE SCORE (PVS) — one 0-100 number that is comparable across positions
================================================================================
SCORE (engine/metrics.py) grades a player against his own position, so a 75
receiver can outrank a 72 running back who is the better fantasy asset. PVS
measures what wins leagues instead: the edge a player gives a starting lineup
over the freely available replacement, backed by usage, upside and stability.

    C   = (0.40 S_vorp + 0.25 S_vol + 0.15 S_ceil + 0.10 S_perf) x M_match
    PVS = 100 x ((C - C_min) / (C_max - C_min)) ^ 1.30

Pillars, each 0-1:
  S_vorp  VORP / the league's best VORP. VORP = projected PPG minus the PPG of
          the first free player at the position (engine/value.replacement_ranks,
          so a 2-QB league lowers the QB baseline automatically).
  S_vol   Usage that repeats, unlike touchdowns: snap share (>= 70% counts as
          full; the closest public stand-in for route participation), touches or
          targets per game, and red-zone touches per game. Each usage input is
          scaled against the 90th percentile of his own position, so a 22-touch
          back and a 10-target receiver both read as "full workload".
  S_ceil  Week-winning upside: the 90th-percentile outcome minus the position's
          replacement level, over the league's best. (The pasted spec used
          (P90 - P50) / P50, which rewards low-median volatile players; this
          form rewards upside that actually beats a waiver add.)
  S_perf  Stability and efficiency: consistency (1 - coefficient of variation),
          efficiency percentile within position (EPA per play / touch / target,
          rush yards over expected) and his last-4-game form.
  M_match Optional multiplier from 0.75 to 1.25 (team implied total / 22 x the
          opponent's positional defence). The season-long board's PROJ already
          averages every defence, so it stays at 1.0 there; the weekly tools
          pass a real one.

The pasted spec gives 1.25 in its header formula and 1.30 in its worked step;
this uses 1.30 (the step that is actually computed), and applies matchup as a
multiplier (its Step 3) rather than also as a fifth 10% addend, which would
count it twice. C is then scaled across the pool being scored: 0 at the lowest
composite, 95 at the mean of the top five, and the few players above that
spread linearly up to 100 for the single best (so ties at the top never hide
the order). The spec's plain C_max let one outlier (a 15-VORP back in a
6-game sample) squash everyone else, so only three players cleared 70 and the
tiers meant nothing.
"""

import numpy as np
import pandas as pd

WEIGHTS = {"vorp": 0.40, "vol": 0.25, "ceil": 0.15, "perf": 0.10}
GAMMA = 1.30
TOP_ANCHOR = 5       # the scale is anchored at the mean of the top five composites, not the single best
ANCHOR_SCORE = 95.0  # that anchor scores 95; only players above it spread up to 100
MATCHUP_RANGE = (0.75, 1.25)
LEAGUE_AVG_ITT = 22.0
SNAP_FULL = 0.70     # at or above this snap share = full marks, as the spec's route% rule
HVT_FULL_PG = 7.0    # high-value touches per game that count as full marks (spec: "7+")

# Fixed bands from the spec; a tier is a statement about the score, not a rank.
TIER_BANDS = [
    (95, "Legendary"), (85, "Cornerstone"), (70, "Every-week starter"),
    (50, "Matchup / flex play"), (25, "Bench stash"), (0, "Replacement"),
]
# Efficiency columns that exist on the boards, per position (higher = better).
EFFICIENCY = {
    "QB": ["epa_per_play", "cpoe"],
    "RB": ["epa_per_touch", "rush_yards_over_expected_per_att", "yards_per_carry"],
    "WR": ["epa_per_target", "yards_per_target"],
    "TE": ["epa_per_target", "yards_per_target"],
}


def tier_label(pvs):
    if pvs is None or pd.isna(pvs):
        return None
    for floor, name in TIER_BANDS:
        if pvs >= floor:
            return name
    return TIER_BANDS[-1][1]


def matchup_multiplier(implied_total, defense_factor=1.0):
    """The 0.75-1.25 dial: team implied total / 22 x the opponent's positional
    defence factor (1.0 = average; above 1 = a defence that gives up points).
    No implied total -> only the defence factor; neither -> 1.0."""
    itt = 1.0 if implied_total is None or pd.isna(implied_total) else float(implied_total) / LEAGUE_AVG_ITT
    d = 1.0 if defense_factor is None or pd.isna(defense_factor) else float(defense_factor)
    return float(np.clip(itt * d, *MATCHUP_RANGE))


def _col(df, name):
    return pd.to_numeric(df[name], errors="coerce") if name in df.columns else pd.Series(np.nan, index=df.index)


def _scaled_by_p90(series):
    """series / the 90th percentile of itself, capped at 1. NaN stays NaN."""
    s = pd.to_numeric(series, errors="coerce")
    ref = s.dropna().quantile(0.9) if s.notna().any() else np.nan
    if not ref or pd.isna(ref) or ref <= 0:
        return pd.Series(np.nan, index=s.index)
    return (s / ref).clip(0, 1)


def _percentile(series):
    s = pd.to_numeric(series, errors="coerce")
    return s.rank(pct=True) if s.notna().any() else pd.Series(np.nan, index=s.index)


def _volume(g, pos):
    """0-1 usage score for one position's rows."""
    games = _col(g, "games").replace(0, np.nan)
    parts = [(_col(g, "snap_pct") / SNAP_FULL).clip(0, 1)]
    per_game = _col(g, "touches_per_game") if pos == "RB" else None
    if pos in ("WR", "TE"):
        per_game = _col(g, "target_share")
        if per_game.isna().all():
            per_game = _col(g, "targets") / games
    elif pos == "QB":
        per_game = (_col(g, "attempts").fillna(0) + _col(g, "carries").fillna(0)) / games
        per_game = per_game.where(_col(g, "attempts").notna() | _col(g, "carries").notna())
    parts.append(_scaled_by_p90(per_game))
    rz = _col(g, "redzone_touches") / games
    parts.append((rz / HVT_FULL_PG).clip(0, 1) if rz.notna().any() else pd.Series(np.nan, index=g.index))
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True)


def _perf(g, pos):
    """0-1 stability + efficiency score for one position's rows."""
    consistency = 1.0 - _col(g, "cv").clip(0, 1)
    eff_parts = [_percentile(_col(g, c)) for c in EFFICIENCY.get(pos, [])]
    eff = pd.concat(eff_parts, axis=1).mean(axis=1, skipna=True) if eff_parts else pd.Series(np.nan, index=g.index)
    trend = (0.5 + _col(g, "FORM").clip(-25, 25) / 50.0)   # +-25% last-4-vs-season maps to 0..1
    frame = pd.concat([consistency, eff, trend], axis=1)
    w = np.array([0.4, 0.4, 0.2])
    vals = frame.to_numpy(dtype=float)
    ok = ~np.isnan(vals)
    num = np.where(ok, vals, 0.0) @ w
    den = ok @ w
    return pd.Series(np.where(den > 0, num / np.where(den > 0, den, 1), 0.5), index=g.index)


def add_pvs(allp, league=None, matchup=None):
    """Adds PVS (0-100), PVS_tier and the four pillar scores to a frame from
    value.compute_value (needs position, PROJ, VOR, replacement_proj; uses
    ceiling, snap_pct, usage, cv, FORM and efficiency columns where present).
    `matchup` is an optional {player_id: multiplier}; missing = 1.0.
    Returns a copy; the input is not modified."""
    if allp is None or allp.empty:
        return allp
    df = allp.copy()
    vorp = (df["PROJ"] - df["replacement_proj"]).clip(lower=0)
    s_vorp = vorp / max(float(vorp.max()), 1e-9)

    ceil_edge = (_col(df, "ceiling").fillna(df["PROJ"]) - df["replacement_proj"]).clip(lower=0)
    s_ceil = ceil_edge / max(float(ceil_edge.max()), 1e-9)

    s_vol = pd.Series(np.nan, index=df.index)
    s_perf = pd.Series(np.nan, index=df.index)
    for pos, g in df.groupby("position"):
        s_vol.loc[g.index] = _volume(g, pos)
        s_perf.loc[g.index] = _perf(g, pos)
    s_vol = s_vol.fillna(s_vol.median() if s_vol.notna().any() else 0.5)
    s_perf = s_perf.fillna(0.5)

    m = pd.Series(1.0, index=df.index)
    if matchup:
        m = pd.Series({pid: float(np.clip(matchup.get(pid, 1.0), *MATCHUP_RANGE)) for pid in df.index})
    c = (WEIGHTS["vorp"] * s_vorp + WEIGHTS["vol"] * s_vol + WEIGHTS["ceil"] * s_ceil + WEIGHTS["perf"] * s_perf) * m
    lo, top = float(c.min()), float(c.max())
    hi = min(float(c.nlargest(min(TOP_ANCHOR, len(c))).mean()), top)
    if hi - lo <= 1e-9:
        pvs = pd.Series(0.0, index=df.index)
    else:
        below = ((c.clip(upper=hi) - lo) / (hi - lo)) ** GAMMA * ANCHOR_SCORE
        above = (c - hi).clip(lower=0) / max(top - hi, 1e-9) * (100.0 - ANCHOR_SCORE)
        pvs = below + above
    df["PVS"] = pvs.clip(0, 100).round(1)
    df["PVS_tier"] = [tier_label(v) for v in df["PVS"]]
    df["pvs_vorp"] = s_vorp.round(3)
    df["pvs_vol"] = s_vol.round(3)
    df["pvs_ceil"] = s_ceil.round(3)
    df["pvs_perf"] = s_perf.round(3)
    df["pvs_match"] = m.round(3)
    return df
