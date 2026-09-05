"""
BOARD BUILDER
=============
The single entry point the API (and CLI) calls: build a fully-scored,
matchup-projected big board for one position.

Pipeline: weekly stats -> base metrics -> SCORE (weighted) -> advanced
(NGS + pbp) merged in -> FORM (recent trend) -> optional matchup
projection vs an opponent defense.
"""

from typing import TypedDict

import numpy as np
import pandas as pd

from . import data
from . import defense as defense_layer
from .metrics import METRIC_FNS, WEIGHTS, score_players, form_adjustment
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
    snap_pct: dict
    redzone_touches: dict

ADVANCED_FNS = {"QB": qb_advanced, "RB": rb_advanced, "WR": wr_advanced, "TE": te_advanced}
NGS_KIND = {"QB": "passing", "RB": "rushing", "WR": "receiving", "TE": "receiving"}

POSITIONS = ("QB", "RB", "WR", "TE")

# Minimum "volume" (attempts / touches / targets, position-appropriate) to be
# considered a qualified sample — filters out mop-up-duty / one-play noise
# that would otherwise produce absurd rate stats off a tiny denominator.
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

# Every build_board() call, fully computed, keyed by (position, season,
# scoring) — see build_board()'s docstring for why min_games/min_volume
# aren't part of this key. Cleared wholesale on a forced bundle refresh
# (load_bundle's force=True path below), since a cached board is only
# valid for the raw tables it was built from.
_BOARD_CACHE: dict = {}


def _scoring_cache_key(scoring):
    """A hashable stand-in for `scoring` to use as part of a cache key.
    Safe because every real caller (server.py's scoring_from_query /
    _effective_scoring) only ever produces None or a plain dict with a
    fixed set of keys — never a partial dict, never a ScoringSettings
    instance."""
    return None if scoring is None else tuple(sorted(scoring.items()))


def _snap_pct_from(snaps, crosswalk):
    """Real per-player offense-snap-share, from already-fetched snap-count
    + id-crosswalk tables — pure computation, no I/O."""
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
    whose situation has since changed. Snap share and red-zone touches
    stay season-level on purpose (there's no live equivalent) — they're
    real season context, not claimed to be "as of this week.\""""
    season = season or data.resolve_season(force=force)
    key = _cache_key(season)
    if not force and key in _BUNDLE_CACHE:
        return _BUNDLE_CACHE[key]

    from . import sleeper as sleeper_layer

    wk = data.load_weekly(season, force=force)
    pbp = data.load_pbp(season, force=force)
    ngs_pass = data.load_ngs("passing", season, force=force)
    ngs_rush = data.load_ngs("rushing", season, force=force)
    ngs_rec = data.load_ngs("receiving", season, force=force)
    schedule = data.load_schedule(season, force=force)

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
                  injury_status=injury_status, snap_pct=snap_pct, redzone_touches=redzone_touches)
    _BUNDLE_CACHE[key] = bundle
    if force:
        # Every previously-computed board was built from the raw tables
        # this refresh just superseded — a whole-cache clear is simple,
        # correct, and cheap next to the refresh itself (this only runs
        # on the 24h scheduler tick or an explicit POST /api/refresh, not
        # a hot path).
        _BOARD_CACHE.clear()
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
    base = base[base["volume"] >= min_volume]

    adv = ADVANCED_FNS[position](bundle["pbp"], _ngs_for(position, bundle))
    board = base.join(adv, how="left")

    board["SCORE"] = score_players(base, WEIGHTS[position])
    board["FORM"] = form_adjustment(wk, position, weekly_epa=weekly_epa(bundle["pbp"], position))
    board["FORM"] = board["FORM"].reindex(board.index).fillna(0.0)

    board.index.name = "player_id"

    # Real availability/opportunity signals (see _availability_signals) —
    # merged on, not recomputed per position.
    board["injury_status"] = board.index.to_series().map(bundle.get("injury_status", {}))
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

    retired_ids = bundle.get("retired_ids")
    if retired_ids:
        board = board[~board.index.isin(retired_ids)]
    board.attrs["scoring"] = settings.as_dict()
    return board.sort_values("SCORE", ascending=False)


def build_board(position, season=None, min_games=2, min_volume=None, scoring=None):
    """The scored/advanced/FORM/floor-ceiling board for one position,
    cached by (position, season, scoring) — every real call site (the API,
    waivers, trade/start-sit tools) ends up asking for the same handful of
    these per refresh cycle, and rebuilding one from raw tables is the
    single most expensive thing this app does (metrics + advanced NGS/pbp
    merge + FORM's per-player recency math + floor/ceiling, all over the
    full season). min_games/min_volume deliberately aren't part of the
    cache key: neither affects the cost of any of that — they're a filter
    applied afterward, so a `min_games=0` and a `min_games=3` request for
    the same position/scoring share one cached computation instead of
    paying for it twice."""
    position = position.upper()
    if position not in POSITIONS:
        raise ValueError(f"position must be one of {POSITIONS}")
    season = season or data.resolve_season()
    key = (position, season, _scoring_cache_key(scoring))
    board = _BOARD_CACHE.get(key)
    if board is None:
        board = _build_board_uncached(position, season, min_volume, scoring)
        _BOARD_CACHE[key] = board
    filtered = board[board["games"] >= min_games]
    # .attrs propagation through boolean-mask indexing isn't guaranteed on
    # pandas 1.5.3 (still marked experimental upstream) — set it explicitly
    # rather than trust it survived the filter above.
    filtered.attrs["scoring"] = board.attrs.get("scoring")
    return filtered


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


def project_vs(board, position, opp, bundle=None, season=None, scoring=None):
    """Add a PROJ column: fpts_per_game adjusted for FORM and the real,
    per-stat-category matchup factor vs this specific opponent defense."""
    bundle = bundle or load_bundle(season)
    factor = matchup_multiplier(position, opp, bundle)
    breakdown = defense_layer.matchup_breakdown(position, opp, bundle["defense_factors"]) if opp in bundle["defense_factors"].index else []
    form_mult = 1 + board["FORM"] / 100.0
    board = board.copy()
    board["opponent"] = opp
    board["matchup_factor"] = factor
    board["matchup_tag"] = matchup_tag(factor)
    board["PROJ"] = (board["fpts_per_game"] * form_mult * factor).round(1)
    board.attrs["matchup_breakdown"] = breakdown
    return board


def rest_of_season_value(board, position, bundle=None, season=None, scoring=None):
    """A single blended projection per player: FORM-adjusted fpts/game
    averaged across every real defense's granular matchup factor (no
    single specific opponent). Used by trade/start-sit/waiver tools that
    need one number, not a per-opponent one."""
    bundle = bundle or load_bundle(season)
    avg_factor = defense_layer.league_average_composite(position, bundle["defense_factors"])
    form_mult = 1 + board["FORM"] / 100.0
    return (board["fpts_per_game"] * form_mult * avg_factor).round(1)


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
    board = build_board(position, season, scoring=scoring)
    if player_id not in board.index:
        return None
    row = board.loc[player_id].to_dict()
    row["player_id"] = player_id
    row["position"] = position
    row["scoring"] = board.attrs.get("scoring")

    wk_scored, _ = apply_scoring(prow, scoring)
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

    team = row.get("recent_team")
    if team:
        opp, wk_no = data.next_opponent(bundle["schedule"], team)
        row["next_opponent"] = opp
        row["next_week"] = wk_no
    return row
