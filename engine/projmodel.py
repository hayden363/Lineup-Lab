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

Recency is capped. The regression gives the last four games a big say (the last-4
average and last-4 opportunity terms together are more than half of the projection for
a player on a hot or cold streak), so a streak could move a projection by 3 points a
game. The shipped rate is therefore the BASELINE rate (the same regression with the
last four games replaced by his season-long average and season-long opportunity) plus
his recent-form lift, and that lift is held to +/-RECENCY_CAP_POINTS and to at most
RECENCY_MAX_SHARE of the baseline, so at least 80% of every projection is season-long
volume and production. The walk-forward numbers for capped and uncapped are both in
backtest().

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
RECENCY_CAP_POINTS = 1.5   # most a hot or cold streak may move a projection, in points per game
RECENCY_MAX_SHARE = 0.20   # ... and never more than this share of the baseline (so >= 80% is baseline)
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
    d["opp_ppg"] = g["opp"].transform(lambda s: s.shift(1).expanding().mean())   # season-long, for the baseline
    per = d.groupby(["player_id", "season"])["fpts_active"].agg(["mean", "count"])
    per = per[per["count"] >= MIN_PRIOR_GAMES]["mean"]
    prior = pd.Series([per.get((p, s - 1), np.nan) for p, s in zip(d["player_id"], d["season"])], index=d.index)
    d["has_prior"] = prior.notna()
    d["prior"] = prior.fillna(d["ppg"])
    first = d["season"].min()
    return d[(d["n"] >= MIN_GAMES) & (d["season"] > first)]


FEATURES = ("ppg", "l4", "opp4", "prior")


def baseline_rate(c, ppg, opp_ppg, prior):
    """The regression with the last four games replaced by his season-long average and
    season-long opportunity: what he projects at if he has been exactly himself all year."""
    return c[0] + c[1] * ppg + c[2] * ppg + c[3] * opp_ppg + c[4] * prior


def cap_recency(rate, baseline, cap_points=RECENCY_CAP_POINTS, max_share=RECENCY_MAX_SHARE):
    """`baseline` plus the recent-form lift (rate - baseline), the lift held to +/-cap_points
    and to at most max_share of the baseline. Works on floats or aligned Series/arrays."""
    cap = np.minimum(cap_points, max_share * np.maximum(baseline, 0.0))
    return baseline + np.clip(rate - baseline, -cap, cap)


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
    `history_weight` (the share of the rate that comes from last season), `baseline` (the rate
    with his last four games replaced by his season-long numbers), `recency_lift` (what the
    last four games add to it after the cap) and `recency_lift_raw` (before the cap), for
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
    season_opp = g.groupby("player_id")["opp"].mean()
    f = pd.DataFrame({"n": whole["count"], "ppg": whole["mean"], "l4": recent["fpts_active"], "opp4": recent["opp"],
                      "opp_ppg": season_opp})
    f = f[f["n"] >= MIN_GAMES]
    if f.empty:
        return None
    prior = m["prior"].reindex(f.index)
    has = prior.notna()
    f["prior"] = prior.fillna(f["ppg"])
    c = m["coef"][position]
    raw = c[0] + sum(c[i + 1] * f[name] for i, name in enumerate(FEATURES))
    base = baseline_rate(c, f["ppg"], f["opp_ppg"], f["prior"])
    rate = cap_recency(raw, base)
    weights = c[1:]
    share = (c[4] / weights.sum()) if weights.sum() > 0 else 0.0
    return pd.DataFrame({"rate": rate.clip(lower=0.0), "history_weight": np.where(has, max(0.0, float(share)), 0.0),
                         "baseline": base.clip(lower=0.0), "recency_lift": rate - base, "recency_lift_raw": raw - base},
                        index=f.index)


def capped_form_multiplier(rate, form_pct, cap_points=RECENCY_CAP_POINTS, max_share=RECENCY_MAX_SHARE):
    """The multiplier for a rate that is NOT the fitted model's (a player with too little history),
    1 + form_pct/100, with the points that form adds held to the same cap as the model's recency
    lift: at most cap_points and at most max_share of the rate. Takes floats or Series; 1.0 where
    the rate or the form is missing."""
    r = np.asarray(rate, dtype=float)
    pct = np.nan_to_num(np.asarray(form_pct, dtype=float))
    adj = np.clip(r * pct / 100.0, -np.minimum(cap_points, max_share * np.maximum(r, 0.0)),
                  np.minimum(cap_points, max_share * np.maximum(r, 0.0)))
    with np.errstate(divide="ignore", invalid="ignore"):
        mult = np.where(r > 0, 1.0 + adj / r, 1.0)
    return pd.Series(mult, index=rate.index) if isinstance(rate, pd.Series) else float(mult)


# ---- walk-forward backtest, the evidence behind the model -------------------
def backtest(scoring=None, min_week_games=3):
    """Leave-one-season-out check on the prior seasons in history: each test
    season's games are predicted from the other seasons' fit plus only the
    data before each game. Returns None without at least three seasons, else
    {"rmse", "bias", "r2", "top": {"n", "predicted", "actual"}, "uncapped": {...}, "old": {...}}
    for the shipped (recency-capped) model, the same regression without the cap, and the
    shrink-to-position-average formula this replaced; `top` is
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
            base = c[0] + c[1] * rows.loc[idx, "ppg"] + c[2] * rows.loc[idx, "ppg"] \
                + c[3] * rows.loc[idx, "opp_ppg"] + c[4] * rows.loc[idx, "prior"]
            rows.loc[idx, "base"] = base
    rows["capped"] = cap_recency(rows["pred"], rows["base"])
    # the old formula: shrink toward the average of players with 3+ games that season so far
    pool = {}
    for (s, pos), g in df.groupby(["season", "position"]):
        for w in sorted(g["week"].unique()):
            gg = g[g["week"] < w].groupby("player_id")["fpts_active"].agg(["mean", "count"])
            gg = gg[gg["count"] >= 3]
            pool[(s, pos, w)] = gg["mean"].mean() if len(gg) else np.nan
    rows["pool"] = [pool.get((s, p, w), np.nan) for s, p, w in zip(rows["season"], rows["position"], rows["week"])]
    rows["old"] = (rows["n"] * rows["ppg"] + 3 * rows["pool"]) / (rows["n"] + 3)
    rows = rows.dropna(subset=["pred", "old", "capped"])
    rows = rows[rows["week"] >= 5]
    var = rows["fpts_active"].var()

    def summary(col):
        e = rows[col] - rows["fpts_active"]
        top = rows[(rows[col] >= 16) & (rows["position"] != "QB")]
        return {"rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean()),
                "r2": float(1 - (e ** 2).mean() / var),
                "top": {"n": int(len(top)), "predicted": float(top[col].mean()) if len(top) else None,
                        "actual": float(top["fpts_active"].mean()) if len(top) else None}}
    return {**summary("capped"), "uncapped": summary("pred"), "old": summary("old"), "n": int(len(rows)),
            "mean_abs_recency_lift_raw": float((rows["pred"] - rows["base"]).abs().mean()),
            "share_of_games_capped": float((((rows["pred"] - rows["capped"]).abs()) > 1e-9).mean())}
