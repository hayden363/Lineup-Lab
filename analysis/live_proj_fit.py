"""In-game ("live") projection model: fit + walk-forward validation.

Live final projection = points scored so far + rest-of-game (ROG) expected points.
ROG = pregame projection x f(position, game clock, score margin from the player's team's side), where f is a
table learned from real play-by-play (2023-2026), monotone in time left, shrunk toward the position's time-only curve
where a score-margin bin is thin. Nothing is hand-set: the bins only differ from the time-only curve to the extent the
training data says so.

Data: data_cache/pbp_<yr>.parquet (score_differential, ids, yards, TDs) joined row-for-row with
data_cache/stats_pbp_*_<yr>.parquet (game_id, half_seconds_remaining, down) -- the first has no clock and no game id,
the second no score. 2026: the two files are row-aligned only for weeks 1-7 (the stats copy is a stale snapshot, week 8
partial), so the 2026 held-out set is weeks 1-7.
Not in the cached pbp (so not recoverable per play): fumbles lost. Two-point tries are inferred (down missing, ball
reached the end zone). Fumbles lost come from the weekly stats and are spread evenly over the game clock inside
points_so_far (their true timing is unknown); the final is the weekly stats line.

Split: fit 2023+2024, tune knobs on 2025, report 2026 (never tuned on).
Run from the repo root:  python analysis/live_proj_fit.py   (writes engine/live_proj_params.json and
analysis/live_proj_results.txt)"""
import io
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
import numpy as np
import pandas as pd

from engine import data, projmodel as PM
from engine.scoring import apply_scoring

POS = ("QB", "RB", "WR", "TE")
SEASONS = (2023, 2024, 2025, 2026)
CKPTS = list(range(3600, -1, -300))                       # seconds left at each snapshot
KEY = {3600: "kickoff", 2700: "end Q1", 1800: "halftime", 900: "end Q3", 300: "5:00 left Q4"}
DIFF_CUTS = [-13.5, -7.5, -3.5, 3.5, 8.5, 13.5]           # team margin bins
DIFF_LABELS = ["trail 14+", "trail 8-13", "trail 4-7", "within 3", "lead 4-8", "lead 9-13", "lead 14+"]
CACHE = "data_cache/live_proj"
MAX_2026_WEEK = 7


def diff_bin(d):
    """Index 0..6 of the team margin (his team minus opponent)."""
    return np.searchsorted(np.array(DIFF_CUTS), np.asarray(d, float), side="right")


# ---------------------------------------------------------------------------------------------------------------
# 1. per-play fantasy points
# ---------------------------------------------------------------------------------------------------------------
def load_plays(season):
    a = pd.read_parquet(f"data_cache/pbp_{season}.parquet")
    b = pd.read_parquet(f"data_cache/stats_pbp_5d2a397e_{season}.parquet")
    if season == 2026:
        a = a[a.week <= MAX_2026_WEEK].reset_index(drop=True)
        b = b[b.week <= MAX_2026_WEEK].reset_index(drop=True)
    assert len(a) == len(b) and (a.week.values == b.week.values).all(), "pbp / stats_pbp not row-aligned"
    assert (a.posteam.fillna("") == b.posteam.fillna("")).all(), "posteam mismatch"
    for c in ("passer_player_id", "rusher_player_id", "receiver_player_id", "yards_gained", "complete_pass",
              "pass_touchdown", "rush_touchdown", "interception", "sack"):
        assert (a[c].fillna(-1).values == b[c].fillna(-1).values).all(), c
    b["sd"] = a["score_differential"].values
    b = b[b.season_type == "REG"].copy()
    b = b.sort_values(["game_id", "play_id"], kind="stable").reset_index(drop=True)
    # clock: half_seconds_remaining resets upward at the half and again in overtime
    h = b.groupby("game_id")["half_seconds_remaining"].ffill()
    prev = h.groupby(b["game_id"]).shift(1)
    reset = ((h - prev) > 100).astype(int)
    seg = reset.groupby(b["game_id"]).cumsum()
    b["gsr"] = np.where(seg == 0, 1800 + h, np.where(seg == 1, h, -1.0))   # overtime plays sit after regulation
    parts = b["game_id"].str.split("_")
    b["away"], b["home"] = parts.str[2], parts.str[3]
    hd = np.where(b.posteam == b.home, b.sd, np.where(b.posteam == b.away, -b.sd, np.nan))
    b["home_diff"] = pd.Series(hd, index=b.index).groupby(b["game_id"]).ffill().fillna(0.0)   # before the first scoring state: 0-0
    return b


