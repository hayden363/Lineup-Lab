"""RB / WR / TE matchup grading backtest (owner 2026-11-17: "apply to all the other positions... our own metrics, as
spot on as they can be").

Today every RB/WR/TE matchup metric reads a TEAM-wide defensive stat (yards per target allowed to everyone, yards per
carry allowed to everyone). This tests our own POSITION-SPECIFIC allowed stats, built from play-by-play with each
target/carry tagged by the receiving/rushing player's position (nflverse weekly roster):
    ypt_allowed_<P>       yards per target allowed to position P
    catch_allowed_<P>     catch rate allowed to P
    td_allowed_<P>        TD per target allowed to P
    yac_allowed_<P>       YAC per catch allowed to P
    tgt_pg_allowed_<P>    targets per game going to P against this defense (volume funnel)
    ypc_allowed_RB / rush_td_allowed_RB / touch_pg_allowed_RB   rushing allowed to RBs
each shrunk toward the league mean with SHRINK_* pseudo-observations (a few games are noisy).

Variants per position:  current (what ships), pos (position-specific efficiency stats), pos_vol (pos + the volume
funnel mapped onto the usage metrics), none. Then factor = 1 + alpha * (composite - 1), alpha picked on 2022-23 and
checked on held-out 2024-25, scored by pairwise log loss of "A outscores B" (the probability Start/Sit shows).
Run from the repo root: python analysis/pos_matchup_backtest.py WR   (or RB / TE)
"""
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from math import erf, sqrt

import numpy as np
import pandas as pd

from engine import data, defense, metrics, projmodel as PM
from engine.scoring import apply_scoring

POSN = sys.argv[1].upper() if len(sys.argv) > 1 else "WR"
TEST = range(2021, 2026)
TRAIN_FROM = 2017
MIN_WEEK = 4
MINGRP = 8
SHRINK_TGT, SHRINK_CAR, SHRINK_GAMES = 60.0, 60.0, 4.0
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)
VARIANTS = ("current", "pos", "pos_vol", "none")
_ncdf = np.vectorize(lambda z: 0.5 * (1 + erf(z / sqrt(2))))

# ---- the app's base projection, walk-forward (same as weekly_backtest.py) ----------------------------------------
frames = []
for s in range(TRAIN_FROM, 2026):
    wk = data.load_weekly(s)
    wk = wk[wk["position"].isin(("QB", "RB", "WR", "TE")) & (wk["week"] <= 18)].copy()
    wk["season"] = s
    wk, _ = apply_scoring(wk)
    frames.append(wk[[c for c in PM._COLS if c in wk.columns] + ["opponent_team"]])
df = pd.concat(frames, ignore_index=True)
df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)
opp_of = df.set_index(["player_id", "season", "week"])["opponent_team"]

parts = []
for s in TEST:
    rows = PM._training_rows(df[df.season <= s], PM._opportunity_values(df[df.season < s]))
    coef = PM.fit(rows[rows.season < s])
    t = rows[(rows.season == s) & (rows.position == POSN)].copy()
    c = coef[POSN]
    x = np.column_stack([np.ones(len(t))] + [t[f].to_numpy(float) for f in PM.FEATURES])
    t["raw"] = x @ c
    t["base"] = c[0] + c[1] * t["ppg"] + c[2] * t["ppg"] + c[3] * t["opp_ppg"] + c[4] * t["prior"]
    t["app"] = PM.cap_recency(t["raw"], t["base"])
    parts.append(t[["player_id", "season", "week", "fpts_active", "app"]])
Q = pd.concat(parts).dropna(subset=["app"])
Q = Q[Q.week >= MIN_WEEK].copy()
Q["opp"] = [opp_of.get((p, s, w)) for p, s, w in zip(Q.player_id, Q.season, Q.week)]
Q = Q.dropna(subset=["opp", "fpts_active"])
print(f"{POSN} player-weeks scored: {len(Q)}")


# ---- position-specific allowed stats ------------------------------------------------------------------------
def shrink(num, den, k, league):
    return (num + k * league) / (den + k)


