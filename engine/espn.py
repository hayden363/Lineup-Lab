"""
ESPN LEAGUE SYNC
================
Real ESPN Fantasy league sync, read-only — via the `espn-api` package
(actively maintained on PyPI, MIT licensed) rather than hand-rolling
ESPN's undocumented private API and its cookie-based auth ourselves.

Public league: no cookies needed, works with just the league ID.
Private league: espn_s2 + SWID, the same two session cookies Settings
already collects and stores encrypted (engine/db.py get_espn_secrets /
SECRET_SETTINGS_FIELDS) — proving it's really you, the same way any
browser session cookie does. Never your actual ESPN password, and
nothing here asks for one.

Shaped to match engine/sleeper.py's league_snapshot() as closely as
ESPN's actual data allows, so the rest of the app can eventually treat
an ESPN-connected team the same way it treats a Sleeper one. This file
is the data layer only — wiring it into My Team / Waivers / Trade
(engine/tools.py) so an ESPN team gets the same real DEF/K/rookie
fallback handling Sleeper's does is the next step, not done here yet.

CAVEAT, read before wiring further: unlike every other data source in
this app, this module hasn't been exercised against a real live ESPN
league (no test league available while building it) — the shapes below
come from reading espn-api's own source, not from a verified response.
Treat the first real connection attempt as the actual test.
"""

import os
import re
import time

import pandas as pd

from .data import CACHE_DIR

_LEAGUE_ID_RE = re.compile(r"(?:leagueId=)?(\d{5,})")


def parse_league_id(raw):
    """Bare ID or a pasted ESPN league URL (fantasy.espn.com/football/
    team?leagueId=1234567 or .../league?leagueId=1234567) -> the numeric
    league ID, or None if nothing that looks like one is found. Same
    idea as sleeper.parse_league_id."""
    if not raw:
        return None
    m = _LEAGUE_ID_RE.search(raw.strip())
    return m.group(1) if m else None

# ----------------------------------------------------------------------
# ID CROSSWALK — espn player id -> gsis id, so ESPN rosters can be priced
# by the same board this app already builds from real nflverse stats.
# Deliberately the SAME cache file engine/sleeper.py's id_crosswalk()
# uses (nfl_data_py.import_ids() is one dataframe with both a
# sleeper_id and an espn_id column) — sharing it avoids a second
# redundant download of the same ~12k-row file; each module just
# projects the columns it needs out of it.
# ----------------------------------------------------------------------
CROSSWALK_TTL = 7 * 24 * 60 * 60
_CROSSWALK = None


def id_crosswalk(force=False):
    """espn_id (str) -> gsis player_id."""
    global _CROSSWALK
    if _CROSSWALK is not None and not force:
        return _CROSSWALK

    path = os.path.join(CACHE_DIR, "id_crosswalk.parquet")
    if not force and os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CROSSWALK_TTL:
        df = pd.read_parquet(path)
    else:
        import nfl_data_py as nfl
        df = nfl.import_ids()
        df.to_parquet(path)

    df = df.dropna(subset=["espn_id", "gsis_id"]).copy()
    df["espn_id"] = df["espn_id"].astype(float).astype(int).astype(str)
    _CROSSWALK = dict(zip(df["espn_id"], df["gsis_id"]))
    return _CROSSWALK


# ----------------------------------------------------------------------
# SCORING — ESPN's settings.scoring_format is a list of {id, points, ...}
# keyed by ESPN's own numeric stat ids (espn_api.football.constant
# .SETTINGS_SCORING_FORMAT_MAP is the id -> {abbr, label} half of this;
# this is just the subset of those ids this app's ScoringSettings
# actually models). Same idea as sleeper.SLEEPER_SCORING_MAP, different
# source shape.
# ----------------------------------------------------------------------
ESPN_STAT_ID_MAP = {
    3: "pass_yard", 4: "pass_td", 20: "interception",
    24: "rush_yard", 25: "rush_td",
    41: "reception", 42: "rec_yard", 43: "rec_td",
    72: "fumble_lost",  # "Total Fumbles Lost" — one combined field, same as this app's own model
    62: "two_pt",        # "Total 2pt Conversions" — ESPN splits pass/rush/rec 2pt into 3 stats; this is the combined one
}


def scoring_from_espn(league) -> dict:
    overrides = {}
    for item in league.settings.scoring_format:
        key = ESPN_STAT_ID_MAP.get(item.get("id"))
        if key:
            overrides[key] = item.get("points", 0)
    return overrides


def resolve_year():
    """The live ESPN/fantasy season year — a different number from this
    app's own STATS season (engine/data.py's resolve_season(), which lags
    a season behind until nflverse publishes the current one's games; see
    README). Sleeper's live NFL state is a free, already-fetched source of
    "what year is it really" independent of our stats season; falls back
    to the calendar year if that's ever unavailable. Used everywhere an
    ESPN call needs a `year` and the caller didn't pass one explicitly."""
    from . import sleeper
    try:
        return int(sleeper.get_nfl_state().get("season"))
    except Exception:
        import datetime
        return datetime.date.today().year


def get_league(league_id, year, espn_s2=None, swid=None):
    """The raw espn-api League client — one real HTTP fetch, everything
    else (teams, rosters, schedule) already loaded onto it in memory.
    Public, not `_client`: my_team_espn (engine/tools.py) needs the full
    object, not just the flattened league_snapshot() dict below."""
    from espn_api.football import League  # imported lazily — optional dependency, only needed here
    return League(league_id=int(league_id), year=int(year), espn_s2=espn_s2 or None, swid=swid or None)


