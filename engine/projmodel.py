"""
PER-GAME PROJECTION MODEL — fitted on past seasons, checked walk-forward
=========================================================================
The season-long rate behind every projection used to be a shrinkage formula:
(games x his rate + 3 x the position average) / (games + 3), nudged by a recent
form percentage. That pulls a good player toward the average of every player at
his position, and a walk-forward backtest on 2024 and 2025 (each game predicted
from data available before it) showed what that does: players it rated 14-18
averaged 17.0 and players it rated 18-22 averaged 20.8, an under-projection of
the whole top tier, and an overall bias of -0.4 points a game.

This replaces it with a regression, one per position, fitted on every earlier
season in engine/history.py under the viewer's own scoring:

    rate = c + w1 x season average        (games before this one)
             + w2 x last-4-game average
             + w3 x opportunity points     (last 4 games of targets and carries,
                                            each valued at what the league scored
                                            per target / per carry that position)
             + w4 x last season's average  (his own, 6+ games; his season average
                                            when he has none)

Opportunity is a feature, not the whole model: carries and targets alone were the
worst single predictor in the backtest (RMSE 6.84 against 6.46 for the season
average, bias -0.9) because efficiency and touchdowns are partly real skill. The
regression lets the data decide how much each signal is worth. It already
contains recent form, so FORM is not applied on top of it (board.form_pct).

What the backtest says it buys, honestly: a small accuracy gain (R2 0.406 against
0.383 for the old formula, RMSE 6.31 against 6.43) and a calibrated top tier
(players predicted 16+ averaged 18.2 and projected 18.2; the old formula
projected 17.9 for players who averaged 18.7). Single games stay noisy: every
method tried has an RMSE near 6.3 points, so the useful output is a calibrated
average with a range, not a precise number.

Needs at least two prior seasons on file (one to build last season's average,
one to train on) and 3 games this season; otherwise `predict` returns nothing and
the caller keeps the old formula.
"""

import threading

import numpy as np
import pandas as pd

from . import history
from .scoring import apply_scoring

POSITIONS = ("QB", "RB", "WR", "TE")
MIN_GAMES = 3            # this season's games before a player is modelled
MIN_PRIOR_GAMES = 6      # games that make last season's average a real prior
RECENT = 4
_LOCK = threading.Lock()
_MODELS = {}
_MODEL_LIMIT = 16
_COLS = ["player_id", "position", "season", "week", "targets", "carries", "fpts_active"]


def _key(scoring, current):
    return ("projmodel", history._key(scoring), int(current))


def _scored_history(scoring, current):
    """Every prior season's QB/RB/WR/TE games under `scoring`, sorted for
    cumulative features. Not weighted or trimmed like history._scored_skill."""
    df = history._frames()["skill"]
    if df.empty:
        return df
    df = df[df["season"] < int(current)]
    df, _ = apply_scoring(df, scoring)
    df = df[[c for c in _COLS if c in df.columns]].copy()
    df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
    return df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)


def _opportunity_values(df):
    """{position: (points per target, points per carry)}: a no-intercept
    regression of scored points on targets and carries."""
    out = {}
    for pos in POSITIONS:
        g = df[df["position"] == pos]
        if len(g) < 200:
            continue
        coef, *_ = np.linalg.lstsq(g[["targets", "carries"]].to_numpy(float), g["fpts_active"].to_numpy(float), rcond=None)
        out[pos] = (max(0.0, float(coef[0])), max(0.0, float(coef[1])))
    return out


def _training_rows(df, ppo):
    """One row per player-game with the features known BEFORE that game."""
    d = df.copy()
    d["opp"] = [ppo[p][0] * t + ppo[p][1] * c if p in ppo else 0.0
                for p, t, c in zip(d["position"], d["targets"], d["carries"])]
    g = d.groupby(["player_id", "season"], sort=False)
    d["n"] = g.cumcount()
    d["ppg"] = g["fpts_active"].transform(lambda s: s.shift(1).expanding().mean())
    d["l4"] = g["fpts_active"].transform(lambda s: s.shift(1).rolling(RECENT, min_periods=1).mean())
    d["opp4"] = g["opp"].transform(lambda s: s.shift(1).rolling(RECENT, min_periods=1).mean())
    per = d.groupby(["player_id", "season"])["fpts_active"].agg(["mean", "count"])
    per = per[per["count"] >= MIN_PRIOR_GAMES]["mean"]
    prior = pd.Series([per.get((p, s - 1), np.nan) for p, s in zip(d["player_id"], d["season"])], index=d.index)
    d["has_prior"] = prior.notna()
    d["prior"] = prior.fillna(d["ppg"])
    first = d["season"].min()
    return d[(d["n"] >= MIN_GAMES) & (d["season"] > first)]


FEATURES = ("ppg", "l4", "opp4", "prior")


def fit(rows):
    """{position: coefficient array [c, w_ppg, w_l4, w_opp4, w_prior]}."""
    out = {}
    for pos in POSITIONS:
        g = rows[rows["position"] == pos]
        if len(g) < 300:
            continue
        x = np.column_stack([np.ones(len(g))] + [g[f].to_numpy(float) for f in FEATURES])
        out[pos], *_ = np.linalg.lstsq(x, g["fpts_active"].to_numpy(float), rcond=None)
    return out


