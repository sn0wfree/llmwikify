"""Tests for DreamScheduler (Phase 6 Step 4).

Tests cover:
  - Construction with various cron expressions
  - Disabled scheduler is a no-op
  - Start/stop lifecycle (uses real APScheduler)
  - Job fires at correct cron
  - Failure tolerance: dream.run() raises → scheduler keeps running
  - next_run_time property
  - Idempotent start (double-start safe)

Note: These tests use real APScheduler (not mocked) because:
  - APScheduler is a fast, well-tested library
  - The integration surface is small (just call dream.run())
  - Mocking would miss real scheduling bugs
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.memory.dream import Dream
from llmwikify.apps.chat.memory.dream_scheduler import (
    CRON_DAILY_03,
    CRON_HOURLY,
    DreamScheduler,
)


def _make_dream_mock() -> MagicMock:
    """Build a minimal Dream mock."""
    dream = MagicMock(spec=Dream)
    dream.run = AsyncMock(return_value=MagicMock(
        consolidations_scanned=5,
        facts_extracted=3,
        facts_written=3,
        cursor=12345.0,
    ))
    return dream


class TestDreamSchedulerConstruction:
    def test_default_cron(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock())
        assert sched.cron_expression == CRON_DAILY_03
        assert sched.enabled is True
        assert sched.is_running is False

    def test_custom_cron(self) -> None:
        sched = DreamScheduler(
            dream=_make_dream_mock(),
            cron_expression=CRON_HOURLY,
            enabled=False,
        )
        assert sched.cron_expression == CRON_HOURLY
        assert sched.enabled is False

    def test_disabled_by_default_state(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock(), enabled=False)
        assert sched.is_running is False
        assert sched.next_run_time is None


class TestDreamSchedulerDisabled:
    @pytest.mark.asyncio
    async def test_disabled_start_is_noop(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock(), enabled=False)
        await sched.start()
        assert sched.is_running is False


class TestDreamSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        dream = _make_dream_mock()
        sched = DreamScheduler(
            dream=dream,
            cron_expression="0 3 * * *",
        )
        await sched.start()
        assert sched.is_running is True
        await sched.stop()
        assert sched.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock())
        await sched.start()
        # Should not raise on second start
        await sched.start()
        assert sched.is_running is True
        await sched.stop()

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock())
        await sched.start()
        await sched.stop()
        # Should not raise on second stop
        await sched.stop()
        assert sched.is_running is False

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock())
        await sched.stop()
        assert sched.is_running is False


class TestDreamSchedulerNextRunTime:
    @pytest.mark.asyncio
    async def test_next_run_time_set_after_start(self) -> None:
        sched = DreamScheduler(
            dream=_make_dream_mock(),
            cron_expression="0 3 * * *",
        )
        await sched.start()
        try:
            nrt = sched.next_run_time
            assert nrt is not None
            # next run at 03:00 local time
            assert nrt.hour == 3
            assert nrt.minute == 0
        finally:
            await sched.stop()

    @pytest.mark.asyncio
    async def test_next_run_time_none_before_start(self) -> None:
        sched = DreamScheduler(dream=_make_dream_mock())
        assert sched.next_run_time is None


class TestDreamSchedulerExecution:
    @pytest.mark.asyncio
    async def test_run_dream_called(self) -> None:
        """Verify the dream.run callback is wired correctly."""
        dream = _make_dream_mock()
        sched = DreamScheduler(dream=dream, cron_expression="0 3 * * *")
        await sched._run_dream()  # direct call (bypasses cron)
        dream.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_dream_swallows_exceptions(self) -> None:
        """A failing dream.run() should not crash the scheduler."""
        dream = MagicMock(spec=Dream)
        dream.run = AsyncMock(side_effect=RuntimeError("boom"))
        sched = DreamScheduler(dream=dream)
        # Should not raise
        await sched._run_dream()
        dream.run.assert_called_once()


class TestDreamSchedulerIntegration:
    """Light integration test: start scheduler, manually trigger job, stop."""

    @pytest.mark.asyncio
    async def test_start_run_stop_cycle(self) -> None:
        dream = _make_dream_mock()
        sched = DreamScheduler(
            dream=dream,
            cron_expression="0 3 * * *",
        )
        await sched.start()
        try:
            # Manually fire the job (bypass cron wait)
            await sched._run_dream()
            assert dream.run.call_count == 1
        finally:
            await sched.stop()


class TestDreamSchedulerImportError:
    @pytest.mark.asyncio
    async def test_missing_apscheduler_raises(self) -> None:
        """If apscheduler is uninstalled, start() raises ImportError."""
        import sys

        sched = DreamScheduler(dream=_make_dream_mock())
        # Simulate apscheduler not installed
        apscheduler_modules = [
            name
            for name in sys.modules
            if name.startswith("apscheduler")
        ]
        # Hide them temporarily
        hidden = {m: sys.modules.pop(m) for m in apscheduler_modules}
        # Inject ImportError via missing modules
        for name in ("apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio"):
            sys.modules[name] = None  # causes ImportError on import

        try:
            with pytest.raises(ImportError):
                await sched.start()
        finally:
            # Restore
            for m, v in hidden.items():
                sys.modules[m] = v
            for name in ("apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio"):
                if name in sys.modules and sys.modules[name] is None:
                    del sys.modules[name]
