"""Tests for engine/refresh_scheduler.py: interval parsing, the disabled loop,
failure isolation between the board refresh and the track-record resolve, and
the opt-in warm-on-start.

Everything is patched, no network and no real sleeping.

    .venv/bin/python -m unittest tests.test_refresh_scheduler -v
"""
import asyncio
import os
import unittest
from unittest import mock

from engine import refresh_scheduler as rs


def env(**kw):
    return mock.patch.dict(os.environ, kw, clear=False)


class Interval(unittest.TestCase):
    def setUp(self):
        os.environ.pop("REFRESH_INTERVAL_HOURS", None)
        self.addCleanup(os.environ.pop, "REFRESH_INTERVAL_HOURS", None)

    def test_unset_is_a_day(self):
        self.assertEqual(rs._interval_seconds(), 24 * 3600)

    def test_hours_convert_to_seconds(self):
        with env(REFRESH_INTERVAL_HOURS="6"):
            self.assertEqual(rs._interval_seconds(), 21600)
        with env(REFRESH_INTERVAL_HOURS="0.5"):
            self.assertEqual(rs._interval_seconds(), 1800)

    def test_zero_disables(self):
        with env(REFRESH_INTERVAL_HOURS="0"):
            self.assertEqual(rs._interval_seconds(), 0)

    def test_negative_is_clamped_to_zero(self):
        with env(REFRESH_INTERVAL_HOURS="-3"):
            self.assertEqual(rs._interval_seconds(), 0)

    def test_garbage_falls_back_to_the_default(self):
        with env(REFRESH_INTERVAL_HOURS="abc"), mock.patch("builtins.print"):
            self.assertEqual(rs._interval_seconds(), 24 * 3600)


class WarmFlags(unittest.TestCase):
    def test_truthy_spellings_turn_it_on(self):
        for v in ("1", "true", "YES", " True "):
            with env(WARM_ON_START=v):
                self.assertTrue(rs._warm_enabled(), v)

    def test_everything_else_leaves_it_off(self):
        for v in ("", "0", "no", "false", "off"):
            with env(WARM_ON_START=v):
                self.assertFalse(rs._warm_enabled(), v)
        os.environ.pop("WARM_ON_START", None)
        self.assertFalse(rs._warm_enabled())


class RefreshLoop(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ.pop("REFRESH_INTERVAL_HOURS", None)
        self.addCleanup(os.environ.pop, "REFRESH_INTERVAL_HOURS", None)
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def one_tick_sleep(self, interval):
        """A fake asyncio.sleep: the first loop-length sleep returns, the second cancels the loop.
        (_warm_model_tables sleeps for `delay` too, which must just return.)"""
        state = {"n": 0}

        async def fake(seconds):
            if seconds == interval:
                state["n"] += 1
                if state["n"] > 1:
                    raise asyncio.CancelledError
        return fake

    async def run_one_tick(self):
        interval = rs._interval_seconds()
        with mock.patch.object(rs.asyncio, "sleep", self.one_tick_sleep(interval)):
            with self.assertRaises(asyncio.CancelledError):
                await rs._refresh_loop()

    async def test_disabled_returns_without_sleeping(self):
        os.environ["REFRESH_INTERVAL_HOURS"] = "0"
        sleep = mock.AsyncMock(side_effect=asyncio.CancelledError)   # a loop that wrongly starts fails instead of hanging
        with mock.patch.object(rs.asyncio, "sleep", sleep), \
                mock.patch.object(rs.board, "load_bundle") as lb:
            await rs._refresh_loop()
        sleep.assert_not_called()
        lb.assert_not_called()

    async def test_happy_path_forces_a_refresh_and_warms_the_model_tables(self):
        with mock.patch.object(rs.board, "load_bundle", return_value={"season": 2026, "wk": object()}) as lb, \
                mock.patch.object(rs, "_warm_model_tables", new=mock.AsyncMock()) as warm, \
                mock.patch.object(rs.tools, "resolve_track_record", return_value=0):
            await self.run_one_tick()
        lb.assert_called_once_with(None, True)            # force=True re-resolves the season
        warm.assert_awaited_once_with(delay=0)

    async def test_a_failed_refresh_does_not_stop_the_track_record_resolve(self):
        with mock.patch.object(rs.board, "load_bundle", side_effect=RuntimeError("nflverse down")), \
                mock.patch.object(rs.tools, "resolve_track_record", return_value=2) as rtr:
            await self.run_one_tick()
        rtr.assert_called_once_with()

    async def test_a_failed_track_record_resolve_does_not_undo_the_refresh(self):
        with mock.patch.object(rs.board, "load_bundle", return_value={"season": 2026, "wk": object()}) as lb, \
                mock.patch.object(rs, "_warm_model_tables", new=mock.AsyncMock()) as warm, \
                mock.patch.object(rs.tools, "resolve_track_record", side_effect=RuntimeError("no DATABASE_URL")):
            await self.run_one_tick()
        lb.assert_called_once()
        warm.assert_awaited_once()

    async def test_the_loop_keeps_running_after_an_error(self):
        # two ticks, both failing: the loop must reach the second tick instead of dying on the first
        interval = rs._interval_seconds()
        state = {"n": 0}

        async def fake(seconds):
            if seconds == interval:
                state["n"] += 1
                if state["n"] > 2:
                    raise asyncio.CancelledError
        with mock.patch.object(rs.asyncio, "sleep", fake), \
                mock.patch.object(rs.board, "load_bundle", side_effect=RuntimeError("boom")) as lb, \
                mock.patch.object(rs.tools, "resolve_track_record", return_value=0):
            with self.assertRaises(asyncio.CancelledError):
                await rs._refresh_loop()
        self.assertEqual(lb.call_count, 2)


class WarmOnStart(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    async def test_off_by_default_touches_nothing(self):
        os.environ.pop("WARM_ON_START", None)
        with mock.patch.object(rs.board, "load_bundle") as lb, \
                mock.patch.object(rs.board, "warm_default_boards") as wd:
            await rs._warm_on_start()
        lb.assert_not_called()
        wd.assert_not_called()

    async def test_on_builds_the_bundle_then_the_default_boards(self):
        order = []
        with env(WARM_ON_START="1"), \
                mock.patch.object(rs.board, "load_bundle", side_effect=lambda *a, **k: order.append("bundle")), \
                mock.patch.object(rs.board, "warm_default_boards", side_effect=lambda *a, **k: order.append("boards")):
            await rs._warm_on_start()
        self.assertEqual(order, ["bundle", "boards"])

    async def test_a_failure_is_swallowed(self):
        with env(WARM_ON_START="1"), mock.patch.object(rs.board, "load_bundle", side_effect=RuntimeError("x")):
            await rs._warm_on_start()          # must not raise


class WarmModelTables(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    async def test_builds_both_tables_from_the_bundle_history(self):
        wk = object()
        with mock.patch.object(rs.board, "load_bundle", return_value={"wk": wk}), \
                mock.patch.object(rs.correlation, "table") as ct, \
                mock.patch.object(rs.contingency, "absorption") as ab:
            await rs._warm_model_tables(delay=0)
        ct.assert_called_once_with(wk)
        ab.assert_called_once_with(wk)

    async def test_a_failure_is_swallowed(self):
        with mock.patch.object(rs.board, "load_bundle", side_effect=RuntimeError("x")):
            await rs._warm_model_tables(delay=0)       # must not raise


if __name__ == "__main__":
    unittest.main()
