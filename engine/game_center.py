"""
GAME CENTER — everything the Live tab's deep dive needs beyond the score
========================================================================
Parsed from ESPN's public summary and scoreboard JSON (the same free feeds as engine/live_scores.py
and engine/boxscore.py): the prime-time badge, the live field position and down and distance, the betting
line with each side's implied score, the weather, the injury report, and a play-by-play log where every
play carries the fantasy points it produced under the viewer's own scoring.

The feeds are undocumented, so every access is defensive: a missing or malformed piece comes back as
None or empty, never an exception.

Field geometry: the field is always drawn with the AWAY team's own end zone on the left and the HOME
team's on the right. `yard_line` is how far the ball is from the LEFT goal line (0 to 100).
"""
import re
from datetime import datetime

from .scoring import ScoringSettings

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None

WIND_ALERT_MPH = 15
PLAY_LIMIT = 80


def _g(d, *path, default=None):
    for k in path:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and 0 <= k < len(d):
            d = d[k]
        else:
            return default
        if d is None:
            return default
    return d


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ badge ----
def broadcast_badge(kickoff_iso):
    """'TNF' | 'SNF' | 'MNF' for the prime-time slots (Eastern time), else None."""
    try:
        when = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    if _ET is not None:
        when = when.astimezone(_ET)
    else:   # no tz database: Eastern is UTC-4 until early November, UTC-5 after
        from datetime import timedelta
        when = when + timedelta(hours=-4 if 3 <= when.month <= 10 else -5)
    wd, hr = when.weekday(), when.hour
    if wd == 3 and hr >= 17:
        return "TNF"
    if wd == 6 and hr >= 19:
        return "SNF"
    if wd == 0 and hr >= 17:
        return "MNF"
    return None


# -------------------------------------------------------------- situation ----
_POS_TEXT = re.compile(r"([A-Z]{2,4})\s+(\d{1,2})")


def situation(sit, home, away, teams):
    """The live drive: who has the ball, down and distance, where on the field, the line to gain and whether
    the offense is in the red zone. `teams` maps ESPN team id -> abbreviation. None when it can't be read."""
    if not isinstance(sit, dict):
        return None
    down, dist = sit.get("down"), sit.get("distance")
    poss_raw = sit.get("possession")
    poss = (teams or {}).get(str(poss_raw), poss_raw if poss_raw in (home, away) else None)
    if poss not in (home, away) or not isinstance(down, int) or not isinstance(dist, (int, float)):
        return None
    m = _POS_TEXT.search(str(sit.get("possessionText") or ""))
    if m:
        own = int(m.group(2)) if m.group(1) == poss else 100 - int(m.group(2))
    elif sit.get("yardLine") is not None and _num(sit.get("yardLine")) is not None:
        own = int(_num(sit["yardLine"]))
    else:
        return None
    own = max(0, min(100, own))
    to_goal = 100 - own
    going_right = poss == away
    pos = own if going_right else 100 - own
    ltg = min(100, pos + dist) if going_right else max(0, pos - dist)
    flag = sit.get("isRedZone")
    return {"possession": poss, "down": down, "distance": int(dist), "yard_line": pos, "line_to_gain": ltg,
            "direction": "left-to-right" if going_right else "right-to-left",
            "is_red_zone": bool(flag) if flag is not None else to_goal <= 20,
            "text": sit.get("downDistanceText") or sit.get("shortDownDistanceText")}


# ------------------------------------------------------- odds and weather ----
_ODDS_TEXT = re.compile(r"([A-Z]{2,4})\s+([+-]?\d+(?:\.\d+)?)")


def parse_odds(js, home, away):
    pick = _g(js, "pickcenter", 0)
    if not isinstance(pick, dict):
        return None
    total = _num(pick.get("overUnder"))
    fav, spread = None, 0.0
    m = _ODDS_TEXT.search(str(pick.get("details") or ""))
    if m and m.group(1) in (home, away):
        spread = abs(float(m.group(2)))
        fav = m.group(1) if float(m.group(2)) < 0 else None
    elif _num(pick.get("spread")) not in (None, 0.0):
        spread = abs(float(pick["spread"]))
        fav = home if _g(pick, "homeTeamOdds", "favorite") else away
    if total is None and not spread and fav is None:
        return None
    edge = 0.0 if fav is None else (spread if fav == home else -spread)
    ml = lambda side: _num(_g(pick, side, "moneyLine"))
    hml, aml = ml("homeTeamOdds"), ml("awayTeamOdds")
    return {"favorite": fav, "spread": spread, "total": total, "details": pick.get("details"),
            "home_ml": None if hml is None else int(hml), "away_ml": None if aml is None else int(aml),
            "home_implied": None if total is None else round((total + edge) / 2, 1),
            "away_implied": None if total is None else round((total - edge) / 2, 1)}


def parse_weather(js):
    w = _g(js, "gameInfo", "weather")
    indoor = _g(js, "gameInfo", "venue", "indoor")
    if not isinstance(w, dict) and indoor is None:
        return None
    w = w if isinstance(w, dict) else {}
    wind = _num(w.get("windSpeed", w.get("wind")))
    temp = _num(w.get("temperature"))
    return {"temp": None if temp is None else int(temp),
            "wind": None if wind is None else int(wind), "wind_alert": wind is not None and wind >= WIND_ALERT_MPH,
            "precip": _num(w.get("precipitation")), "summary": w.get("displayValue") or w.get("conditionId"),
            "indoor": bool(indoor) if indoor is not None else None}


