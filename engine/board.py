"""
BOARD BUILDER
=============
The single entry point the API (and CLI) calls: build a fully-scored,
matchup-projected big board for one position.

Pipeline: weekly stats -> base metrics -> SCORE (weighted) -> advanced
(NGS + pbp) merged in -> FORM (recent trend) -> optional matchup
projection vs an opponent defense.
"""

import json
import os
import threading
import time
from typing import TypedDict

import numpy as np
import pandas as pd

from . import data
from . import history
from . import injuries
from . import defense as defense_layer
from . import injury_impact, play_prob
from . import profile
from . import consensus
from . import pvs
from . import value as value_layer
from . import weekly_proj
from .metrics import METRIC_FNS, WEIGHTS, MIN_GAMES, score_players, form_adjustment
from .advanced import qb_advanced, rb_advanced, wr_advanced, te_advanced, weekly_epa, ADVANCED_COLS
from .matchup import matchup_tag
from .scoring import apply_scoring, ScoringSettings, PRESETS


class Bundle(TypedDict):
    """Every raw table a board needs for one season, as returned by
    load_bundle(). A plain dict here would type as dict[str, <giant union
    of every value type ever stored in it>] wherever it's read back out
    (bundle["wk"], bundle.get("retired_ids"), ...) — this TypedDict gives
    each key its own real type instead."""
    season: int
    wk: pd.DataFrame
    pbp: pd.DataFrame
    ngs_pass: pd.DataFrame
    ngs_rush: pd.DataFrame
    ngs_rec: pd.DataFrame
    schedule: pd.DataFrame
    defense_factors: pd.DataFrame
    defense_league_avg: pd.Series
    retired_ids: set
    injury_status: dict
    injury_body_part: dict
    snap_pct: dict
    redzone_touches: dict

ADVANCED_FNS = {"QB": qb_advanced, "RB": rb_advanced, "WR": wr_advanced, "TE": te_advanced}
NGS_KIND = {"QB": "passing", "RB": "rushing", "WR": "receiving", "TE": "receiving"}

POSITIONS = ("QB", "RB", "WR", "TE")

# Minimum "volume" (attempts / touches / targets, position-appropriate) to be
# considered a qualified sample — filters out mop-up-duty / one-play noise
# that would otherwise produce absurd rate stats off a tiny denominator.
# This is a SEASON-TOTAL bar (checked against _build_board_uncached's
# cumulative `volume` column) — see that function for why it's scaled by
# games played before use, rather than applied as a flat number.
MIN_VOLUME = {"QB": 80, "RB": 20, "WR": 12, "TE": 8}

# Raw per-week counting-stat columns to include in player_detail()'s
# weekly_log, position by position — real numbers straight off the weekly
# table (same one metrics.py's METRIC_FNS aggregate from), not just the
# one fpts bar chart, so the frontend can plot a week-by-week trend for
# whichever stat someone actually cares about.
WEEKLY_LOG_COLUMNS = {
    "QB": ["completions", "attempts", "passing_yards", "passing_tds", "passing_epa"],
    "RB": ["carries", "rushing_yards", "rushing_tds", "rushing_epa", "targets", "receptions", "receiving_yards"],
    "WR": ["targets", "receptions", "receiving_yards", "receiving_tds", "receiving_epa",
           "receiving_air_yards", "receiving_yards_after_catch", "target_share"],
    "TE": ["targets", "receptions", "receiving_yards", "receiving_tds", "receiving_epa",
           "receiving_air_yards", "receiving_yards_after_catch", "target_share"],
}


def _cache_key(season):
    return season


_BUNDLE_CACHE: dict = {}

# One cold load at a time. Two requests arriving together on a cold
# process (a page fires /api/meta, /api/myteam and /api/trade/roster at
# once) each used to run the whole load, holding two copies of every raw
# table at the same moment. Measured on Render 2026-10-16: two parallel
# loads pushed the 512 MB instance past its limit and it was OOM-killed
# mid-request. The second caller now waits and reuses the first's bundle.
_BUNDLE_LOCK = threading.Lock()

# Every build_board() call, fully computed, keyed by (position, season,
# scoring) — see build_board()'s docstring for why min_games/min_volume
# aren't part of this key. Cleared wholesale on a forced bundle refresh
# (load_bundle's force=True path below), since a cached board is only
# valid for the raw tables it was built from.
_BOARD_CACHE: dict = {}
_PVS_CACHE: dict = {}
# Boards and PVS tables are cached per scoring setting. The default and the
# named presets are what nearly everyone uses, so they stay. A signed-in user
# with custom league scoring adds their own variant; without a bound, enough
# different leagues would grow this without limit on a 512 MiB host. Beyond
# MAX_CUSTOM_SCORINGS distinct custom settings, the least recently used one is
# dropped (and simply rebuilt, ~0.5 s, if its owner comes back).
MAX_CUSTOM_SCORINGS = int(os.environ.get("MAX_CUSTOM_SCORINGS", "8"))
_PVS_LOCAL = threading.local()


