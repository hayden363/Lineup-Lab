"""
GAME BOX SCORE — the player stat lines inside one NFL game, plus your fantasy points
=====================================================================================
ESPN's public per-game summary feed (the same family as the scoreboard in
engine/live_scores.py: free, no key) lists every player's stat line for both
teams. This module reduces it to what the game panel shows:

  * a flat, merged line per player (a QB who also ran appears once, with both
    his passing and rushing lines),
  * fantasy points computed from the raw counting stats under the viewer's own
    league scoring (engine/scoring.py), not ESPN's,
  * a `mine` flag on anyone on the viewer's roster, matched by name, position
    and team (engine/consensus.match_key), so the panel can highlight them.

The summary endpoint is undocumented, so every access is defensive: anything
missing or malformed degrades to fewer players or blank stats, never a 500.
Fantasy points are only computed for QB/RB/WR/TE. Kickers and defenses show
their stat lines but no points here, and first-down and two-point scoring
isn't in the feed, so a league that pays for those reads slightly low.
"""

import copy
import re
import time

import pandas as pd
import requests

from . import consensus
from . import espn as espn_layer
from . import news as news_layer
from .scoring import ScoringSettings, compute_fantasy_points

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
TTL_SECONDS = 20          # same freshness as the scoreboard; many tabs share one fetch
CACHE_MAX = 64            # games kept; the oldest is dropped past this
_CACHE = {}               # game_id -> (fetched_at, parsed)
_RAW = {}                 # game_id -> the summary JSON behind that parse (the game center reads plays, odds, weather from it)

SKILL = ("QB", "RB", "WR", "TE")
GROUP_ORDER = {"QB": 0, "RB": 1, "FB": 1, "WR": 2, "TE": 3, "K": 4, "PK": 4}   # everyone else (defense, line) follows
_LINE_ORDER = {"QB": ("Passing", "Rushing"), "RB": ("Rushing", "Receiving"), "FB": ("Rushing", "Receiving"),
               "WR": ("Receiving", "Rushing"), "TE": ("Receiving", "Rushing"), "K": ("Kicking",), "PK": ("Kicking",)}
_TEAM_ALIAS = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}
_GAME_ID = re.compile(r"^\d{6,12}$")


def valid_game_id(game_id):
    return bool(_GAME_ID.match(str(game_id or "")))


def _team(abbr):
    a = str(abbr or "").upper()
    return _TEAM_ALIAS.get(a, a)


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _pairs(keys, stats):
    """(key, value) pairs for one stat row. ESPN packs some stats together
    ('completions/passingAttempts' = '22/30', 'sacks-sackYardsLost' = '2-15'),
    so those are split apart; everything else is one key to one value."""
    out = []
    for k, v in zip(keys or [], stats or []):
        k, v = str(k), str(v)
        for sep in ("/", "-"):
            if sep in k:
                ks, vs = k.split(sep), v.split(sep)
                if len(ks) == len(vs):
                    out.extend(zip(ks, vs))
                    break
        else:
            out.append((k, v))
    return out


_POS_BY_ESPN = None


def _position_by_espn_id():
    """{espn athlete id: position} from the cached id crosswalk (the same parquet engine/espn.py reads). ESPN's box
    score feed stopped sending a position for each athlete, and without one nothing downstream (fantasy points,
    sorting, the viewer's `mine` highlight) works. {} when the crosswalk isn't on disk; callers then infer."""
    global _POS_BY_ESPN
    if _POS_BY_ESPN is not None:
        return _POS_BY_ESPN
    out = {}
    try:
        import os
        path = os.path.join(espn_layer.CACHE_DIR, "id_crosswalk.parquet")
        if os.path.exists(path):
            df = pd.read_parquet(path, columns=["espn_id", "position"]).dropna()
            out = {str(int(float(a))): str(p).upper() for a, p in zip(df["espn_id"], df["position"])}
    except Exception as e:
        print(f"[boxscore] couldn't load positions from the id crosswalk: {e}")
    _POS_BY_ESPN = out
    return out


