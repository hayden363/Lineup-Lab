"""Prints one Daily Drive day: 7 season prompts with their thresholds, answer counts, a few answers per tier with
team and stat, and an independent re-derivation of every answer set straight from the nflverse weekly table (plain
pandas filters, not the builders).

    .venv/bin/python -W ignore analysis/daily_drive_sample.py [YYYY-MM-DD] > analysis/daily_drive_sample.txt
"""
import collections
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import daily_drive as dd, data  # noqa: E402

date = sys.argv[1] if len(sys.argv) > 1 else dd.today_et().isoformat()
puzzle = dd.get_puzzle(date, data.HISTORY_DIR)
cur = data.resolve_season()
wk = data.load_weekly(cur)
wk = wk[wk["season_type"] == "REG"]
TPL = {t["key"]: t for t in dd.FANTASY_TEMPLATES}


def source(p):
    """{normalized name: (stat)} straight from the weekly rows: groupby sum/max over the positions, week <= through."""
    tpl = TPL[p["template"]]
    through = int(p["id"].split(":")[3][1:])
    thr = int(p["id"].split(":")[4][1:])
    w = wk[wk["position"].isin(tpl["pos"]) & (wk["week"] <= through)].copy()
    w["fpts"] = w["fantasy_points_ppr"]
    w["tds"] = w["rushing_tds"].fillna(0) + w["receiving_tds"].fillna(0)
    agg = w.groupby("player_id").agg(n=("player_display_name", "first"), v=(tpl["stat"], "max" if tpl["per"] == "game" else "sum"))
    agg = agg[agg["v"] >= thr]
    out = {}
    for n, v in zip(agg["n"], agg["v"]):
        out[dd.norm_name(n)] = float(v)
    return out, thr, through


print(f"THE DAILY DRIVE sample day {date}  ({len(puzzle['prompts'])} prompts; every answer computed from nflverse weekly data, "
      f"season {cur} REG; history/draft prompts off: HISTORY_ENABLED={dd.HISTORY_ENABLED})")
all_ok = True
for i, p in enumerate(puzzle["prompts"], 1):
    c = collections.Counter(a["tier"] for a in p["answers"])
    src, thr, through = source(p)
    got = {dd.norm_name(a["name"]): a["stat"] for a in p["answers"]}
    same = set(got) == set(src) and all(abs(got[k] - src[k]) < 0.06 for k in got)
    all_ok &= same
    print(f"\n{i}. [{p['template']}] {p['text']}\n   category: {p['category']}   id: {p['id']}   threshold: {thr:,}")
    print(f"   answers: {len(p['answers'])} (target {dd.TARGET_MIN}-{dd.TARGET_MAX})   tiers 6..1: " + " ".join(f"{t}:{c.get(t, 0)}" for t in range(6, 0, -1)))
    print(f"   re-derived from the weekly table: {len(src)} distinct names; builder set and stats == source: {same}"
          + ("" if same else f"  (only in builder: {sorted(set(got) - set(src))[:3]}; only in source: {sorted(set(src) - set(got))[:3]})"))
    for t in range(6, 0, -1):
        row = [a for a in p["answers"] if a["tier"] == t]
        print(f"   {dd.TIERS[t][2]} {dd.TIERS[t][0]:<14} ({dd.TIERS[t][1]:>3} yds, {len(row):>2}): "
              + ", ".join(f"{a['name']} ({a['team']} {a['position']}, {a['stat']:,} {a['stat_label']})" for a in row[:3]))
print(f"\nALL 7 ANSWER SETS MATCH A FRESH PANDAS RECOMPUTE: {all_ok}")
