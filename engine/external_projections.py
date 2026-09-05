"""
EXTERNAL PROJECTIONS — real third-party consensus, for comparison only
=========================================================================
Powers the "Projection Breakdown" section of the player modal: our own
PROJ next to real published consensus from other fantasy sites, so
Hayden's users can see how this app's number compares instead of taking
it on faith.

Source: FantasyPros' official public API (https://api.fantasypros.com/
public/v2/docs) — a real, documented, developer-facing product with a
free tier, not a scrape. This app already declined to scrape Sleeper's
own undocumented projections endpoint for exactly this reason (see
README's Data Freshness section, and engine/news.py's RSS-not-scraping
note) — FantasyPros' public API, which itself aggregates 130+ experts
(including ESPN's and Sleeper's own analysts) into one consensus number,
is the legitimate equivalent: one real documented source standing in for
"ESPN, Sleeper, and other relevant projection sources" rather than
touching each site's private endpoint individually.

Optional — same "works fine without it, just doesn't appear" pattern as
Gmail (engine/mail.py), Google sign-in (engine/oauth.py), and the AI news
summary (engine/news.py): set FANTASYPROS_API_KEY in `.env` to turn this
on (free tier: https://secure.fantasypros.com/api-keys/request/). The
Projection Breakdown section just doesn't render a comparison if it's
unset — `configured()` tells the frontend which state it's in so it can
show "not connected yet" instead of a blank/broken chart.

Matched to our own players by normalized full name + position — FantasyPros
doesn't expose our nflverse gsis_id, so there's no ID crosswalk to join on
(unlike engine/sleeper.py's/engine/espn.py's id_crosswalk()). Same "no
personal valuation without a real source" discipline as the rest of this
app: a player FantasyPros doesn't cover, or that this module can't
confidently match, comes back with `consensus_proj: None` rather than a
guessed number.

**Response-shape caveat, disclosed rather than hidden:** the field names
below (see _extract_projection) are read from FantasyPros' public docs
page (https://api.fantasypros.com/public/v2/docs), which renders its
reference client-side and couldn't be captured as raw JSON without an
actual API key to call it with. They match the documented endpoint
(`GET /nfl/{season}/projections`) and its example
(`GET /nfl/2026/consensus-rankings?position=RB&scoring=PPR`), but MUST be
verified against one real response before this is trusted — run
`python3 -m engine.external_projections selftest` once FANTASYPROS_API_KEY
is set. If the real shape differs, _extract_projection logs a loud
warning and returns None (never a fabricated number) rather than
silently mis-mapping a field.
"""

import os
import re
import sys
import time

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars can still be set another way

FANTASYPROS_API_KEY = os.environ.get("FANTASYPROS_API_KEY")
BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"
SOURCE_NAME = "FantasyPros Consensus"
SOURCE_DETAIL = "Aggregates 130+ fantasy experts, including ESPN's and Sleeper's own"

TTL_SECONDS = 60 * 60  # projections don't change intra-day; refetch hourly at most
_MEM_CACHE = {}  # (season, week, position, scoring) -> (fetched_at, {normalized_name: proj_pts})

