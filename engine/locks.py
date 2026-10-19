"""
KICKOFF LOCKS — when each player's lineup slot freezes
=========================================================
A slot locks the moment that player's own game kicks off, not at a single
weekly deadline: a Thursday-night player locks Thursday, a Sunday player
Sunday, a Monday player Monday. Kickoff times come from the schedule feed
(`gameday` + `gametime`, which nflverse publishes in Eastern time).

A team on a bye has no game that week, so it has no lock time and is never
locked (it can't score, but the slot stays editable).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


def kickoff(schedule, team, week):
    """Timezone-aware kickoff datetime for `team` in `week`, or None (bye, or
    the feed has no time yet)."""
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    g = s[(s["week"] == week) & ((s["home_team"] == team) | (s["away_team"] == team))]
    if g.empty:
        return None
    day, t = g.iloc[0].get("gameday"), g.iloc[0].get("gametime")
    if not isinstance(day, str) or not isinstance(t, str) or pd.isna(day) or pd.isna(t):
        return None
    try:
        return datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    except ValueError:
        return None


def is_locked(schedule, team, week, now=None):
    """True once the player's game has kicked off. `now` defaults to the real
    current time and exists so tests can freeze the clock."""
    ko = kickoff(schedule, team, week)
    if ko is None:
        return False
    return (now or datetime.now(ET)) >= ko


def lock_status(schedule, team, week, now=None):
    """{kickoff (ISO), locked, bye} for one player's slot."""
    ko = kickoff(schedule, team, week)
    return {"kickoff": ko.isoformat() if ko else None,
            "locked": bool(ko and (now or datetime.now(ET)) >= ko),
            "bye": ko is None}