def _infer_position(stats):
    """Last resort when neither ESPN nor the crosswalk names a position: kickers and quarterbacks are unmistakable
    from their stat categories; anyone else stays None."""
    if "kicking" in stats:
        return "K"
    if (stats.get("passing") or {}).get("passingAttempts", 0) >= 5:
        return "QB"
    return None


def parse_summary(js):
    """{teams: [{abbr, name, players: [...]}]} from ESPN's summary JSON.
    Each player: {athlete_id, name, position, team, headshot, stats:
    {category: {key: number}}}. Returns teams=[] for anything unusable."""
    teams = []
    try:
        blocks = (js.get("boxscore") or {}).get("players") or []
    except AttributeError:
        return {"teams": []}
    for block in blocks:
        t = block.get("team") or {}
        abbr = t.get("abbreviation")
        by_id = {}
        for cat in block.get("statistics") or []:
            cname = cat.get("name")
            if not cname:
                continue
            for a in cat.get("athletes") or []:
                ath = a.get("athlete") or {}
                aid = str(ath.get("id") or "")
                if not aid:
                    continue
                p = by_id.setdefault(aid, {
                    "athlete_id": aid, "name": ath.get("displayName"),
                    "position": (ath.get("position") or {}).get("abbreviation"),
                    "team": abbr, "headshot": (ath.get("headshot") or {}).get("href"), "stats": {}})
                p["stats"].setdefault(cname, {}).update(
                    {k: _num(v) for k, v in _pairs(cat.get("keys"), a.get("stats"))})
        pos_map = _position_by_espn_id()
        for p in by_id.values():
            if not p.get("position"):
                p["position"] = pos_map.get(p["athlete_id"]) or _infer_position(p["stats"])
        teams.append({"abbr": abbr, "name": t.get("shortDisplayName") or t.get("displayName"),
                      "logo": news_layer.team_logo(_team(abbr)) or t.get("logo"),
                      "players": list(by_id.values())})
    return {"teams": teams}


def _g(p, cat, key):
    return (p["stats"].get(cat) or {}).get(key, 0.0)


def fantasy_row(p):
    """The nflverse-named counting stats scoring.compute_fantasy_points reads."""
    return {
        "passing_yards": _g(p, "passing", "passingYards"), "passing_tds": _g(p, "passing", "passingTouchdowns"),
        "interceptions": _g(p, "passing", "interceptions"),
        "rushing_yards": _g(p, "rushing", "rushingYards"), "rushing_tds": _g(p, "rushing", "rushingTouchdowns"),
        "receiving_yards": _g(p, "receiving", "receivingYards"), "receiving_tds": _g(p, "receiving", "receivingTouchdowns"),
        "receptions": _g(p, "receiving", "receptions"),
        "rushing_fumbles_lost": _g(p, "fumbles", "fumblesLost"),
        "position": p.get("position"),
    }


