"""Fit the rest-of-game (ROG) uncertainty used for the My Team win probability.

For every player-game snapshot in data_cache/live_proj/snapshots.parquet (built by analysis/live_proj_fit.py) the live
model gives an expected rest-of-game score `rog_exp` (engine.live_proj.live_projection). The residual
`rog - rog_exp` is the real surprise left in the game. Model: residual SD = a_pos * rog_exp ** b (one pair per
position, plus a position-agnostic pair "ALL" for K / DEF / anything unknown), fitted by weighted least squares of
log(RMS residual) on log(rog_exp) over rog_exp quantile bins, on 2023-2025 only. 2026 (weeks 1-7) is held out and used
only to report calibration: share of finals inside +-1 and +-2 SD of (so_far + rog_exp), against the 68.3% / 95.4% a
normal would give. Finished players (seconds left 0) have no remaining uncertainty and are not part of the fit.

Run from the repo root:  python analysis/live_var_fit.py   (rewrites engine/live_var_params.json, analysis/live_var_results.txt)"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
import numpy as np
import pandas as pd

from engine import live_proj

SNAP = "data_cache/live_proj/snapshots.parquet"
OUT = "engine/live_var_params.json"
REPORT = "analysis/live_var_results.txt"
FIT_SEASONS, TEST_SEASON = (2023, 2024, 2025), 2026
POS = ("QB", "RB", "WR", "TE")


def add_expected(df):
    exp = [live_proj.live_projection(p, pre, sf, t, d)["rog"]
           for p, pre, sf, t, d in zip(df.position, df.pregame, df.so_far, df.t, df["diff"])]
    out = df.copy()
    out["rog_exp"] = exp
    out["res"] = out["rog"] - out["rog_exp"]
    return out


def fit_curve(d, nbins=24):
    """(a, b, floor) for sd = max(floor, a * rog_exp ** b)."""
    d = d[d.rog_exp > 0.05]
    q = pd.qcut(d.rog_exp, nbins, duplicates="drop")
    g = d.groupby(q, observed=True).agg(x=("rog_exp", "mean"), rms=("res", lambda r: float(np.sqrt(np.mean(r ** 2)))), n=("res", "size"))
    b, loga = np.polyfit(np.log(g.x), np.log(g.rms), 1, w=np.sqrt(g.n))
    return float(np.exp(loga)), float(b), float(g.rms.min())


def sd_of(params, pos, rog_exp):
    p = params.get(pos) or params["ALL"]
    return np.maximum(p["floor"], p["a"] * np.power(np.maximum(rog_exp, 1e-9), p["b"]))


def calibration(df, params, pos=None):
    d = df[(df.rog_exp > 0.05)]
    if pos:
        d = d[d.position == pos]
    sd = np.array([sd_of(params, p, r) for p, r in zip(d.position, d.rog_exp)])
    z = np.abs(d.res.values) / sd
    return len(d), float((z <= 1).mean()), float((z <= 2).mean())


def main():
    snaps = pd.read_parquet(SNAP)
    snaps = snaps[snaps.position.isin(POS) & snaps.pregame.notna() & (snaps.t > 0)]
    fit = add_expected(snaps[snaps.season.isin(FIT_SEASONS)])
    test = add_expected(snaps[snaps.season == TEST_SEASON])
    params = {}
    for pos in POS:
        a, b, fl = fit_curve(fit[fit.position == pos])
        params[pos] = {"a": round(a, 4), "b": round(b, 4), "floor": round(fl, 4)}
    a, b, fl = fit_curve(fit)
    params["ALL"] = {"a": round(a, 4), "b": round(b, 4), "floor": round(fl, 4)}
    lines = [f"fit rows {len(fit)} (2023-2025), held-out rows {len(test)} (2026 weeks 1-7), snapshots with seconds left > 0 and rog_exp > 0.05",
             "calibration = share of finals inside +-1 / +-2 SD of points so far + expected rest of game (normal: 68.3% / 95.4%)",
             f"{'pos':5}{'a':>9}{'b':>8}{'floor':>8}{'fit n':>9}{'fit 1sd':>9}{'fit 2sd':>9}{'test n':>9}{'test 1sd':>10}{'test 2sd':>10}"]
    for pos in POS + ("ALL",):
        pf = fit if pos == "ALL" else fit[fit.position == pos]
        n1, a1, b1 = calibration(pf, params)
        n2, a2, b2 = calibration(test, params, None if pos == "ALL" else pos)
        p = params[pos]
        lines.append(f"{pos:5}{p['a']:9.3f}{p['b']:8.3f}{p['floor']:8.3f}{n1:9d}{a1:9.3f}{b1:9.3f}{n2:9d}{a2:10.3f}{b2:10.3f}")
        params[pos]["calib_test"] = {"n": n2, "within_1sd": round(a2, 3), "within_2sd": round(b2, 3)}
    # by time left, all positions, held-out
    lines.append("held-out calibration by seconds left (all positions):")
    for lo, hi in ((0, 900), (900, 1800), (1800, 2700), (2700, 3601)):
        s = test[(test.t > lo) & (test.t <= hi)]
        n, a1, b1 = calibration(s, params)
        lines.append(f"  {lo:4d}-{hi:4d}s  n={n:6d}  1sd={a1:.3f}  2sd={b1:.3f}")
    out = {"version": 1, "fit_seasons": list(FIT_SEASONS), "test_season": TEST_SEASON,
           "model": "sd = max(floor, a * rog_exp ** b); remaining-points residual, per position; ALL = position-agnostic (K, DEF, unknown)",
           "sd": params}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    with open(REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