def _scoring_cache_key(scoring):
    """A hashable stand-in for `scoring` to use as part of a cache key.
    Safe because every real caller (server.py's scoring_from_query /
    _effective_scoring) only ever produces None or a plain dict with a
    fixed set of keys — never a partial dict, never a ScoringSettings
    instance."""
    return None if scoring is None else tuple(sorted(scoring.items()))


def _snap_pct_from(snaps, crosswalk):
    """Real per-player offense-snap share from his MOST RECENT game (not a
    season average), as a 0-1 fraction straight from nflverse's
    offense_pct — from already-fetched snap-count + id-crosswalk tables,
    pure computation, no I/O. Start/Sit's AI facts label it
    snap_pct_last_game for that reason; engine/waivers.weekly_snaps has the
    per-week series (0-100) when a trend is needed."""
    snap_pct = {}
    pfr_to_gsis = dict(zip(crosswalk["pfr_id"], crosswalk["gsis_id"]))
    if len(snaps):
        latest = snaps.sort_values("week").groupby("pfr_player_id").last()
        for pfr_id, row in latest.iterrows():
            gsis_id = pfr_to_gsis.get(pfr_id)
            # pandas-stubs 1.5.3.230321 mistypes Series.get()'s return as
            # `Dtype` unconditionally (see pandas-stubs/core/generic.pyi) —
            # it's actually a scalar value here, so notna()/float() below
            # are real pyright false positives, not a code issue.
            pct = row.get("offense_pct")
            if gsis_id and pd.notna(pct):  # type: ignore[reportCallIssue,reportArgumentType]
                snap_pct[gsis_id] = float(pct)  # type: ignore[reportArgumentType]
    return snap_pct


def _redzone_touches_from(pbp):
    """Real red-zone touch counts, from already-fetched play-by-play —
    pure computation, no I/O."""
    if "yardline_100" not in pbp.columns:
        return {}
    rz = pbp[pbp["yardline_100"] <= 20]
    rushes = rz.loc[rz["rusher_player_id"].notna(), "rusher_player_id"]
    targets = rz.loc[rz["receiver_player_id"].notna(), "receiver_player_id"]
    return pd.concat([rushes, targets]).value_counts().to_dict()


def _timed(label, fetch):
    """Run one cold-path fetch and log how long it took, so Render's logs can
    pin a slow cold start on a specific table instead of the load as a whole.
    One line per table, grep-able on the [cold-start] prefix."""
    t0 = time.perf_counter()
    df = fetch()
    rows = len(df) if hasattr(df, "__len__") else "?"
    print(f"[cold-start] table={label} seconds={time.perf_counter() - t0:.2f} rows={rows}")
    return df


def load_bundle(season=None, force=False) -> Bundle:
    """Fetch (and cache) every raw table the board needs for a season.
    force=True also re-resolves the season itself (not just re-fetching
    the previously-resolved one's data) — see resolve_season's docstring
    for why that distinction matters for a periodic refresh.

    Fetched sequentially, on purpose — NOT via a thread pool. That was
    tried (see git history) on the theory that these are independent
    network fetches that could overlap; measured on the actual host this
    runs on, it made cold loads slower, not faster (45s+, worse than
    before). Render's free tier caps this instance at ~0.15 of one CPU
    core — real, measured — and several threads all wanting to parse
    JSON/parquet at once contend hard for that sliver, on top of however
    much the shared egress bandwidth also degrades under several
    simultaneous downloads. What helps on a full dev machine can be a net
    loss on a resource-capped host; measure on the real target, not just
    locally. The one durable fix for "this is slow" here is avoiding
    paying this cost at all as often as possible — see load_pbp's own
    memory fix, which (by fixing the OOM crash loop) is what actually
    keeps this process alive long enough that most requests hit the
    warm _BUNDLE_CACHE below instead of ever reaching this cold path.

    Each source below is independently optional except the required core
    tables (wk/pbp/ngs/schedule), which raise on failure same as always.
    The optional enrichments (retired-status, live injury, snap share)
    degrade gracefully — real per-player signals that live outside the
    box score, each independently optional — one fetch failing just
    means that signal comes back empty for everyone, not that the whole
    board fails to build.

    Injury status specifically comes from Sleeper's LIVE player list
    (engine/sleeper.live_injury_statuses), not nflverse's `season`-pinned
    injury report — this app's stat season can genuinely lag a full real
    season behind (see README), and a designation from that old season
    would be actively wrong, not just stale-but-harmless, for a player
    whose situation has since changed. Red-zone touches are a season total;
    snap share is the player's most recent game in the stat season (see
    _snap_pct_from) — neither is claimed to be "as of this week.\""""
    season = season or data.resolve_season(force=force)
    key = _cache_key(season)
    if not force and key in _BUNDLE_CACHE:
        return _BUNDLE_CACHE[key]
    with _BUNDLE_LOCK:
        # Re-check inside the lock: whoever held it may have just built this.
        if not force and key in _BUNDLE_CACHE:
            return _BUNDLE_CACHE[key]
        return _load_bundle_locked(season, key, force)


