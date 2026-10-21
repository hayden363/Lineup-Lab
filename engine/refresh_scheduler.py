"""
WEEKLY-REFRESH AUTOMATION
=========================
An in-process background task that periodically re-fetches everything
engine/board.py's load_bundle() needs, bypassing the disk cache — the
same work POST /api/refresh already does on demand, just run on a timer
instead of waiting for someone to click it (or for the first request
after the disk cache's own TTL expires to eat the fetch cost).

Two things this buys you beyond "the cache is never too stale":
  1. The board is warm the moment someone opens the app, instead of the
     first request of the day paying nflverse's fetch latency.
  2. force=True here also re-resolves the season itself (see
     data.resolve_season's `force` param), not just re-fetching whatever
     season was already resolved — the exact distinction that mattered
     when this app was stuck thinking no 2025 data existed yet (see
     README's "Data freshness" section). Without this, a newly published
     season would sit undetected until the process restarts.

Runs as an asyncio task started from server.py's lifespan, in-process —
no separate cron job, launchd plist, or external scheduler to set up,
matching this app's "single process, single command" design (see
README's "Run it").

Interval: REFRESH_INTERVAL_HOURS in .env, default 24 (daily) — matches
how often nflverse's weekly stats actually change (at most once a day
during the season; see engine/data.py's CACHE_TTL_SECONDS comment), not
the "weekly" the roadmap originally named this after. Set to 0 to
disable the background task entirely (POST /api/refresh still works
on demand either way).
"""

import asyncio
import os
import time

from . import board, contingency, correlation, tools

DEFAULT_INTERVAL_HOURS = 24
_WARM_TASK = None
_TABLES_TASK = None


def _interval_seconds():
    try:
        hours = float(os.environ.get("REFRESH_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS))
    except ValueError:
        print(f"[refresh_scheduler] REFRESH_INTERVAL_HOURS isn't a number, "
              f"using default ({DEFAULT_INTERVAL_HOURS}h)")
        hours = DEFAULT_INTERVAL_HOURS
    return max(hours, 0) * 3600


async def _refresh_loop():
    interval = _interval_seconds()
    if interval <= 0:
        print("[refresh_scheduler] REFRESH_INTERVAL_HOURS=0 — background auto-refresh disabled "
              "(POST /api/refresh still works on demand)")
        return

    print(f"[refresh_scheduler] auto-refresh enabled, every {interval / 3600:g}h")

    # Deliberately NOT warming the board cache here at process start (only
    # after each scheduled/forced refresh below). Precomputing all 16
    # (position, scoring) variants back-to-back is 16 real pandas builds
    # in a tight burst — on a memory-constrained host, that burst itself
    # can push RSS higher than any single request ever would (numpy/pandas'
    # allocator doesn't reliably hand freed memory back to the OS between
    # operations, so a rapid sequence of builds can ratchet peak RSS up
    # even though each one's own live footprint is small). Running on
    # every process start is exactly the wrong time to do that on a host
    # that's already tight on memory — real traffic naturally spreads the
    # same work out over time instead. See git history for why this was
    # tried and reverted.

    while True:
        await asyncio.sleep(interval)
        started = time.time()
        try:
            # load_bundle does its own network I/O synchronously (requests/
            # pandas, not async) — run it off the event loop thread so a
            # slow nflverse/GitHub fetch doesn't stall every other request
            # this process is serving while it runs.
            bundle = await asyncio.to_thread(board.load_bundle, None, True)
            print(f"[refresh_scheduler] refreshed season {bundle['season']} "
                  f"in {time.time() - started:.1f}s")
            await _warm_model_tables(delay=0)   # this week's games change both tables
            # Deliberately not eagerly warming board.py's cache here either
            # (see the comment above this loop) — on a memory-constrained
            # host, real request traffic filling the cache in naturally,
            # one board at a time, is safer than a 16-build burst right
            # after every refresh. board.warm_common_boards() still exists
            # for a host with real headroom to call explicitly.
        except Exception as e:
            # A flaky fetch shouldn't kill the background task — it just
            # tries again next interval, same as any other cache miss
            # elsewhere in this app degrading gracefully instead of crashing.
            print(f"[refresh_scheduler] refresh failed (will retry next interval): {e}")

        # Track record: grade any logged Start/Sit predictions whose real
        # week has fully played out since the last tick — see
        # tools.resolve_track_record's docstring. Independent try/except
        # from the board refresh above: no DATABASE_URL configured (or a
        # transient DB hiccup) shouldn't be treated the same as a failed
        # nflverse fetch, and shouldn't block it either.
        try:
            resolved = await asyncio.to_thread(tools.resolve_track_record)
            if resolved:
                print(f"[refresh_scheduler] resolved {resolved} track-record prediction(s)")
        except Exception as e:
            print(f"[refresh_scheduler] track-record resolve skipped: {e}")


async def _warm_model_tables(delay=20):
    """Always on, and cheap (no extra memory measured): the correlation and
    teammate-absence tables are built from history, take a few seconds on a
    small host, and would otherwise land on whichever visitor first compares
    two teammates or opens a card with an injured teammate."""
    try:
        await asyncio.sleep(delay)
        bundle = await asyncio.to_thread(board.load_bundle)
        await asyncio.to_thread(correlation.table, bundle["wk"])
        await asyncio.to_thread(contingency.absorption, bundle["wk"])
        print("[refresh_scheduler] correlation and teammate-absence tables ready")
    except Exception as e:
        print(f"[refresh_scheduler] model-table warm skipped: {e}")


def _warm_enabled():
    return os.environ.get("WARM_ON_START", "").strip().lower() in ("1", "true", "yes")


async def _warm_on_start():
    """Opt-in (WARM_ON_START=1): after a deploy or restart, build the default
    boards in the background so the first visitors don't all pay for it at once.
    Off by default: on a 512 MiB host the older 16-build version of this pushed
    memory too high (see the note in _refresh_loop). Turn it on once the host has
    headroom (about 1 GB or more)."""
    if not _warm_enabled():
        return
    started = time.time()
    try:
        await asyncio.to_thread(board.load_bundle)
        await asyncio.to_thread(board.warm_default_boards)
        print(f"[refresh_scheduler] default boards warmed in {time.time() - started:.1f}s")
    except Exception as e:
        print(f"[refresh_scheduler] warm on start skipped: {e}")


def start():
    """Schedule the background refresh loop. Call once, from server.py's
    lifespan startup, inside a running event loop. Returns the
    asyncio.Task — server.py holds onto it only so it isn't
    garbage-collected mid-flight (a bare fire-and-forget task has no
    other referent keeping it alive); nothing else needs the handle."""
    global _WARM_TASK
    _WARM_TASK = asyncio.ensure_future(_warm_on_start())   # held so it isn't garbage-collected mid-flight
    global _TABLES_TASK
    _TABLES_TASK = asyncio.ensure_future(_warm_model_tables())
    return asyncio.ensure_future(_refresh_loop())
