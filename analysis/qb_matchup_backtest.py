"""QB matchup grading backtest (owner 2026-11-17: "make a decision on how to grade that, based on what gives the best
probability output").

Question: a QB's matchup factor today maps his own rushing (rush_yards_per_game, learned weight ~29% of the QB grade) to
the defense's TEAM yards-per-carry allowed, i.e. mostly how it defends running backs. Does that help or hurt?

Method, walk-forward and leak-free:
  * base = the app's own per-game projection (engine/projmodel.py regression, fitted only on seasons before the test
    season, using only games before each week; same as analysis/weekly_backtest.py).
  * every week w >= MIN_WEEK of 2021-2025, the defense profile is rebuilt from that season's play-by-play (and NGS) of
    weeks < w only, then engine/defense.league_relative_factors, exactly as the app builds it.
  * PROJ = base x composite multiplier, the way engine/board.project_vs applies it. Variants change ONLY how the QB's
    rush_yards_per_game metric is graded:
      current  - team yards per carry allowed (what ships today)
      qb_rush  - QB rush yards per game allowed by that defense (scrambles + designed QB runs; QBs identified from the
                 weekly stats), shrunk toward the league mean with SHRINK pseudo-games
      damp50   - today's factor pulled halfway back to 1.0
      pass_only- QB rushing gets no matchup factor (neutral 1.0)
      none     - no matchup factor at all (reference)
  * scored on real PPR points: MAE, RMSE, weekly rank correlation, and the pairwise probability the app would show
    ("A outscores B" = Phi(diff / (sigma*sqrt2)), sigma fitted per variant on the training seasons' residuals) by log loss
    and Brier score. Lower log loss = better probability output.
Run from the repo root: python analysis/qb_matchup_backtest.py
"""
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from math import erf, sqrt

_ncdf = np.vectorize(lambda z: 0.5 * (1 + erf(z / sqrt(2))))   # normal CDF without scipy

from engine import data, defense, metrics, projmodel as PM
from engine.scoring import apply_scoring

TEST = range(2021, 2026)
TRAIN_FROM = 2017
MIN_WEEK = 4
MINGRP = 8
SHRINK = 4.0
POSN = sys.argv[1].upper() if len(sys.argv) > 1 else "QB"     # QB (default) or RB / WR / TE for the strength check
VARIANTS = ("current", "qb_rush", "damp50", "pass_only", "none") if POSN == "QB" else ("current", "none")

# ---- the app's base projection, walk-forward (same as weekly_backtest.py) ---------------------------------------
frames = []
for s in range(TRAIN_FROM, 2026):
    wk = data.load_weekly(s)
    wk = wk[wk["position"].isin(("QB", "RB", "WR", "TE")) & (wk["week"] <= 18)].copy()
    wk["season"] = s
    wk, _ = apply_scoring(wk)
    frames.append(wk[[c for c in PM._COLS if c in wk.columns] + ["player_display_name", "recent_team", "opponent_team"]])
df = pd.concat(frames, ignore_index=True)
df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)
opp_of = df.set_index(["player_id", "season", "week"])["opponent_team"]

rows_all = []
for s in TEST:
    hist = df[df.season < s]
    ppo = PM._opportunity_values(hist)
    rows = PM._training_rows(df[df.season <= s], ppo)
    coef = PM.fit(rows[rows.season < s])
    t = rows[(rows.season == s) & (rows.position == POSN)].copy()
    c = coef[POSN]
    x = np.column_stack([np.ones(len(t))] + [t[f].to_numpy(float) for f in PM.FEATURES])
    t["raw"] = x @ c
    t["base"] = c[0] + c[1] * t["ppg"] + c[2] * t["ppg"] + c[3] * t["opp_ppg"] + c[4] * t["prior"]
    t["app"] = PM.cap_recency(t["raw"], t["base"])
    rows_all.append(t[["player_id", "season", "week", "fpts_active", "app"]])
Q = pd.concat(rows_all).dropna(subset=["app"])
Q = Q[Q.week >= MIN_WEEK].copy()
Q["opp"] = [opp_of.get((p, s, w)) for p, s, w in zip(Q.player_id, Q.season, Q.week)]
Q = Q.dropna(subset=["opp", "fpts_active"])
print(f"{POSN} player-weeks scored: {len(Q)} ({Q.season.min()}-{Q.season.max()}, weeks {MIN_WEEK}+)")