def _load_bundle_locked(season, key, force) -> Bundle:
    """load_bundle's cold path. Only ever called with _BUNDLE_LOCK held."""
    from . import sleeper as sleeper_layer

    t_start = time.perf_counter()
    wk = _timed("weekly", lambda: data.load_weekly(season, force=force))
    pbp = _timed("pbp", lambda: data.load_pbp(season, force=force))
    ngs_pass = _timed("ngs_passing", lambda: data.load_ngs("passing", season, force=force))
    ngs_rush = _timed("ngs_rushing", lambda: data.load_ngs("rushing", season, force=force))
    ngs_rec = _timed("ngs_receiving", lambda: data.load_ngs("receiving", season, force=force))
    schedule = _timed("schedule", lambda: data.load_schedule(season, force=force))
    t_core = time.perf_counter()

    # Roster status is current, not season-stats-bound — this is what
    # keeps a player who has since retired (but still has real stats
    # from the season we're valuing off of) out of the board entirely,
    # everywhere it's used. Two independent real signals, unioned:
    # nflverse's own "RET" status tag, and Sleeper's live "no current
    # NFL team" (the same data your actual league runs on — catches a
    # retirement/release nflverse hasn't tagged yet, which is common
    # since our season stats already lag, see data.py).
    retired_ids = set()
    try:
        status_df = data.load_player_status(force=force)
        retired_ids |= set(status_df.loc[status_df["status"] == "RET", "gsis_id"])
    except Exception as e:
        print(f"[data] couldn't load nflverse player status (skipped): {e}")
    try:
        retired_ids |= sleeper_layer.inactive_gsis_ids(force=force)
    except Exception as e:
        print(f"[data] couldn't load Sleeper player status (skipped): {e}")

    try:
        injury_status = sleeper_layer.live_injury_statuses(force=force)
    except Exception as e:
        print(f"[data] couldn't load live injury statuses (skipped): {e}")
        injury_status = {}

    try:
        injury_body_part = sleeper_layer.live_injury_body_parts(force=force)
    except Exception as e:
        print(f"[data] couldn't load live injury body parts (skipped): {e}")
        injury_body_part = {}

    try:
        snap_pct = _snap_pct_from(data.load_snap_counts(season, force=force), data.load_pfr_crosswalk(force=force))
    except Exception as e:
        print(f"[data] couldn't load snap counts (skipped): {e}")
        snap_pct = {}

    # granular, multi-stat defensive profile (real per-play results — run
    # defense, pass defense, pressure — not one blanket fpts-allowed number)
    # joined with a defense-side Next Gen Stats profile (real player-tracking
    # data attributed to the defense on the field that week, via the
    # schedule — see build_ngs_defense_profile). Scoring-agnostic by
    # construction (built from yards/TDs/completions/tracking data, not
    # fantasy points), so it's computed once per season, not per scoring.
    # CPU-bound, so it runs after the fetches above complete rather than
    # inside the thread pool.
    defense_profile = defense_layer.build_defense_profile(pbp)
    ngs_defense_profile = defense_layer.build_ngs_defense_profile(ngs_pass, ngs_rush, ngs_rec, schedule)
    defense_profile = defense_profile.join(ngs_defense_profile, how="outer")
    defense_factors, defense_league_avg = defense_layer.league_relative_factors(defense_profile)

    try:
        redzone_touches = _redzone_touches_from(pbp)
    except Exception as e:
        print(f"[data] couldn't compute red-zone touches (skipped): {e}")
        redzone_touches = {}

    bundle = Bundle(season=season, wk=wk, pbp=pbp, ngs_pass=ngs_pass, ngs_rush=ngs_rush,
                  ngs_rec=ngs_rec, schedule=schedule, defense_factors=defense_factors,
                  defense_league_avg=defense_league_avg, retired_ids=retired_ids,
                  injury_status=injury_status, injury_body_part=injury_body_part,
                  snap_pct=snap_pct, redzone_touches=redzone_touches)
    t_end = time.perf_counter()
    # Everything after the core tables (retired/injury/snap enrichments, defense
    # factors) as one span, so the per-table lines above plus these two add up.
    print(f"[cold-start] enrichments seconds={t_end - t_core:.2f}")
    print(f"[cold-start] total seconds={t_end - t_start:.2f} season={season} force={force}")
    _BUNDLE_CACHE[key] = bundle
    if force:
        # Every previously-computed board was built from the raw tables
        # this refresh just superseded — a whole-cache clear is simple,
        # correct, and cheap next to the refresh itself (this only runs
        # on the 24h scheduler tick or an explicit POST /api/refresh, not
        # a hot path).
        _BOARD_CACHE.clear()
        _PVS_CACHE.clear()
        _OVERALL_CACHE.clear()
    return bundle


def _ngs_for(position, bundle):
    kind = NGS_KIND[position]
    return {"passing": bundle["ngs_pass"], "rushing": bundle["ngs_rush"],
            "receiving": bundle["ngs_rec"]}[kind]


