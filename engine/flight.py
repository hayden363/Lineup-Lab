"""One build at a time per cache key.

When a cache is empty (just after a deploy, after an entry was dropped, or the
first time someone uses a new scoring setting) every request that arrives in the
same moment used to build the same thing on its own: 40 visitors meant 40
parallel copies of a board build, each holding its own tables in memory. On a
512 MB host that was a crash; on any host it made everyone wait for 40 builds
instead of one. With a flight lock the first caller builds, the rest wait and
then read the result from the cache the caller re-checks.

Used like this around the *miss* path only (hits never touch it):

    hit = cache.get(key)
    if hit is None:
        with FLIGHT.hold(("board", key)):
            hit = cache.get(key)          # someone else may have built it while we waited
            if hit is None:
                hit = build(); cache[key] = hit

Safety:
  * re-entrant per thread, so a build that asks for the same key again does not
    wait on itself;
  * a waiter gives up after `wait_seconds` and builds on its own (the old
    behaviour) instead of hanging, so a lock-order mistake can slow a request
    down but can never freeze the server;
  * locks are dropped once nobody holds or waits for them, so the table of locks
    stays as small as the number of builds actually in progress.
"""
import threading
from contextlib import contextmanager

DEFAULT_WAIT_SECONDS = 180


class SingleFlight:
    def __init__(self, wait_seconds=DEFAULT_WAIT_SECONDS):
        self.wait_seconds = wait_seconds
        self._guard = threading.Lock()
        self._entries = {}              # key -> [RLock, users]

    @contextmanager
    def hold(self, key):
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = [threading.RLock(), 0]
            entry[1] += 1
        got = entry[0].acquire(timeout=self.wait_seconds)
        try:
            yield got
        finally:
            if got:
                entry[0].release()
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0 and self._entries.get(key) is entry:
                    del self._entries[key]

    def in_flight(self):
        """Number of keys with a build running or waiting (for tests and logs)."""
        with self._guard:
            return len(self._entries)


FLIGHT = SingleFlight()
