"""
Does a player's record against THIS opponent over the previous two seasons predict anything the
projection and the opponent's general defense don't already?

  .venv/bin/python scripts/backtest_h2h.py

For every QB/RB/WR/TE game in 2024 and 2025 (week 4+, 3+ games already played that season) the base prediction is
the shipped model (engine/projmodel, recency-capped), fitted without that season. Two candidate signals, each known
before the game:

  h2h      his average in games against this opponent (the previous two seasons, plus earlier meetings this
           season) over his average across the same seasons, minus 1
  defense  how many points this opponent allows to his position, over the previous season and this season so far,
           relative to the league average, minus 1   (the matchup factor the app already applies)

Each is turned into points (base x signal) and regressed on the miss (actual - base), through the origin:
a slope near 1 means the signal is real at full strength, near 0 means noise. The app's head-to-head factor
(engine/history.h2h_factor) uses a slope of n/(n+12) for n meetings, i.e. about 0.14 at 2 meetings.
2025 has two full prior seasons of history; 2024 has one, so it is reported separately.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import history, projmodel as P  # noqa: E402


def build():
    P._COLS = P._COLS + ["opponent_team"]
    cur = int(history._frames()["skill"]["season"].max()) + 1
    df = P._scored_history(None, cur)
    ppo = P._opportunity_values(df)
    rows = P._training_rows(df, ppo)
    rows = rows[rows["position"].isin(P.POSITIONS)].copy()
    rows["pred"] = np.nan
    rows["base"] = np.nan
    for test in sorted(rows["season"].unique()):
        coef = P.fit(rows[rows["season"] != test])
        for pos, c in coef.items():
            idx = (rows["season"] == test) & (rows["position"] == pos)
            x = np.column_stack([np.ones(idx.sum())] + [rows.loc[idx, f].to_numpy(float) for f in P.FEATURES])
            rows.loc[idx, "pred"] = x @ c
            rows.loc[idx, "base"] = P.baseline_rate(c, rows.loc[idx, "ppg"], rows.loc[idx, "opp_ppg"], rows.loc[idx, "prior"])
    rows["capped"] = P.cap_recency(rows["pred"], rows["base"])
    return df, rows


def add_signals(df, rows):
    games = df.dropna(subset=["opponent_team"])
    by_player = {pid: g.sort_values(["season", "week"]) for pid, g in games.groupby("player_id")}
    lg = games.groupby(["position"])["fpts_active"].mean()
    # points allowed per opponent/position/season, and per week for the "this season so far" part
    allowed = games.groupby(["opponent_team", "position", "season"])["fpts_active"].agg(["sum", "count"])
    cum = games.sort_values(["season", "week"]).groupby(["opponent_team", "position", "season", "week"])["fpts_active"].agg(["sum", "count"])
    h2h, nmeet, dfn = [], [], []
    for r in rows.itertuples(index=False):
        g = by_player.get(r.player_id)
        opp = getattr(r, "opponent_team")
        prior = g[((g["season"] >= r.season - 2) & (g["season"] < r.season)) | ((g["season"] == r.season) & (g["week"] < r.week))]
        meet = prior[prior["opponent_team"] == opp]
        if len(meet) >= 1:
            ref = prior[prior["season"].isin(meet["season"].unique())]["fpts_active"].mean()
            h2h.append(meet["fpts_active"].mean() / ref - 1.0 if ref and ref > 0 else np.nan)
        else:
            h2h.append(np.nan)
        nmeet.append(len(meet))
        # opponent strength vs this position: last season in full + this season before this week
        s_sum = s_n = 0.0
        if (opp, r.position, r.season - 1) in allowed.index:
            a = allowed.loc[(opp, r.position, r.season - 1)]; s_sum += a["sum"]; s_n += a["count"]
        for w in range(1, int(r.week)):
            if (opp, r.position, r.season, w) in cum.index:
                a = cum.loc[(opp, r.position, r.season, w)]; s_sum += a["sum"]; s_n += a["count"]
        dfn.append(s_sum / s_n / lg[r.position] - 1.0 if s_n >= 20 else np.nan)
    rows = rows.copy()
    rows["h2h"], rows["n_meet"], rows["defn"] = h2h, nmeet, dfn
    return rows


def slope(y, x):
    x, y = np.asarray(x, float), np.asarray(y, float)
    b = (x * y).sum() / (x * x).sum()
    resid = y - b * x
    se = np.sqrt((resid ** 2).sum() / (len(y) - 1) / (x * x).sum())
    return b, se


def report(rows, label):
    d = rows[(rows["week"] >= 4) & rows["capped"].notna() & rows["h2h"].notna() & rows["defn"].notna() & (rows["n_meet"] >= 1)].copy()
    d["miss"] = d["fpts_active"] - d["capped"]
    d["e_h"] = d["capped"] * d["h2h"].clip(-0.6, 0.6)
    d["e_d"] = d["capped"] * d["defn"].clip(-0.4, 0.4)
    print(f"\n== {label}: {len(d)} games with at least one prior meeting; typical meetings {d['n_meet'].median():.0f}")
    print(f"{'':28}{'slope':>8}{'+/- se':>9}")
    b, se = slope(d["miss"], d["e_d"]); print(f"{'opponent defense alone':28}{b:8.2f}{se:9.2f}")
    b, se = slope(d["miss"], d["e_h"]); print(f"{'head-to-head alone':28}{b:8.2f}{se:9.2f}")
    X = np.column_stack([d["e_d"], d["e_h"]]); y = d["miss"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef; cov = np.linalg.inv(X.T @ X) * (res @ res) / (len(y) - 2)
    print(f"{'both: defense':28}{coef[0]:8.2f}{np.sqrt(cov[0, 0]):9.2f}")
    print(f"{'both: head-to-head':28}{coef[1]:8.2f}{np.sqrt(cov[1, 1]):9.2f}   <- what meetings add beyond the defense")
    for lo, hi in ((1, 1), (2, 2), (3, 9)):
        s = d[(d["n_meet"] >= lo) & (d["n_meet"] <= hi)]
        if len(s) > 150:
            b, se = slope(s["miss"] - coef[0] * s["e_d"], s["e_h"])
            print(f"   head-to-head, {lo}{'' if lo == hi else '+'} meeting(s), n={len(s):5d}   {b:6.2f} +/- {se:.2f}")
    return d


if __name__ == "__main__":
    df, rows = build()
    rows = add_signals(df, rows)
    for season in sorted(rows["season"].unique()):
        s = rows[rows["season"] == season]
        report(s, f"{season} ({'two' if season - 2 >= df['season'].min() else 'one'} prior season(s) of history)")
