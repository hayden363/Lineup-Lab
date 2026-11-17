"""Do our own play-by-play metrics add anything to the DEF/ST and kicker market model? (owner 2026-11-17)

engine/kdef_model.py projects a defense from its shrunk rate + the opponent's implied team total, and a kicker from his
rate + his own implied total + a dome, both from the betting lines (scripts/backtest_kdef.py). Points allowed is most of
DEF scoring and the market prices it; sacks and takeaways are the rest. A kicker's FG volume depends on drives that stall
in the red zone. Features tested here, each from that season's play-by-play of the weeks BEFORE the game, shrunk toward
the league rate with pseudo-plays:
    DEF  opp_sack   the opposing offense's sack rate allowed (sacks / dropbacks)
         opp_give   the opposing offense's giveaways per play (INT + fumbles lost)
    K    opp_rz     the opposing defense's red-zone TD rate allowed (lower = more drives end in a FG try)
         wind       game wind (0 indoors), from the schedule
Same walk-forward least squares as scripts/backtest_kdef.py ("market"), with and without the new features, scored
2024+.   Run from the repo root: python analysis/kdef_adv_backtest.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import numpy as np
import pandas as pd

import backtest_kdef as B  # noqa: E402
from engine import data, defense_scoring, kicker_scoring  # noqa: E402

SHRINK_PLAYS = 150.0


def _before(df, key, num, den, k):
    """Per (season, week, key) shrunk rate num/den over that key's games in weeks BEFORE `week`."""
    g = df.groupby(["season", key, "week"])[[num, den]].sum().reset_index().sort_values(["season", key, "week"])
    g[[num + "_c", den + "_c"]] = g.groupby(["season", key])[[num, den]].cumsum() - g[[num, den]].to_numpy()
    lg = df.groupby("season")[[num, den]].sum()
    league = (lg[num] / lg[den]).rename("lg")
    g = g.merge(league, left_on="season", right_index=True)
    g["v"] = (g[num + "_c"] + k * g["lg"]) / (g[den + "_c"] + k) / g["lg"]   # ratio to league: 1.0 = average
    return g.set_index(["season", key, "week"])["v"]


def adv_tables(seasons):
    parts = []
    for s in seasons:
        p = data.load_pbp(s)
        p = p[p["week"] <= 18].assign(season=s)
        parts.append(p)
    p = pd.concat(parts, ignore_index=True)
    p["play"] = p["play_type"].isin(["pass", "run"]).astype(float)
    p["drop"] = (p["qb_dropback"] == 1).astype(float)
    p["sackf"] = p["sack"].fillna(0).astype(float)
    lost = p["fumble_recovery_1_team"].notna() & (p["fumble_recovery_1_team"] != p["posteam"])
    p["give"] = p["interception"].fillna(0).astype(float) + lost.astype(float)
    rz = p[(p["yardline_100"] <= 20) & (p["play"] == 1)].copy()
    rz["td"] = rz["touchdown"].fillna(0).astype(float)
    rz["one"] = 1.0
    return {
        "opp_sack": _before(p[p["drop"] == 1], "posteam", "sackf", "drop", SHRINK_PLAYS / 2),
        "opp_give": _before(p[p["play"] == 1], "posteam", "give", "play", SHRINK_PLAYS * 2),
        "opp_rz": _before(rz, "defteam", "td", "one", SHRINK_PLAYS / 3),
    }


