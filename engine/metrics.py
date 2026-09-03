"""
BASE METRICS + WEIGHTS
=======================
Per-position efficiency/volume metrics computed from weekly stats, and the
weights that turn them into a single 0-100 SCORE.

All positions key on player_id (nflverse gsis_id) so they join cleanly
against play-by-play and Next Gen Stats in engine/advanced.py.

WEIGHTS starts from the hand-picked defaults below, then any position/
metric present in data_cache/learned_weights.json overrides its default —
real weights learned from multi-season history instead of guessed, via
weight_tuner.py (`python weight_tuner.py --write`, then restart the
server; see that file). A metric the tuner didn't touch, or a position it
wasn't run for, just keeps its hand-picked default — this is a partial
override, not a wholesale replacement, so it's always safe to run for
only the positions you trust the sample size for.
"""

import json
import os

import numpy as np
import pandas as pd

MIN_GAMES = {"QB": 2, "RB": 2, "WR": 2, "TE": 2}

# ---- hand-picked defaults (fallback for anything the tuner hasn't learned) ----
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

_DEFAULT_WEIGHTS = {"QB": QB_WEIGHTS, "RB": RB_WEIGHTS, "WR": WR_WEIGHTS, "TE": TE_WEIGHTS}

LEARNED_WEIGHTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_cache", "learned_weights.json")


def _load_learned_weights():
    """Read weight_tuner.py's output, if it's ever been run. Never raises —
    a missing/corrupt file just means "no learned weights yet," same as a
    fresh checkout that's never run the tuner."""
    if not os.path.exists(LEARNED_WEIGHTS_PATH):
        return {}
    try:
        with open(LEARNED_WEIGHTS_PATH) as f:
            return json.load(f).get("weights", {})
    except Exception as e:
        print(f"[metrics] couldn't read {LEARNED_WEIGHTS_PATH} (using hand-picked defaults): {e}")
        return {}


def _merged_weights():
    learned = _load_learned_weights()
    return {pos: {**defaults, **learned.get(pos, {})} for pos, defaults in _DEFAULT_WEIGHTS.items()}


# The effective weights the app actually scores with — hand-picked defaults
# with any learned overrides applied on top, per position/metric. Computed
# once at import time; run weight_tuner.py --write and restart the server
# to pick up a new learned_weights.json (same "restart to pick up a config
# change" pattern as everything else in this app).
WEIGHTS = _merged_weights()


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


def _recency_weighted_pct(values, halflife, min_games_full_confidence):
    """A recency-weighted average vs the plain season average, as a
    fraction of that average, shrunk toward 0 by how few games there are
    to judge from yet. Shared math for the raw-points FORM read and (via
    _recency_weighted_zscore) the EPA-based luck check below."""
    n = len(values)
    if n == 0:
        return 0.0
    season_avg = values.mean()
    if not season_avg or abs(season_avg) < 1e-9:
        return 0.0
    decay = 0.5 ** (1 / halflife)
    weights = decay ** np.arange(n - 1, -1, -1)   # oldest->newest, newest weighted highest
    weighted_avg = np.average(values, weights=weights)
    raw_pct = (weighted_avg - season_avg) / season_avg
    confidence = min(1.0, n / min_games_full_confidence)
    return raw_pct * confidence


def _recency_weighted_zscore(values, halflife, min_games_full_confidence):
    """Same idea as _recency_weighted_pct, for a metric that crosses zero
    and sits near it (EPA), where 'percent of baseline' is unstable the
    same way it is for the EPA columns in engine/defense.py — a z-score
    swing instead of a ratio."""
    n = len(values)
    if n < 2:
        return 0.0
    season_avg = values.mean()
    season_std = values.std()
    if not season_std or season_std < 1e-9:
        return 0.0
    decay = 0.5 ** (1 / halflife)
    weights = decay ** np.arange(n - 1, -1, -1)
    weighted_avg = np.average(values, weights=weights)
    z = (weighted_avg - season_avg) / season_std
    confidence = min(1.0, n / min_games_full_confidence)
    return z * confidence


def form_adjustment(wk, position, weekly_epa=None, halflife=2.5, min_games_full_confidence=8):
    """Recent performance vs season baseline -> a capped +/- % adjustment
    — real refinements over a blunt "last 3 games vs season" cutoff:

    1. CONTINUOUS RECENCY WEIGHTING instead of a hard window: each game's
       weight decays exponentially with how long ago it was (half-life
       ~2.5 games — the most recent game counts roughly 2x the one
       before it, ~4x two games back), so the read moves smoothly as new
       games land instead of a game dropping out of consideration the
       instant it ages past a fixed cutoff.

    2. SAMPLE-SIZE CONFIDENCE: a hot 3-game stretch when that IS a
       player's whole season so far (Weeks 1-3) tells you far less than
       the identical swing 12 games in, once there's a real baseline to
       measure it against. The raw recency-weighted swing is shrunk
       toward 0 in proportion to how few total games are on the board —
       a real Week 2 breakout still moves the read, just not as
       confidently as that same swing would in Week 10 (see
       _recency_weighted_pct's `confidence` term).

    3. A LUCK CHECK against real per-play EPA, when `weekly_epa` is
       supplied (engine/advanced.weekly_epa — pass bundle["pbp"] run
       through it in board.py). A fantasy-point swing gets compared
       against the SAME recency-weighted swing in EPA — "how the play
       actually went," not just how it ended (EPA already accounts for
       down/distance/field position/score context, so a broken-tackle
       house call and a stuffed-at-the-two carry that both "worked" in
       box-score terms don't read as identical here). The final read is
       a straight 50/50 blend of the points-based and EPA-based swings:
       where they agree, blending two equal numbers changes nothing;
       where they diverge — points hot on touchdown variance the
       underlying play quality doesn't back up, or the reverse, quietly
       improving play the scoreboard hasn't caught up to yet — the read
       moves halfway toward the process-based signal. Half, not all the
       way: touchdown variance is real and well-documented (see any
       "TD rate regression" analysis) but not pure noise, since the same
       usage that produces yardage also creates the scoring opportunity."""
    sub = wk[wk["position"] == position]
    adj = {}
    for pid, pdata in sub.groupby("player_id"):
        pdata = pdata.sort_values("week")
        fpts_pct = _recency_weighted_pct(pdata["fpts_active"].to_numpy(), halflife, min_games_full_confidence)
        pct = fpts_pct

        if weekly_epa is not None:
            try:
                epa_for_player = weekly_epa.xs(pid, level="player_id")
            except KeyError:
                epa_for_player = None
            if epa_for_player is not None:
                epa_series = epa_for_player.reindex(pdata["week"]).to_numpy(dtype=float)
                valid_epa = epa_series[~np.isnan(epa_series)]
                if len(valid_epa) >= 2:
                    epa_z = _recency_weighted_zscore(valid_epa, halflife, min_games_full_confidence)
                    epa_pct_equiv = float(np.clip(epa_z / 2.0, -1.0, 1.0)) * 0.4
                    pct = 0.5 * fpts_pct + 0.5 * epa_pct_equiv

        adj[pid] = round(float(np.clip(pct, -0.4, 0.4)) * 100, 1)
    return pd.Series(adj, name="FORM")