def event_points(b):
    """One row per (play, player): PPR points (pass yd .04, pass TD 4, INT -2, rush/rec yd .1, TD 6, rec 1, 2-pt 2)."""
    pr = b[b.play_type.isin(["pass", "run"]) & (b.sack != 1)]
    two = pr.down.isna()                                           # a two-point try is the only scrimmage play with no down
    good = two & (pr.yards_gained >= pr.yardline_100)
    td = lambda c: pr[c].fillna(0)
    yds = pr.yards_gained.fillna(0)
    comp = pr.complete_pass == 1
    out = []
    m = pr.passer_player_id.notna() & (pr.play_type == "pass")
    pts = np.where(two, 0.0, 0.04 * yds * comp + 4 * td("pass_touchdown") - 2 * td("interception")) + 2 * (good & comp)
    out.append(pd.DataFrame({"game_id": pr.game_id, "gsr": pr.gsr, "player_id": pr.passer_player_id,
                             "team": pr.posteam, "pts": pts})[m])
    m = pr.receiver_player_id.notna() & comp
    pts = np.where(two, 0.0, 1 + 0.1 * yds + 6 * td("pass_touchdown")) + 2 * good
    out.append(pd.DataFrame({"game_id": pr.game_id, "gsr": pr.gsr, "player_id": pr.receiver_player_id,
                             "team": pr.posteam, "pts": pts})[m])
    m = pr.rusher_player_id.notna() & (pr.play_type == "run")
    pts = np.where(two, 0.0, 0.1 * yds + 6 * td("rush_touchdown")) + 2 * good
    kn = b[(b.play_type == "qb_kneel") & b.rusher_player_id.notna()]       # a kneel-down is a (negative) rush in the stats line
    kneel = pd.DataFrame({"game_id": kn.game_id, "gsr": kn.gsr, "player_id": kn.rusher_player_id, "team": kn.posteam,
                          "pts": 0.1 * kn.yards_gained.fillna(0)})
    out.append(pd.DataFrame({"game_id": pr.game_id, "gsr": pr.gsr, "player_id": pr.rusher_player_id,
                             "team": pr.posteam, "pts": pts})[m])
    out.append(kneel)
    return pd.concat(out, ignore_index=True)


def load_weekly_reg(season):
    w = data.load_weekly(season)
    if "season_type" in w.columns:
        w = w[w.season_type == "REG"]
    w = w[w.week <= 18].copy()
    w["season"] = season
    return w


