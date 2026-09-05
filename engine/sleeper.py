"""
LEAGUE SYNC — Sleeper
=======================
WalterPicks' other core pitch is "advice custom to your exact league" via
platform sync. Sleeper's API is fully public and read-only (just a league
ID — no login, no OAuth, no credentials), so it's the cleanest place to
start. ESPN/Yahoo/CBS support is the natural next step (their private
leagues need a cookie the user copies from their own browser session --
never something we'd collect via a login form).

Player identity crosswalk (Sleeper's numeric IDs -> our gsis-based
player_id) comes from nfl_data_py.import_ids(), which is itself a free,
public table nflverse maintains -- it links dozens of platforms' IDs
together, including Sleeper's. We only ever use it as an ID map, never to
pull grades from any paid source.
"""

import json
import os
import re
import time

import pandas as pd
import requests

from .data import CACHE_DIR
from .scoring import ScoringSettings

SLEEPER_BASE = "https://api.sleeper.app/v1"
AVATAR_BASE = "https://sleepercdn.com/avatars/thumbs"
JSON_TTL = 15 * 60         # league/roster data: refresh every 15 min
CROSSWALK_TTL = 24 * 60 * 60  # id crosswalk: refresh daily
TRENDING_TTL = 30 * 60     # trending adds/drops: refresh every 30 min
PLAYERS_TTL = 24 * 60 * 60    # full player list (~5-15MB): Sleeper asks for at most once/day

# accepts a bare league ID or any Sleeper URL that has one in it, e.g.
# https://sleeper.com/leagues/289646328504385536  or  .../leagues/289646328504385536/team
LEAGUE_ID_RE = re.compile(r"(\d{10,25})")


def parse_league_id(raw):
    """Bare ID or a pasted Sleeper league URL -> the numeric league ID, or
    None if nothing that looks like one is found."""
    if not raw:
        return None
    raw = raw.strip()
    m = LEAGUE_ID_RE.search(raw)
    return m.group(1) if m else None


def avatar_url(avatar_id):
    return f"{AVATAR_BASE}/{avatar_id}" if avatar_id else None


def _json_cache_path(name):
    return os.path.join(CACHE_DIR, f"sleeper_{name}.json")


# Process-lifetime in-memory front-cache, same idea as data.py's _MEM —
# without it, a "cache hit" here still meant re-reading and re-parsing the
# on-disk JSON from scratch on every single call. Harmless for the small
# per-league payloads, but all_players() (~5-15MB, every NFL player ever)
# is called once per unscored roster slot (DEF/K/crosswalk-miss) — a real
# league sync calls it dozens of times per request (measured: 97 calls,
# 8.2s of an 11.4s my_team() request, almost entirely JSON parsing the
# same bytes over and over). Keyed by cache_name, same as the disk cache.
_MEM: dict = {}


def _cached_get(url, cache_name, ttl, force=False):
    if not force:
        mem = _MEM.get(cache_name)
        if mem and (time.time() - mem[0]) < ttl:
            return mem[1]
        path = _json_cache_path(cache_name)
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if (time.time() - mtime) < ttl:
                with open(path) as f:
                    data = json.load(f)
                _MEM[cache_name] = (mtime, data)
                return data
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    with open(_json_cache_path(cache_name), "w") as f:
        json.dump(data, f)
    _MEM[cache_name] = (time.time(), data)
    return data


def get_league(league_id, force=False):
    return _cached_get(f"{SLEEPER_BASE}/league/{league_id}", f"league_{league_id}", JSON_TTL, force)


def get_rosters(league_id, force=False):
    return _cached_get(f"{SLEEPER_BASE}/league/{league_id}/rosters", f"rosters_{league_id}", JSON_TTL, force)


def get_users(league_id, force=False):
    return _cached_get(f"{SLEEPER_BASE}/league/{league_id}/users", f"users_{league_id}", JSON_TTL, force)


def get_nfl_state(force=False):
    """Sleeper's live 'what week is it' — the real NFL calendar, independent
    of which season our own stats engine has data for."""
    return _cached_get(f"{SLEEPER_BASE}/state/nfl", "nfl_state", 60 * 60, force)


