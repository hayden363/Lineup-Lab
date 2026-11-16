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

# ---- sweep: ECR rank mapped onto the app's own points scale, blended at weight w ------------------
TOPN = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
WS = [0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
res = []
for (s, w, pos), g in J.groupby(["season", "week", "position"]):
    if len(g) < 12:
        continue
    g = g.copy()
    y = g.fpts_active
    desc = np.sort(g.app.to_numpy())[::-1]
    order = g.ecr_rank.rank(method="first").astype(int).to_numpy() - 1   # 0 = best consensus
    g["ecr_pts"] = desc[order]                                            # quantile map to app points scale
    r = {"season": s, "week": w, "pos": pos}
    for wt in WS:
        sc = wt * g.ecr_pts + (1 - wt) * g.app
        r[f"rho_{wt}"] = sc.rank().corr(y.rank())
        n = TOPN[pos]
        r[f"top_{wt}"] = len(set(sc.nlargest(n).index) & set(y.nlargest(n).index)) / n
    res.append(r)
R = pd.DataFrame(res)
print(f"{len(R)} groups")
for pos in list(POS) + ["ALL"]:
    sub = R if pos == "ALL" else R[R.pos == pos]
    print(pos, "rho", {wt: round(sub[f"rho_{wt}"].mean(), 4) for wt in WS})
    print(pos, "top", {wt: round(sub[f"top_{wt}"].mean(), 4) for wt in WS})