# ---------------------------------------------------------------------------------------------------------------
# 2. snapshots
# ---------------------------------------------------------------------------------------------------------------
def build_snapshots(season, report):
    b = load_plays(season)
    ev = event_points(b)
    wk = load_weekly_reg(season)
    wk = wk[wk.position.isin(POS)]
    if season == 2026:
        wk = wk[wk.week <= MAX_2026_WEEK]
    wk = wk[["player_id", "position", "season", "week", "game_id", "recent_team", "fantasy_points_ppr",
             "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].copy()
    wk["fum_pts"] = -2.0 * wk[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
    # step-1 check: pbp points (+ weekly fumbles) vs the weekly stats line
    tot = ev.groupby(["game_id", "player_id"]).pts.sum().rename("pbp_pts").reset_index()
    g = wk.merge(tot, on=["game_id", "player_id"], how="left")
    g["pbp_pts"] = g.pbp_pts.fillna(0.0)
    g["err_raw"] = (g.pbp_pts - g.fantasy_points_ppr).abs()
    g["err_fum"] = (g.pbp_pts + g.fum_pts - g.fantasy_points_ppr).abs()
    report.append(g[["season", "position", "fantasy_points_ppr", "pbp_pts", "fum_pts", "err_raw", "err_fum"]])
    # team of each player-game, for the score margin from his side
    teams = ev.groupby(["game_id", "player_id"]).team.first().rename("team").reset_index()
    g = g.merge(teams, on=["game_id", "player_id"], how="left")
    g["team"] = g.team.fillna(g.recent_team)
    gp = g.game_id.str.split("_")
    g["home"], g["away"] = gp.str[3], gp.str[2]
    bad = ~((g.team == g.home) | (g.team == g.away))
    n_bad = int(bad.sum())
    g = g[~bad].copy()
    g["is_home"] = (g.team == g.home).astype(int)
    plays = b[["game_id", "gsr", "home_diff"]].dropna(subset=["gsr"])
    sched = data.load_schedule(season)
    sched = sched[sched.game_type == "REG"].set_index("game_id")
    fin = (sched.home_score - sched.away_score).to_dict()
    rows = []
    base = g[["player_id", "game_id", "position", "season", "week", "is_home", "fantasy_points_ppr", "fum_pts"]]
    for t in CKPTS:
        sf = ev[ev.gsr > t].groupby(["game_id", "player_id"]).pts.sum().rename("so_far").reset_index()
        st = plays[plays.gsr <= t].drop_duplicates("game_id", keep="first")[["game_id", "home_diff"]]
        s = base.merge(sf, on=["game_id", "player_id"], how="left").merge(st, on="game_id", how="left")
        s["so_far"] = s.so_far.fillna(0.0) + s.fum_pts * (1.0 - t / 3600.0)      # fumble timing unknown: spread evenly
        s["home_diff"] = s.home_diff.fillna(s.game_id.map(fin))
        s["diff"] = np.where(s.is_home == 1, s.home_diff, -s.home_diff)
        s["t"] = t
        rows.append(s)
    snap = pd.concat(rows, ignore_index=True).rename(columns={"fantasy_points_ppr": "final"})
    snap["rog"] = snap.final - snap.so_far
    return snap.drop(columns=["fum_pts", "home_diff", "is_home"]), n_bad


# ---------------------------------------------------------------------------------------------------------------
# 3. walk-forward pregame projections (the app's own projmodel, as analysis/weekly_backtest.py does it)
# ---------------------------------------------------------------------------------------------------------------
def pregame_table():
    frames = []
    for s in range(2017, 2027):
        wk = load_weekly_reg(s)
        wk = wk[wk.position.isin(POS)]
        wk, _ = apply_scoring(wk)
        frames.append(wk[[c for c in PM._COLS if c in wk.columns]])
    df = pd.concat(frames, ignore_index=True)
    df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
    df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)
    out = []
    for s in SEASONS:
        hist = df[df.season < s]
        ppo = PM._opportunity_values(hist)
        rows = PM._training_rows(df[df.season <= s], ppo)
        coef = PM.fit(rows[rows.season < s])
        t = rows[rows.season == s].copy()
        t["raw"] = np.nan
        t["base"] = np.nan
        for pos, c in coef.items():
            i = t.position == pos
            x = np.column_stack([np.ones(i.sum())] + [t.loc[i, f].to_numpy(float) for f in PM.FEATURES])
            t.loc[i, "raw"] = x @ c
            t.loc[i, "base"] = c[0] + c[1] * t.loc[i, "ppg"] + c[2] * t.loc[i, "ppg"] + c[3] * t.loc[i, "opp_ppg"] + c[4] * t.loc[i, "prior"]
        t["pregame"] = PM.cap_recency(t["raw"], t["base"])
        out.append(t[["player_id", "season", "week", "pregame"]].dropna().assign(src="projmodel"))
    app = pd.concat(out)
    # fallback for games projmodel skips (first 3 games of a season): season-to-date average (2+ games), else last
    # season's average (6+ games)
    d = df.copy()
    keys = ["player_id", "season"]
    d["n"] = d.groupby(keys).cumcount()
    d["std"] = d.groupby(keys)["fpts_active"].transform(lambda s: s.shift(1).expanding().mean())
    per = d.groupby(keys)["fpts_active"].agg(["mean", "count"])
    per = per[per["count"] >= PM.MIN_PRIOR_GAMES]["mean"]
    d["prior"] = per.reindex(pd.MultiIndex.from_arrays([d.player_id, d.season - 1])).to_numpy(dtype=float)
    d["pregame"] = np.where(d.n >= 2, d["std"], d["prior"])
    d["src"] = np.where(d.n >= 2, "season-to-date", "last-season")
    fb = d[d.season.isin(SEASONS)][["player_id", "season", "week", "pregame", "src"]].dropna()
    return pd.concat([app, fb]).drop_duplicates(["player_id", "season", "week"], keep="first")   # projmodel wins


# ---------------------------------------------------------------------------------------------------------------
# 4/5. naive baseline and the fitted table
# ---------------------------------------------------------------------------------------------------------------
def pav_nondecreasing(y, w):
    """Weighted pool-adjacent-violators: the closest non-decreasing sequence to y."""
    blocks = []
    for yi, wi in zip(y, w):
        blocks.append([yi * wi, wi, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, ww, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += ww
            blocks[-1][2] += n
    out = []
    for s, ww, n in blocks:
        out += [s / ww] * n
    return np.array(out)


def fit_table(snap, k):
    """f[pos]['bins'][bin][i] = expected ROG as a fraction of the pregame projection at clock knot ts[i].

    Time-only curve per position c(t) = sum(ROG) / sum(pregame) at that clock time. A margin bin's value is
    (sum ROG + k x c(t)) / (sum pregame + k): the bin's own ratio, pulled toward c(t) with weight k pregame-projection
    points. Non-decreasing in time left within each bin (weighted pool-adjacent-violators)."""
    f = {}
    for pos in POS:
        sp = snap[(snap.position == pos) & (snap.t > 0)]
        curve = {t: g.rog.sum() / g.pregame.sum() for t, g in sp.groupby("t")}
        ts = sorted(curve)
        tabs = {}
        for bi in range(len(DIFF_LABELS)):
            y, w = [], []
            for t in ts:
                g = sp[(sp.t == t) & (sp.dbin == bi)]
                den = g.pregame.sum() + k
                y.append((g.rog.sum() + k * curve[t]) / den)
                w.append(den)
            tabs[bi] = pav_nondecreasing(y, w)
        f[pos] = {"ts": ts, "bins": tabs}
    return f


def predict_rog(snap, f, mode="model"):
    """ROG for every snapshot row. 'naive': pregame x t/3600. 'model': table lookup, linear in time between knots."""
    if mode == "naive":
        return snap.pregame.to_numpy() * snap.t.to_numpy() / 3600.0
    out = np.zeros(len(snap))
    for pos in POS:
        i = (snap.position == pos).to_numpy()
        ts = np.concatenate([[0.0], np.array(f[pos]["ts"], float)])
        tt = snap.t.to_numpy()[i].astype(float)
        db = snap.dbin.to_numpy()[i]
        val = np.zeros(i.sum())
        for bi in range(len(DIFF_LABELS)):
            j = db == bi
            val[j] = np.interp(tt[j], ts, np.concatenate([[0.0], np.asarray(f[pos]["bins"][bi])]))
        out[i] = snap.pregame.to_numpy()[i] * val
    return out


def err(snap, rog):
    """predicted final - actual final, never predicting below points already scored."""
    return snap.so_far.to_numpy() + np.maximum(rog, 0.0) - snap.final.to_numpy()


def mae_table(snap, preds):
    rows = []
    for t, name in KEY.items():
        for pos in ("ALL",) + POS:
            m = ((snap.t == t) if pos == "ALL" else ((snap.t == t) & (snap.position == pos))).to_numpy()
            r = {"checkpoint": name, "pos": pos, "n": int(m.sum())}
            for k, e in preds.items():
                r[k + "_MAE"] = float(np.abs(e[m]).mean())
                r[k + "_bias"] = float(e[m].mean())
            rows.append(r)
    return pd.DataFrame(rows)


def usage_z(d):
    """How far his points so far run ahead of (+) or behind (-) pregame x elapsed share, as a share of the pregame
    projection, clipped to [-1, 1]. Non-decreasing in time left at fixed points so far."""
    p, t = d.pregame.to_numpy(), d.t.to_numpy() / 3600.0
    return np.clip((d.so_far.to_numpy() - p * (1 - t)) / p, -1.0, 1.0)


def fit_beta(trp, f):
    """Per position beta in ROG = table x (1 + beta x z): least squares of (ROG - table) on table x z, beta kept in [0, 1]
    so the adjustment can never flip sign or make ROG negative."""
    base = predict_rog(trp, f)
    x = base * usage_z(trp)
    y = trp.rog.to_numpy() - base
    out = {}
    for pos in POS:
        i = (trp.position == pos).to_numpy()
        out[pos] = float(np.clip((x[i] * y[i]).sum() / (x[i] ** 2).sum(), 0.0, 1.0))
    return out


def apply_usage(d, base, beta):
    return base * (1.0 + d.position.map(beta).to_numpy() * usage_z(d))


def main():
    buf = io.StringIO()

    def P(*a):
        s = " ".join(str(x) for x in a)
        print(s)
        buf.write(s + "\n")

    rep, parts, bad = [], [], {}
    for s in SEASONS:
        sn_, nb = build_snapshots(s, rep)
        parts.append(sn_)
        bad[s] = nb
    snap = pd.concat(parts, ignore_index=True)
    rep = pd.concat(rep, ignore_index=True)
    preg = pregame_table()

    P("LIVE PROJECTION FIT  (analysis/live_proj_fit.py)")
    P("=" * 78)
    P("\n1. PLAY-BY-PLAY POINTS vs WEEKLY STATS LINE (fantasy_points_ppr), QB/RB/WR/TE regular-season player-games")
    P("   raw = points from the cached pbp only; +fum = plus the weekly fumbles-lost (not in the cached pbp)")
    for s, g in rep.groupby("season"):
        P(f"   {s}: n={len(g)}  within 0.05 pts: raw {(g.err_raw <= .05).mean():.1%}, +fum {(g.err_fum <= .05).mean():.1%};"
          f"  within 1.0: raw {(g.err_raw <= 1).mean():.1%}, +fum {(g.err_fum <= 1).mean():.1%};  "
          f"mean abs err raw {g.err_raw.mean():.3f}, +fum {g.err_fum.mean():.3f}")
    for pos, g in rep.groupby("position"):
        P(f"   {pos}: n={len(g)}  within 0.05 +fum {(g.err_fum <= .05).mean():.1%}, mean abs err +fum {g.err_fum.mean():.3f}, "
          f"mean fumble pts {g.fum_pts.mean():+.3f}")
    P(f"   player-games dropped (his team not in the game): {bad}")

    sn = snap.merge(preg, on=["player_id", "season", "week"], how="left")
    pg = sn.drop_duplicates(["player_id", "season", "week"])
    P("\n2. PREGAME PROJECTION COVERAGE (player-games with a pregame number; others excluded)")
    for s, g in pg.groupby("season"):
        P(f"   {s}: {len(g)} player-games; with pregame {g.pregame.notna().sum()} "
          f"(projmodel {(g.src == 'projmodel').sum()}, season-to-date {(g.src == 'season-to-date').sum()}, "
          f"last-season {(g.src == 'last-season').sum()}); excluded (no pregame) {g.pregame.isna().sum()}")
    sn = sn.dropna(subset=["pregame"])
    sn = sn[sn.pregame > 0.0].copy()
    sn["dbin"] = diff_bin(sn["diff"])
    sn = sn.reset_index(drop=True)
    os.makedirs(CACHE, exist_ok=True)
    sn.to_parquet(f"{CACHE}/snapshots.parquet")
    P(f"   kept {sn.drop_duplicates(['player_id', 'season', 'week']).shape[0]} player-games with pregame > 0 "
      f"({len(sn)} snapshots)")

    tr = sn[sn.season.isin([2023, 2024])]
    va = sn[(sn.season == 2025) & (sn.t > 0)]
    te = sn[sn.season == 2026]

    P("\n3. SHRINKAGE k (pregame-projection points) CHOSEN ON 2025 -- fit on 2023+2024")
    res_k = {}
    for k in (0, 5, 15, 40, 100, 300, 1000, 10 ** 6):
        res_k[k] = np.abs(err(va, predict_rog(va, fit_table(tr, k)))).mean()
        P(f"   k={k:>8}: 2025 MAE over the 12 in-game checkpoints {res_k[k]:.4f}")
    # rule fixed before looking at 2026: the most shrinkage whose 2025 MAE is within 0.001 of the best
    k_best = max(k for k, v in res_k.items() if v <= min(res_k.values()) + 0.001)
    P(f"   -> k = {k_best}: the largest k within 0.001 MAE of the best (k=1000000 is the time-only curve, no margin effect)")
    P(f"   2025 naive MAE over the same checkpoints: {np.abs(err(va, predict_rog(va, None, 'naive'))).mean():.4f}")

    f_tr = fit_table(tr, k_best)
    trp = tr[tr.t > 0]
    beta = fit_beta(trp, f_tr)
    r0 = predict_rog(va, f_tr)
    mae_no = np.abs(err(va, r0)).mean()
    mae_u = np.abs(err(va, apply_usage(va, r0, beta))).mean()
    use_usage = bool(mae_u < mae_no - 0.002)
    P("\n4. OPTIONAL IN-GAME USAGE TERM: table x (1 + beta x z), z = clip((points so far - pregame x elapsed share) / pregame, -1, 1)")
    P("   betas fit on 2023+2024: " + ", ".join(f"{p} {b:+.3f}" for p, b in beta.items()))
    P(f"   2025 MAE without {mae_no:.4f}, with {mae_u:.4f}  ->  "
      f"{'INCLUDED' if use_usage else 'NOT included (does not improve held-out error)'}")

    trva = sn[sn.season.isin([2023, 2024, 2025])]
    f_fin = fit_table(trva, k_best)
    f_time = fit_table(trva, 10 ** 9)          # time-only curve (runtime uses it when no score margin is known)
    if use_usage:
        beta = fit_beta(trva[trva.t > 0], f_fin)
    tep = te.reset_index(drop=True)
    rog_m = predict_rog(tep, f_fin)
    if use_usage:
        rog_m = apply_usage(tep, rog_m, beta)
    preds = {"naive": err(tep, predict_rog(tep, None, "naive")), "model": err(tep, rog_m)}
    nte = tep.drop_duplicates(["player_id", "season", "week"]).shape[0]
    P(f"\n5. FINAL FIT on 2023-2025 (k={k_best}{', usage term' if use_usage else ''}); REPORT ON 2026 weeks 1-{MAX_2026_WEEK} "
      f"({nte} player-games, never tuned on)")
    T = mae_table(tep, preds)
    P("   MAE / bias of predicted FINAL points vs actual final (points; bias = predicted - actual)")
    P(f"   {'checkpoint':<14}{'pos':<5}{'n':>6}{'naive MAE':>11}{'model MAE':>11}{'naive bias':>12}{'model bias':>12}")
    for _, r in T.iterrows():
        P(f"   {r.checkpoint:<14}{r.pos:<5}{r.n:>6}{r.naive_MAE:>11.3f}{r.model_MAE:>11.3f}{r.naive_bias:>+12.3f}{r.model_bias:>+12.3f}")
    keym = tep.t.isin(list(KEY)).to_numpy()
    allm = (tep.t > 0).to_numpy()
    mn, mm = np.abs(preds["naive"][keym]).mean(), np.abs(preds["model"][keym]).mean()
    P(f"\n   OVERALL 2026 MAE, five reported checkpoints pooled: naive {mn:.4f}  model {mm:.4f}")
    P(f"   OVERALL 2026 MAE, all 12 in-game checkpoints (3600..300): naive {np.abs(preds['naive'][allm]).mean():.4f}  "
      f"model {np.abs(preds['model'][allm]).mean():.4f}")
    pgid = (tep.player_id + "|" + tep.season.astype(str) + "|" + tep.week.astype(str)).to_numpy()
    d = np.abs(preds["model"]) - np.abs(preds["naive"])
    dd = pd.Series(d[keym]).groupby(pgid[keym]).mean()
    bs = [dd.sample(len(dd), replace=True, random_state=i).mean() for i in range(300)]
    P(f"   model minus naive MAE, paired by player-game (five checkpoints): {dd.mean():+.4f}, "
      f"95% bootstrap interval [{np.percentile(bs, 2.5):+.4f}, {np.percentile(bs, 97.5):+.4f}]")
    ship = bool(mm < mn)
    P(f"\n   SHIP MODEL? {'YES' if ship else 'NO'}: the model {'beats' if ship else 'does not beat'} naive on 2026 overall MAE")

    P("\n6. WHAT THE TABLE LEARNED (fit on 2023-2025): expected rest-of-game points as a share of the pregame projection")
    for t in (2700, 1800, 900, 300):
        P(f"\n   {KEY[t]}  (naive share = {t / 3600:.3f})")
        P(f"   {'':<5}" + "".join(f"{l:>12}" for l in DIFF_LABELS))
        for pos in POS:
            i = f_fin[pos]["ts"].index(t)
            P(f"   {pos:<5}" + "".join(f"{f_fin[pos]['bins'][bi][i]:>12.3f}" for bi in range(len(DIFF_LABELS))))
    iw = f_fin["WR"]["ts"].index(300)
    P("\n   WR, 5:00 left: share of pregame still to come, by margin (naive 0.083): " +
      ", ".join(f"{lab} {f_fin['WR']['bins'][bi][iw]:.3f}" for bi, lab in enumerate(DIFF_LABELS)))
    ir = f_fin["RB"]["ts"].index(900)
    P("   RB, 15:00 left (end Q3): by margin (naive 0.250): " +
      ", ".join(f"{lab} {f_fin['RB']['bins'][bi][ir]:.3f}" for bi, lab in enumerate(DIFF_LABELS)))
    P("   Sample sizes behind those bins (player-game snapshots, 2023-2025): " +
      ", ".join(f"{lab} {int(((trva.dbin == bi) & (trva.t == 300)).sum())}" for bi, lab in enumerate(DIFF_LABELS)) + "  (5:00 left)")

    params = {
        "version": 1, "fit_seasons": [2023, 2024, 2025], "k": k_best, "ship_model": ship,
        "ts": [int(t) for t in f_fin["QB"]["ts"]], "diff_cuts": DIFF_CUTS, "diff_labels": DIFF_LABELS,
        "curve": {pos: [round(float(v), 5) for v in f_time[pos]["bins"][0]] for pos in POS},
        "usage_beta": ({p: round(b, 5) for p, b in beta.items()} if use_usage else None),
        "f": {pos: [[round(float(v), 5) for v in f_fin[pos]["bins"][bi]] for bi in range(len(DIFF_LABELS))] for pos in POS},
    }
    with open("engine/live_proj_params.json", "w") as fh:
        json.dump(params, fh, separators=(",", ":"))
    P(f"\n   wrote engine/live_proj_params.json (ship_model={ship})")
    with open("analysis/live_proj_results.txt", "w") as fh:
        fh.write(buf.getvalue())


if __name__ == "__main__":
    main()
