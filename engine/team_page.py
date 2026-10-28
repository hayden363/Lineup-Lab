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

DIVISIONS = {}
for _div, _teams in {
    "AFC East": "BUF MIA NE NYJ", "AFC North": "BAL CIN CLE PIT", "AFC South": "HOU IND JAX TEN", "AFC West": "DEN KC LV LAC",
    "NFC East": "DAL NYG PHI WAS", "NFC North": "CHI DET GB MIN", "NFC South": "ATL CAR NO TB", "NFC West": "ARI LA SF SEA",
}.items():
    for _t in _teams.split():
        DIVISIONS[_t] = _div

_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def _record_and_diff(code, schedule):
    w = l = t = diff = 0
    g = schedule[(schedule["home_team"] == code) | (schedule["away_team"] == code)]
    for r in g.itertuples():
        if pd.isna(r.home_score) or pd.isna(r.away_score):
            continue
        mine, theirs = (r.home_score, r.away_score) if r.home_team == code else (r.away_score, r.home_score)
        diff += mine - theirs
        w, l, t = w + (mine > theirs), l + (mine < theirs), t + (mine == theirs)
    n = w + l + t
    return ((w + 0.5 * t) / n if n else 0.0), diff, n


def standing(code, schedule):
    """{rank, division, text}: the team's place among its four division rivals by win percentage, then point
    differential. rank is None before anyone has played."""
    div = DIVISIONS.get(code)
    if not div:
        return {"rank": None, "division": None, "text": None}
    mates = [t for t, d in DIVISIONS.items() if d == div]
    table = {t: _record_and_diff(t, schedule) for t in mates}
    if not any(n for _, _, n in table.values()):
        return {"rank": None, "division": div, "text": None}
    order = sorted(mates, key=lambda t: (-table[t][0], -table[t][1], t))
    rank = order.index(code) + 1
    return {"rank": rank, "division": div, "text": f"{_ORD[rank]} {div}"}


def streak(games):
    """The run of identical results at the end of the played games: {type: W|L|T|None, n}."""
    played = [g["result"] for g in games if g.get("result")]
    if not played:
        return {"type": None, "n": 0}
    n = 1
    while n < len(played) and played[-1 - n] == played[-1]:
        n += 1
    return {"type": played[-1], "n": n}


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
            shot = last["headshot_url"] if "headshot_url" in g.columns and isinstance(last["headshot_url"], str) else None
            players.append({"player_id": pid, "name": last["player_display_name"], "position": last["position"], "headshot_url": shot,
                            "ppg": _r1(g["fantasy_points_ppr"].mean()), "games": int(g["week"].nunique())})
        players.sort(key=lambda p: -p["ppg"] * min(p["games"], 4))       # a one-game cameo doesn't outrank a starter
    from . import profile
    return {"team": code, "standing": standing(code, schedule), "streak": streak(games),
            "bye_week": profile.bye_weeks(schedule).get(code), "record": {"wins": int(w), "losses": int(l), "ties": int(t), "text": f"{w}-{l}" + (f"-{t}" if t else "")},
            "points_for": int(pf), "points_against": int(pa), "games": games, "next_game": nxt, "stats": stats, "players": players}
