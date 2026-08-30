"""
WEIGHT TUNER  (Task 3)
Instead of guessing how much each metric matters, LEARN the weights from
past data: which metrics actually predicted fantasy points?

Method: regress each player's advanced metrics against their fantasy
points per game. The resulting coefficients become data-driven weights.
This is what turns "I think YPA matters a lot" into "YPA is worth X,
proven on real results."

Uses a simple normal-equation linear regression (no sklearn needed, so it
runs anywhere). Real version feeds in the metric tables from the other
modules across many players/seasons.
"""

import numpy as np
import pandas as pd


def learn_weights(metrics_df, target_col, feature_cols):
    """
    metrics_df: rows = players, cols = metrics + target
    Returns learned weight per feature (standardized, so comparable).
    """
    df = metrics_df.dropna(subset=feature_cols + [target_col]).copy()
    if len(df) < len(feature_cols) + 1:
        print("  [tuner] not enough rows to learn reliably — showing correlations instead")
        return _correlation_fallback(df, target_col, feature_cols)

    # standardize features so weights are comparable in size
    X = df[feature_cols].values.astype(float)
    X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)
    y = df[target_col].values.astype(float)
    Xb = np.column_stack([np.ones(len(X)), X])          # add intercept

    # normal equation: beta = (X'X)^-1 X'y  (ridge-regularized for stability)
    lam = 1.0
    I = np.eye(Xb.shape[1]); I[0, 0] = 0                 # don't penalize intercept
    beta = np.linalg.solve(Xb.T @ Xb + lam * I, Xb.T @ y)

    weights = pd.Series(beta[1:], index=feature_cols)
    return weights.round(3)


def _correlation_fallback(df, target_col, feature_cols):
    cors = {f: df[f].corr(df[target_col]) for f in feature_cols}
    return pd.Series(cors).round(3)


def to_weight_dict(learned):
    """Scale learned weights to the 0-25ish range the engine uses."""
    scale = 25 / (learned.abs().max() + 1e-9)
    return (learned * scale).round(1).to_dict()


def run():
    # sample: players with metrics + their actual fantasy pts/game
    sample = pd.DataFrame({
        "yards_per_attempt":  [8.4, 7.1, 9.0, 6.8, 7.9, 8.8, 6.5, 9.3],
        "td_rate":            [5.2, 3.1, 6.0, 2.8, 4.5, 5.8, 2.5, 6.4],
        "int_rate":           [1.1, 2.4, 0.9, 3.0, 1.8, 1.0, 3.2, 0.8],
        "pressure_rate":      [22,  35,  18,  40,  28,  20,  42,  16],
        "explosive_pass_rate":[14,  8,   16,  6,   11,  15,  5,   18],
        "fpts_per_game":      [24,  16,  27,  12,  20,  26,  11,  29],
    })
    features = ["yards_per_attempt","td_rate","int_rate","pressure_rate","explosive_pass_rate"]

    print("===== LEARNED QB WEIGHTS (from what predicted fantasy pts) =====")
    learned = learn_weights(sample, "fpts_per_game", features)
    print(learned.to_string())

    print("\n===== SCALED TO ENGINE WEIGHTS =====")
    wd = to_weight_dict(learned)
    for k, v in wd.items():
        print(f"  {k}: {v}")
    print("\n(Positive = more of it predicts MORE fantasy pts; "
          "negative = predicts fewer. These replace your guessed weights.)")


if __name__ == "__main__":
    run()