def pos_profile(p, pos_of):
    out = pd.DataFrame(index=sorted(p.defteam.dropna().unique()))
    games = p.groupby("defteam")["week"].nunique()
    tg = p[(p.play_type == "pass") & (p.sack == 0) & p.receiver_player_id.notna()].copy()
    tg["rpos"] = tg.receiver_player_id.map(pos_of)
    for P in ("WR", "TE", "RB"):
        t = tg[tg.rpos == P]
        g = t.groupby("defteam")
        n = g.size().reindex(out.index).fillna(0)
        yds = g["yards_gained"].sum().reindex(out.index).fillna(0)
        cat = g["complete_pass"].sum().reindex(out.index).fillna(0)
        td = g["pass_touchdown"].sum().reindex(out.index).fillna(0)
        yac = t[t.complete_pass == 1].groupby("defteam")["yards_after_catch"].sum().reindex(out.index).fillna(0)
        L = lambda a, b: a.sum() / max(b.sum(), 1)
        out[f"ypt_allowed_{P}"] = shrink(yds, n, SHRINK_TGT, L(yds, n))
        out[f"catch_allowed_{P}"] = shrink(cat, n, SHRINK_TGT, L(cat, n))
        out[f"td_allowed_{P}"] = shrink(td, n, SHRINK_TGT, L(td, n))
        out[f"yac_allowed_{P}"] = shrink(yac, cat, SHRINK_TGT / 2, L(yac, cat))
        gm = games.reindex(out.index).fillna(0)
        out[f"tgt_pg_allowed_{P}"] = shrink(n, gm, SHRINK_GAMES, L(n, gm))
    ru = p[(p.play_type == "run") & p.rusher_player_id.notna()].copy()
    ru = ru[ru.rusher_player_id.map(pos_of) == "RB"]
    g = ru.groupby("defteam")
    n = g.size().reindex(out.index).fillna(0)
    yds = g["yards_gained"].sum().reindex(out.index).fillna(0)
    td = g["rush_touchdown"].sum().reindex(out.index).fillna(0)
    gm = games.reindex(out.index).fillna(0)
    L = lambda a, b: a.sum() / max(b.sum(), 1)
    out["ypc_allowed_RB"] = shrink(yds, n, SHRINK_CAR, L(yds, n))
    out["rush_td_allowed_RB"] = shrink(td, n, SHRINK_CAR, L(td, n))
    rb_t = out["tgt_pg_allowed_RB"] * 0 + 0  # placeholder for alignment
    touches = n + tg[tg.rpos == "RB"].groupby("defteam").size().reindex(out.index).fillna(0)
    out["touch_pg_allowed_RB"] = shrink(touches, gm, SHRINK_GAMES, L(touches, gm))
    return out


POS_MAP = {
    "WR": {"yards_per_target": "ypt_allowed_WR", "td_rate_targets": "td_allowed_WR", "catch_rate": "catch_allowed_WR",
           "yac_per_reception": "yac_allowed_WR"},
    "TE": {"yards_per_target": "ypt_allowed_TE", "td_rate_targets": "td_allowed_TE", "catch_rate": "catch_allowed_TE",
           "yac_per_reception": "yac_allowed_TE"},
    "RB": {"yards_per_carry": "ypc_allowed_RB", "td_rate": "rush_td_allowed_RB", "yards_per_target": "ypt_allowed_RB",
           "rushing_epa_per_carry": "ypc_allowed_RB"},
}
VOL_MAP = {"WR": {"target_share": "tgt_pg_allowed_WR", "wopr": "tgt_pg_allowed_WR", "air_yards_share": "tgt_pg_allowed_WR"},
           "TE": {"target_share": "tgt_pg_allowed_TE", "wopr": "tgt_pg_allowed_TE", "air_yards_share": "tgt_pg_allowed_TE"},
           "RB": {"touches_per_game": "touch_pg_allowed_RB", "target_share": "tgt_pg_allowed_RB"}}