def get_league_drafts(league_id, force=False):
    return _cached_get(f"{SLEEPER_BASE}/league/{league_id}/drafts", f"drafts_{league_id}", JSON_TTL, force)


def get_draft(draft_id, force=False):
    """Live drafts refresh fast — short TTL so pick tracking feels real-time."""
    return _cached_get(f"{SLEEPER_BASE}/draft/{draft_id}", f"draft_{draft_id}", 15, force)


def get_draft_picks(draft_id, force=False):
    return _cached_get(f"{SLEEPER_BASE}/draft/{draft_id}/picks", f"draftpicks_{draft_id}", 15, force)


def build_pick_order(draft):
    """The full pick_no -> roster_id schedule for a snake draft, computed
    from slot_to_roster_id (who sits in which draft slot) — Sleeper's
    /picks endpoint only tells you picks already made, not who's on the
    clock next, so this fills in the rest of the board."""
    slot_to_roster = {int(k): v for k, v in (draft.get("slot_to_roster_id") or {}).items()}
    teams = draft.get("settings", {}).get("teams") or len(slot_to_roster)
    rounds = draft.get("settings", {}).get("rounds") or 15
    is_snake = draft.get("type", "snake") == "snake"

    order = []
    pick_no = 1
    for rnd in range(1, rounds + 1):
        slots = range(1, teams + 1)
        if is_snake and rnd % 2 == 0:
            slots = range(teams, 0, -1)
        for slot in slots:
            order.append({"pick_no": pick_no, "round": rnd, "draft_slot": slot,
                           "roster_id": slot_to_roster.get(slot)})
            pick_no += 1
    return order


def get_matchups(league_id, week, force=False):
    """Head-to-head fantasy matchups for one week: a list of per-roster
    entries sharing a matchup_id with their opponent."""
    return _cached_get(f"{SLEEPER_BASE}/league/{league_id}/matchups/{week}",
                        f"matchups_{league_id}_{week}", JSON_TTL, force)


def get_trending(kind="add", lookback_hours=48, limit=50, force=False):
    """Real platform-wide add/drop counts over the last `lookback_hours` —
    Sleeper's own 'who's trending' signal, not something we're inferring."""
    url = f"{SLEEPER_BASE}/players/nfl/trending/{kind}?lookback_hours={lookback_hours}&limit={limit}"
    return _cached_get(url, f"trending_{kind}_{lookback_hours}_{limit}", TRENDING_TTL, force)


def trending_gsis_counts(kind="add", lookback_hours=48, limit=100):
    """{gsis_player_id: add/drop count} — trending data translated through
    the id crosswalk so it can be joined onto our board by player_id."""
    crosswalk = id_crosswalk()
    raw = get_trending(kind=kind, lookback_hours=lookback_hours, limit=limit)
    out = {}
    for row in raw:
        gsis = crosswalk.get(str(row.get("player_id")))
        if gsis:
            out[gsis] = row.get("count", 0)
    return out


def all_players(force=False):
    """Sleeper's full player list — the same data every real Sleeper league
    (including yours) is built on. Cached at most once/day per Sleeper's own
    guidance for this endpoint.

    This is the freshest 'is this player actually still in the league'
    signal available to us: our own season stats lag (see engine/data.py —
    the app may be valuing players off a season that isn't the live one),
    so a player who retired or went unsigned after that season would still
    look fine by the numbers alone. Sleeper's live `team` field catches
    that: no current NFL team means they can't really be added in any
    fantasy league right now, whatever the reason."""
    return _cached_get(f"{SLEEPER_BASE}/players/nfl", "all_players", PLAYERS_TTL, force)


def live_injury_statuses(force=False):
    """gsis_id -> current injury designation (Out/Doubtful/Questionable/...),
    straight from Sleeper's live player list — the actual "is this real
    person playing this week" signal, refreshed on Sleeper's own cadence
    (see all_players), not tied to whatever stat season the app's box-score
    data happens to be pinned to (engine/data.py's season resolver, which
    can genuinely lag a full season behind — see README). A player's own
    box-score-derived metrics can be perfectly real and still describe a
    season that's over; this field describes right now."""
    players = all_players(force=force)
    crosswalk = id_crosswalk(force=force)
    out = {}
    for sleeper_id, p in players.items():
        status = p.get("injury_status")
        if not status:
            continue
        gsis_id = crosswalk.get(sleeper_id)
        if gsis_id:
            out[gsis_id] = status
    return out


