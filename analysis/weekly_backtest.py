"""Weekly start/sit backtest: the app's per-game projection model vs FantasyPros weekly consensus, judged on the
player's REAL PPR points that week.

The app side is engine/projmodel.py's own regression (season average, last-4 average, opportunity, last season's
average) with its recency cap, fitted STRICTLY on seasons before the test season, using only games before each week.
Not included: the matchup / weather / injury layers the live app adds on top (they are not reconstructible for past
weeks), so this tests the base projection, not every adjustment.
Run from the repo root: python analysis/weekly_backtest.py <train_from> <test_from>"""
import sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, ".")
import numpy as np, pandas as pd
from engine import data, projmodel as PM
from engine.scoring import apply_scoring

SCRATCH = "data_cache"   # ecr_hist/db_fpecr.parquet: DynastyProcess archive https://github.com/dynastyprocess/data (db_fpecr.parquet)
POS = ("QB", "RB", "WR", "TE")
TEST_SEASONS = range(int(sys.argv[2]) if len(sys.argv) > 2 else 2021, 2026)
TRAIN_FROM = int(sys.argv[1]) if len(sys.argv) > 1 else 2017      # first season used for fitting (2023 = what the app ships with)

# ---- weekly actuals, scored PPR -------------------------------------------------------------
frames = []
for s in range(TRAIN_FROM, 2026):
    wk = data.load_weekly(s)
    wk = wk[wk["position"].isin(POS) & (wk["week"] <= 18)].copy()
    wk["season"] = s
    wk, _ = apply_scoring(wk)
    frames.append(wk[[c for c in PM._COLS if c in wk.columns] + ["player_display_name"]])
df = pd.concat(frames, ignore_index=True)
df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0)
df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)

# ---- weekly consensus -----------------------------------------------------------------------
ecr = pd.read_parquet(SCRATCH + "/ecr_hist/db_fpecr.parquet",
                      columns=["page_type", "id", "pos", "ecr", "scrape_date"])
ecr = ecr[ecr.page_type.isin(["weekly-qb", "weekly-rb", "weekly-wr", "weekly-te"])].copy()
ecr["d"] = pd.to_datetime(ecr.scrape_date)
xw = pd.read_parquet("data_cache/id_crosswalk.parquet", columns=["fantasypros_id", "gsis_id"]).dropna()
xw["fantasypros_id"] = xw.fantasypros_id.astype(float).astype(int).astype(str)
ecr["player_id"] = ecr["id"].astype(str).map(dict(zip(xw.fantasypros_id, xw.gsis_id)))
ecr = ecr.dropna(subset=["player_id"])


def week_of_snapshot(season):
    """{scrape date: nfl week}: the week whose games run from 4 days before its first game to its last game contains
    the date; with two snapshots in one week (Thanksgiving) keep the earlier."""
    sch = data.load_schedule(season)
    sch = sch[sch["game_type"] == "REG"]
    g = sch.groupby("week")["gameday"].agg(["min", "max"]).apply(pd.to_datetime)
    out = {}
    for d in sorted(ecr[ecr.d.dt.year == season].d.unique()):
        d = pd.Timestamp(d)
        for w, r in g.iterrows():
            if r["min"] - pd.Timedelta(days=4) <= d <= r["max"] and w not in out.values():
                out[d] = int(w)
                break
    return out


# ---- walk-forward app projections -------------------------------------------------------------
rows_all = []
for s in TEST_SEASONS:
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
    t["app"] = PM.cap_recency(t["raw"], t["base"])
    t["season_ppg"] = t["ppg"]
    t["last4"] = t["l4"]
    rows_all.append(t[["player_id", "position", "season", "week", "fpts_active", "app", "season_ppg", "last4"]])
app = pd.concat(rows_all).dropna(subset=["app"])

