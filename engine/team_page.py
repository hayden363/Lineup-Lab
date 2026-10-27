"""
TEAM PAGE — one NFL team's season at a glance
=============================================
Record and a week-by-week results list, the next game with its betting-line outlook (spread and each side's
implied total, the same numbers the projections lean on), per-game team stats summed from the players' lines,
and the roster ranked by fantasy scoring. Pure: takes the schedule and weekly frames, so it's testable without
the network; engine/tools.py adds per-player next-game projections on top.
"""

import pandas as pd

from . import news as news_layer

FANTASY_POS = ("QB", "RB", "WR", "TE")


def _r1(x):
    return round(float(x), 1)


def build(code, schedule, wk):
    code = str(code or "").upper()
    if code not in news_layer.TEAM_CODES:
        return None

    games, w, l, t, pf, pa = [], 0, 0, 0, 0, 0
    mine = schedule[(schedule["home_team"] == code) | (schedule["away_team"] == code)].sort_values(["week", "gameday"])
    for r in mine.itertuples():
        home = r.home_team == code
        opp = r.away_team if home else r.home_team
        played = pd.notna(r.home_score) and pd.notna(r.away_score)
        ts, os_ = (r.home_score, r.away_score) if home else (r.away_score, r.home_score)
        res = None
        if played:
            ts, os_ = int(ts), int(os_)
            res = "W" if ts > os_ else "L" if ts < os_ else "T"
            w, l, t, pf, pa = w + (res == "W"), l + (res == "L"), t + (res == "T"), pf + ts, pa + os_
        games.append({"week": int(r.week), "opponent": opp, "home": home, "date": str(r.gameday)[:10],
                      "team_score": ts if played else None, "opp_score": os_ if played else None, "result": res})

    nxt = None
    for r, g in zip(mine.itertuples(), games):
        if g["result"] is None:
            spread, total = r.spread_line, r.total_line                  # nflverse: positive spread = home favored
            have = pd.notna(spread) and pd.notna(total)
            sgn = 1 if g["home"] else -1
            nxt = {"week": g["week"], "opponent": g["opponent"], "home": g["home"], "date": g["date"],
                   "spread": (-sgn * float(spread)) if have else None,
                   "total": float(total) if have else None,
                   "implied_total": _r1((float(total) + sgn * float(spread)) / 2) if have else None,
                   "opp_implied_total": _r1((float(total) - sgn * float(spread)) / 2) if have else None}
            break

    n = w + l + t
    stats = {"games": n, "points_for_pg": _r1(pf / n) if n else None, "points_against_pg": _r1(pa / n) if n else None,
             "pass_yds_pg": None, "rush_yds_pg": None}
    team_wk = wk[wk["recent_team"] == code] if len(wk) else wk
    if n and len(team_wk):
        weeks = max(1, team_wk["week"].nunique())
        stats["pass_yds_pg"] = _r1(team_wk["passing_yards"].sum() / weeks)
        stats["rush_yds_pg"] = _r1(team_wk["rushing_yards"].sum() / weeks)

    players = []
    if len(team_wk):
        base = team_wk[team_wk["position"].isin(FANTASY_POS)]
        for pid, g in base.groupby("player_id"):
            last = g.sort_values("week").iloc[-1]
            players.append({"player_id": pid, "name": last["player_display_name"], "position": last["position"],
                            "ppg": _r1(g["fantasy_points_ppr"].mean()), "games": int(g["week"].nunique())})
        players.sort(key=lambda p: -p["ppg"] * min(p["games"], 4))       # a one-game cameo doesn't outrank a starter
    return {"team": code, "record": {"wins": int(w), "losses": int(l), "ties": int(t), "text": f"{w}-{l}" + (f"-{t}" if t else "")},
            "points_for": int(pf), "points_against": int(pa), "games": games, "next_game": nxt, "stats": stats, "players": players}
