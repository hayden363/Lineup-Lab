"""
INJURIES — who is hurt right now, with what, and when he is expected back
==========================================================================
Sleeper's player list is the app's injury-status source, but it refreshes once
a day and carries no detail. Practice reports and game-day inactives move far
faster than that. This module adds ESPN's public NFL injury feed (no key),
re-read every 15 minutes:

  status       Out / Doubtful / Questionable / IR / PUP / Sus
  body part    "Hamstring", "Ankle", "Concussion", ...
  detail       "Sprain", "Bruise" when ESPN has it
  return date  ESPN's own estimate, turned into "back in Week N" and an
               estimated number of games missed from the team schedule
  note         ESPN's short report, with its timestamp

It is merged over Sleeper's data on the boards (engine/board.build_board), so
every projection that reads a player's injury status sees the fresher one.
ESPN listing a player as Active clears an older Sleeper designation. A player
ESPN does not list keeps whatever Sleeper says.

Players are matched by ESPN id through the nflverse crosswalk, then by name
and position for anyone the crosswalk lacks (new rookies). A name that matches
two players is skipped rather than guessed.

Never invents a timeline: with no return date the card says none was reported.
The only rules stated as fact are the NFL's own (injured reserve means at
least four games).
"""

import re
import threading
import time
from datetime import date, datetime, timezone

import pandas as pd
import requests

FEED = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
TTL = 15 * 60
TIMEOUT = 8

# ESPN fantasyStatus abbreviation (or status text) -> the vocabulary the rest
# of the app already uses.
STATUS_MAP = {
    "OUT": "Out", "DOUBTFUL": "Doubtful", "QUESTIONABLE": "Questionable",
    "DAY-TO-DAY": "Questionable", "IR": "IR", "IR-R": "IR", "INJURED RESERVE": "IR",
    "PUP-R": "PUP", "PUP-P": "PUP", "RESERVE-SUS": "Sus", "SUSPENSION": "Sus", "SUSPENDED": "Sus",
}
KEEP_POSITIONS = {"QB", "RB", "WR", "TE", "K", "PK"}

# What each designation means. IR's four-game minimum is the NFL's own rule.
MEANING = {
    "Out": "Ruled out for his next game.",
    "Doubtful": "Unlikely to play.",
    "Questionable": "Might play; his status is decided closer to kickoff.",
    "IR": "On injured reserve: he must miss at least four games.",
    "PUP": "On the physically-unable-to-perform list: he must miss at least four games.",
    "Sus": "Suspended by the league.",
}

_LOCK = threading.Lock()
_CACHE = {"at": 0.0, "records": None, "listed": None}
_NAMES = {}


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace(".", ""))


def _suffixless(name):
    return re.sub(r"(jr|sr|ii|iii|iv|v)$", "", _norm(name))


def _canon(status, fantasy):
    for raw in (fantasy, status):
        if raw and raw.upper() in STATUS_MAP:
            return STATUS_MAP[raw.upper()]
    return None


def parse(feed):
    """ESPN feed JSON -> [{espn_id, name, position, status|None, ...}] for every
    injury row. status None means ESPN lists him as Active (cleared)."""
    out = []
    for team in feed.get("injuries", []):
        for i in team.get("injuries", []):
            ath = i.get("athlete") or {}
            pos = ((ath.get("position") or {}).get("abbreviation") or "").upper()
            if pos not in KEEP_POSITIONS:
                continue
            d = i.get("details") or {}
            fantasy = (d.get("fantasyStatus") or {}).get("abbreviation") if isinstance(d.get("fantasyStatus"), dict) else None
            status = _canon(i.get("status"), fantasy)
            comment = (i.get("shortComment") or "").strip()
            if comment.lower() in ("questionable", "doubtful", "out", "injured reserve"):
                comment = ""   # the generic placeholder ESPN uses, not a report
            part = d.get("type") if d.get("type") not in (None, "Not Specified") else None
            detail = d.get("detail") if d.get("detail") not in (None, "Not Specified") else None
            side = d.get("side") if d.get("side") not in (None, "Not Specified") else None
            out.append({
                "espn_id": str(i.get("id")) if i.get("id") is not None and not str(i.get("id")).startswith("-") else None,
                "name": ath.get("displayName"), "position": "K" if pos == "PK" else pos, "team_name": team.get("displayName"),
                "status": status, "body_part": part, "detail": detail, "side": side,
                "return_date": d.get("returnDate"), "note": comment or None, "updated": i.get("date"),
            })
    return out


def _fetch():
    r = requests.get(FEED, timeout=TIMEOUT, headers={"User-Agent": "LineupLab/1.0"})
    r.raise_for_status()
    return parse(r.json())


