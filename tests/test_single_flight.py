"""Tests for engine/flight.py and its use around the board, overall-board, PVS,
projection-model and waiver-pool caches: when many requests miss the same cache
entry at once, exactly one of them builds it.

No network, no real data; the expensive builders are replaced with counters.

    .venv/bin/python -m unittest tests.test_single_flight -v
"""
import threading
import time
import unittest
from unittest import mock

import pandas as pd

from engine import board, projmodel, waivers
from engine.flight import SingleFlight

THREADS = 12


def run_together(fn, n=THREADS):
    """Start n threads at the same instant; return their results (exceptions re-raised)."""
    barrier = threading.Barrier(n)
    out, errs = [None] * n, []

    def worker(i):
        try:
            barrier.wait(timeout=10)
            out[i] = fn()
        except BaseException as e:          # noqa: BLE001 - surfaced below
            errs.append(e)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    if errs:
        raise errs[0]
    return out


class Counter:
    def __init__(self, delay=0.15):
        self.calls, self.delay, self._lock = 0, delay, threading.Lock()

    def tick(self):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)             # long enough that every other thread is already waiting


class SingleFlightUnit(unittest.TestCase):
    def test_one_build_for_many_simultaneous_misses(self):
        flight, cache, c = SingleFlight(), {}, Counter()

        def get():
            if "k" not in cache:
                with flight.hold("k"):
                    if "k" not in cache:
                        c.tick()
                        cache["k"] = object()
            return cache["k"]
        results = run_together(get)
        self.assertEqual(c.calls, 1)
        self.assertEqual(len({id(r) for r in results}), 1)

    def test_different_keys_do_not_wait_on_each_other(self):
        flight = SingleFlight()
        both_inside = threading.Barrier(2)

        def get(key):
            with flight.hold(key):
                both_inside.wait(timeout=5)         # raises BrokenBarrierError if the other key is blocked
        ts = [threading.Thread(target=get, args=(k,)) for k in ("a", "b")]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in ts))
        self.assertEqual(both_inside.broken, False)

    def test_same_thread_may_ask_for_the_same_key_again(self):
        flight = SingleFlight(wait_seconds=0.3)
        with flight.hold("k") as outer:
            with flight.hold("k") as inner:
                pass
        self.assertTrue(outer and inner)

    def test_a_waiter_gives_up_and_builds_itself_instead_of_hanging(self):
        flight = SingleFlight(wait_seconds=0.2)
        release, holding = threading.Event(), threading.Event()

        def holder():
            with flight.hold("k"):
                holding.set()
                release.wait(timeout=10)
        t = threading.Thread(target=holder)
        t.start()
        holding.wait(timeout=5)
        started = time.time()
        with flight.hold("k") as got:
            waited = time.time() - started
        release.set()
        t.join(timeout=5)
        self.assertFalse(got)                       # proceeded without the lock
        self.assertLess(waited, 2.0)

    def test_locks_are_dropped_when_nobody_needs_them(self):
        flight = SingleFlight()
        for k in range(50):
            with flight.hold(k):
                pass
        self.assertEqual(flight.in_flight(), 0)

    def test_an_error_in_the_build_releases_the_lock_for_the_next_caller(self):
        flight = SingleFlight()
        with self.assertRaises(RuntimeError):
            with flight.hold("k"):
                raise RuntimeError("build failed")
        self.assertEqual(flight.in_flight(), 0)
        with flight.hold("k") as got:
            self.assertTrue(got)