def _line(p):
    """Short readable stat lines, one per category the player has numbers in."""
    s = p["stats"]
    out = []
    if "passing" in s:
        c = s["passing"]
        out.append(("Passing", f"{c.get('completions', 0):.0f}/{c.get('passingAttempts', 0):.0f}, "
                               f"{c.get('passingYards', 0):.0f} yds, {c.get('passingTouchdowns', 0):.0f} TD, "
                               f"{c.get('interceptions', 0):.0f} INT"))
    if "rushing" in s:
        c = s["rushing"]
        out.append(("Rushing", f"{c.get('rushingAttempts', c.get('carries', 0)):.0f} car, {c.get('rushingYards', 0):.0f} yds, "
                               f"{c.get('rushingTouchdowns', 0):.0f} TD"))
    if "receiving" in s:
        c = s["receiving"]
        out.append(("Receiving", f"{c.get('receptions', 0):.0f} rec, {c.get('receivingYards', 0):.0f} yds, "
                                 f"{c.get('receivingTouchdowns', 0):.0f} TD"
                                 + (f", {c['receivingTargets']:.0f} tgt" if "receivingTargets" in c else "")))
    if "kicking" in s:
        c = s["kicking"]
        out.append(("Kicking", f"{c.get('fieldGoalsMade', 0):.0f}/{c.get('fieldGoalAttempts', 0):.0f} FG, "
                               f"{c.get('extraPointsMade', 0):.0f}/{c.get('extraPointAttempts', 0):.0f} XP"))
    if "defensive" in s:
        c = s["defensive"]
        out.append(("Defense", f"{c.get('totalTackles', 0):.0f} tkl, {c.get('sacks', 0):g} sk"))
    if "fumbles" in s and s["fumbles"].get("fumblesLost"):
        out.append(("Fumbles", f"{s['fumbles']['fumblesLost']:.0f} lost"))
    pref = _LINE_ORDER.get(p.get("position"), ())
    out.sort(key=lambda ab: pref.index(ab[0]) if ab[0] in pref else len(pref))     # stable: the rest keep feed order
    return [{"label": a, "text": b} for a, b in out]


def _mine_team(mine_keys, p):
    """The roster team for this box-score player, or None. Name+position first; when the feed gave no position,
    fall back to the name alone so a rostered player is never dropped for a missing field."""
    hit = mine_keys.get(consensus.match_key(p.get("name"), p.get("position")))
    if hit is None and not p.get("position"):
        nm = consensus.normalize_name(p.get("name"))
        hit = next((v for k, v in mine_keys.items() if k.split("|")[0] == nm), None)
    return hit


def annotate(parsed, roster, scoring=None):
    """Adds `lines`, `fantasy_points` (QB/RB/WR/TE only, else None) and `mine`
    to every player, sorts each team mine-first then by points, and returns
    {teams, mine_points, mine_count}. `roster` is a list of {player_display_name
    or name, position, recent_team or team}; `scoring` is a scoring dict or None
    for full PPR."""
    parsed = copy.deepcopy(parsed)   # the cached parse is shared; never edit it in place
    settings = ScoringSettings.from_dict(scoring) if scoring else ScoringSettings.from_preset("ppr")
    mine_keys = {}
    for r in roster or []:
        nm = r.get("player_display_name") or r.get("name")
        mine_keys[consensus.match_key(nm, r.get("position"))] = _team(r.get("recent_team") or r.get("team"))

    mine_points, mine_count = 0.0, 0
    for t in parsed["teams"]:
        skill = [p for p in t["players"] if p.get("position") in SKILL]
        if skill:
            pts = compute_fantasy_points(pd.DataFrame([fantasy_row(p) for p in skill]), settings)
            for p, v in zip(skill, pts):
                p["fantasy_points"] = round(float(v), 1)
        for p in t["players"]:
            p.setdefault("fantasy_points", None)
            p["lines"] = _line(p)
            want = _mine_team(mine_keys, p)
            p["mine"] = want is not None and (not want or want == _team(p.get("team")))
            if p["mine"]:
                mine_count += 1
                mine_points += p["fantasy_points"] or 0.0
            p.pop("stats", None)
        # QBs, then RBs, WRs, TEs, kickers, then the rest; best fantasy day first inside each group
        t["players"].sort(key=lambda p: (GROUP_ORDER.get(p.get("position"), 9),
                                         -(p["fantasy_points"] if p["fantasy_points"] is not None else -1e9), p.get("name") or ""))
    return {"teams": parsed["teams"], "mine_points": round(mine_points, 1), "mine_count": mine_count}


