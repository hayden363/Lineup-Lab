"""
WEIGHT TUNER
============
Learn engine/metrics.py's SCORE weights from real multi-season history
instead of hand-picking them: for each position, regress season N's
metrics against the SAME players' season-(N+1) real fantasy points per
game — "did this metric actually predict next year's production," not
just describe this year's box score after the fact. Regressing a rate
metric against the very same season's point total it's partly derived
from (yards_per_attempt against a total built from those same passing
yards) would be closer to circular reasoning than genuine prediction;
the year-over-year setup is what makes this an honest test.

Reaches back several real historical seasons on its own, independent of
the live app's single "current season" — engine/data.resolve_season()
(what the web app actually values players on right now) is untouched by
this script.

Method: ridge-regularized linear regression on standardized features (see
learn_weights) — ordinary least squares would blow up on the correlated
metrics these are (e.g. touches_per_game and target_share both move with
raw volume); the ridge term keeps coefficients finite and comparable
without needing sklearn or any dependency this project doesn't already
have.

Run:
    python weight_tuner.py                  # dry run: prints learned vs
                                              # current weights, writes nothing
    python weight_tuner.py --write           # also saves data_cache/learned_weights.json,
                                              # which engine/metrics.py picks up
                                              # automatically on next import —
                                              # restart the server to apply it
    python weight_tuner.py --only WR,TE      # limit to specific positions
    python weight_tuner.py --season-pairs 5  # how many (year, year+1) pairs to use
"""

import argparse
import json
import os
import time

import numpy as np
import pandas as pd

from engine import data
from engine.board import MIN_VOLUME
from engine.metrics import METRIC_FNS, MIN_GAMES, _DEFAULT_WEIGHTS
from engine.scoring import apply_scoring

LEARNED_WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache", "learned_weights.json")
POSITIONS = ("QB", "RB", "WR", "TE")


def learn_weights(train_df, target_col, feature_cols):
    """
    train_df: rows = player-seasons, cols = feature metrics + target.
    Returns a learned coefficient per feature (standardized, so comparable
    to each other regardless of the feature's raw units/scale).
    """
    df = train_df.dropna(subset=feature_cols + [target_col]).copy()
    if len(df) < len(feature_cols) * 3:
        print(f"  [tuner] only {len(df)} qualifying rows for {len(feature_cols)} features "
              "— too thin to regress reliably, falling back to plain correlations")
        return _correlation_fallback(df, target_col, feature_cols)

    X = df[feature_cols].values.astype(float)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1.0
    Xn = (X - X.mean(axis=0)) / X_std
    y = df[target_col].values.astype(float)
    Xb = np.column_stack([np.ones(len(Xn)), Xn])  # intercept

    # normal equation, ridge-regularized for stability against collinear features
    lam = 1.0
    I = np.eye(Xb.shape[1])
    I[0, 0] = 0  # don't penalize the intercept
    beta = np.linalg.solve(Xb.T @ Xb + lam * I, Xb.T @ y)

    return pd.Series(beta[1:], index=feature_cols).round(4)


def _correlation_fallback(df, target_col, feature_cols):
    if df.empty:
        return pd.Series(0.0, index=feature_cols)
    cors = {f: (df[f].corr(df[target_col]) or 0.0) for f in feature_cols}
    return pd.Series(cors).round(4)


def to_weight_dict(learned, reference_weights):
    """Scale learned coefficients so their total magnitude matches the
    hand-picked defaults' total (sum of |weight|) for this position — this
    keeps SCORE's overall spread familiar (still a 0-100ish composite),
    changing only each metric's relative share of it. Sign is whatever the
    regression found (a metric that predicts FEWER points next year keeps
    a negative weight, same convention engine/metrics.py already uses)."""
    target_total = sum(abs(w) for w in reference_weights.values())
    learned_total = learned.abs().sum()
    if learned_total <= 0:
        return dict(reference_weights)
    scale = target_total / learned_total
    return (learned * scale).round(1).to_dict()


