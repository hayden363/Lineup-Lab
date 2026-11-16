"""LIVE My Team: real points so far + a live projection for every starter, mine and my opponent's.

Pure composition, no network: server.py fetches the three inputs and hands them in.
  base     slim copy of the cached My Team result (ids, positions, teams, pregame PROJ, settled flags), see make_base()
  games    engine.live_scores.live_scoreboard(): state / period / clock / score per NFL game
  points   {"source": "sleeper"|"espn"|None, "by_roster": {roster_id: {raw_player_id: points}}}, the league's own scoring
Nothing is invented: a number that cannot be sourced is None (points when the league site did not answer, live_proj when
the clock is unreadable) and the response says which source the points came from.
"""
import re
import time
from datetime import datetime, timezone

from . import live_proj

# One spelling for every NFL team code that shows up across Sleeper (WAS, LAR is not used there but LA is), ESPN (WSH, LAR),
# nflverse (LA, WAS, JAX) and the older aliases the other modules already map (engine/boxscore.py, engine/news.py).
_TEAM_ALIAS = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI"}
SOON_SECONDS = 10 * 60          # a game kicking off within this many seconds counts as "about to be live"
POLL_SECONDS = 30
HALF = 1800.0
QUARTER = 900.0


def norm_team(code):
    a = str(code or "").strip().upper()
    return _TEAM_ALIAS.get(a, a) or None


def parse_clock(text):
    """'10:42' -> 642.0; '0:48' -> 48.0; '48.0' (ESPN's under-a-minute form) -> 48.0. None when unreadable."""
    s = str(text or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\.\d+)?", s)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2})(?:\.\d+)?", s)
    if m and ("." in s):
        return float(s)
    return None


def seconds_left(state, period, clock_text):
    """Regulation seconds remaining: (4 - quarter) * 900 + clock for quarters 1-4 (halftime reads Q2 0:00 -> 1800),
    0 in overtime or after the game, None while a live clock cannot be read."""
    if state == "post":
        return 0.0
    if state != "in":
        return None
    try:
        q = int(period)
    except (TypeError, ValueError):
        return None
    if q >= 5:
        return 0.0
    if q < 1:
        return None
    clock = parse_clock(clock_text)
    if clock is None:
        return None
    return (4 - q) * QUARTER + min(clock, QUARTER)


def _parse_kickoff(iso):
    try:
        s = str(iso).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (TypeError, ValueError):
        return None


def game_index(games, week=None):
    """norm team code -> what a player on that team needs from his game. Games from a different NFL week are ignored
    (the scoreboard only ever shows the current week, a past/future My Team week must not borrow its states)."""
    out = {}
    for g in games or []:
        gw = g.get("week")
        if week is not None and gw is not None and int(gw) != int(week):
            continue
        state = g.get("state")
        if state not in ("pre", "in", "post"):
            continue
        home, away = g.get("home") or {}, g.get("away") or {}
        for me, other in ((home, away), (away, home)):
            code = norm_team(me.get("abbr"))
            if not code:
                continue
            ms, os_ = me.get("score"), other.get("score")
            diff = (ms - os_) if (ms is not None and os_ is not None) else None
            out[code] = {
                "state": state, "period": g.get("period") or None, "clock": g.get("display_clock"),
                "detail": g.get("status_detail"), "kickoff": g.get("kickoff"),
                "seconds_left": seconds_left(state, g.get("period"), g.get("display_clock")),
                "score_diff": diff,
            }
    return out