cache = {}
for s in TEST:
    pbp = data.load_pbp(s)
    sched = data.load_schedule(s)
    w = data.load_weekly(s)
    pos_of = w.drop_duplicates("player_id", keep="last").set_index("player_id")["position"]
    try:
        ngs = {k: data.load_ngs(k, s) for k in ("passing", "rushing", "receiving")}
    except Exception:
        ngs = None
    for wk_ in sorted(Q[Q.season == s].week.unique()):
        p = pbp[pbp.week < wk_]
        prof = defense.build_defense_profile(p)
        if ngs is not None:
            try:
                n = {k: v[v.week < wk_] for k, v in ngs.items()}
                prof = prof.join(defense.build_ngs_defense_profile(n["passing"], n["rushing"], n["receiving"], sched), how="left")
            except Exception:
                pass
        prof = prof.join(defense.position_allowed(p, pos_of), how="left")   # the shipped engine code
        f, _ = defense.league_relative_factors(prof)
        cache[(s, int(wk_))] = f
    print(f"season {s} done")

W = metrics.WEIGHTS[POSN]
# the team-wide mapping that shipped before 2026-11-17, frozen here so "current" stays the old baseline
OLD_MAP = {
    "RB": {"yards_per_carry": "ypc_allowed", "td_rate": "rush_td_rate_allowed", "touches_per_game": None,
           "yards_per_target": "ypt_allowed", "target_share": None, "rushing_epa_per_carry": "rush_efficiency_allowed"},
    "WR": {"target_share": None, "yards_per_target": "ypt_allowed", "td_rate_targets": "pass_td_rate_allowed",
           "catch_rate": "sep_allowed", "air_yards_share": None, "wopr": None, "yac_per_reception": "yac_oe_allowed"},
}
OLD_MAP["TE"] = OLD_MAP["WR"]
BASE_MAP = OLD_MAP[POSN]


def composite(f, opp, variant):
    if variant == "none" or opp not in f.index:
        return 1.0
    m = dict(BASE_MAP)
    if variant in ("pos", "pos_vol"):
        m.update(POS_MAP[POSN])
    if variant == "pos_vol":
        m.update(VOL_MAP[POSN])
    tot = acc = 0.0
    for k, w in W.items():
        col = m.get(k)
        fac = float(f.loc[opp, col]) if col and col in f.columns and pd.notna(f.loc[opp, col]) else 1.0
        acc += abs(w) * (fac if w >= 0 else 2 - fac)
        tot += abs(w)
    return acc / tot if tot else 1.0


for v in VARIANTS:
    Q["m_" + v] = [composite(cache[(s, int(w))], o, v) for s, w, o in zip(Q.season, Q.week, Q.opp)]


def pair_ll(frame, col, sigma):
    ll = n = 0.0
    for _, g in frame.groupby(["season", "week"]):
        if len(g) < MINGRP:
            continue
        a, y = g[col].to_numpy(), g.fpts_active.to_numpy()
        iu = np.triu_indices(len(g), 1)
        d, dy = (a[:, None] - a[None, :])[iu], (y[:, None] - y[None, :])[iu]
        k = dy != 0
        pr = np.clip(_ncdf(d[k] / (sigma * np.sqrt(2))), 1e-6, 1 - 1e-6)
        o = (dy[k] > 0).astype(float)
        ll += -(o * np.log(pr) + (1 - o) * np.log(1 - pr)).sum()
        n += k.sum()
    return ll / n


grid = []
for v in VARIANTS:
    for a in (ALPHAS if v != "none" else (0.0,)):
        col = f"g_{v}_{a}"
        Q[col] = Q.app * (1 + a * (Q["m_" + v] - 1))
        sig = float((Q[col] - Q.fpts_active)[Q.season == 2021].std())
        pick, hold = Q[Q.season.isin((2022, 2023))], Q[Q.season.isin((2024, 2025))]
        grid.append({"variant": v, "alpha": a, "pick_ll": pair_ll(pick, col, sig), "hold_ll": pair_ll(hold, col, sig),
                     "hold_mae": (hold[col] - hold.fpts_active).abs().mean(), "mult_sd": Q["m_" + v].std() * a})
G = pd.DataFrame(grid)
pd.set_option("display.width", 200)
print(G.round(4).to_string(index=False))
bp = G.loc[G.pick_ll.idxmin()]
none_h = G[G.variant == "none"].hold_ll.iloc[0]
cur_h = G[(G.variant == "current") & (G.alpha == 1.0)].hold_ll.iloc[0]
print(f"\n{POSN}: picked on 2022-23 -> {bp.variant} alpha={bp.alpha}; held-out 2024-25 log loss {bp.hold_ll:.4f} "
      f"(no matchup {none_h:.4f}, today {cur_h:.4f})")