_INACTIVE_GSIS_IDS = None


def inactive_gsis_ids(force=False):
    """gsis_ids (our player_id, same as everywhere else in this app) for
    players Sleeper currently has no NFL team on record for — retired,
    released-and-unsigned, whatever the reason, they're not addable in a
    real league right now."""
    global _INACTIVE_GSIS_IDS
    if _INACTIVE_GSIS_IDS is not None and not force:
        return _INACTIVE_GSIS_IDS
    players = all_players(force=force)
    crosswalk = id_crosswalk(force=force)
    out = set()
    for sleeper_id, p in players.items():
        if not p.get("team"):
            gsis_id = crosswalk.get(sleeper_id)
            if gsis_id:
                out.add(gsis_id)
    _INACTIVE_GSIS_IDS = out
    return out


_CROSSWALK = None


def id_crosswalk(force=False):
    """sleeper_id (str) -> gsis player_id, cached to disk (~12k rows, cheap)."""
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

    df = df.dropna(subset=["sleeper_id", "gsis_id"]).copy()
    df["sleeper_id"] = df["sleeper_id"].astype(float).astype(int).astype(str)
    _CROSSWALK = dict(zip(df["sleeper_id"], df["gsis_id"]))
    return _CROSSWALK


SLEEPER_SCORING_MAP = {
    "rec": "reception",
    "pass_yd": "pass_yard",
    "pass_td": "pass_td",
    "pass_int": "interception",
    "rush_yd": "rush_yard",
    "rush_td": "rush_td",
    "rec_yd": "rec_yard",
    "rec_td": "rec_td",
    "fum_lost": "fumble_lost",
    "rush_2pt": "two_pt",
}


def scoring_from_sleeper(scoring_settings: dict) -> ScoringSettings:
    overrides = {}
    for sleeper_key, our_key in SLEEPER_SCORING_MAP.items():
        if sleeper_key in scoring_settings:
            overrides[our_key] = scoring_settings[sleeper_key]
    return ScoringSettings.from_dict(overrides)


def league_snapshot(league_id, force=False):
    """Everything a client needs to render 'your league': scoring settings
    (mapped to our ScoringSettings), and each roster's players translated
    to our gsis player_id, joined to owner display names."""
    league = get_league(league_id, force=force)
    rosters = get_rosters(league_id, force=force)
    users = get_users(league_id, force=force)
    crosswalk = id_crosswalk()

    user_by_id = {u["user_id"]: u for u in users}
    teams = []
    all_rostered = set()
    for r in rosters:
        sleeper_players = r.get("players") or []
        gsis_players = [crosswalk[p] for p in sleeper_players if p in crosswalk]
        all_rostered.update(gsis_players)
        owner = user_by_id.get(r.get("owner_id"), {})
        team_name = (owner.get("metadata") or {}).get("team_name") or owner.get("display_name") or f"Team {r.get('roster_id')}"
        # a custom team logo (roster.metadata.avatar) wins if the league set
        # one; otherwise fall back to the owner's own Sleeper profile picture
        team_avatar = (r.get("metadata") or {}).get("avatar") or owner.get("avatar")
        teams.append({
            "roster_id": r.get("roster_id"),
            "owner": owner.get("display_name"),
            "owner_avatar_url": avatar_url(owner.get("avatar")),
            "team_name": team_name,
            "avatar_url": avatar_url(team_avatar),
            "player_ids": gsis_players,
        })

    settings = scoring_from_sleeper(league.get("scoring_settings") or {})
    return {
        "league_id": league_id,
        "league_name": league.get("name"),
        "league_avatar_url": avatar_url(league.get("avatar")),
        "season": league.get("season"),
        "total_rosters": league.get("total_rosters"),
        "scoring": settings.as_dict(),
        "teams": teams,
        "rostered_player_ids": sorted(all_rostered),
    }


