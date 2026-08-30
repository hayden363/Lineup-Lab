"""
DATA LAYER
==========
Everything that touches the network lives here. All data comes from
nflverse / nfl_data_py — free, public, and legal to build on:
  https://github.com/nflverse/nflverse-data

We do NOT use PFF (Pro Football Focus) grades anywhere in this app. PFF
data is a paid, proprietary product and scraping/redistributing it would
violate their terms of service. Instead we lean on nflverse's *free*
tracking-data feed (Next Gen Stats) for separation, cushion, completion %
above expectation, rush yards over expected, etc. — the same flavor of
"how good is this player really" signal PFF sells, computed from public
NFL data.

Responsibilities:
  - figure out which season actually has data published yet
  - fetch weekly stats, play-by-play, Next Gen Stats, schedules
  - cache everything to disk (data_cache/) so repeat requests are instant
    and the app still works offline once warmed up
"""

import json
import os
import time

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours — stats update at most daily during the season
_MANIFEST_PATH = os.path.join(CACHE_DIR, "manifest.json")

# in-memory cache so a running server doesn't hit disk on every request
_MEM = {}


def _cache_path(kind, season):
    return os.path.join(CACHE_DIR, f"{kind}_{season}.parquet")


def _load_manifest():
    if os.path.exists(_MANIFEST_PATH):
        try:
            with open(_MANIFEST_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_manifest(m):
    with open(_MANIFEST_PATH, "w") as f:
        json.dump(m, f, indent=2)


def _disk_cached(kind, season, fetch_fn, force=False):
    """Load `kind` for `season` from disk cache if fresh, else fetch + save."""
    mem_key = (kind, season)
    if not force and mem_key in _MEM:
        return _MEM[mem_key]

    path = _cache_path(kind, season)
    manifest = _load_manifest()
    entry = manifest.get(f"{kind}_{season}")
    fresh = entry and (time.time() - entry.get("fetched_at", 0)) < CACHE_TTL_SECONDS

    if not force and fresh and os.path.exists(path):
        df = pd.read_parquet(path)
        _MEM[mem_key] = df
        return df

    df = fetch_fn()
    try:
        df.to_parquet(path)
        manifest[f"{kind}_{season}"] = {"fetched_at": time.time(), "rows": len(df)}
        _save_manifest(manifest)
    except Exception as e:
        print(f"[cache] could not write {path}: {e}")
    _MEM[mem_key] = df
    return df


# ----------------------------------------------------------------------
# SEASON RESOLUTION
# nflverse tags a season's files as soon as week 1 data lands. If the
# "current" season per the calendar isn't published yet, fall back to the
# most recent season that is. Resolved once per process and cached.
# ----------------------------------------------------------------------
_resolved_season = None


def resolve_season(preferred=None, lookback=4):
    global _resolved_season
    if _resolved_season is not None and preferred is None:
        return _resolved_season

    import nfl_data_py as nfl

    start = preferred or (pd.Timestamp.now().year)
    last_err = None
    for year in range(start, start - lookback - 1, -1):
        try:
            probe = nfl.import_weekly_data([year], columns=["season", "week"])
            if len(probe):
                if preferred is None:
                    _resolved_season = year
                print(f"[data] using season {year} ({len(probe)} weekly rows available)")
                return year
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"No NFL season data found going back {lookback} years from {start}: {last_err}")


# ----------------------------------------------------------------------
# LOADERS
# ----------------------------------------------------------------------
def load_weekly(season=None, force=False):
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_weekly_data([season])
        print(f"[data] fetched weekly stats {season}: {len(df)} rows")
        return df

    return _disk_cached("weekly", season, fetch, force=force)


