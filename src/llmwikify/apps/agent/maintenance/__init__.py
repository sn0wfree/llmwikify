"""Self-maintenance: unified manager started by the server lifespan.

Covers ALL LOCAL wikis in the registry. Track A (auto-ingest, direct write)
runs per-wiki via FileSystemWatcher; Track B (gap filler, proposal-based)
and DB maintenance run as shared periodic loops iterating every wiki.

All blocking wiki calls are wrapped in ``asyncio.to_thread``; a shared
``asyncio.Semaphore(3)`` caps concurrent LLM work (provider limit).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager
from llmwikify.kernel.multi_wiki.instance import WikiType

from .auto_ingest import AutoIngestService
from .config import MaintenanceConfig, load_maintenance_config, to_dict
from .gap_filler import GapFiller
from .rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)

LLM_CONCURRENCY = 3
HEALTH_HISTORY_LIMIT = 30


class MaintenanceManager:
    """Orchestrates auto-ingest / gap filling / DB maintenance for all wikis."""

    def __init__(
        self,
        registry: Any,
        config: MaintenanceConfig | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.registry = registry
        self.config = config or load_maintenance_config()
        self.llm_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
        # Process-wide background-LLM rate limit (default ≤5 units / 5s)
        # shared by every wiki's services, so maintenance never starves
        # the foreground chat/research traffic. See rate_limit.py.
        self.llm_rate_limiter = SlidingWindowRateLimiter(
            max_requests=self.config.llm_rate_limit.max_requests,
            window_seconds=self.config.llm_rate_limit.window_seconds,
            enabled=self.config.llm_rate_limit.enabled,
            name="maintenance_llm",
        )
        self.auto_ingest_services: dict[str, AutoIngestService] = {}
        self.gap_fillers: dict[str, GapFiller] = {}
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._health_history: list[dict[str, Any]] = []
        self._last_lint_summary: dict[str, Any] = {}
        self._last_db_maintenance_at: float | None = None
        # Shared WikiDatabase (same physical .llmwiki_agent.db as
        # WikiService's facades — get_connection is a per-path singleton),
        # so fallback proposals land in the SAME table the WebUI
        # /wiki-dream/proposals review flow reads. None → in-memory
        # proposals (pre-B1b behavior) when no data_dir is available.
        self._data_dir = data_dir
        self._proposal_db: Any = None

    def _get_proposal_db(self) -> Any:
        if self._proposal_db is not None or self._data_dir is None:
            return self._proposal_db
        try:
            from llmwikify.apps.wiki.db import WikiDatabase

            self._proposal_db = WikiDatabase(Path(self._data_dir))
        except Exception:
            logger.warning(
                "maintenance: proposal DB init failed, fallback proposals "
                "will be in-memory only",
                exc_info=True,
            )
            self._proposal_db = None
        return self._proposal_db

    def _make_proposal_manager(self, wiki_id: str) -> WikiDreamProposalManager:
        db = self._get_proposal_db()
        if db is None:
            return WikiDreamProposalManager(wiki_id=wiki_id)
        return WikiDreamProposalManager(db=db, wiki_id=wiki_id)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start watchers + periodic loops. Safe to call once; idempotent."""
        if self._running or not self.config.enabled:
            return
        self._running = True
        loop = asyncio.get_running_loop()

        for wiki_id, wiki in self._local_wikis():
            try:
                if self.config.auto_ingest.enabled:
                    service = AutoIngestService(
                        wiki=wiki,
                        wiki_id=wiki_id,
                        config=self.config.auto_ingest,
                        llm_semaphore=self.llm_semaphore,
                        loop=loop,
                        proposal_manager=self._make_proposal_manager(wiki_id),
                        rate_limiter=self.llm_rate_limiter,
                    )
                    if await service.start():
                        self.auto_ingest_services[wiki_id] = service
                if self.config.gap_filler.enabled:
                    self.gap_fillers[wiki_id] = GapFiller(
                        wiki=wiki,
                        wiki_id=wiki_id,
                        config=self.config.gap_filler,
                        llm_semaphore=self.llm_semaphore,
                        proposal_manager=self._make_proposal_manager(wiki_id),
                        rate_limiter=self.llm_rate_limiter,
                    )
            except Exception:
                logger.exception("maintenance: start failed for wiki %s", wiki_id)

        if self.gap_fillers:
            self._tasks.append(
                self._periodic_loop(
                    "maintenance_gaps",
                    self.config.gaps_interval_seconds,
                    self._gaps_tick,
                ),
            )
        self._tasks.append(
            self._periodic_loop(
                "maintenance_db",
                self.config.db_maintenance_interval_seconds,
                self._db_tick,
            ),
        )
        logger.info(
            "maintenance: started (%d auto_ingest watchers, %d gap fillers)",
            len(self.auto_ingest_services), len(self.gap_fillers),
        )

    async def stop(self) -> None:
        self._running = False
        for service in self.auto_ingest_services.values():
            try:
                await service.stop()
            except Exception:
                logger.warning("maintenance: watcher stop failed", exc_info=True)
        self.auto_ingest_services.clear()
        self.gap_fillers.clear()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ── periodic ticks ─────────────────────────────────────────────────

    def _periodic_loop(
        self,
        name: str,
        interval: float,
        tick: Any,
    ) -> asyncio.Task:
        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("maintenance: %s tick failed", name, exc_info=True)

        return asyncio.create_task(_loop(), name=name)

    async def _gaps_tick(self) -> None:
        for wiki_id, filler in list(self.gap_fillers.items()):
            try:
                result = await filler.run_cycle()
                self._health_history.append({
                    "timestamp": time.time(),
                    "type": "gaps",
                    "wiki_id": wiki_id,
                    **{
                        k: getattr(result, k)
                        for k in (
                            "detected", "processed", "mechanical_fixes",
                            "proposals_created", "errors",
                        )
                    },
                })
            except Exception:
                logger.warning("maintenance: gaps tick failed for %s", wiki_id, exc_info=True)
        self._trim_history()

    async def _db_tick(self) -> None:
        for wiki_id, wiki in self._local_wikis():
            try:
                await asyncio.to_thread(self._maintain_db, wiki.db_path)
            except Exception:
                logger.warning("maintenance: db tick failed for %s", wiki_id, exc_info=True)
        self._last_db_maintenance_at = time.time()

    @staticmethod
    def _maintain_db(db_path: Path) -> dict[str, Any]:
        """Checkpoint WAL + VACUUM. Skips quietly if the DB is busy."""
        if not Path(db_path).exists():
            return {"status": "skipped", "reason": "no db"}
        result: dict[str, Any] = {"status": "ok", "db": str(db_path)}
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout = 3000")
            wal = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            result["wal_checkpoint"] = list(wal) if wal else None
            before = conn.execute("PRAGMA page_count").fetchone()[0]
            conn.execute("VACUUM")
            after = conn.execute("PRAGMA page_count").fetchone()[0]
            result["pages_before"] = before
            result["pages_after"] = after
            result["pages_reclaimed"] = max(0, before - after)
        except sqlite3.OperationalError as exc:
            result["status"] = "skipped"
            result["reason"] = str(exc)
        finally:
            conn.close()
        return result

    # ── manual trigger (API) ───────────────────────────────────────────

    async def trigger(self, task: str) -> dict[str, Any]:
        """Manually trigger a maintenance task: gaps | db | all."""
        results: dict[str, Any] = {"task": task}
        if task in ("gaps", "all"):
            await self._gaps_tick()
            results["gaps"] = {
                wid: filler.status().get("last_cycle")
                for wid, filler in self.gap_fillers.items()
            }
        if task in ("db", "all"):
            db_results = {}
            for wiki_id, wiki in self._local_wikis():
                try:
                    db_results[wiki_id] = await asyncio.to_thread(
                        self._maintain_db, wiki.db_path,
                    )
                except Exception as exc:
                    db_results[wiki_id] = {"status": "error", "reason": str(exc)}
            self._last_db_maintenance_at = time.time()
            results["db"] = db_results
        if task not in ("gaps", "db", "all"):
            results["error"] = f"unknown task: {task!r} (expected gaps|db|all)"
        return results

    # ── reporting ──────────────────────────────────────────────────────

    def _local_wikis(self) -> list[tuple[str, Any]]:
        """(wiki_id, wiki) pairs for LOCAL wikis; REMOTE are skipped."""
        pairs: list[tuple[str, Any]] = []
        try:
            for instance in self.registry.list_wikis():
                if instance.wiki_type != WikiType.LOCAL:
                    continue
                try:
                    wiki = self.registry.get_wiki(instance.wiki_id)
                except Exception:
                    logger.warning(
                        "maintenance: failed to load wiki %s", instance.wiki_id,
                        exc_info=True,
                    )
                    continue
                if wiki is not None:
                    pairs.append((instance.wiki_id, wiki))
        except Exception:
            logger.exception("maintenance: registry listing failed")
        return pairs

    def _trim_history(self) -> None:
        if len(self._health_history) > HEALTH_HISTORY_LIMIT:
            self._health_history = self._health_history[-HEALTH_HISTORY_LIMIT:]

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "config": to_dict(self.config),
            "llm_rate_limit": self.llm_rate_limiter.stats(),
            "auto_ingest": {
                wid: svc.status() for wid, svc in self.auto_ingest_services.items()
            },
            "gap_filler": {
                wid: filler.status() for wid, filler in self.gap_fillers.items()
            },
            "last_db_maintenance_at": self._last_db_maintenance_at,
        }

    def health_report(self) -> dict[str, Any]:
        return {
            **self.status(),
            "health_history": list(self._health_history),
        }


__all__ = ["MaintenanceManager", "MaintenanceConfig", "load_maintenance_config"]