# ---- defense factors per (season, week), from games before that week ------------------------------------------
def qb_ids(season):
    w = data.load_weekly(season)
    return set(w.loc[w["position"] == "QB", "player_id"])


def factors_for(pbp, ngs, sched, qbs, week):
    p = pbp[pbp.week < week]
    prof = defense.build_defense_profile(p)
    if ngs is not None:
        try:
            n = {k: v[v.week < week] for k, v in ngs.items()}
            prof = prof.join(defense.build_ngs_defense_profile(n["passing"], n["rushing"], n["receiving"], sched), how="left")
        except Exception:
            pass
    # qb_rush_ypg_allowed comes from engine.defense.qb_rush_allowed (built into build_defense_profile): the shipped code
    f, _ = defense.league_relative_factors(prof)
    return f


W = metrics.WEIGHTS[POSN]
MAP = defense.METRIC_TO_DEFENSE[POSN]


def mult(f, opp, variant):
    if variant == "none" or opp not in f.index:
        return 1.0
    tot, acc = 0.0, 0.0
    for m, w in W.items():
        col = MAP.get(m)
        if m == "rush_yards_per_game":
            col = {"current": "ypc_allowed", "damp50": "ypc_allowed", "qb_rush": "qb_rush_ypg_allowed", "pass_only": None}.get(variant, col)
        fac = float(f.loc[opp, col]) if col and col in f.columns and pd.notna(f.loc[opp, col]) else 1.0
        if m == "rush_yards_per_game" and variant == "damp50":
            fac = 1 + 0.5 * (fac - 1)
        eff = fac if w >= 0 else 2 - fac
        tot += abs(w)
        acc += abs(w) * eff
    return acc / tot if tot else 1.0


cache = {}
for s in TEST:
    pbp = data.load_pbp(s)
    sched = data.load_schedule(s)
    try:
        ngs = {k: data.load_ngs(k, s) for k in ("passing", "rushing", "receiving")}
    except Exception as e:
        print(f"[ngs {s}] unavailable: {e}")
        ngs = None
    qbs = qb_ids(s)
    for w in sorted(Q[Q.season == s].week.unique()):
        cache[(s, w)] = factors_for(pbp, ngs, sched, qbs, int(w))
    print(f"season {s}: factors for {len([k for k in cache if k[0] == s])} weeks")

for v in VARIANTS:
    Q["m_" + v] = [mult(cache[(s, w)], o, v) for s, w, o in zip(Q.season, Q.week, Q.opp)]
    Q["p_" + v] = Q["app"] * Q["m_" + v]


# ---- score ----------------------------------------------------------------------------------------------------
def pair_scores(g, col, sigma):
    a, y = g[col].to_numpy(), g["fpts_active"].to_numpy()
    iu = np.triu_indices(len(g), 1)
    d = (a[:, None] - a[None, :])[iu]
    dy = (y[:, None] - y[None, :])[iu]
    keep = dy != 0
    pr = np.clip(_ncdf(d[keep] / (sigma * np.sqrt(2))), 1e-6, 1 - 1e-6)
    out = (dy[keep] > 0).astype(float)
    return -(out * np.log(pr) + (1 - out) * np.log(1 - pr)).sum(), ((pr - out) ** 2).sum(), keep.sum(), ((pr > .5) == (out > .5)).sum()


res = []
first = min(TEST)
for v in VARIANTS:
    col = "p_" + v
    err = Q[col] - Q.fpts_active
    # sigma for the probabilities: fitted on the first test season, scored on the rest (no peeking)
    sigma = float(err[Q.season == first].std())
    ll = br = n = hit = 0.0
    rhos = []
    for (s, w), g in Q[Q.season > first].groupby(["season", "week"]):
        if len(g) < MINGRP:
            continue
        a, b, c, d = pair_scores(g, col, sigma)
        ll += a; br += b; n += c; hit += d
        rhos.append(g[col].rank().corr(g.fpts_active.rank()))
    late = Q.season > first
    res.append({"variant": v, "MAE": err[late].abs().mean(), "RMSE": np.sqrt((err[late] ** 2).mean()),
                "rank_rho": np.mean(rhos), "pair_logloss": ll / n, "pair_brier": br / n, "pair_acc": hit / n, "pairs": int(n),
                "mult_sd": Q.loc[late, "m_" + v].std()})