# ---- join and score ----------------------------------------------------------------------------
parts = []
for s in TEST_SEASONS:
    wk_map = week_of_snapshot(s)
    e = ecr[ecr.d.dt.year == s].copy()
    e["week"] = e.d.map(wk_map)
    e = e.dropna(subset=["week"]).copy()
    e["week"] = e["week"].astype(int)
    e = e.rename(columns={"ecr": "ecr_rank"})[["player_id", "week", "pos", "ecr_rank"]]
    e = e.drop_duplicates(["player_id", "week"])
    j = app[app.season == s].merge(e, on=["player_id", "week"], how="inner")
    j = j[j.position == j.pos]
    parts.append(j)
J = pd.concat(parts)
TOPN = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
METHODS = {"ecr": lambda g: -g.ecr_rank, "app": lambda g: g.app, "season_ppg": lambda g: g.season_ppg, "last4": lambda g: g.last4,
           "blend70": lambda g: 0.7 * (-g.ecr_rank).rank() + 0.3 * g.app.rank(),
           "blend50": lambda g: 0.5 * (-g.ecr_rank).rank() + 0.5 * g.app.rank()}

res = []
pair = {"agree": 0, "disagree": 0, "ecr_right": 0, "app_right": 0}
pair_by = {p: dict(disagree=0, ecr_right=0, app_right=0) for p in POS}
for (s, w, pos), g in J.groupby(["season", "week", "position"]):
    if len(g) < 12:
        continue
    y = g.fpts_active
    r = {"season": s, "week": w, "pos": pos, "n": len(g)}
    for k, fn in METHODS.items():
        sc = fn(g)
        r[k + "_rho"] = sc.rank().corr(y.rank())
        n = TOPN[pos]
        r[k + "_top"] = len(set(sc.nlargest(n).index) & set(y.nlargest(n).index)) / n
    res.append(r)
    # head to head on the pairs where the two methods disagree about who is better
    e_s, a_s, yy = (-g.ecr_rank).to_numpy(), g.app.to_numpy(), y.to_numpy()
    de = np.sign(e_s[:, None] - e_s[None, :])
    da = np.sign(a_s[:, None] - a_s[None, :])
    dy = np.sign(yy[:, None] - yy[None, :])
    iu = np.triu_indices(len(g), 1)
    de, da, dy = de[iu], da[iu], dy[iu]
    m = (de != 0) & (da != 0) & (de != da) & (dy != 0)
    pair_by[pos]["disagree"] += int(m.sum())
    pair_by[pos]["ecr_right"] += int((de[m] == dy[m]).sum())
    pair_by[pos]["app_right"] += int((da[m] == dy[m]).sum())

R = pd.DataFrame(res)
K = list(METHODS)
print(f"training seasons from {TRAIN_FROM}; test seasons {min(TEST_SEASONS)}-{max(TEST_SEASONS)}; "
      f"{len(R)} season-week-position groups, {int(R.n.sum())} player-weeks")
print("\nMEAN WEEKLY RANK CORRELATION with real points")
print(R.groupby("pos")[[k + "_rho" for k in K]].mean().round(3).to_string())
print("ALL", {k: round(R[k + "_rho"].mean(), 3) for k in K})
print("\nTOP-N HIT RATE (share of the real top-N players in the method's top-N)")
print(R.groupby("pos")[[k + "_top" for k in K]].mean().round(3).to_string())
print("ALL", {k: round(R[k + "_top"].mean(), 3) for k in K})
print("\nBY SEASON (all positions)")
print(R.groupby("season")[[k + "_rho" for k in K]].mean().round(3).to_string())
print("\nHEAD TO HEAD on pairs where ECR and the app disagree about who is better")
tot = dict(disagree=0, ecr_right=0, app_right=0)
for p in POS:
    d = pair_by[p]
    print(f"  {p}: {d['disagree']} pairs, ECR right {d['ecr_right']/max(d['disagree'],1):.3f}, app right {d['app_right']/max(d['disagree'],1):.3f}")
    for k in tot:
        tot[k] += d[k]
print(f"  ALL: {tot['disagree']} pairs, ECR right {tot['ecr_right']/tot['disagree']:.3f}, app right {tot['app_right']/tot['disagree']:.3f}")
wins = (R.app_rho > R.ecr_rho).mean()
print(f"\napp beats ECR in {wins:.1%} of season-week-position groups")