class BoardCaches(unittest.TestCase):
    def setUp(self):
        for name in ("_BOARD_CACHE", "_PVS_CACHE", "_OVERALL_CACHE"):
            getattr(board, name).clear()
        self.addCleanup(lambda: [getattr(board, n).clear() for n in ("_BOARD_CACHE", "_PVS_CACHE", "_OVERALL_CACHE")])
        mock.patch.object(board, "pvs_lookup", return_value={}).start()
        mock.patch.object(board.injuries, "overlay", side_effect=lambda df, bundle: df).start()
        mock.patch.object(board, "load_bundle", return_value={}).start()
        self.addCleanup(mock.patch.stopall)

    def test_build_board_builds_once_for_simultaneous_misses(self):
        c = Counter()

        def fake_build(position, season, min_volume, scoring):
            c.tick()
            df = pd.DataFrame({"games": [3, 4]}, index=["a", "b"])
            df.attrs["scoring"] = {}
            return df
        with mock.patch.object(board, "_build_board_uncached", side_effect=fake_build), \
                mock.patch.object(board, "shrunk_rate", return_value=pd.Series([1.0, 2.0], index=["a", "b"])):
            results = run_together(lambda: board.build_board("WR", season=2026))
        self.assertEqual(c.calls, 1)
        self.assertTrue(all(list(r.index) == ["a", "b"] for r in results))

    def test_build_board_still_builds_one_per_position(self):
        c = Counter(delay=0.05)

        def fake_build(position, season, min_volume, scoring):
            c.tick()
            df = pd.DataFrame({"games": [3]}, index=["a"])
            df.attrs["scoring"] = {}
            return df
        positions = ["QB", "RB", "WR", "TE"]
        idx = iter(range(10 ** 6))
        lock = threading.Lock()

        def pick():
            with lock:
                i = next(idx)
            return board.build_board(positions[i % 4], season=2026)
        with mock.patch.object(board, "_build_board_uncached", side_effect=fake_build), \
                mock.patch.object(board, "shrunk_rate", return_value=pd.Series([1.0], index=["a"])):
            run_together(pick)
        self.assertEqual(c.calls, 4)

    def test_a_custom_min_volume_still_bypasses_the_cache(self):
        c = Counter(delay=0)

        def fake_build(position, season, min_volume, scoring):
            c.tick()
            df = pd.DataFrame({"games": [3]}, index=["a"])
            df.attrs["scoring"] = {}
            return df
        with mock.patch.object(board, "_build_board_uncached", side_effect=fake_build), \
                mock.patch.object(board, "shrunk_rate", return_value=pd.Series([1.0], index=["a"])):
            board.build_board("WR", season=2026, min_volume=5)
            board.build_board("WR", season=2026, min_volume=5)
        self.assertEqual(c.calls, 2)
        self.assertEqual(board._BOARD_CACHE, {})

    def test_overall_board_builds_once_and_every_caller_gets_its_own_copy(self):
        c = Counter()

        def fake_overall(scoring, league, season, ecr):
            c.tick()
            df = pd.DataFrame({"PVS": [1.0, 2.0]}, index=["a", "b"])
            df.attrs["scoring"] = {"x": 1}
            return df
        with mock.patch.object(board, "_overall_board_uncached", side_effect=fake_overall):
            results = run_together(lambda: board.overall_board(season=2026))
        self.assertEqual(c.calls, 1)
        self.assertEqual(len({id(r) for r in results}), THREADS)        # copies, not one shared frame
        results[0].loc["a", "PVS"] = 99.0
        self.assertEqual(board.overall_board(season=2026).loc["a", "PVS"], 1.0)
        self.assertTrue(all(r.attrs == {"scoring": {"x": 1}} for r in results))

    def test_overall_board_rebuilds_after_the_ttl_once_not_per_caller(self):
        c = Counter(delay=0.1)

        def fake_overall(scoring, league, season, ecr):
            c.tick()
            return pd.DataFrame({"PVS": [1.0]}, index=["a"])
        with mock.patch.object(board, "_overall_board_uncached", side_effect=fake_overall):
            board.overall_board(season=2026)
            key = next(iter(board._OVERALL_CACHE))
            board._OVERALL_CACHE[key] = (time.time() - board.OVERALL_TTL_SECONDS - 1, board._OVERALL_CACHE[key][1])
            run_together(lambda: board.overall_board(season=2026))
        self.assertEqual(c.calls, 2)

    def test_pvs_lookup_builds_once(self):
        mock.patch.stopall()                       # this test needs the real pvs_lookup
        self.addCleanup(lambda: None)
        c = Counter()

        def fake_overall(scoring=None, league=None, season=None, ecr=None):
            c.tick()
            return pd.DataFrame({"PVS": [1.0, 2.0], "PVS_tier": ["T1", "T2"]}, index=["a", "b"])
        with mock.patch.object(board, "overall_board", side_effect=fake_overall):
            results = run_together(lambda: board.pvs_lookup(2026))
        self.assertEqual(c.calls, 1)
        self.assertTrue(all(r == {"a": (1.0, "T1"), "b": (2.0, "T2")} for r in results))
        self.assertFalse(getattr(board._PVS_LOCAL, "building", False))


class ModelAndPool(unittest.TestCase):
    def test_projection_model_trains_once_per_scoring(self):
        projmodel._MODELS.clear()
        self.addCleanup(projmodel._MODELS.clear)
        c = Counter()
        df = pd.DataFrame({"season": [2024, 2025], "player_id": ["a", "a"], "fpts_active": [1.0, 2.0]})

        def fake_scored(scoring, current):
            c.tick()
            return df
        with mock.patch.object(projmodel.history, "available", return_value=True), \
                mock.patch.object(projmodel, "_scored_history", side_effect=fake_scored), \
                mock.patch.object(projmodel, "_opportunity_values", return_value={}), \
                mock.patch.object(projmodel, "_training_rows", return_value=None), \
                mock.patch.object(projmodel, "fit", return_value={"QB": [1.0]}):
            results = run_together(lambda: projmodel.model({"reception": 0.5}, 2026))
        self.assertEqual(c.calls, 1)
        self.assertEqual(len({id(r) for r in results}), 1)

    def test_a_model_for_a_different_scoring_is_a_separate_build(self):
        projmodel._MODELS.clear()
        self.addCleanup(projmodel._MODELS.clear)
        c = Counter(delay=0.05)
        df = pd.DataFrame({"season": [2024, 2025], "player_id": ["a", "a"], "fpts_active": [1.0, 2.0]})

        def fake_scored(scoring, current):
            c.tick()
            return df
        scorings = [{"reception": 0.0}, {"reception": 0.5}, {"reception": 1.0}]
        idx, lock = iter(range(10 ** 6)), threading.Lock()

        def pick():
            with lock:
                i = next(idx)
            return projmodel.model(scorings[i % 3], 2026)
        with mock.patch.object(projmodel.history, "available", return_value=True), \
                mock.patch.object(projmodel, "_scored_history", side_effect=fake_scored), \
                mock.patch.object(projmodel, "_opportunity_values", return_value={}), \
                mock.patch.object(projmodel, "_training_rows", return_value=None), \
                mock.patch.object(projmodel, "fit", return_value={"QB": [1.0]}):
            run_together(pick)
        self.assertEqual(c.calls, 3)

    def test_waiver_pool_builds_once(self):
        waivers._POOL_CACHE.clear()
        self.addCleanup(waivers._POOL_CACHE.clear)
        c = Counter()

        def fake_pool(scoring, bundle):
            c.tick()
            return pd.DataFrame({"x": [1]}), {}
        with mock.patch.object(waivers, "player_pool", side_effect=fake_pool), \
                mock.patch.object(waivers, "usage_scores", return_value=pd.Series([1.0])):
            results = run_together(lambda: waivers.cached_pool(None, {"season": 2026}))
        self.assertEqual(c.calls, 1)
        self.assertEqual(len({id(r[0]) for r in results}), 1)


if __name__ == "__main__":
    unittest.main()
