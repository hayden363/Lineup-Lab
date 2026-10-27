"""
How accurate are the kicker and DEF/ST projections? Replays every kicker game and every
team defense game from past seasons, predicting each from only the games before it.

  .venv/bin/python scripts/backtest_kdef.py

Models, from simplest up (default Sleeper-style scoring, regular season):
  league   the league's average that season, no player info
  live     what the app does today: history-blended rate x (1 + FORM) [x the opposing offense's
           factor for a defense], FORM = recency-weighted form capped at +/-40%
  rate     the same history-blended rate, no FORM, no opponent factor
  market   rate + the betting market's implied team totals (and home/dome for kickers), fitted
           walk-forward by least squares on only the games before each prediction (the honest
           out-of-sample number)
  shipped  engine/kdef_model.py exactly as the app runs it. Its coefficients were fit on all of
           2023-25, so on 2024-25 it is slightly flattered; "market" is the fair comparison.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import defense_scoring, kdef_model, kicker_scoring  # noqa: E402

HIST_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.5}
BASE_K, HIST_K, HIST_FULL = 3.0, 1.5, 24.0   # engine/history.py: kickers and defenses repeat less year to year
FIRST_EVAL = 2024


def _schedule(seasons):
    import nfl_data_py as nfl
    s = nfl.import_schedules(seasons)
    s = s[s["game_type"] == "REG"]
    rows = []
    for g in s.itertuples():
        spread = g.spread_line if pd.notna(g.spread_line) else np.nan
        total = g.total_line if pd.notna(g.total_line) else np.nan
        indoor = 1.0 if str(g.roof) in ("dome", "closed") else 0.0
        wind = 0.0 if indoor else (g.wind if pd.notna(g.wind) else 0.0)
        for team, opp, home in ((g.home_team, g.away_team, 1.0), (g.away_team, g.home_team, 0.0)):
            sgn = 1.0 if home else -1.0
            rows.append({"season": g.season, "week": g.week, "team": team, "opp": opp, "home": home,
                         "itt": (total + sgn * spread) / 2, "itt_opp": (total - sgn * spread) / 2,
                         "indoor": indoor, "wind": wind})
    return pd.DataFrame(rows)


def _features(df, ent, y="y"):
    """Per row, using only that entity's earlier games: rate (history-blended), form, n."""
    df = df.sort_values([ent, "season", "week"]).reset_index(drop=True)
    season_stats = df.groupby([ent, "season"])[y].agg(["size", "mean"])
    pool = df.groupby("season")[y].mean()
    out = []
    for (e, season), g in df.groupby([ent, "season"], sort=False):
        ys = g[y].to_numpy()
        hn = hs = 0.0
        for back, wt in HIST_WEIGHTS.items():
            if (e, season - back) in season_stats.index:
                n_, m_ = season_stats.loc[(e, season - back)]
                hn += wt * n_
                hs += wt * n_ * m_
        pm = pool.get(season, np.nan)
        hist = hs / hn if hn else pm
        for i in range(len(ys)):
            before = ys[:i]
            n = len(before)
            cur = before.mean() if n else pm
            prior = (hn * hist + BASE_K * pm) / (hn + BASE_K)
            k = BASE_K + HIST_K * min(1.0, hn / HIST_FULL)
            rate = (n * cur + k * prior) / (n + k)
            form = 0.0
            if n and cur:
                decay = 0.5 ** (1 / 2.5 * np.arange(n - 1, -1, -1))
                form = (np.average(before, weights=decay) - cur) / cur * min(1.0, n / 8)
            out.append((rate, float(np.clip(form, -0.4, 0.4)), n, pm))
    f = pd.DataFrame(out, columns=["rate", "form", "n", "pool"], index=df.index)
    return pd.concat([df, f], axis=1)


def _walk_forward_ols(df, cols, min_train=200):
    """Predict each (season, week) from a least-squares fit on every earlier week."""
    pred = pd.Series(np.nan, index=df.index)
    for (season, week), idx in df.groupby(["season", "week"]).groups.items():
        train = df[(df["season"] < season) | ((df["season"] == season) & (df["week"] < week))].dropna(subset=cols + ["y"])
        if len(train) < min_train:
            continue
        X = np.c_[np.ones(len(train)), train[cols].to_numpy()]
        beta = np.linalg.lstsq(X, train["y"].to_numpy(), rcond=None)[0]
        test = df.loc[idx]
        Xt = np.c_[np.ones(len(test)), test[cols].fillna(test[cols].mean()).to_numpy()]
        pred.loc[idx] = Xt @ beta
    return pred