def short_stat(lines):
    """A player's day in one short line for My Team: his main stat line, then only the yards (and TDs) of a second one.
    '22 car, 89 yds, 1 TD · 3 rec yds'. Zero TDs, zero INTs and targets are left out."""
    out = []
    for ln in lines or []:
        label, text = ln.get("label"), str(ln.get("text") or "")
        if label not in ("Passing", "Rushing", "Receiving", "Kicking"):
            continue
        text = re.sub(r", 0 (TD|INT)\b", "", re.sub(r", \d+ tgt", "", text))
        if out:
            m = re.search(r"(-?\d+) yds(, \d+ TD)?", text)
            if not m or (m.group(1) == "0" and not m.group(2)):
                continue
            text = f"{m.group(1)} {'rush' if label == 'Rushing' else 'rec'} yds{m.group(2) or ''}"
        out.append(text)
    return " · ".join(out)


def stat_lines(parsed, roster):
    """{player_id: short stat line} for the roster players found in a parsed box score, matched on name, position and
    team like annotate() (name and team alone when the feed gave no position). `roster`: {player_id, name, position, team}."""
    by_key, by_name = {}, {}
    for t in (parsed or {}).get("teams", []):
        for p in t.get("players", []):
            team = _team(p.get("team") or t.get("abbr"))
            by_key[(consensus.match_key(p.get("name"), p.get("position")), team)] = p
            if not p.get("position"):
                by_name[(consensus.normalize_name(p.get("name")), team)] = p
    out = {}
    for r in roster or []:
        team = _team(r.get("team"))
        p = by_key.get((consensus.match_key(r.get("name"), r.get("position")), team)) or by_name.get((consensus.normalize_name(r.get("name")), team))
        text = short_stat(_line(p)) if p else ""
        if text:
            out[str(r.get("player_id"))] = text
    return out


def game_boxscore(game_id, force=False, keep_raw=True):
    """Parsed summary for one game id, cached TTL_SECONDS. Raises ValueError
    for a malformed id; a failed fetch returns the last good copy, else
    {"teams": []} — a flaky ESPN response should never become a 500.
    keep_raw=False (My Team's game lines) does not hold the large raw feed in memory; the game center, which needs it,
    calls with the default and gets a fresh fetch when only the parse is cached."""
    if not valid_game_id(game_id):
        raise ValueError("bad game id")
    now = time.time()
    hit = _CACHE.get(game_id)
    if hit and not force and now - hit[0] < TTL_SECONDS and (not keep_raw or game_id in _RAW):
        return hit[1]
    try:
        resp = requests.get(SUMMARY_URL, params={"event": game_id}, timeout=5)
        resp.raise_for_status()
        raw = resp.json()
        parsed = parse_summary(raw)
    except Exception as e:
        print(f"[boxscore] couldn't fetch game {game_id}: {e}")
        return hit[1] if hit else {"teams": []}
    if len(_CACHE) >= CACHE_MAX:
        oldest = min(list(_CACHE.items()), key=lambda kv: kv[1][0])[0]     # list(): several games can load at once
        _CACHE.pop(oldest, None)
    _CACHE[game_id] = (now, parsed)
    if keep_raw:
        _RAW[game_id] = raw
    else:
        _RAW.pop(game_id, None)
    for k in [k for k in list(_RAW) if k not in _CACHE]:
        _RAW.pop(k, None)
    return parsed


def game_summary_raw(game_id):
    """The raw summary JSON for a game already fetched by game_boxscore (or {})."""
    return _RAW.get(game_id) or {}


def athlete_index(parsed, roster):
    """({athlete_id: (name, position, team)}, {athlete ids on the viewer's roster}) for a parsed box score, using the
    same name+position+team matching annotate() uses for `mine`."""
    mine_keys = {}
    for r in roster or []:
        nm = r.get("player_display_name") or r.get("name")
        mine_keys[consensus.match_key(nm, r.get("position"))] = _team(r.get("recent_team") or r.get("team"))
    names, mine = {}, set()
    for t in (parsed or {}).get("teams", []):
        for p in t.get("players", []):
            names[p["athlete_id"]] = (p.get("name"), p.get("position"), p.get("team") or t.get("abbr"))
            want = _mine_team(mine_keys, p)
            if want is not None and (not want or want == _team(p.get("team") or t.get("abbr"))):
                mine.add(p["athlete_id"])
    return names, mine
