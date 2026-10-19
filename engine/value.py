"""
CROSS-POSITION VALUE — who is actually worth more, QB vs RB vs WR vs TE
===========================================================================
SCORE (engine/metrics.py) is a 0-100 grade *within* a position. It answers
"how good is this QB compared to other QBs", so sorting all positions by it
puts quarterbacks on top just because the best quarterbacks are very good at
quarterbacking. Fantasy value is different: what matters is how many points a
player gives you over the freely available replacement at his position.

    VOR (value over replacement) = projected points/game - replacement points/game

Replacement level for a position is the projection of the player ranked
`teams x (starter slots + that position's share of the flex slots)`. That is
the last player a typical league would still be starting. So in a 12-team,
1-QB league the 13th QB is "free", while a tight end at 10 points/game is
barely above free and a tight end at 22 is a huge edge. In a superflex league
the QB replacement drops to about QB24 and quarterbacks rise accordingly.

The final order blends our VOR rank with the expert consensus rank (ECR, see
engine/consensus.py) at 30% weight: other sites don't decide anything, but a
big disagreement is worth showing and a mild nudge keeps early-season noise
from dominating. Both ranks are returned so the UI can show the gap.

Tiers are cut where the VOR drops by a lot between neighbours, which is how
draft-day tier sheets are made.
"""

import numpy as np
import pandas as pd

POSITIONS = ("QB", "RB", "WR", "TE")

DEFAULT_LEAGUE = {
    "teams": 12,
    "slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 0},
}

# Where the flex slots are typically spent (FLEX = RB/WR/TE; SUPERFLEX adds QB).
FLEX_SHARE = {"QB": 0.0, "RB": 0.4, "WR": 0.5, "TE": 0.1}
SUPERFLEX_SHARE = {"QB": 0.7, "RB": 0.1, "WR": 0.15, "TE": 0.05}

ECR_WEIGHT = 0.30
ECR_MISSING_RANK = 450  # not in the experts' top ~400 -> treat as deep


def replacement_ranks(league=None):
    """{position: the rank of the first 'free' player} for this league shape."""
    league = league or DEFAULT_LEAGUE
    teams = int(league.get("teams", 12))
    slots = {**DEFAULT_LEAGUE["slots"], **(league.get("slots") or {})}
    out = {}
    for pos in POSITIONS:
        demand = slots.get(pos, 0) + slots.get("FLEX", 0) * FLEX_SHARE[pos] \
            + slots.get("SUPERFLEX", 0) * SUPERFLEX_SHARE[pos]
        out[pos] = max(1, int(round(teams * demand)))
    return out


def _replacement_level(proj, rank):
    """PROJ of the player at `rank` (1-based) in a descending list; the last
    player if the list is shorter than that."""
    s = proj.dropna().sort_values(ascending=False)
    if s.empty:
        return 0.0
    return float(s.iloc[min(rank, len(s)) - 1])


def assign_tiers(vor_sorted, min_gap_frac=0.06, min_gap=1.0):
    """Tier numbers (1 = best) for a VOR series already sorted descending.
    A new tier starts where the drop to the next player exceeds both an
    absolute floor and a fraction of the top VOR."""
    v = np.asarray(vor_sorted, dtype=float)
    if len(v) == 0:
        return np.array([], dtype=int)
    threshold = max(min_gap, min_gap_frac * max(v[0], 0.0))
    drops = v[:-1] - v[1:]
    return 1 + np.concatenate([[0], np.cumsum(drops > threshold)]).astype(int)


def compute_value(frames, ecr=None, league=None, ecr_weight=ECR_WEIGHT):
    """frames: {pos: DataFrame indexed by player_id with PROJ, player_display_name,
    recent_team}. ecr: {match_key: {...}} from consensus.overall_lookup (or None).
    Returns one cross-position DataFrame, best first."""
    from engine.consensus import match_key  # local import keeps this module pure-pandas at top level

    repl_rank = replacement_ranks(league)
    parts = []
    for pos in POSITIONS:
        df = frames.get(pos)
        if df is None or df.empty:
            continue
        df = df.copy()
        df["position"] = pos
        level = _replacement_level(df["PROJ"], repl_rank[pos])
        df["replacement_proj"] = level
        df["VOR"] = (df["PROJ"] - level).round(2)
        df["pos_rank"] = df["PROJ"].rank(ascending=False, method="first").astype(int)
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    allp = pd.concat(parts)
    allp.index.name = "player_id"

    allp["our_rank"] = allp["VOR"].rank(ascending=False, method="first")
    ecr = ecr or {}
    keys = [match_key(n, p) for n, p in zip(allp["player_display_name"], allp["position"])]
    info = [ecr.get(k) for k in keys]
    allp["ecr"] = [i["ecr"] if i else np.nan for i in info]
    allp["ecr_sd"] = [i["ecr_sd"] if i else np.nan for i in info]
    # The board's own bye week comes from the real NFL schedule; ECR's is only
    # a fallback. Overwriting it used to blank every bye whenever the ECR
    # file was unreachable, and for anyone ECR didn't list.
    ecr_bye = np.array([i["bye_week"] if i and i["bye_week"] is not None else np.nan for i in info], dtype=float)
    if "bye_week" in allp.columns:
        sched_bye = pd.to_numeric(allp["bye_week"], errors="coerce").to_numpy(dtype=float)
        allp["bye_week"] = np.where(np.isnan(sched_bye), ecr_bye, sched_bye)
    else:
        allp["bye_week"] = ecr_bye
    filled = allp["ecr"].fillna(ECR_MISSING_RANK)
    allp["blend"] = (1 - ecr_weight) * allp["our_rank"] + ecr_weight * filled \
        if ecr else allp["our_rank"]
    allp = allp.sort_values(["blend", "VOR"], ascending=[True, False])
    allp["overall_rank"] = range(1, len(allp) + 1)
    # Tiers follow the final order, using VOR so a tier means "similar real edge".
    allp["tier"] = assign_tiers(allp["VOR"].clip(lower=0).to_numpy())
    top = max(float(allp["VOR"].max()), 1e-9)
    allp["VALUE"] = (allp["VOR"].clip(lower=0) / top * 100).round(1)
    # Positive = the experts like him more than we do (lower ECR number than our rank).
    allp["ecr_gap"] = (allp["our_rank"] - allp["ecr"]).round(0)
    return allp