def _report(name, df, preds):
    d = df[(df["season"] >= FIRST_EVAL)].copy()
    print(f"\n=== {name}: {len(d)} games, {FIRST_EVAL}+ ===")
    print(f"{'model':<8}{'RMSE':>7}{'MAE':>7}{'bias':>7}{'corr':>7}{'wk-rank':>9}{'top20% hit':>12}")
    for label, p in preds.items():
        q = p.loc[d.index]
        ok = q.notna()
        e = (q[ok] - d.loc[ok, "y"])
        wk = d[ok].assign(p=q[ok]).groupby(["season", "week"]).apply(
            lambda g: g["p"].rank().corr(g["y"].rank()) if len(g) > 5 else np.nan).mean()
        top = d[ok].assign(p=q[ok])
        hit = top[top["p"] >= top.groupby(["season", "week"])["p"].transform(lambda s: s.quantile(0.8))]["y"].mean()
        print(f"{label:<8}{np.sqrt((e ** 2).mean()):7.3f}{e.abs().mean():7.3f}{e.mean():7.3f}"
              f"{q[ok].corr(d.loc[ok, 'y']):7.3f}{wk:9.3f}{hit:12.2f}")
    print(f"(mean points scored {d['y'].mean():.2f}; top-20%-hit = avg actual points of each week's top-20% projections)")


def defense(sched):
    w = pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))
    w = w[w["week"] <= 18]
    w["y"] = defense_scoring.score_defense_weekly(w, defense_scoring.def_scoring_from_sleeper(None))
    w = w.merge(sched, left_on=["season", "week", "defteam"], right_on=["season", "week", "team"], how="left")
    d = _features(w, "defteam")
    # the live opposing-offense factor: what past DEFs scored against this opponent to date / league average to date
    fac = []
    for r in d.itertuples():
        prev = d[(d["opp"] == r.opp) & ((d["season"] == r.season) & (d["week"] < r.week))]
        lg = d[(d["season"] == r.season) & (d["week"] < r.week)]["y"].mean()
        fac.append(prev["y"].mean() / lg if len(prev) and lg else 1.0)
    d["frag"] = fac
    preds = {"league": d["pool"], "live": d["rate"] * (1 + d["form"]) * d["frag"], "rate": d["rate"],
             "market": _walk_forward_ols(d, ["rate", "itt_opp"])}
    preds["shipped"] = pd.Series([kdef_model.defense_projection(r.rate, r.pool, r.itt_opp) for r in d.itertuples()], index=d.index)
    _report("DEF/ST", d, preds)
    return d


def kicker(sched):
    from engine import data
    k = pd.read_parquet(os.path.join(ROOT, "history_data", "kicker_weekly.parquet"))
    k = k[k["week"] <= 18]
    k["y"] = kicker_scoring.score_kicker_weekly(k, kicker_scoring.k_scoring_from_sleeper(None))
    cols = ["week", "kicker_player_id", "posteam", "field_goal_attempt", "extra_point_attempt"]
    pbp = pd.concat([data.load_pbp(s)[cols].assign(season=s) for s in sorted(k["season"].unique().tolist())])
    kick = pbp[(pbp["field_goal_attempt"] == 1) | (pbp["extra_point_attempt"] == 1)].dropna(subset=["kicker_player_id", "posteam"])
    team = kick.groupby(["season", "week", "kicker_player_id"])["posteam"].agg(lambda s: s.mode().iloc[0]).reset_index()
    k = k.merge(team, left_on=["season", "week", "player_id"], right_on=["season", "week", "kicker_player_id"], how="inner")
    k = k.merge(sched, left_on=["season", "week", "posteam"], right_on=["season", "week", "team"], how="left")
    d = _features(k, "player_id")
    preds = {"league": d["pool"], "live": d["rate"] * (1 + d["form"]), "rate": d["rate"],
             "market": _walk_forward_ols(d, ["rate", "itt"])}
    preds["shipped"] = pd.Series([kdef_model.kicker_projection(r.rate, r.pool, r.itt, r.indoor) for r in d.itertuples()], index=d.index)
    _report("Kicker", d, preds)
    return d


if __name__ == "__main__":
    seasons = sorted(pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))["season"].unique().tolist())
    sched = _schedule(seasons)
    defense(sched)
    kicker(sched)