def model(scoring, current):
    """{"coef", "ppo", "prior_by_player"} for this scoring and season, or None
    when history can't support it. Cached (one per scoring, bounded)."""
    key = _key(scoring, current)
    with _LOCK:
        if key in _MODELS:
            return _MODELS[key]
    built = None
    if history.available():
        df = _scored_history(scoring, current)
        if not df.empty and df["season"].nunique() >= 2:
            ppo = _opportunity_values(df)
            coef = fit(_training_rows(df, ppo))
            if coef:
                last = int(current) - 1
                prev = df[df["season"] == last].groupby("player_id")["fpts_active"].agg(["mean", "count"])
                built = {"coef": coef, "ppo": ppo, "prior": prev[prev["count"] >= MIN_PRIOR_GAMES]["mean"]}
    with _LOCK:
        if len(_MODELS) >= _MODEL_LIMIT:
            _MODELS.clear()
        _MODELS[key] = built
    return built


def predict(position, wk_scored, scoring, season):
    """DataFrame indexed by player_id with `rate` (points per game) and
    `history_weight` (the share of the rate that comes from last season), for
    every player at `position` with MIN_GAMES+ games in `wk_scored` (this
    season's weekly stats already under `scoring`). None when there's no model."""
    m = model(scoring, season)
    if m is None or position not in m["coef"] or position not in m["ppo"]:
        return None
    g = wk_scored[wk_scored["position"] == position].sort_values(["player_id", "week"]).copy()
    if g.empty:
        return None
    for col in ("targets", "carries"):
        g[col] = g[col].fillna(0.0)
    bt, bc = m["ppo"][position]
    g["opp"] = bt * g["targets"] + bc * g["carries"]
    recent = g.groupby("player_id").tail(RECENT).groupby("player_id")[["fpts_active", "opp"]].mean()
    whole = g.groupby("player_id")["fpts_active"].agg(["mean", "count"])
    f = pd.DataFrame({"n": whole["count"], "ppg": whole["mean"], "l4": recent["fpts_active"], "opp4": recent["opp"]})
    f = f[f["n"] >= MIN_GAMES]
    if f.empty:
        return None
    prior = m["prior"].reindex(f.index)
    has = prior.notna()
    f["prior"] = prior.fillna(f["ppg"])
    c = m["coef"][position]
    rate = c[0] + sum(c[i + 1] * f[name] for i, name in enumerate(FEATURES))
    weights = c[1:]
    share = (c[4] / weights.sum()) if weights.sum() > 0 else 0.0
    return pd.DataFrame({"rate": rate.clip(lower=0.0), "history_weight": np.where(has, max(0.0, float(share)), 0.0)},
                        index=f.index)


# ---- walk-forward backtest, the evidence behind the model -------------------
def backtest(scoring=None, min_week_games=3):
    """Leave-one-season-out check on the prior seasons in history: each test
    season's games are predicted from the other seasons' fit plus only the
    data before each game. Returns None without at least three seasons, else
    {"rmse", "bias", "r2", "top": {"n", "predicted", "actual"}, "old": {...}}
    where `old` is the shrink-to-position-average formula this replaced and
    `top` is the non-QB games predicted at 16+ points."""
    if not history.available():
        return None
    cur = int(history._frames()["skill"]["season"].max()) + 1
    df = _scored_history(scoring, cur)
    if df.empty or df["season"].nunique() < 3:
        return None
    ppo = _opportunity_values(df)
    rows = _training_rows(df, ppo)
    rows = rows[rows["position"].isin(POSITIONS)].copy()
    rows["pred"] = np.nan
    for test in sorted(rows["season"].unique()):
        coef = fit(rows[rows["season"] != test])
        for pos, c in coef.items():
            idx = (rows["season"] == test) & (rows["position"] == pos)
            x = np.column_stack([np.ones(idx.sum())] + [rows.loc[idx, f].to_numpy(float) for f in FEATURES])
            rows.loc[idx, "pred"] = x @ c
    # the old formula: shrink toward the average of players with 3+ games that season so far
    pool = {}
    for (s, pos), g in df.groupby(["season", "position"]):
        for w in sorted(g["week"].unique()):
            gg = g[g["week"] < w].groupby("player_id")["fpts_active"].agg(["mean", "count"])
            gg = gg[gg["count"] >= 3]
            pool[(s, pos, w)] = gg["mean"].mean() if len(gg) else np.nan
    rows["pool"] = [pool.get((s, p, w), np.nan) for s, p, w in zip(rows["season"], rows["position"], rows["week"])]
    rows["old"] = (rows["n"] * rows["ppg"] + 3 * rows["pool"]) / (rows["n"] + 3)
    rows = rows.dropna(subset=["pred", "old"])
    rows = rows[rows["week"] >= 5]
    var = rows["fpts_active"].var()

    def summary(col):
        e = rows[col] - rows["fpts_active"]
        top = rows[(rows[col] >= 16) & (rows["position"] != "QB")]
        return {"rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean()),
                "r2": float(1 - (e ** 2).mean() / var),
                "top": {"n": int(len(top)), "predicted": float(top[col].mean()) if len(top) else None,
                        "actual": float(top["fpts_active"].mean()) if len(top) else None}}
    return {**summary("pred"), "old": summary("old"), "n": int(len(rows))}