def matchups_for_week(league_id, week):
    """Every real head-to-head pairing in the league for one week, from the
    league's own schedule — [{matchup_id, roster_ids: [a, b]}, ...]. A bye
    (odd roster count, or a team with no pair) comes back with one entry
    and a single roster_id."""
    matchups = get_matchups(league_id, week)
    by_matchup = {}
    for m in matchups:
        mid = m.get("matchup_id")
        if mid is None:
            continue  # team has no matchup set this week (bye / not scheduled)
        by_matchup.setdefault(mid, []).append(m["roster_id"])
    return [{"matchup_id": mid, "roster_ids": roster_ids} for mid, roster_ids in by_matchup.items()]


def starters_for_week(league_id, week):
    """roster_id -> ordered list of starting player_ids (Sleeper's own raw
    ids, not yet translated to our gsis player_id) for that specific week —
    straight from Sleeper's matchup data, so it reflects whatever real
    lineup the league is actually configured with (including multi-FLEX),
    not something we reconstruct ourselves. Empty-slot placeholders ("0")
    are dropped."""
    matchups = get_matchups(league_id, week)
    out = {}
    for m in matchups:
        rid = m.get("roster_id")
        if rid is None:
            continue
        out[rid] = [pid for pid in (m.get("starters") or []) if pid and pid != "0"]
    return out


def roster_level_starters(league_id, force=False):
    """roster_id -> current default starting lineup, straight from the
    roster object itself rather than a specific week's matchup. Fallback
    for weeks Sleeper doesn't have week-specific matchup data for yet (far
    enough into the future that lineups haven't locked)."""
    rosters = get_rosters(league_id, force=force)
    return {r.get("roster_id"): [pid for pid in (r.get("starters") or []) if pid and pid != "0"] for r in rosters}


def raw_roster_players(league_id, force=False):
    """roster_id -> raw (untranslated) Sleeper player_ids on that roster.
    Needed alongside league_snapshot's gsis-translated roster list because
    our stat engine only scores QB/RB/WR/TE — defense and kicker ids have
    no gsis crosswalk entry and get silently dropped by that translation,
    but a roster/lineup display still needs to know they're there."""
    rosters = get_rosters(league_id, force=force)
    return {r.get("roster_id"): (r.get("players") or []) for r in rosters}


def resolve_unscored_player(sleeper_id, force=False):
    """Name/team/photo for a roster slot our own stat engine can't price —
    defenses (Sleeper's own id for a D/ST is just the team code, e.g.
    "PHI"), kickers, and (this is the important one) any other player
    Sleeper knows about that our gsis id crosswalk simply doesn't cover.
    That crosswalk (nfl_data_py.import_ids()) isn't exhaustive — an older
    or journeyman player can be for-real on a roster and still miss it,
    and the old behavior of only handling DEF/K here meant anyone else in
    that gap just silently vanished from the lineup instead of showing up
    unscored. No position restriction now: if Sleeper has them, they show.

    Real photos, not a generic icon: Sleeper hosts team logos and player
    photos directly, at a predictable URL, independent of our own data —
    https://sleepercdn.com/images/team_logos/nfl/{abbr}.png for a defense,
    https://sleepercdn.com/content/nfl/players/thumb/{sleeper_id}.jpg for
    a person (kicker or otherwise)."""
    players = all_players(force=force)
    p = players.get(sleeper_id)
    if not p:
        return None
    pos = p.get("position") or "?"
    if pos == "DEF":
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or f"{sleeper_id} D/ST"
        headshot = f"https://sleepercdn.com/images/team_logos/nfl/{sleeper_id.lower()}.png"
    else:
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or sleeper_id
        headshot = f"https://sleepercdn.com/content/nfl/players/thumb/{sleeper_id}.jpg"
    return {"position": pos, "player_display_name": name, "recent_team": p.get("team") or sleeper_id,
            "headshot_url": headshot,
            # Live current depth-chart slot (e.g. RB1/RB2) — Sleeper's own,
            # refreshed on the same cadence as everything else in
            # all_players(). Real signal for a player with no personal
            # stat history yet: see engine/role_baseline.py.
            "depth_chart_order": p.get("depth_chart_order")}
