"""
BASE METRICS + WEIGHTS
=======================
Per-position efficiency/volume metrics computed from weekly stats, and the
weights that turn them into a single 0-100 SCORE. This is your "secret
sauce" — tune WEIGHTS to change what the model values.

All positions key on player_id (nflverse gsis_id) so they join cleanly
against play-by-play and Next Gen Stats in engine/advanced.py.
"""

import numpy as np
import pandas as pd

MIN_GAMES = {"QB": 2, "RB": 2, "WR": 2, "TE": 2}

QB_WEIGHTS = {
    "yards_per_attempt": 20,
    "td_rate": 18,
    "completion_pct": 12,
    "int_rate": -14,
    "sack_rate": -8,
    "rush_yards_per_game": 12,
    "dakota": 16,          # nflverse's own EPA+CPOE composite — a strong single-number QB grade
}

RB_WEIGHTS = {
    "yards_per_carry": 18,
    "td_rate": 16,
    "touches_per_game": 24,     # volume = opportunity, still king in fantasy
    "yards_per_target": 10,
    "target_share": 14,          # receiving work is where RB fantasy value hides
    "rushing_epa_per_carry": 18,
}

WR_WEIGHTS = {
    "target_share": 24,
    "yards_per_target": 14,
    "td_rate_targets": 14,
    "catch_rate": 10,
    "air_yards_share": 12,
    "wopr": 16,                  # weighted opportunity rating — volume + air yards combined
    "yac_per_reception": 10,
}

TE_WEIGHTS = {
    "target_share": 20,
    "catch_rate": 18,
    "td_rate_targets": 18,
    "yards_per_target": 14,
    "wopr": 16,
    "yac_per_reception": 8,     # TE value skews more toward "gets the target" than YAC ability
    "air_yards_share": 6,
}

WEIGHTS = {"QB": QB_WEIGHTS, "RB": RB_WEIGHTS, "WR": WR_WEIGHTS, "TE": TE_WEIGHTS}


def _identity(g, wk):
    """Grab the last known display name/team/headshot per player_id group."""
    last = wk.sort_values("week").groupby("player_id").last()
    return last[["player_display_name", "recent_team", "headshot_url", "position"]]


def qb_metrics(wk):
    sub = wk[wk["position"] == "QB"].copy()
    g = sub.groupby("player_id")
    atts = g["attempts"].sum().replace(0, np.nan)
    out = pd.DataFrame({
        "games": g.size(),
        "volume": g["attempts"].sum(),
        "yards_per_attempt": g["passing_yards"].sum() / atts,
        "completion_pct": g["completions"].sum() / atts * 100,
        "td_rate": g["passing_tds"].sum() / atts * 100,
        "int_rate": g["interceptions"].sum() / atts * 100,
        "sack_rate": g["sacks"].sum() / (atts + g["sacks"].sum()) * 100,
        "rush_yards_per_game": g["rushing_yards"].sum() / g.size(),
        "dakota": g["dakota"].mean() * 100 if "dakota" in sub else np.nan,
        "fpts_per_game": g["fpts_active"].sum() / g.size(),
    })
    return out.join(_identity(g, sub))


def rb_metrics(wk):
    sub = wk[wk["position"] == "RB"].copy()
    g = sub.groupby("player_id")
    carries = g["carries"].sum().replace(0, np.nan)
    targets = g["targets"].sum().replace(0, np.nan)
    out = pd.DataFrame({
        "games": g.size(),
        "volume": g["carries"].sum() + g["receptions"].sum(),
        "yards_per_carry": g["rushing_yards"].sum() / carries,
        "td_rate": (g["rushing_tds"].sum() + g["receiving_tds"].sum()) / (carries.fillna(0) + targets.fillna(0)).replace(0, np.nan) * 100,
        "touches_per_game": (g["carries"].sum() + g["receptions"].sum()) / g.size(),
        "yards_per_target": g["receiving_yards"].sum() / targets,
        "target_share": g["target_share"].mean() * 100 if "target_share" in sub else np.nan,
        "rushing_epa_per_carry": g["rushing_epa"].sum() / carries if "rushing_epa" in sub else np.nan,
        "fpts_per_game": g["fpts_active"].sum() / g.size(),
    })
    return out.join(_identity(g, sub))


def _receiver_metrics(wk, position):
    sub = wk[wk["position"] == position].copy()
    g = sub.groupby("player_id")
    targets = g["targets"].sum().replace(0, np.nan)
    out = pd.DataFrame({
        "games": g.size(),
        "volume": g["targets"].sum(),
        "catch_rate": g["receptions"].sum() / targets * 100,
        "yards_per_target": g["receiving_yards"].sum() / targets,
        "td_rate_targets": g["receiving_tds"].sum() / targets * 100,
        "target_share": g["target_share"].mean() * 100 if "target_share" in sub else np.nan,
        "air_yards_share": g["air_yards_share"].mean() * 100 if "air_yards_share" in sub else np.nan,
        "wopr": g["wopr"].mean() * 100 if "wopr" in sub else np.nan,
        "yac_per_reception": g["receiving_yards_after_catch"].sum() / g["receptions"].sum().replace(0, np.nan),
        "fpts_per_game": g["fpts_active"].sum() / g.size(),
    })
    return out.join(_identity(g, sub))


def wr_metrics(wk):
    return _receiver_metrics(wk, "WR")


def te_metrics(wk):
    return _receiver_metrics(wk, "TE")


METRIC_FNS = {"QB": qb_metrics, "RB": rb_metrics, "WR": wr_metrics, "TE": te_metrics}


# ----------------------------------------------------------------------
# SCORING — normalize each metric 0-1 within the position, weight, combine
# ----------------------------------------------------------------------
def score_players(metrics, weights):
    scores = pd.Series(0.0, index=metrics.index)
    total_w = sum(abs(w) for w in weights.values())
    used_w = pd.Series(0.0, index=metrics.index)
    for metric, w in weights.items():
        if metric not in metrics.columns:
            continue
        col = metrics[metric].astype(float)
        valid = col.notna()
        rng = col[valid].max() - col[valid].min() if valid.any() else 0
        norm = pd.Series(0.5, index=metrics.index)
        if rng and rng > 0:
            norm[valid] = (col[valid] - col[valid].min()) / rng
        if w < 0:
            norm = 1 - norm
        scores += norm.fillna(0.5) * abs(w)
        used_w += valid.astype(float) * abs(w)
    denom = used_w.replace(0, total_w)
    return (scores / denom.clip(lower=1e-9) * 100).round(1)


def form_adjustment(wk, position, recent=3):
    """Recent games vs season baseline -> capped +/- % adjustment."""
    sub = wk[wk["position"] == position]
    adj = {}
    for pid, pdata in sub.groupby("player_id"):
        pdata = pdata.sort_values("week")
        season_avg = pdata["fpts_active"].mean()
        recent_avg = pdata["fpts_active"].tail(recent).mean()
        if season_avg and season_avg > 0:
            pct = (recent_avg - season_avg) / season_avg
            adj[pid] = round(float(np.clip(pct, -0.4, 0.4)) * 100, 1)
        else:
            adj[pid] = 0.0
    return pd.Series(adj, name="FORM")
