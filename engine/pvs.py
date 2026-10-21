"""
PLAYER VALUE SCORE (PVS) — one 0-100 number that is comparable across positions
================================================================================
SCORE (engine/metrics.py) grades a player against his own position, so a 75
receiver can outrank a 72 running back who is the better fantasy asset. PVS
measures what wins leagues instead: the edge a player gives a starting lineup
over the freely available replacement, backed by usage, upside and stability.

    C   = 0.40 S_vorp + 0.25 S_vol + 0.15 S_ceil + 0.10 S_perf + 0.10 S_match
    PVS = 100 x C

Pillars, each 0-1:
  S_vorp  VORP / the average VORP of the league's top ten players, capped at 1.
          VORP = projected PPG minus the PPG of the first free player at the
          position (engine/value.replacement_ranks, so a 2-QB league lowers the
          QB baseline automatically).
  S_vol   Usage that repeats, unlike touchdowns: snap share (>= 70% counts as
          full; the closest public stand-in for route participation), touches or
          targets per game, and red-zone touches per game. Each usage input is
          scaled against the 90th percentile of his own position, so a 22-touch
          back and a 10-target receiver both read as "full workload".
  S_ceil  Week-winning upside: the 90th-percentile outcome minus the position's
          replacement level, over the top-ten average, capped at 1. (The pasted
          spec used (P90 - P50) / P50, which rewards low-median volatile
          players; this rewards upside that actually beats a waiver add.)
  S_perf  Stability and efficiency: consistency (1 - coefficient of variation),
          efficiency percentile within position (EPA per play / touch / target,
          rush yards over expected) and his last-4-game form.
  S_match Where this week's game sits between a bad spot (0.75x: low team total,
          tough defence) and a great one (1.25x): (multiplier - 0.75) / 0.5.
          The multiplier is team implied total / 22 x the opponent's
          positional defence. An average game is 1.0x = 0.5, so a perfect
          player in a neutral matchup scores 95 and only a perfect player in a
          great one reaches 100. The season-long board's PROJ already averages
          every defence, so it uses the neutral 0.5 there; the weekly tools
          pass a real multiplier.

Differences from the pasted spec, on purpose:
  * The spec lists matchup as a 10% weight in its table but as a multiplier in
    its Step 3. Using both counts it twice, so it is the 10% pillar only.
  * No power curve. The spec stretches the elite tier (^1.30; its header says
    1.25); on real data that made one back 100 and the next elite receiver 81.
    Instead the VORP and ceiling pillars saturate at the top-ten average, so
    the elite cluster sits close together, and the scale is absolute (C = 1 is
    100), not "best player in the pool = 100". The best player lands in the
    high 80s, with headroom for a better season, and a score means the same
    thing next week as it does today.
"""

import numpy as np
import pandas as pd

WEIGHTS = {"vorp": 0.40, "vol": 0.25, "ceil": 0.15, "perf": 0.10, "match": 0.10}
TOP_REF = 10       # VORP and ceiling are scored against the average of the league's top ten
MATCHUP_RANGE = (0.75, 1.25)
LEAGUE_AVG_ITT = 22.0
SNAP_FULL = 0.70     # at or above this snap share = full marks, as the spec's route% rule
HVT_FULL_PG = 7.0    # high-value touches per game that count as full marks (spec: "7+")

# Fixed score bands (the spec's, shifted down to fit the absolute scale); a tier
# is a statement about the score, not a rank.
TIER_BANDS = [
    (90, "Legendary"), (80, "Cornerstone"), (68, "Every-week starter"),
    (52, "Matchup / flex play"), (32, "Bench stash"), (0, "Replacement"),
]
# Efficiency columns that exist on the boards, per position (higher = better).
EFFICIENCY = {
    "QB": ["epa_per_play", "cpoe"],
    "RB": ["epa_per_touch", "rush_yards_over_expected_per_att", "yards_per_carry"],
    "WR": ["epa_per_target", "yards_per_target"],
    "TE": ["epa_per_target", "yards_per_target"],
}


def tier_number(pvs):
    """1 (Legendary) ... 6 (Replacement), the position of the PVS band."""
    for i, (floor, _) in enumerate(TIER_BANDS, start=1):
        if pvs is not None and not pd.isna(pvs) and pvs >= floor:
            return i
    return len(TIER_BANDS)


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


def _top_ref(series):
    """Average of the league's top TOP_REF values: the 'elite' reference a
    pillar is scored against (never zero)."""
    top = series.nlargest(min(TOP_REF, len(series)))
    return max(float(top.mean()) if len(top) else 0.0, 1e-9)


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
    s_vorp = (vorp / _top_ref(vorp)).clip(0, 1)

    ceil_edge = (_col(df, "ceiling").fillna(df["PROJ"]) - df["replacement_proj"]).clip(lower=0)
    s_ceil = (ceil_edge / _top_ref(ceil_edge)).clip(0, 1)

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
    s_match = (m - MATCHUP_RANGE[0]) / (MATCHUP_RANGE[1] - MATCHUP_RANGE[0])
    c = (WEIGHTS["vorp"] * s_vorp + WEIGHTS["vol"] * s_vol + WEIGHTS["ceil"] * s_ceil
         + WEIGHTS["perf"] * s_perf + WEIGHTS["match"] * s_match)
    df["PVS"] = (100.0 * c).clip(0, 100).round(1)
    df["PVS_tier"] = [tier_label(v) for v in df["PVS"]]
    df["pvs_vorp"] = s_vorp.round(3)
    df["pvs_vol"] = s_vol.round(3)
    df["pvs_ceil"] = s_ceil.round(3)
    df["pvs_perf"] = s_perf.round(3)
    df["pvs_match"] = m.round(3)
    return df


def reorder(df):
    """Big Board order: by PVS, best first, with ties broken by VOR. Re-numbers
    overall_rank, our_rank, ecr_gap and the tier number (1 = Legendary ... 6 =
    Replacement, the fixed PVS bands) so every column agrees with the order shown. The
    expert rank is kept as a comparison; it no longer moves a player."""
    if df is None or df.empty or "PVS" not in df.columns:
        return df
    out = df.sort_values(["PVS", "VOR"], ascending=[False, False], kind="stable").copy()
    out["overall_rank"] = range(1, len(out) + 1)
    out["our_rank"] = out["overall_rank"].astype(float)
    if "ecr" in out.columns:
        out["ecr_gap"] = (out["our_rank"] - out["ecr"]).round(0)
    out["tier"] = [tier_number(v) for v in out["PVS"]]
    return out
