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

from . import board, tools

DEFAULT_INTERVAL_HOURS = 24


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


def start():
    """Schedule the background refresh loop. Call once, from server.py's
    lifespan startup, inside a running event loop. Returns the
    asyncio.Task — server.py holds onto it only so it isn't
    garbage-collected mid-flight (a bare fire-and-forget task has no
    other referent keeping it alive); nothing else needs the handle."""
    return asyncio.ensure_future(_refresh_loop())
