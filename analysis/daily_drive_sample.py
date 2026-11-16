"""Prints one Daily Drive day with answer counts, a few answers per tier, and an independent re-derivation of
every answer set straight from the nflverse tables (plain pandas filters, not the builders).

    .venv/bin/python -W ignore analysis/daily_drive_sample.py [YYYY-MM-DD] > analysis/daily_drive_sample.txt
"""
import collections
import datetime as dt
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
hist = data.load_season_history(cur - 1)
picks = data.load_draft_picks()
POS = {t["key"]: t for t in dd.FANTASY_TEMPLATES}
HIST = {t["key"]: t for t in dd.HISTORY_TEMPLATES}
DRAFT = {t["key"]: t for t in dd.DRAFT_TEMPLATES}


def source_names(p):
    t = p["template"]
    if t in POS:
        tpl = POS[t]
        wkf = wk.assign(fpts=wk["fantasy_points_ppr"])
        wkf = wkf[wkf["position"].isin(tpl["pos"])]
        week = int(p["id"].rsplit(":", 1)[1][1:])
        sub = wkf[wkf["week"] == week] if tpl["scope"] == "week" else wkf[wkf["week"] <= week]
        tot = sub.groupby("player_id").agg(n=("player_display_name", "first"), v=(tpl["stat"], "sum"))
        return set(tot[tot["v"] >= tpl["min"]]["n"].map(dd.norm_name))
    if t in HIST:
        tpl = HIST[t]
        h = hist[hist["position"].isin(tpl["pos"]) & (hist[tpl["stat"]] >= tpl["min"])]
        return set(h["player_display_name"].map(dd.norm_name))
    tpl = DRAFT[t]
    d = picks[(picks["season"] >= tpl["since"]) & (picks["season"] <= dt.date.fromisoformat(date).year)]
    if tpl["rnd"] is not None:
        d = d[d["round"].isin(tpl["rnd"] if isinstance(tpl["rnd"], tuple) else (tpl["rnd"],))]
    if tpl["pick"] is not None:
        d = d[d["pick"] == tpl["pick"]]
    if tpl["pos"]:
        d = d[d["position"].isin(tpl["pos"])]
    return set(d["pfr_player_name"].dropna().map(dd.norm_name))


print(f"THE DAILY DRIVE sample day {date}  (7 prompts; every answer computed from nflverse data; season {cur} weeks through "
      f"{int(wk['week'].max())}, history 1999-{cur - 1})")
for i, p in enumerate(puzzle["prompts"], 1):
    c = collections.Counter(a["tier"] for a in p["answers"])
    src = source_names(p)
    got = {dd.norm_name(a["name"]) for a in p["answers"]}
    print(f"\n{i}. [{p['kind']}/{p['template']}] {p['text']}\n   category: {p['category']}   id: {p['id']}")
    print(f"   answers: {len(p['answers'])}   tiers 6..1: " + " ".join(f"{t}:{c.get(t, 0)}" for t in range(6, 0, -1)))
    print(f"   re-derived from source: {len(src)} distinct names; builder set == source set: {got == src}"
          + ("" if got == src else f"  (only in builder: {sorted(got - src)[:3]}; only in source: {sorted(src - got)[:3]})"))
    for t in range(6, 0, -1):
        names = [a["name"] for a in p["answers"] if a["tier"] == t]
        print(f"   {dd.TIERS[t][2]} {dd.TIERS[t][0]:<14} ({dd.TIERS[t][1]:>3} yds, {len(names):>2}): " + ", ".join(names[:4]))
