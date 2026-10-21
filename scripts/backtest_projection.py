"""
How accurate is the projection formula? Replays every QB/RB/WR/TE game from past
seasons, predicting each one from only the games before it, and reports the error.

  .venv/bin/python scripts/backtest_projection.py [first_season last_season]

Formula tested (same shape as engine/board.py): the season rate shrunk toward his
own last three seasons (engine/history.py weights and k) and the position average,
times (1 + half the recency-weighted form, capped at +/-40%). The live FORM also
blends in play-by-play EPA, which is not rebuilt here, so this is a close proxy.

Also prints how a more recency-heavy blend does, on everyone and on players who
are running hot, which is the check behind engine/tools.BACKTEST.
"""
import sys
import warnings

import nfl_data_py as nfl
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HIST_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.5}
BASE_K, HIST_K, HIST_FULL, MIN_GAMES_BEFORE = 3.0, 4.0, 24.0, 3


def build(first, last):
    w = nfl.import_weekly_data(list(range(first, last + 1)))
    w = w[(w.season_type == "REG") & w.position.isin(["QB", "RB", "WR", "TE"])]
    w = w[["player_id", "season", "week", "position", "fantasy_points_ppr"]].rename(columns={"fantasy_points_ppr": "y"})
    w = w.sort_values(["player_id", "season", "week"])
    seasons = {(r.player_id, r.season): (r.n, r.m) for r in
               w.groupby(["player_id", "season"]).agg(n=("y", "size"), m=("y", "mean")).reset_index().itertuples()}
    rows = []
    for (pid, season), g in w.groupby(["player_id", "season"]):
        ys, weeks, pos = g["y"].to_numpy(), g["week"].to_numpy(), g["position"].iloc[0]
        hn = hs = 0.0
        for back, wt in HIST_WEIGHTS.items():
            t = seasons.get((pid, season - back))
            if t:
                hn += wt * t[0]
                hs += wt * t[0] * t[1]
        for i in range(MIN_GAMES_BEFORE, len(ys)):
            before = ys[:i]
            decay = 0.5 ** (1 / 2.5 * np.arange(i - 1, -1, -1))
            rows.append({"season": season, "week": weeks[i], "pos": pos, "y": ys[i], "n": i, "cur": before.mean(),
                         "last3": before[-3:].mean(), "ew": np.average(before, weights=decay),
                         "h": hn, "hist_ppg": hs / hn if hn else np.nan})
    return pd.DataFrame(rows)


def predict(d):
    pool = d.groupby(["pos", "season"])["cur"].transform("mean")
    ppg = d.hist_ppg.where(d.h > 0, pool).fillna(pool)
    prior = (d.h * ppg + BASE_K * pool) / (d.h + BASE_K)
    k = BASE_K + HIST_K * (d.h / HIST_FULL).clip(upper=1)
    rate = (d.n * d.cur + k * prior) / (d.n + k)
    form = ((d.ew - d.cur) / d.cur.replace(0, np.nan)).fillna(0) * np.minimum(1, d.n / 8)
    return rate, rate * (1 + 0.5 * form.clip(-0.4, 0.4))


def line(name, pred, d, mask=None):
    m = np.ones(len(d), bool) if mask is None else mask
    e = (pred - d.y)[m]
    print(f"{name:40s} MAE {e.abs().mean():5.2f}  bias {e.mean():+5.2f}  n={int(m.sum())}")


if __name__ == "__main__":
    first, last = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (2016, 2024)
    d = build(first, last)
    rate, shipped = predict(d)
    hot = ((d.last3 >= 1.25 * rate) & (d.n >= 4)).to_numpy()
    print(f"{len(d)} games, seasons {first}-{last}\n")
    line("season average", d.cur, d)
    line("shrunk rate", rate, d)
    line("shrunk rate x form (shipped)", shipped, d)
    for a in (0.3, 0.5):
        line(f"more recency: {int((1 - a) * 100)}% rate / {int(a * 100)}% recent", (1 - a) * rate + a * d.ew, d)
    print("\nPlayers running hot (last 3 games 25%+ above his rate):")
    line("shrunk rate", rate, d, hot)
    line("shrunk rate x form (shipped)", shipped, d, hot)
    line("more recency: 50% / 50%", 0.5 * rate + 0.5 * d.ew, d, hot)