def run():
    seasons = sorted(pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))["season"].unique().tolist())
    sched = B._schedule(seasons)
    T = adv_tables(seasons)

    # ---- DEF/ST ----
    w = pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))
    w = w[w["week"] <= 18]
    w["y"] = defense_scoring.score_defense_weekly(w, defense_scoring.def_scoring_from_sleeper(None))
    w = w.merge(sched, left_on=["season", "week", "defteam"], right_on=["season", "week", "team"], how="left")
    d = B._features(w, "defteam")
    for f in ("opp_sack", "opp_give"):
        d[f] = [T[f].get((s, o, wk), 1.0) for s, o, wk in zip(d.season, d.opp, d.week)]
    preds = {"market": B._walk_forward_ols(d, ["rate", "itt_opp"]),
             "+sack": B._walk_forward_ols(d, ["rate", "itt_opp", "opp_sack"]),
             "+give": B._walk_forward_ols(d, ["rate", "itt_opp", "opp_give"]),
             "+both": B._walk_forward_ols(d, ["rate", "itt_opp", "opp_sack", "opp_give"])}
    B._report("DEF/ST", d, preds)

    # ---- Kicker ----
    k = pd.read_parquet(os.path.join(ROOT, "history_data", "kicker_weekly.parquet"))
    k = k[k["week"] <= 18]
    k["y"] = kicker_scoring.score_kicker_weekly(k, kicker_scoring.k_scoring_from_sleeper(None))
    cols = ["week", "kicker_player_id", "posteam", "field_goal_attempt", "extra_point_attempt"]
    pbp = pd.concat([data.load_pbp(s)[cols].assign(season=s) for s in sorted(k["season"].unique().tolist())])
    kick = pbp[(pbp["field_goal_attempt"] == 1) | (pbp["extra_point_attempt"] == 1)].dropna(subset=["kicker_player_id", "posteam"])
    team = kick.groupby(["season", "week", "kicker_player_id"])["posteam"].agg(lambda s: s.mode().iloc[0]).reset_index()
    k = k.merge(team, left_on=["season", "week", "player_id"], right_on=["season", "week", "kicker_player_id"], how="inner")
    k = k.merge(sched, left_on=["season", "week", "posteam"], right_on=["season", "week", "team"], how="left")
    kd = B._features(k, "player_id")
    kd["opp_rz"] = [T["opp_rz"].get((s, o, wk), 1.0) for s, o, wk in zip(kd.season, kd.opp, kd.week)]
    preds = {"market": B._walk_forward_ols(kd, ["rate", "itt"]),
             "+dome": B._walk_forward_ols(kd, ["rate", "itt", "indoor"]),
             "+rz": B._walk_forward_ols(kd, ["rate", "itt", "indoor", "opp_rz"]),
             "+wind": B._walk_forward_ols(kd, ["rate", "itt", "indoor", "wind"]),
             "+rz+wind": B._walk_forward_ols(kd, ["rate", "itt", "indoor", "opp_rz", "wind"])}
    B._report("Kicker", kd, preds)


if __name__ == "__main__" and "--fit" not in sys.argv:
    run()


def fit_def_ratio():
    """Coefficients for engine/kdef_model.DEF_COEF with the opponent sack-rate term, fitted like the original on 2023-25:
    y/pool = base + rate*(rate/pool - 1) + itt_opp*(itt_opp - 22) + opp_sack*(opp_sack - 1)."""
    seasons = sorted(pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))["season"].unique().tolist())
    sched = B._schedule(seasons)
    T = adv_tables(seasons)
    w = pd.read_parquet(os.path.join(ROOT, "history_data", "defense_weekly.parquet"))
    w = w[w["week"] <= 18]
    w["y"] = defense_scoring.score_defense_weekly(w, defense_scoring.def_scoring_from_sleeper(None))
    w = w.merge(sched, left_on=["season", "week", "defteam"], right_on=["season", "week", "team"], how="left")
    d = B._features(w, "defteam").dropna(subset=["itt_opp", "pool"])
    d = d[d.season >= 2023]
    d["opp_sack"] = [T["opp_sack"].get((s, o, wk), 1.0) for s, o, wk in zip(d.season, d.opp, d.week)]
    itt = d.itt_opp.clip(14, 31)
    X = np.c_[np.ones(len(d)), d.rate / d.pool - 1, itt - 22, d.opp_sack - 1]
    beta = np.linalg.lstsq(X, (d.y / d.pool).to_numpy(), rcond=None)[0]
    print("DEF_COEF =", {k: round(float(v), 4) for k, v in zip(("base", "rate", "itt_opp", "opp_sack"), beta)}, f"(n={len(d)})")
    return beta


if __name__ == "__main__" and "--fit" in sys.argv:
    fit_def_ratio()