def make_base(result, crosswalk, platform):
    """Slim, long-lived copy of a my_team()/my_team_espn() result: only what the live view needs for each STARTER.
    `raw_id` is the id the league site's own points use (Sleeper / ESPN id), recovered from the gsis player_id through the
    inverse crosswalk. DEF rows already carry the league site's id (the team code)."""
    inv = {}
    for raw, gsis in (crosswalk or {}).items():
        inv.setdefault(gsis, raw)

    def card(team):
        if not team:
            return None
        starters = []
        for p in team.get("players") or []:
            if not p.get("is_starter"):
                continue
            pid = p.get("player_id")
            pos = p.get("position")
            raw = pid if (pos == "DEF" or p.get("unresolved") or pid not in inv) else inv[pid]
            starters.append({"player_id": pid, "raw_id": str(raw), "position": pos,
                             "team": norm_team(p.get("recent_team")), "proj": p.get("PROJ"),
                             "settled": bool(p.get("final")), "on_bye": bool(p.get("on_bye"))})
        return {"roster_id": team.get("roster_id"), "starters": starters}

    return {"week": result.get("nfl_week"), "live_week": result.get("live_week"), "platform": platform,
            "my_team": card(result.get("my_team")), "opponent": card(result.get("opponent"))}


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _player(s, idx, pts):
    g = idx.get(s["team"]) if s["team"] else None
    settled = s["settled"]
    proj = _num(s["proj"])
    state = "post" if settled else (g["state"] if g else None)
    points = _num(pts)
    pregame = None if settled else proj
    live = None
    if settled:
        points = points if points is not None else proj          # PROJ of a settled row IS his real score
        live = points
    elif state == "pre" or state is None:
        points = None
        live = pregame
    elif state == "in":
        if points is not None and g["seconds_left"] is not None:
            live = live_proj.live_projection(s["position"], pregame, points, g["seconds_left"], g["score_diff"],
                                             quarter=g["period"])["live_proj"]
    else:                                                          # post, not yet settled by our box scores
        live = points
    return {"player_id": s["player_id"], "position": s["position"], "game_state": state, "points": points,
            "pregame_proj": pregame, "live_proj": live, "quarter": g["period"] if (g and state == "in") else None,
            "clock": g["clock"] if (g and state == "in") else None,
            "detail": g["detail"] if g else None, "kickoff": g["kickoff"] if g else None}


def _team(card, idx, by_roster):
    if not card:
        return None
    pts = (by_roster or {}).get(card["roster_id"]) or (by_roster or {}).get(str(card["roster_id"])) or {}
    players = [_player(s, idx, pts.get(s["raw_id"])) for s in card["starters"]]
    unknown = any(p["game_state"] in ("in", "post") and p["points"] is None for p in players)
    points_total = None if unknown else round(sum(p["points"] or 0.0 for p in players), 1)
    total = 0.0
    for p, s in zip(players, card["starters"]):
        st = p["game_state"]
        if st == "post":
            v = p["points"] if p["points"] is not None else _num(s["proj"])      # unreadable score: his projection stands
        elif st == "in":
            v = p["live_proj"] if p["live_proj"] is not None else p["pregame_proj"]
        else:
            v = p["pregame_proj"]
        total += v or 0.0
    return {"roster_id": card["roster_id"], "points_total": points_total, "live_proj_total": round(total, 1),
            "final": bool(players) and all(p["game_state"] == "post" for p in players), "players": players}


def compose(base, games, points, now=None):
    """The /api/myteam/live body. `now` is epoch seconds (injectable for tests)."""
    now = time.time() if now is None else now
    week = base.get("week")
    is_live_week = base.get("live_week") is not None and base.get("live_week") == week
    if not is_live_week:
        return {"live": False, "week": week, "reason": "not the live NFL week", "my_team": None, "opponent": None,
                "scoreboard_ok": True, "points_source": None, "active": False, "wake_in_seconds": None, "as_of": now}
    idx = game_index(games, week)
    by_roster = (points or {}).get("by_roster") or {}
    mine, opp = _team(base["my_team"], idx, by_roster), _team(base["opponent"], idx, by_roster)
    players = [p for t in (mine, opp) if t for p in t["players"]]
    active, soonest = False, None
    for p in players:
        if p["game_state"] == "in":
            active = True
        elif p["game_state"] == "pre":
            k = _parse_kickoff(p["kickoff"])
            if k is None:
                continue
            if k - now <= SOON_SECONDS:
                active = True
            else:
                soonest = k if soonest is None else min(soonest, k)
    wake = None if (active or soonest is None) else max(5, int(soonest - SOON_SECONDS - now))
    return {"live": True, "week": week, "platform": base.get("platform"), "scoreboard_ok": bool(idx),
            "points_source": (points or {}).get("source"), "points_note": (points or {}).get("note"),
            "active": active, "poll_seconds": POLL_SECONDS, "wake_in_seconds": wake, "as_of": now,
            "my_team": mine, "opponent": opp}