def parse_injuries(js):
    out = {}
    for block in js.get("injuries") or [] if isinstance(js, dict) else []:
        abbr = _g(block, "team", "abbreviation")
        rows = []
        for i in _g(block, "injuries", default=[]) or []:
            name = _g(i, "athlete", "displayName")
            if name:
                rows.append({"name": name, "position": _g(i, "athlete", "position", "abbreviation"),
                             "status": i.get("status"), "detail": _g(i, "details", "type")})
        if abbr and rows:
            out[abbr] = rows
    return out


# ------------------------------------------------------------- play by play ----
def _athlete_id(p):
    a = p.get("athlete") if isinstance(p, dict) else None
    if not isinstance(a, dict):
        return None
    if a.get("id") is not None:
        return str(a["id"])
    m = re.search(r"/athletes/(\d+)", str(a.get("$ref") or ""))
    return m.group(1) if m else None


def _play_points(kind, yds, td, parts, names, s):
    """[(athlete_id, points)] for one play: rushing and receiving yards and touchdowns, receptions, the passer's
    yardage and touchdowns, and interceptions. Incompletions, sacks, punts and the like score nobody."""
    k = str(kind).lower()
    by = {}
    for ptype, aid in parts:
        by.setdefault(ptype, aid)
    out = []
    if "interception" in k and "passer" in by:
        out.append((by["passer"], s.interception))
    elif "rusher" in by:
        out.append((by["rusher"], yds * s.rush_yard + (s.rush_td if td else 0)))
    elif "receiver" in by and "incompletion" not in k:
        pos = (names.get(by["receiver"]) or (None, None, None))[1]
        rec = s.reception + (s.te_reception if pos == "TE" else 0)
        out.append((by["receiver"], rec + yds * s.rec_yard + (s.rec_td if td else 0)))
        if "passer" in by:
            out.append((by["passer"], yds * s.pass_yard + (s.pass_td if td else 0)))
    return out


def parse_plays(js, names, scoring, mine, limit=PLAY_LIMIT):
    """Plays newest first. `names` maps athlete id -> (name, position, team); `mine` is the set of athlete ids on
    the viewer's roster."""
    s = ScoringSettings.from_dict(scoring) if scoring else ScoringSettings.from_preset("ppr")
    drives = []
    prev = _g(js, "drives", "previous")
    if isinstance(prev, list):
        drives += [d for d in prev if isinstance(d, dict)]
    cur = _g(js, "drives", "current")
    if isinstance(cur, dict):
        drives.append(cur)
    plays = []
    for d in drives:
        team = _g(d, "team", "abbreviation")
        for p in d.get("plays") or []:
            if not isinstance(p, dict):
                continue
            kind = _g(p, "type", "text", default="")
            yds = _num(p.get("statYardage")) or 0.0
            td = bool(p.get("scoringPlay")) and ("touchdown" in str(kind).lower() or p.get("scoreValue") == 6)
            parts = [(pt.get("type"), _athlete_id(pt)) for pt in p.get("participants") or [] if isinstance(pt, dict)]
            parts = [(t, a) for t, a in parts if t and a]
            fantasy = []
            for aid, pts in _play_points(kind, yds, td, parts, names, s):
                nm = names.get(aid)
                if nm:
                    fantasy.append({"name": nm[0], "position": nm[1], "points": round(float(pts), 1), "mine": aid in mine})
            target = next((names[a][0] for t, a in parts if t == "target" and a in names), None)
            plays.append({"id": str(p.get("id")), "text": p.get("text"), "type": kind, "team": team,
                          "quarter": _g(p, "period", "number"), "clock": _g(p, "clock", "displayValue"),
                          "scoring": bool(p.get("scoringPlay")), "yards": int(yds),
                          "away_score": p.get("awayScore"), "home_score": p.get("homeScore"),
                          "down": _g(p, "start", "down"), "distance": _g(p, "start", "distance"),
                          "fantasy": fantasy, "target": target})
    return plays[::-1][:limit]


# ------------------------------------------------------------------ bundle ----
def center(js, game, names, scoring, mine):
    """Everything the deep dive shows for one game, from its summary JSON. `game` is the scoreboard row
    (home/away abbr); never raises."""
    js = js if isinstance(js, dict) else {}
    home, away = _g(game, "home", "abbr"), _g(game, "away", "abbr")
    teams = {}
    for c in _g(js, "header", "competitions", 0, "competitors", default=[]) or []:
        if isinstance(c, dict) and _g(c, "team", "id") and _g(c, "team", "abbreviation"):
            teams[str(c["team"]["id"])] = c["team"]["abbreviation"]
    sit = situation(js.get("situation"), home, away, teams) or situation(game.get("situation_raw"), home, away, teams)
    wp = _g(js, "winprobability")
    win = None
    if isinstance(wp, list) and wp and isinstance(wp[-1], dict) and _num(wp[-1].get("homeWinPercentage")) is not None:
        win = round(float(wp[-1]["homeWinPercentage"]) * 100)
    return {"situation": sit, "odds": parse_odds(js, home, away), "weather": parse_weather(js),
            "injuries": parse_injuries(js), "plays": parse_plays(js, names, scoring, mine), "home_win_pct": win}