def _name_index(bundle):
    """(normalized name, position) -> gsis id, only where the name is unique."""
    key = bundle["season"]
    if key in _NAMES:
        return _NAMES[key]
    wk = bundle["wk"]
    idx, dup = {}, set()
    for pid, name, pos in wk[["player_id", "player_display_name", "position"]].drop_duplicates().itertuples(index=False):
        for k in {(_norm(name), pos), (_suffixless(name), pos)}:
            if k in idx and idx[k] != pid:
                dup.add(k)
            idx[k] = pid
    for k in dup:
        idx.pop(k, None)
    _NAMES[key] = idx
    return idx


def _match(rows, bundle):
    """{gsis: record} for rows we can place on a player."""
    try:
        from . import espn
        cw = espn.id_crosswalk()
    except Exception as e:
        print(f"[injuries] ESPN crosswalk unavailable ({e}); matching by name only")
        cw = {}
    names = _name_index(bundle)
    out = {}
    for r in rows:
        gsis = cw.get(r["espn_id"]) if r["espn_id"] else None
        if not gsis:
            gsis = names.get((_norm(r["name"]), r["position"])) or names.get((_suffixless(r["name"]), r["position"]))
        if gsis:
            out[gsis] = r
    return out


def snapshot(bundle, force=False):
    """{gsis: record}, refreshed at most every TTL seconds. A failed refresh
    keeps serving the last good copy (or nothing, on the first call)."""
    now = time.time()
    if not force and _CACHE["records"] is not None and now - _CACHE["at"] < TTL:
        return _CACHE["records"]
    with _LOCK:
        if not force and _CACHE["records"] is not None and time.time() - _CACHE["at"] < TTL:
            return _CACHE["records"]
        try:
            matched = _match(_fetch(), bundle)
            _CACHE.update(records=matched, at=time.time())
        except Exception as e:
            print(f"[injuries] ESPN feed unavailable ({e}); keeping {'last copy' if _CACHE['records'] is not None else 'Sleeper only'}")
            _CACHE["at"] = time.time() - TTL + 60   # retry in a minute, not on every request
            if _CACHE["records"] is None:
                _CACHE["records"] = {}
        return _CACHE["records"]


def overlay(board, bundle):
    """A copy of `board` whose injury columns reflect the live ESPN feed over
    Sleeper's. Adds injury_report (a dict, or None) next to injury_status and
    injury_body_part. The input board is never modified (it is shared)."""
    board = board.copy()
    board["injury_report"] = None
    recs = snapshot(bundle)
    if not recs:
        return board
    status = board["injury_status"].copy() if "injury_status" in board.columns else None
    part = board["injury_body_part"].copy() if "injury_body_part" in board.columns else None
    reports = {}
    for pid in board.index.intersection(list(recs.keys())):
        r = recs[pid]
        if r["status"] is None:
            if status is not None:
                status.loc[pid] = None
            continue
        if status is not None:
            status.loc[pid] = r["status"]
        if part is not None and r["body_part"]:
            part.loc[pid] = r["body_part"]
        reports[pid] = r
    if status is not None:
        board["injury_status"] = status
    if part is not None:
        board["injury_body_part"] = part
    board["injury_report"] = pd.Series([reports.get(pid) for pid in board.index], index=board.index, dtype="object")
    return board


# ---- the timeline ---------------------------------------------------------
# One build asks for the same team's remaining games hundreds of times (every board, every injured player), and each
# ask used to re-filter the whole schedule table. They are remembered per schedule table instead. Each table gets its
# OWN memo object, so a thread that is still working on an old table can only ever write into that table's memo, never
# into the current one (two tables are briefly in use when a data refresh swaps the bundle under running requests).
# A memo is replaced when a different table object arrives or when anything a schedule answer depends on changes
# (a game moved, a team changed, a score came in), so it can never serve an outdated answer. Only real team codes are
# stored: at most one entry per team.
_SCHEDULE_COLUMNS = ("week", "home_team", "away_team", "game_type", "gameday", "gametime")


class _ScheduleMemo:
    __slots__ = ("schedule", "fingerprint", "games", "left")

    def __init__(self, schedule, fingerprint):
        self.schedule, self.fingerprint, self.games, self.left = schedule, fingerprint, {}, {}


def schedule_fingerprint(schedule):
    """Changes whenever anything a schedule answer is built from changes. str() makes missing values hash the same on
    every call and every Python version. About 0.1 ms for a full season."""
    parts = tuple(hash(tuple(map(str, schedule[c].tolist()))) for c in _SCHEDULE_COLUMNS if c in schedule.columns)
    scores = schedule["home_score"].isna().to_numpy().tobytes() if "home_score" in schedule.columns else b""
    return len(schedule), parts, scores


_REMAINING = _ScheduleMemo(None, None)


