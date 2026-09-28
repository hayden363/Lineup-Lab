"""Walk-forward backtest: does FORM make next-week projections more accurate?

What this answers
-----------------
FORM (engine/metrics.form_adjustment) nudges a player's projection up or down
by recent trend, and optionally blends in an EPA "luck check". It has no
trained parameters — halflife=2.5, the 8-game confidence ramp, the 50/50 blend
and the +/-40% cap are all hand-set — so there is nothing to "train and
hold out". The real question is whether applying it helps. For every target
week W this uses ONLY weeks < W (no future information), then compares three
predictions of each player's actual week-W fantasy points:

  base      season-to-date mean fantasy points (no FORM)
  form_pts  base * (1 + FORM/100), FORM from points only
  form_epa  base * (1 + FORM/100), FORM with the EPA luck check (as in prod)

Scored by mean absolute error, with a paired bootstrap 95% CI on the MAE
improvement over base, so a real effect can be told apart from noise.

What it does NOT answer: the app's full PROJ also uses matchups, injuries and
more. This isolates FORM's marginal contribution on top of a plain average.

Runs the app's real form_adjustment and weekly_epa on the cached 2025 season,
read straight from data_cache/ — no network.

    .venv/bin/python -m analysis.form_backtest
"""

import os
import sys

import numpy as np
import pandas as pd

from engine.advanced import weekly_epa
from engine.metrics import form_adjustment
from engine.scoring import apply_scoring

SEASON = 2025
POSITIONS = ("QB", "RB", "WR", "TE")
FIRST_TARGET_WEEK = 4      # need a few prior weeks before a trend means anything
MIN_PRIOR_GAMES = 3
BOOTSTRAP_RESAMPLES = 2000
CACHE = os.path.join(os.path.dirname(__file__), "..", "data_cache")


def _load(kind):
    path = os.path.join(CACHE, f"{kind}_{SEASON}.parquet")
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run the app once so it caches the {SEASON} season")
    return pd.read_parquet(path)


def _bootstrap_ci(diffs, rng):
    """95% CI for the mean of paired per-prediction differences."""
    n = len(diffs)
    means = np.array([diffs[rng.integers(0, n, n)].mean() for _ in range(BOOTSTRAP_RESAMPLES)])
    return np.percentile(means, [2.5, 97.5])


def run():
    wk, _ = apply_scoring(_load("weekly"))          # adds fpts_active (PPR)
    wk = wk[wk["season_type"] == "REG"] if "season_type" in wk.columns else wk
    pbp = _load("pbp")

    rows = []
    last_week = int(wk["week"].max())
    for pos in POSITIONS:
        epa_all = weekly_epa(pbp, pos)
        for w in range(FIRST_TARGET_WEEK, last_week + 1):
            hist = wk[(wk["week"] < w) & (wk["position"] == pos)]
            target = wk[(wk["week"] == w) & (wk["position"] == pos)]
            if hist.empty or target.empty:
                continue
            # weekly_epa is (player_id, week)-indexed; keep only past weeks so
            # nothing from week W or later can reach the prediction.
            epa_hist = epa_all[epa_all.index.get_level_values("week") < w]

            form_pts = form_adjustment(hist, pos)
            form_epa = form_adjustment(hist, pos, weekly_epa=epa_hist)
            games = hist.groupby("player_id")["fpts_active"]
            base = games.mean()
            n_games = games.size()

            for _, t in target.iterrows():
                pid = t["player_id"]
                if n_games.get(pid, 0) < MIN_PRIOR_GAMES:
                    continue
                b = float(base[pid])
                rows.append({
                    "position": pos, "week": w, "actual": float(t["fpts_active"]),
                    "base": b,
                    "form_pts": b * (1 + float(form_pts.get(pid, 0.0)) / 100),
                    "form_epa": b * (1 + float(form_epa.get(pid, 0.0)) / 100),
                })

    df = pd.DataFrame(rows)
    if df.empty:
        sys.exit("no predictions produced — check the cached data")

    rng = np.random.default_rng(20260928)
    print(f"FORM backtest — {SEASON} regular season, target weeks {FIRST_TARGET_WEEK}-{last_week}, "
          f"players with >= {MIN_PRIOR_GAMES} prior games\n")
    header = f"{'':6}{'n':>6}{'MAE base':>11}{'form_pts':>11}{'form_epa':>11}   epa-vs-base improvement (95% CI)"
    print(header)
    print("-" * len(header))
    for label, sub in list(df.groupby("position")) + [("ALL", df)]:
        err = {k: (sub[k] - sub["actual"]).abs().to_numpy() for k in ("base", "form_pts", "form_epa")}
        gain = err["base"] - err["form_epa"]            # >0 means FORM+EPA was closer
        lo, hi = _bootstrap_ci(gain, rng)
        verdict = "helps" if lo > 0 else ("hurts" if hi < 0 else "no clear effect")
        print(f"{label:6}{len(sub):>6}{err['base'].mean():>11.3f}{err['form_pts'].mean():>11.3f}"
              f"{err['form_epa'].mean():>11.3f}   {gain.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]  {verdict}")

    # Does the EPA luck check add anything over points-only FORM?
    all_err_pts = (df["form_pts"] - df["actual"]).abs().to_numpy()
    all_err_epa = (df["form_epa"] - df["actual"]).abs().to_numpy()
    luck = all_err_pts - all_err_epa
    lo, hi = _bootstrap_ci(luck, rng)
    print(f"\nEPA luck check vs points-only FORM (ALL): {luck.mean():+.3f} MAE [{lo:+.3f}, {hi:+.3f}] "
          f"-> {'the EPA blend helps' if lo > 0 else ('the EPA blend hurts' if hi < 0 else 'no clear effect')}")
    return df


if __name__ == "__main__":
    run()