def load_pbp(season=None, force=False):
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_pbp_data([season], downcast=True, cache=False)
        print(f"[data] fetched play-by-play {season}: {len(df)} rows")
        keep = [
            "passer_player_id", "rusher_player_id", "receiver_player_id",
            "play_type", "yards_gained", "air_yards", "yards_after_catch",
            "complete_pass", "sack", "qb_hit", "epa", "posteam", "defteam",
            "week", "pass", "qb_dropback", "interception", "pass_touchdown",
            "rush_touchdown", "touchdown", "yardline_100", "goal_to_go",
        ]
        return df[[c for c in keep if c in df.columns]]

    return _disk_cached("pbp", season, fetch, force=force)


def load_ngs(stat_type, season=None, force=False):
    """stat_type: 'passing' | 'rushing' | 'receiving' — real Next Gen Stats
    tracking data (free, public via nflverse). This is our PFF-grade proxy:
    separation, cushion, CPOE, time to throw, rush yards over expected."""
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_ngs_data(stat_type, [season])
        print(f"[data] fetched NGS {stat_type} {season}: {len(df)} rows")
        return df

    return _disk_cached(f"ngs_{stat_type}", season, fetch, force=force)


def load_schedule(season=None, force=False):
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_schedules([season])
        print(f"[data] fetched schedule {season}: {len(df)} rows")
        return df

    return _disk_cached("schedule", season, fetch, force=force)


def load_injuries(season=None, force=False):
    """Real weekly injury reports — official practice-participation/game
    status (Out/Doubtful/Questionable/...), not something we're inferring.
    Keyed by gsis_id, matches our player_id directly."""
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_injuries([season])
        print(f"[data] fetched injury reports {season}: {len(df)} rows")
        return df

    return _disk_cached("injuries", season, fetch, force=force)


def load_snap_counts(season=None, force=False):
    """Real offensive snap counts/percentage per player per week — a
    workload/opportunity signal independent of box-score stats. Keyed by
    pfr_id (Pro Football Reference), not gsis_id — see load_pfr_crosswalk."""
    season = season or resolve_season()

    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_snap_counts([season])
        print(f"[data] fetched snap counts {season}: {len(df)} rows")
        return df

    return _disk_cached("snaps", season, fetch, force=force)


def load_pfr_crosswalk(force=False):
    """gsis_id <-> pfr_id, needed only because snap counts are keyed by
    pfr_id while everything else in this app uses gsis_id."""
    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_ids()
        return df[["gsis_id", "pfr_id"]].dropna()

    return _disk_cached("pfr_crosswalk", "live", fetch, force=force)


def load_player_status(force=False):
    """Current roster status (Active/Retired/Reserve/Cut/etc.) for every
    player nflverse tracks — nflverse's players master file, refreshed on
    its own cadence independent of season stats. This is what catches a
    retirement or release that happened after the stats season we're
    valuing players on (e.g. we might be scoring off 2024 production for a
    player who has since retired) so the board doesn't rank or surface
    someone who's actually left the league. Keyed by gsis_id (== our
    player_id everywhere else in this app)."""
    def fetch():
        import nfl_data_py as nfl
        df = nfl.import_players()
        print(f"[data] fetched player status: {len(df)} rows")
        return df[["gsis_id", "display_name", "status"]].dropna(subset=["gsis_id"])

    return _disk_cached("player_status", "live", fetch, force=force)


def current_week(schedule):
    """Best-guess 'current' week: latest week with a completed game, else 1."""
    played = schedule[schedule["home_score"].notna()] if "home_score" in schedule else schedule.iloc[0:0]
    if len(played):
        return int(played["week"].max())
    return 1


def next_opponent(schedule, team, week=None):
    """Who does `team` play in `week` (default: next unplayed week)?"""
    sched = schedule[(schedule["home_team"] == team) | (schedule["away_team"] == team)]
    if week is None:
        upcoming = sched[sched["home_score"].isna()] if "home_score" in sched else sched
        if upcoming.empty:
            return None, None
        row = upcoming.sort_values("week").iloc[0]
    else:
        row = sched[sched["week"] == week]
        if row.empty:
            return None, None
        row = row.iloc[0]
    opp = row["away_team"] if row["home_team"] == team else row["home_team"]
    return opp, int(row["week"])