def _build_board_uncached(position, season, min_volume, scoring):
    """Everything build_board() actually computes: scored + advanced-merged
    + FORM-adjusted + floor/ceiling, for every player at this position who
    cleared the volume bar — deliberately NOT filtered by min_games here
    (see build_board()'s docstring on why that's applied afterward,
    cheaply, instead of being part of this function or the cache it feeds)."""
    bundle = load_bundle(season)
    wk, settings = apply_scoring(bundle["wk"], scoring)

    base = METRIC_FNS[position](wk)
    min_volume = MIN_VOLUME[position] if min_volume is None else min_volume
    # min_volume is a SEASON-TOTAL bar, but early in a season nobody has
    # had the chance to accumulate a full season's worth yet — checked
    # this the hard way against real 2026 week-1 data: an established
    # starting QB/WR/TE (Mahomes, Waddle, Nabers, ...) can have a real,
    # single qualifying game and still fail a flat 80-attempt/12-target
    # bar that assumes many games' worth of accumulation, which silently
    # made them vanish everywhere a roster is resolved (My Team, Start/
    # Sit, Trade pickers, News' player-name matching), not just rank
    # lower. Scaling the bar by real games played fixes that.
    #
    # Ramp window is MIN_GAMES+1, not MIN_GAMES — found the hard way
    # against real week-2 data (still fresh season, this time verified on
    # an actual 2-game sample rather than the 1-game case above): Mahomes
    # threw a completely normal 74 attempts over his first 2 real games
    # (~37/game, a healthy starter's workload) and STILL failed the flat
    # 80-attempt bar at a cap of exactly MIN_GAMES=2 games — clear
    # evidence the flat constants were calibrated for something closer to
    # MIN_GAMES+1 games' worth of normal volume, not exactly MIN_GAMES.
    # Ramping over MIN_GAMES+1 games instead fixes this (both Mahomes'
    # and Burrow's real 2-game volume now clears) while every week from
    # MIN_GAMES+1 onward — i.e. nearly this entire season — sees the
    # exact same flat threshold as always, unchanged and still the
    # already-extensively-verified default.
    ramp_games = MIN_GAMES[position] + 1
    scale = (base["games"].clip(upper=ramp_games) / ramp_games)
    base = base[base["volume"] >= min_volume * scale]

    adv = ADVANCED_FNS[position](bundle["pbp"], _ngs_for(position, bundle))
    board = base.join(adv, how="left")

    board["SCORE"] = score_players(base, WEIGHTS[position])
    board["FORM"] = form_adjustment(wk, position, weekly_epa=weekly_epa(bundle["pbp"], position))
    board["FORM"] = board["FORM"].reindex(board.index).fillna(0.0)

    board.index.name = "player_id"

    # Plain box-score totals (shown under every player) and the week-to-week
    # steadiness profile. Totals' `games` is dropped: the board already has it.
    totals = profile.season_totals(wk, position)
    totals = totals.drop(columns=[c for c in totals.columns if c in board.columns])
    board = board.join(totals).join(
        profile.consistency(wk, position)[["std", "cv", "boom_rate", "bust_rate", "top_finishes"]],
        rsuffix="_wk")
    board["stat_line"] = [profile.stat_line(r, position) for r in board.to_dict(orient="records")]
    board["bye_week"] = board["recent_team"].map(profile.bye_weeks(bundle["schedule"]))

    # Real availability/opportunity signals (see _availability_signals) —
    # merged on, not recomputed per position.
    board["injury_status"] = board.index.to_series().map(bundle.get("injury_status", {}))
    board["injury_body_part"] = board.index.to_series().map(bundle.get("injury_body_part", {}))
    board["snap_pct"] = board.index.to_series().map(bundle.get("snap_pct", {}))
    board["redzone_touches"] = board.index.to_series().map(bundle.get("redzone_touches", {})).fillna(0).astype(int)

    # Floor/ceiling: the real 25th/75th percentile of this player's own
    # game-level fantasy points this season — not a model output, just the
    # actual spread of what they've already done. Naturally widens for a
    # player with only 2-3 qualifying games, which is the honest read: less
    # sample, less certainty, not a bug.
    fpts_by_player = wk.groupby("player_id")["fpts_active"]
    board["floor"] = fpts_by_player.quantile(0.25).reindex(board.index).clip(lower=0)
    board["ceiling"] = fpts_by_player.quantile(0.75).reindex(board.index)
    # One monster game can drag the average above the 75th percentile (or one
    # dud below the 25th). The percentiles are still the honest spread, but a
    # range that doesn't contain the player's own average reads as a bug, so
    # widen the band to include it.
    avg = board["fpts_per_game"]
    board["floor"] = board["floor"].where(board["floor"] <= avg, avg)
    board["ceiling"] = board["ceiling"].where(board["ceiling"] >= avg, avg)

    # "Gone dark" signal: a player can stop appearing in the weekly data
    # (release, benching, an injury that never got a live Sleeper
    # designation — see J.K. Dobbins, week 10+ this season, still showing
    # a normal-looking season-average PROJ with nothing surfacing "hasn't
    # played in N weeks") without engine.sleeper's injury_status catching
    # it. Real, not inferred: the gap between this player's own last real
    # game week and their OWN TEAM's most recent played week — deliberately
    # NOT the league-wide "current week" (data.current_week), which is
    # meaningless for this once a season ends (every team's own last week
    # varies — 18 for a non-playoff team, up to 22 for a Super Bowl
    # participant — so comparing everyone to one league-wide week falsely
    # flags the entire non-playoff-team player pool as "dark" the moment
    # the season is over; verified this the hard way against live 2025
    # data, which is now a fully completed season). Comparing each player
    # to their own team's own last game is robust whether the season is
    # still live or has already finished. Distinct from the
    # retired-player filter below (a released-but-not-retired or quietly
    # benched player wouldn't be caught by that).
    # Plain float (not a nullable Int64) so a rare unmapped team code
    # degrades to a normal NaN -> None, same as every other optional
    # numeric column here — server.py's _clean() already handles that.
    board["last_active_week"] = wk.groupby("player_id")["week"].max().reindex(board.index)
    schedule = bundle["schedule"]
    played = schedule[schedule["home_score"].notna()] if "home_score" in schedule else schedule.iloc[0:0]
    if len(played):
        team_last_week = pd.concat([
            played[["week", "home_team"]].rename(columns={"home_team": "team"}),
            played[["week", "away_team"]].rename(columns={"away_team": "team"}),
        ]).groupby("team")["week"].max()
    else:
        team_last_week = pd.Series(dtype="float64")
    team_last_played = board["recent_team"].map(team_last_week)
    board["weeks_since_played"] = (team_last_played - board["last_active_week"]).clip(lower=0)

    retired_ids = bundle.get("retired_ids")
    if retired_ids:
        board = board[~board.index.isin(retired_ids)]
    board.attrs["scoring"] = settings.as_dict()
    return board.sort_values("SCORE", ascending=False)