def owner_name(team):
    if not team.owners:
        return None
    o = team.owners[0]
    name = f"{o.get('firstName', '')} {o.get('lastName', '')}".strip()
    return name or o.get("displayName")


def league_snapshot(league_id, year, espn_s2=None, swid=None):
    """Everything a client needs to render 'your league': scoring
    settings, every team's real roster. A roster player is translated to
    our own gsis_id where the crosswalk covers them (most of the skill
    positions); DEF/K/anyone the crosswalk misses comes through with
    gsis_id=None and their real ESPN-provided name/team/position intact
    — the same "unscored, needs a fallback" shape Sleeper's raw rosters
    already produce for engine/tools.py to resolve."""
    league = get_league(league_id, year, espn_s2, swid)
    crosswalk = id_crosswalk()

    teams = []
    for t in league.teams:
        roster = []
        for p in t.roster:
            roster.append({
                "espn_id": str(p.playerId),
                "gsis_id": crosswalk.get(str(p.playerId)),
                "player_display_name": p.name,
                "position": p.position,
                "recent_team": p.proTeam,
                "lineup_slot": p.lineupSlot,      # "RB", "BE", "IR", "D/ST", etc.
                "injury_status": p.injuryStatus if p.injuryStatus not in ("ACTIVE", "NORMAL") else None,
            })
        teams.append({
            "team_id": t.team_id,
            "team_name": t.team_name,
            "logo_url": t.logo_url or None,
            "owner": owner_name(t),
            "wins": t.wins, "losses": t.losses, "ties": t.ties,
            "roster": roster,
        })

    return {
        "league_id": str(league_id),
        "league_name": league.settings.name,
        "season": year,
        "scoring": scoring_from_espn(league),
        "team_count": len(teams),
        "teams": teams,
    }


# ----------------------------------------------------------------------
# ROSTER RESOLUTION — the two pieces engine/tools.py's my_team_espn()
# needs to reuse the exact same _roster_players()/_defense_row()/
# _kicker_row()/_role_rank_row() machinery Sleeper rosters already go
# through, instead of a second parallel scoring pipeline.
# ----------------------------------------------------------------------
BENCH_SLOTS = {"BE", "IR"}


def roster_lineup(team):
    """(raw_ids, starters, slot_labels) in the exact shape
    engine/tools.py's _roster_players()/_team_total() already expect.
    A D/ST entry uses its real team abbreviation as the id — matching
    Sleeper's own convention, where a D/ST's "player id" already IS the
    team code — so the existing _defense_row/resolve_defense_row code
    (keyed on a team abbreviation, not a crosswalk-able id) works
    completely unmodified. Everyone else uses their espn_id, which the
    crosswalk in this file resolves to a gsis_id."""
    raw_ids, starters, slot_labels = [], [], []
    for p in team.roster:
        raw_id = p.proTeam if p.position == "D/ST" else str(p.playerId)
        raw_ids.append(raw_id)
        if p.lineupSlot not in BENCH_SLOTS:
            starters.append(raw_id)
            slot_labels.append(p.lineupSlot)
    return raw_ids, starters, slot_labels


def build_unscored_resolver(league):
    """A resolve_unscored_player-shaped function (see
    sleeper.resolve_unscored_player, and _roster_players' `resolve_unscored`
    param in engine/tools.py) built from this league's own already-fetched
    rosters — no extra request, since espn-api loads every team's full
    roster along with the league itself.

    Real name/team/position/injury status straight from ESPN. Position is
    normalized to this app's own naming ("D/ST" -> "DEF") since
    engine/tools.py's dispatch checks for "DEF" specifically. No
    depth_chart_order: ESPN doesn't expose a live depth-chart rank the
    way Sleeper does, so the role-baseline rookie/backup fallback just
    has nothing to key off for an ESPN-only player and degrades to the
    plain unscored (PROJ 0.0) case rather than crashing — a real,
    disclosed gap, not a bug.

    One real oddity found while building this against a live league: a
    "Team QB" format (some leagues roster a whole real NFL team's
    offense as one QB-slot unit instead of an individual quarterback —
    espn-api reports these as position "TQB" with a negative pseudo
    player id, same convention as D/ST). This app has no concept of a
    team-as-QB unit to score it with, so it correctly falls through to
    the generic "unscored" case in _roster_players — the fix here is
    just not fabricating a headshot URL for a pseudo-player id that
    isn't a real individual (it isn't D/ST either, so the espncdn
    per-player headshot pattern below would 404 on a made-up id)."""
    by_id = {}
    for t in league.teams:
        for p in t.roster:
            is_real_player = p.playerId > 0
            raw_id = p.proTeam if p.position == "D/ST" else str(p.playerId)
            headshot_url = None
            if p.position == "D/ST":
                headshot_url = f"https://a.espncdn.com/i/teamlogos/nfl/500/{p.proTeam.lower()}.png"
            elif is_real_player:
                headshot_url = f"https://a.espncdn.com/i/headshots/nfl/players/full/{p.playerId}.png"
            by_id[raw_id] = {
                "position": "DEF" if p.position == "D/ST" else p.position,
                "player_display_name": p.name,
                "recent_team": p.proTeam,
                "headshot_url": headshot_url,
                "depth_chart_order": None,
            }
    return lambda raw_id: by_id.get(raw_id)
