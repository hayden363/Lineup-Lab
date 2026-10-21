"""
Measures how often a player listed Questionable/Doubtful actually plays, from
real nflverse injury reports joined to real weekly stat lines.

A player "played" when he took an offensive snap (snap counts) or has a weekly
stat row with a pass attempt, carry or target. Players with neither, even if
active, count as not playing. Only players who were regulars that season count (see REGULAR_SHARE). Buckets are position x status x Friday
practice level (Full / Limited / DNP); a bucket under MIN_N falls back to
position x status, then to status alone.

Run:  .venv/bin/python -m engine.play_prob_tuner
Writes engine/play_prob_factors.json
"""
import datetime as dt
import json
import os

import nfl_data_py as nfl
import pandas as pd

SEASONS = list(range(2016, 2025))
MIN_N = 40
REGULAR_SHARE = 0.6
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "play_prob_factors.json")
POSITIONS = ("QB", "RB", "WR", "TE")


def practice_level(s):
    s = str(s or "")
    if s.startswith("Full"):
        return "full"
    if s.startswith("Limited"):
        return "limited"
    if s.startswith("Did Not"):
        return "dnp"
    return "unknown"


def build():
    inj = nfl.import_injuries(SEASONS)
    inj = inj[inj["report_status"].isin(["Questionable", "Doubtful"]) & inj["position"].isin(POSITIONS)
              & (inj["game_type"] == "REG")].copy()
    wk = nfl.import_weekly_data(SEASONS)
    wk = wk[wk["season_type"] == "REG"]
    touches = wk[["attempts", "carries", "targets"]].fillna(0).sum(axis=1)
    played = set(zip(wk.loc[touches > 0, "player_id"], wk.loc[touches > 0, "season"], wk.loc[touches > 0, "week"]))
    sn = nfl.import_snap_counts(SEASONS)
    sn = sn[(sn["game_type"] == "REG") & (sn["offense_snaps"] > 0)]
    pfr = nfl.import_ids()[["gsis_id", "pfr_id"]].dropna().drop_duplicates("pfr_id").set_index("pfr_id")["gsis_id"]
    sn_g = sn["pfr_player_id"].map(pfr)
    played |= set(zip(sn_g[sn_g.notna()], sn.loc[sn_g.notna(), "season"], sn.loc[sn_g.notna(), "week"]))
    inj["played"] = [(g, s, w) in played for g, s, w in zip(inj["gsis_id"], inj["season"], inj["week"])]
    inj["practice"] = inj["practice_status"].map(practice_level)

    # Only regulars: depth players listed Questionable who never played would drag
    # the rate down for the starters this is used on. A regular played in at
    # least REGULAR_SHARE of his earlier weeks that season (and 2+ of them).
    by_player = {}
    for g, se, w in played:
        by_player.setdefault((g, se), set()).add(w)

    def regular(g, se, w):
        prior = [x for x in by_player.get((g, se), ()) if x < w]
        return w > 2 and len(prior) >= 2 and len(prior) / (w - 1) >= REGULAR_SHARE

    inj = inj[[regular(g, se, w) for g, se, w in zip(inj["gsis_id"], inj["season"], inj["week"])]]

    out = {}

    def add(key, df):
        if len(df) >= MIN_N:
            out[key] = {"n": int(len(df)), "p_play": round(float(df["played"].mean()), 3)}

    for st in ("Questionable", "Doubtful"):
        d = inj[inj["report_status"] == st]
        add(st, d)
        for pos in POSITIONS:
            dp = d[d["position"] == pos]
            add(f"{pos}|{st}", dp)
            for pr in ("full", "limited", "dnp"):
                add(f"{pos}|{st}|{pr}", dp[dp["practice"] == pr])
        for pr in ("full", "limited", "dnp"):
            add(f"{st}|{pr}", d[d["practice"] == pr])
    return {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "seasons_used": SEASONS, "min_n": MIN_N,
            "method": "share of Questionable/Doubtful player-weeks with at least one attempt, carry or target",
            "factors": out}


if __name__ == "__main__":
    res = build()
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1)
    for k, v in sorted(res["factors"].items()):
        print(f"{k:32s} n={v['n']:5d}  p_play={v['p_play']:.3f}")
