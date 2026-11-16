"""Runs every pool template through the real tiering path for one season/week and prints/saves the results.
usage: run_pool.py SEASON THROUGH_WEEK [out.json]"""
import collections, json, sys
import pandas as pd
from engine import consensus, data, daily_drive as dd, daily_drive_pool as pool

def setup(season, through):
    wk = data.load_weekly(season)
    sched = data.load_schedule(season)
    draft = data.load_draft_picks()
    ctx = pool.build_context(wk, sched, season, through, draft)
    ecr = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
    history = data.load_season_history(season - 1)
    av = {g: float(v) for g, v in zip(draft["gsis_id"], draft["car_av"]) if isinstance(g, str) and pd.notna(v)}
    wkr = wk[wk["season_type"] == "REG"] if "season_type" in wk.columns else wk
    fame = (dd.career_points(history, wkr[wkr["week"] <= through]), av)
    return ctx, ecr, fame

def summarize(p):
    c = collections.Counter(a["tier"] for a in p["answers"])
    return {"threshold": p["threshold"], "text": p["text"], "n": len(p["answers"]), "tiers": [c[t] for t in range(1, 7)],
            "t1": [a["name"] for a in p["answers"] if a["tier"] == 1][:3], "t6": [a["name"] for a in p["answers"] if a["tier"] == 6][:3]}

def run(season, through, pl=None):
    ctx, ecr, fame = setup(season, through)
    out = {}
    for tpl in (pl or pool.POOL):
        scopes = pool.SCOPES[tpl["scope"]] if tpl.get("scope") else [None]
        res = {}
        for sc in scopes:
            p = pool.build_pool_prompt(tpl, ctx, ecr, fame, sc)
            res[sc or "-"] = summarize(p) if p else None
        out[tpl["key"]] = res
    return out

if __name__ == "__main__":
    season, through = int(sys.argv[1]), int(sys.argv[2])
    out = run(season, through)
    if len(sys.argv) > 3:
        json.dump(out, open(sys.argv[3], "w"), indent=1)
    for k, res in out.items():
        for sc, r in res.items():
            print(k, sc, "FAIL" if r is None else (r["threshold"], r["n"], r["tiers"]))
