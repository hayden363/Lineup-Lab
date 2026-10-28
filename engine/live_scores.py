"""
LIVE SCORES — real in-game NFL scoring, free and public
=========================================================
Pulls ESPN's public scoreboard feed (the same JSON ESPN's own website
reads — no key, no signup, same "free and legal" bar as the RSS feeds in
engine/news.py) and reduces it to just what a live scoreboard needs:
score, quarter, clock, and game state (pre/in/post) for every game on
the current NFL week.

This is a separate concern from engine/data.py's season stats: that
layer is post-game box scores used to build SCORE/PROJ, refreshed once
a season/week is actually final. This one is *during* a game — no
predictive value yet, just "what's the score right now" — which is
also why the two are cached completely differently: a short TTL here
(scores change by the minute on Sundays) instead of a season-long one.

ESPN's scoreboard endpoint is undocumented/unofficial (there's no public
contract guaranteeing it won't change), so every field access below is
defensive — a malformed or missing field degrades to a blank scoreboard
rather than a 500.
"""

import time

import requests

from . import game_center

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# Short on purpose — live scores are exactly the kind of data where a
# 20-minute news-style cache would show a stale score for a whole
# quarter. Still long enough that a page full of people watching the
# same Sunday slate doesn't turn into a request per browser tab.
TTL_SECONDS = 20
_CACHE = {"at": 0, "games": []}


def _team_info(competitor):
    team = competitor.get("team") or {}
    return {
        "abbr": team.get("abbreviation"),
        "name": team.get("shortDisplayName") or team.get("displayName"),
        "score": int(competitor["score"]) if str(competitor.get("score", "")).isdigit() else None,
        "winner": bool(competitor.get("winner")),
        "record": next((r.get("summary") for r in competitor.get("records") or [] if r.get("type") == "total"), None),
    }


def _parse_event(event):
    try:
        comp = event["competitions"][0]
        status = comp.get("status") or {}
        status_type = status.get("type") or {}
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if home is None or away is None:
            return None
        home_abbr, away_abbr = _team_info(home)["abbr"], _team_info(away)["abbr"]
        teams = {str((c.get("team") or {}).get("id")): (c.get("team") or {}).get("abbreviation") for c in competitors}
        nets = [n for b in comp.get("broadcasts") or [] for n in (b.get("names") or [])]
        odds = game_center.parse_odds({"pickcenter": comp.get("odds") or []}, home_abbr, away_abbr)
        wx = game_center.parse_weather({"gameInfo": {"weather": event.get("weather") and {
            "temperature": event["weather"].get("temperature"), "displayValue": event["weather"].get("displayWeather") or event["weather"].get("displayValue"),
            "windSpeed": event["weather"].get("windSpeed")}, "venue": comp.get("venue")}})
        return {
            "badge": game_center.broadcast_badge(event.get("date")),
            "network": nets[0] if nets else None,
            "odds": odds, "weather": wx,
            "situation": game_center.situation(comp.get("situation"), home_abbr, away_abbr, teams)
            if (status_type.get("state") == "in") else None,
            "game_id": event.get("id"),
            "week": (event.get("week") or {}).get("number"),
            "kickoff": event.get("date"),
            "home": _team_info(home),
            "away": _team_info(away),
            # "pre" | "in" | "post" — the three states a scoreboard card cares about
            "state": status_type.get("state", "pre"),
            "period": status.get("period", 0),
            "display_clock": status.get("displayClock"),
            # e.g. "Final", "Wed 8:20 PM EDT", "10:42 - 3rd" — already
            # human-phrased by ESPN, no need to reconstruct it ourselves
            "status_detail": status_type.get("shortDetail") or status_type.get("detail"),
            "completed": bool(status_type.get("completed")),
        }
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def live_scoreboard(force=False):
    """Every game on the current NFL week, real-time when a game is
    actually being played. Never raises — a fetch failure just returns
    whatever was cached last (or an empty list on the very first call),
    since a scoreboard glitch shouldn't take down the rest of the app."""
    now = time.time()
    if not force and (now - _CACHE["at"]) < TTL_SECONDS:
        return _CACHE["games"]

    try:
        resp = requests.get(SCOREBOARD_URL, timeout=5)
        resp.raise_for_status()
        events = resp.json().get("events", [])
        games = [g for g in (_parse_event(e) for e in events) if g is not None]
        _CACHE["at"] = now
        _CACHE["games"] = games
    except Exception as e:
        print(f"[live_scores] couldn't fetch scoreboard: {e}")
        # keep serving the last good snapshot rather than blanking the
        # scoreboard over one flaky request
        _CACHE["at"] = now

    return _CACHE["games"]