def _season_metrics(position, season):
    """One season's qualified metric rows for a position — the same
    filtering build_board() applies in production, so the tuner learns
    from the same population the live app actually scores."""
    wk = data.load_weekly(season)
    wk, _ = apply_scoring(wk)  # default PPR; SCORE is scoring-agnostic by design, see engine/scoring.py
    m = METRIC_FNS[position](wk)
    return m[(m["games"] >= MIN_GAMES[position]) & (m["volume"] >= MIN_VOLUME[position])]


def _probe_seasons(n_pairs):
    """Walk backward from the most recent completed season, collecting
    real weekly data year by year until we have enough for n_pairs
    consecutive (year, year+1) training pairs — or nflverse runs out.
    The live app's in-progress "current" season is deliberately excluded
    as a training year: an incomplete season's per-game rates are a
    biased sample of what a full season would show, and it can't serve as
    a year+1 target yet either way."""
    current = data.resolve_season()
    seasons = {}
    year = current - 1
    while len(seasons) < n_pairs + 1 and year > current - 15:
        try:
            wk = data.load_weekly(year)
            if len(wk):
                seasons[year] = True
                print(f"[tuner] {year}: {len(wk)} weekly rows available")
        except Exception as e:
            print(f"[tuner] {year}: unavailable ({e})")
        year -= 1
    return sorted(seasons.keys())


def tune_position(position, seasons):
    """Build every valid (year, year+1) training pair for this position,
    concatenate across all of them, and regress."""
    feature_cols = list(_DEFAULT_WEIGHTS[position].keys())
    frames = []
    for year in seasons:
        if (year + 1) not in seasons:
            continue
        train = _season_metrics(position, year)
        target = _season_metrics(position, year + 1)[["fpts_per_game"]].rename(
            columns={"fpts_per_game": "target_fpts_per_game"})
        joined = train.join(target, how="inner")  # only players who qualified in BOTH seasons
        if len(joined):
            frames.append(joined)

    if not frames:
        print(f"  [tuner] {position}: no season-over-season pairs with enough overlap — skipped")
        return None

    combined = pd.concat(frames, ignore_index=True)
    print(f"  [tuner] {position}: {len(combined)} player-season pairs across {len(frames)} season transitions")
    learned = learn_weights(combined, "target_fpts_per_game", feature_cols)
    return to_weight_dict(learned, _DEFAULT_WEIGHTS[position])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="save learned_weights.json (default: dry run, prints only)")
    ap.add_argument("--only", default=None, help="comma-separated positions, e.g. WR,TE (default: all)")
    ap.add_argument("--season-pairs", type=int, default=4, help="how many (year, year+1) pairs to gather (default 4)")
    args = ap.parse_args()

    positions = [p.strip().upper() for p in args.only.split(",")] if args.only else list(POSITIONS)
    bad = [p for p in positions if p not in POSITIONS]
    if bad:
        ap.error(f"not a position: {bad}")

    seasons = _probe_seasons(args.season_pairs)
    if len(seasons) < 2:
        print("[tuner] fewer than 2 real seasons of data available — nothing to learn from yet.")
        return

    print(f"\n[tuner] using seasons {seasons} ({len(seasons) - 1} year-over-year transition(s))\n")

    results = {}
    for pos in positions:
        print(f"===== {pos} =====")
        learned = tune_position(pos, seasons)
        if learned is None:
            continue
        results[pos] = learned
        for metric, old in _DEFAULT_WEIGHTS[pos].items():
            new = learned.get(metric, old)
            arrow = "→" if abs(new - old) >= 0.5 else "≈"
            print(f"  {metric:<28} {old:>7.1f}  {arrow}  {new:>7.1f}")
        print()

    if not results:
        print("[tuner] nothing learned — no position had enough data.")
        return

    if args.write:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seasons_used": seasons,
            "weights": results,
        }
        os.makedirs(os.path.dirname(LEARNED_WEIGHTS_PATH), exist_ok=True)
        with open(LEARNED_WEIGHTS_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"[tuner] wrote {LEARNED_WEIGHTS_PATH} — restart the server for engine/metrics.py to pick it up.")
    else:
        print("[tuner] dry run — nothing written. Re-run with --write to save these as the live weights.")


if __name__ == "__main__":
    main()