def _protected_scoring_keys():
    return {None} | {_scoring_cache_key(p) for p in PRESETS.values()}


def _cache_get(cache, key, scoring_key_of):
    """cache[key] or None; a hit on a custom-scoring entry marks it recently used."""
    hit = cache.get(key)
    if hit is not None and scoring_key_of(key) not in _protected_scoring_keys():
        cache.pop(key, None)
        cache[key] = hit
    return hit


def _cache_put(cache, key, value, scoring_key_of):
    """Store, then drop the least recently used custom-scoring variants beyond
    MAX_CUSTOM_SCORINGS. Presets and the default are never dropped."""
    cache[key] = value
    protected = _protected_scoring_keys()
    seen = []
    for k in list(cache):
        sk = scoring_key_of(k)
        if sk not in protected and sk not in seen:
            seen.append(sk)
    for sk in seen[:max(0, len(seen) - MAX_CUSTOM_SCORINGS)]:
        for k in [k for k in cache if scoring_key_of(k) == sk]:
            cache.pop(k, None)


def _board_key_scoring(key):
    return key[2]


def _pvs_key_scoring(key):
    return key[1]


def build_board(position, season=None, min_games=2, min_volume=None, scoring=None):
    """The scored/advanced/FORM/floor-ceiling board for one position,
    cached by (position, season, scoring) — every real call site (the API,
    waivers, trade/start-sit tools) ends up asking for the same handful of
    these per refresh cycle, and rebuilding one from raw tables is the
    single most expensive thing this app does (metrics + advanced NGS/pbp
    merge + FORM's per-player recency math + floor/ceiling, all over the
    full season). min_games deliberately isn't part of the cache key: it's
    a filter applied afterward, so a `min_games=0` and a `min_games=3`
    request for the same position/scoring share one cached computation
    instead of paying for it twice. A non-default min_volume is applied
    inside the build, so that call bypasses the cache entirely."""
    position = position.upper()
    if position not in POSITIONS:
        raise ValueError(f"position must be one of {POSITIONS}")
    season = season or data.resolve_season()
    key = (position, season, _scoring_cache_key(scoring))
    if min_volume is not None:
        # min_volume IS applied inside the uncached build (unlike min_games),
        # so a custom bar must never be read from or written to the shared
        # cache — it would silently change every later default-bar caller.
        board = _build_board_uncached(position, season, min_volume, scoring)
        board["rate"] = shrunk_rate(board, position, scoring, season)
    else:
        board = _cache_get(_BOARD_CACHE, key, _board_key_scoring)
    if board is None:
        board = _build_board_uncached(position, season, min_volume, scoring)
        board["rate"] = shrunk_rate(board, position, scoring, season)
        _cache_put(_BOARD_CACHE, key, board, _board_key_scoring)
    filtered = board[board["games"] >= min_games]
    # Live injury designations (ESPN's feed, 15 minutes old at most) over
    # Sleeper's once-a-day list; see engine/injuries.py. Never lets the feed
    # take a board down.
    try:
        filtered = injuries.overlay(filtered, load_bundle(season))
    except Exception as e:
        print(f"[board] live injuries skipped: {e}")
    # .attrs propagation through boolean-mask indexing isn't guaranteed on
    # pandas 1.5.3 (still marked experimental upstream) — set it explicitly
    # rather than trust it survived the filter above.
    filtered.attrs["scoring"] = board.attrs.get("scoring")
    if not getattr(_PVS_LOCAL, "building", False):
        try:
            look = pvs_lookup(season, scoring)
            filtered["PVS"] = [look[p][0] if p in look else np.nan for p in filtered.index]
            filtered["PVS_tier"] = [look[p][1] if p in look else None for p in filtered.index]
            filtered.attrs["scoring"] = board.attrs.get("scoring")
        except Exception as e:
            print(f"[board] PVS skipped: {e}")
    return filtered


