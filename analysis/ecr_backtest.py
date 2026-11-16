"""Preseason (Week 1) backtest: FantasyPros consensus rank vs this app's SCORE (hand-picked, walk-forward learned) vs
last season's points/game, each judged against the player's REAL points per game that season (PPR).
Run from the repo root: python analysis/ecr_backtest.py"""
import sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, ".")
import numpy as np, pandas as pd
import weight_tuner as T
from engine.metrics import score_players, _DEFAULT_WEIGHTS

SCRATCH = "data_cache"   # ecr_hist/db_fpecr.parquet: DynastyProcess archive https://github.com/dynastyprocess/data (db_fpecr.parquet)
ecr = pd.read_parquet(SCRATCH + "/ecr_hist/db_fpecr.parquet",
                      columns=["page_type", "player", "id", "pos", "ecr", "scrape_date", "fp_page"])
ecr = ecr[(ecr.page_type == "redraft-overall") & ecr.fp_page.str.contains("ppr-cheatsheets")].copy()
ecr["d"] = pd.to_datetime(ecr.scrape_date)
xw = pd.read_parquet("data_cache/id_crosswalk.parquet", columns=["fantasypros_id", "gsis_id"]).dropna()
xw["fantasypros_id"] = xw.fantasypros_id.astype(float).astype(int).astype(str)
fp2gsis = dict(zip(xw.fantasypros_id, xw.gsis_id))


def snapshot(y):
    """The earliest cheat-sheet snapshot in the Aug 15 - Sep 15 window: the Week 1 consensus, before results exist
    (for some years the first archived day is just after the Thursday opener)."""
    s = ecr[(ecr.d >= f"{y}-08-15") & (ecr.d <= f"{y}-09-15")]
    day = s.d.min()
    s = s[s.d == day].copy()
    s["gsis"] = s["id"].astype(str).map(fp2gsis)
    return day.date(), s.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis")["ecr"]


seasons = T._probe_seasons(9)
TOPN = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
KEYS = ("ecr", "hand", "learned", "last_ppg", "blend")
rows = []
for y in range(2021, 2026):
    day, ecr_y = snapshot(y)
    print(f"{y}: using ECR snapshot {day}, {len(ecr_y)} matched players")
    for pos in ("QB", "RB", "WR", "TE"):
        pairs = T._season_pairs(pos, [s for s in seasons if s <= y])
        if (y - 1) not in pairs:
            continue
        everyone, joined = pairs[y - 1]
        prior = [j for a, (_, j) in pairs.items() if a + 1 < y]      # strictly earlier transitions: no peeking
        hand = _DEFAULT_WEIGHTS[pos]
        learned = {**hand, **T._fit(pos, prior)}
        cand = pd.DataFrame({
            "hand": score_players(everyone, hand), "learned": score_players(everyone, learned),
            "last_ppg": everyone["fpts_per_game"]}).reindex(joined.index)
        cand["ecr"] = -ecr_y.reindex(joined.index)                     # lower rank number = better
        d = cand.dropna(subset=["ecr"]).copy()
        tgt = joined.loc[d.index, "target_fpts_per_game"]
        if len(d) < 12:
            continue
        d["blend"] = d["ecr"].rank() + d["learned"].rank()
        n = TOPN[pos]
        r = {"year": y, "pos": pos, "n": len(d)}
        for k in KEYS:
            r[k + "_rho"] = d[k].rank().corr(tgt.rank())
            r[k + "_top"] = len(set(d[k].nlargest(n).index) & set(tgt.nlargest(n).index)) / n
        rows.append(r)

df = pd.DataFrame(rows)
print(df.round(3).to_string(index=False))
print()
for pos, g in df.groupby("pos"):
    print(pos, "years", len(g), "rho", {k: round(g[k + "_rho"].mean(), 3) for k in KEYS},
          "| top-N hit", {k: round(g[k + "_top"].mean(), 3) for k in KEYS})
print("ALL ", "rho", {k: round(df[k + "_rho"].mean(), 3) for k in KEYS},
      "| top-N hit", {k: round(df[k + "_top"].mean(), 3) for k in KEYS})
print("learned beats ecr in", int((df.learned_rho > df.ecr_rho).sum()), "of", len(df), "position-years;",
      "ecr beats learned in", int((df.ecr_rho > df.learned_rho).sum()),
      "| blend beats ecr in", int((df.blend_rho > df.ecr_rho).sum()))
