"""DreamScheduler — APScheduler wrapper for periodic Dream runs.

Phase 6 (2026-06-19): Borrowed from nanobot cron pattern
(nanobot uses apscheduler in ``nanobot/cron/``).

Schedules ``Dream.run()`` to fire at a configured cron expression
(default: daily at 03:00 local time). Uses APScheduler's
``AsyncIOScheduler`` to integrate cleanly with FastAPI's event loop.

Usage:
    sched = DreamScheduler(
        dream=mm.dream,
        cron_expression="0 3 * * *",  # daily 03:00
    )
    await sched.start()
    # ... application runs ...
    await sched.stop()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─── Cron presets ────────────────────────────────────────────────

CRON_DAILY_03 = "0 3 * * *"
CRON_HOURLY = "0 * * * *"
CRON_WEEKLY_SUN_03 = "0 3 * * 0"


class DreamScheduler:
    """Periodic Dream trigger (Phase 6 Step 4).

    Thin wrapper over APScheduler's AsyncIOScheduler. Idempotent
    start/stop; safe to call multiple times.
    """

    def __init__(
        self,
        dream: Any,
        cron_expression: str = CRON_DAILY_03,
        enabled: bool = True,
    ):
        self.dream = dream
        self.cron_expression = cron_expression
        self.enabled = enabled
        self._scheduler: Any = None
        self._job: Any = None

    async def start(self) -> None:
        """Start the background scheduler.

        Lazy-imports apscheduler to keep the dependency optional
        for callers that only use /memory_dream (not the cron
        scheduler). If apscheduler is unavailable, this raises
        ImportError and the caller can fall back to a no-op.
        """
        if not self.enabled:
            logger.info("DreamScheduler: disabled, not starting")
            return

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as e:
            logger.error(
                "DreamScheduler: apscheduler not installed: %s. "
                "Install with `pip install 'llmwikify[agent]'`.",
                e,
            )
            raise

        if self._scheduler is not None:
            logger.debug("DreamScheduler: already started")
            return

        self._scheduler = AsyncIOScheduler()
        trigger = CronTrigger.from_crontab(self.cron_expression)
        self._job = self._scheduler.add_job(
            self._run_dream,
            trigger=trigger,
            id="phase6_dream_run",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "DreamScheduler: started with cron=%r",
            self.cron_expression,
        )

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
            logger.info("DreamScheduler: stopped")
        except Exception:
            logger.warning("DreamScheduler: shutdown error", exc_info=True)
        finally:
            self._scheduler = None
            self._job = None

    async def _run_dream(self) -> None:
        """Job callback: run Dream once. Failures logged + swallowed."""
        try:
            result = await self.dream.run()
            logger.info(
                "DreamScheduler: dream run completed "
                "(scanned=%d extracted=%d written=%d cursor=%.0f)",
                result.consolidations_scanned,
                result.facts_extracted,
                result.facts_written,
                result.cursor,
            )
        except Exception:
            logger.exception("DreamScheduler: dream run failed")

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None

    @property
    def next_run_time(self) -> Any:
        """Return APScheduler's computed next-run time (or None)."""
        if self._job is None:
            return None
        try:
            return self._job.next_run_time
        except (AttributeError, Exception):
            return None


__all__ = [
    "CRON_DAILY_03",
    "CRON_HOURLY",
    "CRON_WEEKLY_SUN_03",
    "DreamScheduler",
]