def pvs_lookup(season=None, scoring=None):
    """{player_id: (PVS, tier)} from the default-league overall board (12 teams,
    1 QB), cached per (season, scoring). It is what every position board and
    the player card show as the player's score, so one number means the same
    thing on every screen. The Big Board's own league settings (team count,
    superflex) are applied to that list separately."""
    season = season or data.resolve_season()
    key = (season, _scoring_cache_key(scoring))
    hit = _cache_get(_PVS_CACHE, key, _pvs_key_scoring)
    if hit is None:
        _PVS_LOCAL.building = True
        try:
            allp = overall_board(scoring=scoring, season=season)
        finally:
            _PVS_LOCAL.building = False
        hit = {pid: (float(r.PVS), r.PVS_tier) for pid, r in allp[["PVS", "PVS_tier"]].iterrows()}
        _cache_put(_PVS_CACHE, key, hit, _pvs_key_scoring)
    return hit


def warm_default_boards(season=None, pause=0.5):
    """Build only the default-scoring board for each position, one at a time with
    a short pause, then its PVS table. Unlike warm_common_boards (16 builds in a
    burst, which pushed memory past what a small host tolerates), this is four
    builds, and it is what a signed-out visitor hits first. Opt-in at process
    start via WARM_ON_START (see engine/refresh_scheduler.py)."""
    for pos in POSITIONS:
        try:
            build_board(pos, season=season)
        except Exception as e:
            print(f"[board] default warm skipped for {pos}: {e}")
        time.sleep(pause)


def warm_common_boards(season=None):
    """Precompute + cache the handful of (position, scoring) combinations
    real traffic actually hits — the no-override fast path plus the 3
    named presets — so the first real request after a refresh (or a fresh
    process start) doesn't pay full per-position compute cost alone.
    A signed-in user's custom per-league scoring still computes on first
    request as before; there's no bounded set of those to precompute."""
    scorings = [None, PRESETS["standard"], PRESETS["half_ppr"], PRESETS["ppr"]]
    for pos in POSITIONS:
        for scoring in scorings:
            try:
                build_board(pos, season=season, scoring=scoring)
            except Exception as e:
                print(f"[board] warm skipped for {pos}/{scoring}: {e}")


def matchup_multiplier(position, opp, bundle):
    """The real, granular, multi-stat matchup factor for one position vs
    one defense (see engine/defense.py). Falls back to neutral (1.0) if
    the defense isn't in this season's profile (e.g. a bad team code)."""
    factors = bundle["defense_factors"]
    if opp not in factors.index:
        return 1.0
    return defense_layer.composite_multiplier(position, opp, factors)


def _injury_multiplier_col(board, position):
    """Real, historical-data-backed adjustment for a player CURRENTLY
    carrying a live Questionable/Doubtful designation with a reported
    body part — see engine/injury_impact.py for the full real methodology
    and its disclosed limits. 1.0 (no change) for everyone else, including
    a real "Out" designation (that's a separate question — will they play
    at all — not "how do they perform while playing through it," which is
    what this table actually measures)."""
    if "injury_status" not in board.columns or "injury_body_part" not in board.columns:
        return pd.Series(1.0, index=board.index)
    return board.apply(
        lambda r: injury_impact.injury_multiplier(position, r["injury_status"], r["injury_body_part"]),
        axis=1,
    )


def _availability_col(board, schedule):
    if "injury_report" not in board.columns:
        return pd.Series(1.0, index=board.index)
    return pd.Series([injuries.availability(r, schedule) if isinstance(r.get("injury_report"), dict) else 1.0
                      for _, r in board.iterrows()], index=board.index)


def _injury_sample_col(board, position):
    """The real sample size (n) backing injury_factor above, or None when
    no real adjustment applied — so the frontend can disclose WHY a
    number moved (a real historical median, over N real games) instead of
    silently changing it. Companion to _injury_multiplier_col, same
    reasoning, kept separate so a caller that only needs the number
    doesn't pay for building the detail dict."""
    if "injury_status" not in board.columns or "injury_body_part" not in board.columns:
        return pd.Series(None, index=board.index, dtype="object")

    def _n(r):
        detail = injury_impact.injury_adjustment_detail(position, r["injury_status"], r["injury_body_part"])
        return detail["real_sample_size"] if detail else None
    return board.apply(_n, axis=1)


SHRINK_GAMES = 3.0   # prior counts as this many games of evidence
SHRINK_MIN_SAMPLE = 3