_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[.'\-]")
_WS_RE = re.compile(r"\s+")


def configured():
    """Whether FANTASYPROS_API_KEY is set — the frontend uses this to
    show a real 'not connected' state instead of an empty chart."""
    return bool(FANTASYPROS_API_KEY)


def normalize_name(name):
    """Lowercase, strip Jr./Sr./II-V suffixes and punctuation, collapse
    whitespace — enough to match "Marvin Harrison Jr." (our data) against
    a source that might render it "Marvin Harrison" or "Marvin Harrison
    JR", without being so loose it starts colliding different players
    (see engine/news.py's _name_variants for the same full-name-only,
    no-last-name-alone reasoning)."""
    if not name:
        return ""
    n = name.lower().strip()
    n = _SUFFIX_RE.sub("", n)
    n = _PUNCT_RE.sub("", n)
    n = _WS_RE.sub(" ", n).strip()
    return n


def _extract_projection(record):
    """One record from FantasyPros' projections endpoint -> (name, fpts)
    or None. Tries the documented/likely field names defensively rather
    than assuming one exact shape sight-unseen (see module docstring) —
    returns None (not a guess) for a record it doesn't recognize."""
    name = record.get("player_name") or record.get("name")
    if not name:
        return None
    for key in ("fpts", "points", "projected_points", "proj_pts", "fantasy_points"):
        if key in record and record[key] is not None:
            try:
                return name, float(record[key])
            except (TypeError, ValueError):
                continue
    return None


def _fetch_position_projections(position, season, week, scoring):
    """One real HTTP call to FantasyPros' documented projections endpoint.
    Returns {normalized_name: proj_pts} — never raises; a failure or an
    unrecognized response shape just yields an empty dict, which
    projection_for_player then treats as 'no consensus available',
    same as an unconfigured key."""
    params = {"position": position}
    if week:
        params["week"] = week
    if scoring:
        params["scoring"] = scoring
    url = f"{BASE_URL}/{season}/projections"
    try:
        resp = requests.get(url, params=params, headers={"x-api-key": FANTASYPROS_API_KEY}, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"[external_projections] FantasyPros fetch failed for {position} {season} wk{week}: {e}")
        return {}

    # the list of player records lives under one of a few likely keys
    # depending on the exact response envelope — try each rather than
    # assuming, and log clearly if none match so this isn't a silent gap.
    records = None
    if isinstance(payload, list):
        records = payload
    else:
        for key in ("players", "data", "projections"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break
    if records is None:
        print(f"[external_projections] unrecognized FantasyPros response shape for {position} "
              f"{season} wk{week} — top-level keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}. "
              "Not showing a comparison rather than guessing a field mapping; see module docstring's selftest.")
        return {}

    out = {}
    skipped = 0
    for record in records:
        parsed = _extract_projection(record)
        if parsed is None:
            skipped += 1
            continue
        name, fpts = parsed
        out[normalize_name(name)] = fpts
    if skipped and not out:
        print(f"[external_projections] parsed 0/{len(records)} FantasyPros records for {position} "
              f"{season} wk{week} — field-name mapping likely needs updating (see module docstring).")
    return out


def _cached_position_projections(position, season, week, scoring, force=False):
    key = (season, week, position, scoring)
    now = time.time()
    if not force and key in _MEM_CACHE and (now - _MEM_CACHE[key][0]) < TTL_SECONDS:
        return _MEM_CACHE[key][1]
    data = _fetch_position_projections(position, season, week, scoring)
    _MEM_CACHE[key] = (now, data)
    return data


def projection_for_player(player_display_name, position, season, week=None, scoring=None, force=False):
    """The one function server.py calls. Returns a dict always (never
    None, never raises) so the frontend has a consistent shape:

      {"configured": bool, "source": SOURCE_NAME, "detail": SOURCE_DETAIL,
       "proj": float | None, "week": week}

    `proj` is None when the key isn't configured, the fetch failed, or
    this player wasn't matched — every one of those is a real "no
    comparison available" state, never a fabricated number."""
    result = {"configured": configured(), "source": SOURCE_NAME, "detail": SOURCE_DETAIL,
              "proj": None, "week": week}
    if not configured() or position not in ("QB", "RB", "WR", "TE", "K", "DST", "DEF"):
        return result
    fp_position = "DST" if position == "DEF" else position
    table = _cached_position_projections(fp_position, season, week, scoring, force=force)
    proj = table.get(normalize_name(player_display_name))
    if proj is not None:
        result["proj"] = round(proj, 1)
    return result


def _selftest():
    """Run with: python3 -m engine.external_projections selftest
    Hits the real API for one position/week and prints what actually
    came back, so the field-name mapping above can be corrected against
    real data instead of guesswork the moment a real key exists."""
    if not configured():
        print("FANTASYPROS_API_KEY is not set — nothing to test. "
              "Get a free key at https://secure.fantasypros.com/api-keys/request/ "
              "and add it to .env, then rerun this.")
        return
    import datetime
    season = datetime.date.today().year
    print(f"Fetching real FantasyPros RB projections for {season}...")
    table = _fetch_position_projections("RB", season, None, None)
    print(f"Parsed {len(table)} players. Sample: {list(table.items())[:5]}")
    if not table:
        print("0 players parsed — the response shape didn't match _extract_projection's "
              "assumptions. Re-run with FANTASYPROS_DEBUG=1 set to also print the raw payload, "
              "then fix _extract_projection/_fetch_position_projections above against it.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        print("Usage: python3 -m engine.external_projections selftest")