def _memo(schedule, team):
    """The memo for this schedule table, or None when it should not be used (not a real team code, or a table that
    isn't a normal schedule: the plain code path then runs and behaves exactly as before)."""
    global _REMAINING
    if not isinstance(team, str) or not isinstance(schedule, pd.DataFrame):
        return None
    try:
        fingerprint = schedule_fingerprint(schedule)
    except Exception:
        return None
    memo = _REMAINING
    if memo.schedule is not schedule or memo.fingerprint != fingerprint:
        memo = _REMAINING = _ScheduleMemo(schedule, fingerprint)
    return memo


def _remaining_rows(schedule, team):
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    s = s[(s["home_team"] == team) | (s["away_team"] == team)]
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    return s


def _remaining_games(schedule, team):
    """[(week, game date)] for the team's unplayed regular-season games, soonest first; games whose date can't be read
    are left out."""
    memo = _memo(schedule, team)
    hit = memo.games.get(team) if memo is not None else None
    if hit is not None:
        return hit
    games = []
    for r in _remaining_rows(schedule, team).sort_values("week").itertuples(index=False):
        try:
            games.append((int(r.week), date.fromisoformat(str(r.gameday)[:10])))
        except (TypeError, ValueError):
            continue
    if memo is not None:
        memo.games[team] = games
    return games


def timeline(return_date, schedule, team, today=None):
    """From ESPN's estimated return date and the team's remaining games:
    {return_date, return_week, games_out, days_out}. games_out counts games
    before that date; None values when nothing can be said."""
    out = {"return_date": return_date, "return_week": None, "games_out": None, "days_out": None, "games_left": None}
    if not return_date:
        return out
    today = today or date.today()
    try:
        back = date.fromisoformat(str(return_date)[:10])
    except ValueError:
        return out
    out["days_out"] = (back - today).days
    games = _remaining_games(schedule, team)
    out["games_left"] = len(games)
    missed = [w for w, d in games if d < back]
    out["games_out"] = len(missed)
    later = [w for w, d in games if d >= back]
    out["return_week"] = later[0] if later else None
    return out


def report_for(player_id, row, schedule, today=None):
    """The card's injury block for one player, or None when he has no status.
    `row` is his board row (dict-like) after overlay."""
    status = row.get("injury_status")
    if not isinstance(status, str) or not status:
        return None
    rec = row.get("injury_report") if isinstance(row.get("injury_report"), dict) else {}
    tl = timeline(rec.get("return_date"), schedule, row.get("recent_team"), today)
    part = rec.get("body_part") or (row.get("injury_body_part") if isinstance(row.get("injury_body_part"), str) else None)
    out = {
        "status": status, "meaning": MEANING.get(status),
        "body_part": part, "detail": rec.get("detail"), "side": rec.get("side"),
        "note": rec.get("note"), "updated": rec.get("updated"),
        "source": "ESPN" if rec else "Sleeper",
        **tl,
    }
    return out


LONG_ABSENCE_GAMES = 4   # the NFL's own IR minimum


# Games he is assumed to miss when ESPN gives no return date: a plain Out is the next game;
# IR and PUP are at least the NFL's own IR minimum. Anything else (Sus, NA, Questionable...)
# has no safe default length, so it gets no discount.
ASSUMED_GAMES_OUT = {"Out": 1, "IR": LONG_ABSENCE_GAMES, "PUP": LONG_ABSENCE_GAMES}


def _games_left(schedule, team):
    memo = _memo(schedule, team)
    hit = memo.left.get(team) if memo is not None else None
    if hit is not None:
        return hit
    n = int(len(_remaining_rows(schedule, team)))
    if memo is not None:
        memo.left[team] = n
    return n


def availability(row, schedule, today=None):
    """Share of his team's remaining regular-season games he is expected to play: the discount on
    his rest-of-season (trade) value. From ESPN's estimated return date when there is one (0.0 for a
    season-ending injury); without one, from the assumed minimum for his status (ASSUMED_GAMES_OUT);
    1.0 when neither applies."""
    status = row.get("injury_status")
    if not isinstance(status, str):
        return 1.0
    rec = row.get("injury_report")
    if isinstance(rec, dict) and rec.get("return_date"):
        tl = timeline(rec["return_date"], schedule, row.get("recent_team"), today)
        if not tl["games_left"]:
            return 1.0
        return max(0.0, 1.0 - tl["games_out"] / tl["games_left"])
    out = ASSUMED_GAMES_OUT.get(status)
    left = _games_left(schedule, row.get("recent_team")) if out else 0
    if not out or not left:
        return 1.0
    return max(0.0, 1.0 - min(out, left) / left)


def out_long(row, schedule, today=None):
    """True when he will miss at least the IR minimum of games: on a long-term
    list, or ESPN's return date is that many games away."""
    if row.get("injury_status") in ("IR", "PUP", "Sus", "NA"):
        return True
    rec = row.get("injury_report")
    if not isinstance(rec, dict) or not rec.get("return_date"):
        return False
    tl = timeline(rec["return_date"], schedule, row.get("recent_team"), today)
    return (tl["games_out"] or 0) >= LONG_ABSENCE_GAMES