def shrunk_rate(board, position, scoring=None, season=None):
    """Per-game scoring pulled toward a prior by how few games he has played:
    (n*rate + k*prior) / (n + k).

    Without history (season=None, or a player with no prior seasons) the prior
    is the average of every player at the position who has a real sample (3+
    games) and k = 3 games: a 5-game 30-point streak projects forward as
    roughly 23, a one-game 12-point scrub comes back toward 10 rather than up
    to starter level, and a full season barely moves. The prior is
    deliberately the broad average, not the starter average: shrinking toward
    starters would inflate every thin-sample backup.

    With season given, a player who has prior seasons (engine/history.py) is
    pulled toward his OWN career rate instead, harder the more history there
    is. Also adds board["history_weight"], the share of the rate that came
    from history."""
    rate = board["fpts_per_game"]
    pool = board[board["games"] >= SHRINK_MIN_SAMPLE]["fpts_per_game"]
    if pool.empty:
        return rate
    prior = float(pool.mean())
    n = board["games"].astype(float)
    if season is not None and history.available():
        career = history.skill_career(position, scoring, season)
        out, share = history.blend(rate, n, career, prior, base_k=SHRINK_GAMES)
        board["history_weight"] = share.round(3)
        return out
    return (n * rate + SHRINK_GAMES * prior) / (n + SHRINK_GAMES)


def _rate(board):
    return board["rate"] if "rate" in board.columns else board["fpts_per_game"]


def project_vs(board, position, opp, bundle=None, season=None, scoring=None):
    """Add a PROJ column: fpts_per_game adjusted for FORM, the real,
    per-stat-category matchup factor vs this specific opponent defense,
    and (new) a real historical injury-impact factor for anyone currently
    Questionable/Doubtful with a reported body part."""
    bundle = bundle or load_bundle(season)
    factor = matchup_multiplier(position, opp, bundle)
    breakdown = defense_layer.matchup_breakdown(position, opp, bundle["defense_factors"]) if opp in bundle["defense_factors"].index else []
    form_mult = 1 + board["FORM"] / 100.0
    injury_mult = _injury_multiplier_col(board, position)
    injury_n = _injury_sample_col(board, position)
    board = board.copy()
    board["opponent"] = opp
    board["matchup_factor"] = factor
    board["matchup_tag"] = matchup_tag(factor)
    board["injury_factor"] = injury_mult
    board["injury_sample_n"] = injury_n
    board["PROJ"] = (_rate(board) * form_mult * factor * injury_mult).round(1)
    board.attrs["matchup_breakdown"] = breakdown
    return board


def rest_of_season_value(board, position, bundle=None, season=None, scoring=None):
    """A single blended projection per player: FORM-adjusted fpts/game
    averaged across every real defense's granular matchup factor (no
    single specific opponent), also carrying the same real injury-impact
    factor project_vs applies. Used by trade/start-sit/waiver tools that
    need one number, not a per-opponent one."""
    bundle = bundle or load_bundle(season)
    avg_factor = defense_layer.league_average_composite(position, bundle["defense_factors"])
    form_mult = 1 + board["FORM"] / 100.0
    injury_mult = _injury_multiplier_col(board, position)
    # Games he is expected to miss (ESPN's return date) cut his rest-of-season
    # value: a season-ending injury is worth nothing.
    avail = _availability_col(board, bundle["schedule"])
    return (_rate(board) * form_mult * avg_factor * injury_mult * avail).round(1)


_OVERALL_CACHE: dict = {}
OVERALL_TTL_SECONDS = 120   # live injuries (15 min feed) are the freshest input; 2 minutes is well inside that


def _overall_key_scoring(key):
    return key[1]


def overall_board(scoring=None, league=None, season=None, ecr=None):
    """Cached for OVERALL_TTL_SECONDS per (season, scoring, league): it is the
    same stitched list for everyone who asks for it, and rebuilding it per
    request (four boards, the expert-rank lookup, value and PVS) was the
    heaviest thing a signed-out visitor could trigger. Always returns a copy.
    A caller that passes its own `ecr` bypasses the cache."""
    if ecr is not None:
        return _overall_board_uncached(scoring, league, season, ecr)
    season = season or data.resolve_season()
    league_key = None if league is None else json.dumps(league, sort_keys=True, default=str)
    key = (season, _scoring_cache_key(scoring), league_key)
    hit = _cache_get(_OVERALL_CACHE, key, _overall_key_scoring)
    if hit is not None and time.time() - hit[0] < OVERALL_TTL_SECONDS:
        out = hit[1].copy()
        out.attrs = dict(hit[1].attrs)
        return out
    out = _overall_board_uncached(scoring, league, season, None)
    _cache_put(_OVERALL_CACHE, key, (time.time(), out), _overall_key_scoring)
    copy = out.copy()
    copy.attrs = dict(out.attrs)
    return copy


def _overall_board_uncached(scoring=None, league=None, season=None, ecr=None):
    """Every QB/RB/WR/TE ranked on ONE list by value over replacement, blended
    with the expert consensus rank (see engine/value.py). `league` is
    {teams, slots} (engine/value.DEFAULT_LEAGUE shape) or None for a 12-team
    1QB/2RB/2WR/1TE/1FLEX league. Not cached: it only stitches together the
    four cached position boards."""
    season = season or data.resolve_season()
    bundle = load_bundle(season)
    frames = {}
    for pos in POSITIONS:
        b = build_board(pos, season, min_games=1, scoring=scoring).copy()
        b["PROJ"] = rest_of_season_value(b, pos, bundle=bundle)
        frames[pos] = b
    if ecr is None:
        ecr = consensus.overall_lookup()
    out = value_layer.compute_value(frames, ecr=ecr, league=league)
    out = pvs.reorder(pvs.add_pvs(out, league=league))
    out.attrs["scoring"] = frames["QB"].attrs.get("scoring")
    out.attrs["replacement_ranks"] = value_layer.replacement_ranks(league)
    return out