R = pd.DataFrame(res).set_index("variant")
print(f"\n{POSN} weekly projections, seasons", first + 1, "-", max(TEST), "(first season fits the probability spread)")
print(R.round(4).to_string())
best = R.pair_logloss.idxmin()
print(f"\nbest probability output (lowest pairwise log loss): {best}")

# bootstrap by season-week: how often does each variant beat 'current' on log loss?
rng = np.random.default_rng(7)
keys = [k for k, g in Q[Q.season > first].groupby(["season", "week"]) if len(g) >= MINGRP]
per = {v: {} for v in VARIANTS}
for v in VARIANTS:
    sigma = float((Q["p_" + v] - Q.fpts_active)[Q.season == first].std())
    for k in keys:
        g = Q[(Q.season == k[0]) & (Q.week == k[1])]
        a, b, c, d = pair_scores(g, "p_" + v, sigma)
        per[v][k] = (a, c)
for v in VARIANTS:
    if v == "current":
        continue
    wins = 0
    for _ in range(2000):
        idx = rng.integers(0, len(keys), len(keys))
        ks = [keys[i] for i in idx]
        lv = sum(per[v][k][0] for k in ks) / sum(per[v][k][1] for k in ks)
        lc = sum(per["current"][k][0] for k in ks) / sum(per["current"][k][1] for k in ks)
        wins += lv < lc
    print(f"  {v:9s} beats current in {wins / 2000:.1%} of bootstrap resamples (by season-week)")


# ---- how much of the matchup to keep: factor = 1 + alpha * (m - 1) ---------------------------------------------
# alpha is chosen on 2022-2023 and checked on 2024-2025 (held out), so the pick is not fitted to the seasons it is scored on.
ALPHAS = (0.0, 0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.75, 1.0)


def logloss(frame, col, sigma):
    ll = n = 0.0
    for _, g in frame.groupby(["season", "week"]):
        if len(g) >= MINGRP:
            a, b, c, d = pair_scores(g, col, sigma)
            ll += a; n += c
    return ll / n


print("\nSHRUNK MATCHUP: pairwise log loss by alpha (pick on 2022-23, held-out check on 2024-25)")
grid = []
for v in ([x for x in VARIANTS if x != "none"]):
    for a in ALPHAS:
        col = f"g_{v}_{a}"
        Q[col] = Q["app"] * (1 + a * (Q["m_" + v] - 1))
        sigma = float((Q[col] - Q.fpts_active)[Q.season == first].std())
        pick = Q[Q.season.isin((2022, 2023))]
        hold = Q[Q.season.isin((2024, 2025))]
        grid.append({"variant": v, "alpha": a, "pick_ll": logloss(pick, col, sigma), "hold_ll": logloss(hold, col, sigma),
                     "hold_mae": (hold[col] - hold.fpts_active).abs().mean()})
G = pd.DataFrame(grid)
print(G.pivot(index="alpha", columns="variant", values="pick_ll").round(4).to_string())
print("held out 2024-25:")
print(G.pivot(index="alpha", columns="variant", values="hold_ll").round(4).to_string())
bp = G.loc[G.pick_ll.idxmin()]
print(f"\npicked on 2022-23: {bp.variant} alpha={bp.alpha}  ->  held-out 2024-25 log loss {bp.hold_ll:.4f} "
      f"(no matchup {G[(G.alpha == 0)].hold_ll.iloc[0]:.4f}, current full {G[(G.variant == 'current') & (G.alpha == 1.0)].hold_ll.iloc[0]:.4f})")

if POSN == "QB":
    k = defense.MATCHUP_STRENGTH.get("QB", 1.0)
    col = f"g_qb_rush_{k}"
    if col in Q.columns:
        sig = float((Q[col] - Q.fpts_active)[Q.season == first].std())
        allq = Q[Q.season > first]
        print(f"\nSHIPPED (qb_rush at strength {k}): 2022-25 log loss {logloss(allq, col, sig):.4f}, "
              f"MAE {(allq[col] - allq.fpts_active).abs().mean():.3f}  vs today's grading at full strength "
              f"{logloss(allq, 'p_current', float((Q['p_current'] - Q.fpts_active)[Q.season == first].std())):.4f}, "
              f"MAE {(allq['p_current'] - allq.fpts_active).abs().mean():.3f}")