def search_players(query, season=None, limit=20):
    """Lightweight name/team search across all positions — used by the
    start/sit and trade pickers so they aren't locked to one position tab.
    Cheap: no metric computation, just the latest identity row per player."""
    bundle = load_bundle(season)
    wk = bundle["wk"]
    sub = wk[wk["position"].isin(POSITIONS)]
    last = sub.sort_values("week").groupby("player_id").last().reset_index()
    q = query.strip().lower()
    if not q:
        return []
    mask = (last["player_display_name"].str.lower().str.contains(q, na=False) |
            last["recent_team"].str.lower().str.contains(q, na=False))
    cols = ["player_id", "player_display_name", "position", "recent_team", "headshot_url"]
    return last[mask][cols].head(limit).to_dict(orient="records")


def player_detail(player_id, season=None, scoring=None):
    """Full record for one player across every position's tables (whichever
    position they belong to), for a player detail view."""
    bundle = load_bundle(season)
    wk_raw = bundle["wk"]
    prow = wk_raw[wk_raw["player_id"] == player_id]
    if prow.empty:
        return None
    position = prow.iloc[-1]["position"]
    if position not in POSITIONS:
        return None
    # min_games=0, not the ranked-list default of 2: this is one player asked
    # for by id (his card, his news, his projection compare), the same case
    # My Team/Start-Sit/Trade already fall back for. With the default, every
    # card 404'd in week 1 (nobody has 2 games yet) and any 1-game player
    # clicked from a roster later on. The volume bar still applies.
    board = build_board(position, season, min_games=0, scoring=scoring)
    if player_id not in board.index:
        return None
    row = board.loc[player_id].to_dict()
    row["player_id"] = player_id
    row["position"] = position
    row["scoring"] = board.attrs.get("scoring")
    row["injury"] = injuries.report_for(player_id, row, bundle["schedule"])
    if row["injury"]:
        row["injury"]["impact"] = injury_impact.injury_adjustment_detail(
            position, row["injury"]["status"], row["injury"]["body_part"])
        row["injury"]["play_chance"] = play_prob.play_probability(position, row["injury"]["status"], row.get("injury_report"))
    if history.available():
        row["history"] = history.summary(player_id, position, scoring, bundle["season"], row.get("history_weight"))

    wk_scored, settings = apply_scoring(prow, scoring)
    # Real per-week raw counting stats, not just fantasy points — lets the
    # frontend plot week-by-week trends/breakdowns for whichever stats
    # actually apply to this position, not just one aggregate bar chart.
    weekly_cols = WEEKLY_LOG_COLUMNS.get(position, [])
    present_cols = [c for c in weekly_cols if c in wk_scored.columns]
    weekly_log = (wk_scored.sort_values("week")
                  [["week", "opponent_team", "fpts_active"] + present_cols]
                  .rename(columns={"fpts_active": "fpts"})
                  .to_dict(orient="records"))
    row["weekly_log"] = weekly_log

    # Every week of the schedule tagged played / BYE / missed / upcoming, with
    # the stat columns for weeks he played.
    team = row.get("recent_team")
    if team:
        played = wk_scored[["week", "fpts_active"] + present_cols].rename(columns={"fpts_active": "fpts"})
        row["weekly_status"] = profile.weekly_status(played, bundle["schedule"], team)
        # Each played week's real pre-game projection (Sleeper), so the weekly
        # breakdown can show whether he beat it or fell short.
        try:
            played_weeks = [r["week"] for r in row["weekly_status"] if r["status"] == "played"]
            projs = weekly_proj.player_projections(player_id, position, season or data.resolve_season(),
                                                   played_weeks, settings)
            weekly_proj.attach(row["weekly_status"], projs)
        except Exception as e:
            print(f"[board] weekly projections skipped for {player_id}: {e}")
        row["bye_week"] = profile.bye_weeks(bundle["schedule"]).get(team)

    # Plain totals, steadiness, and every Next Gen Stat with its percentile.
    row["totals"] = {k: (None if pd.isna(v) else float(v))
                     for k, v in profile.season_totals(wk_scored, position).loc[player_id].items()}
    cons = profile.consistency(wk_scored, position)
    if player_id in cons.index:
        row["consistency"] = {k: (None if pd.isna(v) else float(v)) for k, v in cons.loc[player_id].items()}
    kind = NGS_KIND[position]
    row["ngs"] = profile.ngs_profile(_ngs_for(position, bundle), kind, player_id)

    team = row.get("recent_team")
    if team:
        opp, wk_no = data.next_opponent(bundle["schedule"], team)
        row["next_opponent"] = opp
        row["next_week"] = wk_no
    return row
