"""AgentService — composition root (v0.33.0).

Per v0.33-service-refactor.md, this is the main entry point
that wires together the 5+1-service architecture:

  - AppDatabase (3-facade aggregate)
  - ChatService (SSE chat + DB + session)
  - WikiService (multi-wiki + wiki_dream/notify/scheduler/tool)
  - SkillService (skill registry + runtime)
  - HarnessService (6 eval primitives)
  - MemoryManager (6 memory stores)

This is the new non-deprecated AgentService. The old
wrapper was deleted in v0.34.0.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentService:
    """Composition root for the 5+1-service architecture.

    Wires together AppDatabase + ChatService + WikiService +
    SkillService + HarnessService + MemoryManager.

    Phase 7 (2026-06-19): Accepts ``provider`` (LLM client) and
    forwards it to ``MemoryManager`` so the Consolidator + Dream
    pipeline (Phase 6) can run without relying on lazy lookup.
    Also exposes ``start_dream_scheduler`` / ``stop_dream_scheduler``
    for lifespan integration with the FastAPI app.
    """

    def __init__(
        self,
        wiki_registry: Any,
        data_dir: Path,
        app_db: Any = None,
        skill_service: Any = None,
        harness_service: Any = None,
        memory_manager: Any = None,
        config: Any = None,
        provider: Any = None,
    ):
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator
        from llmwikify.apps.db import AppDatabase
        from llmwikify.apps.wiki.service import WikiService

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.provider = provider

        # AppDatabase (or use provided one)
        if app_db is not None:
            self.app_db = app_db
        else:
            self.app_db = AppDatabase(self.data_dir)

        # WikiService (multi-wiki registry)
        self.wiki_service = WikiService(
            wiki_registry, self.data_dir, self.app_db.chat,
        )

        # MemoryManager (6 memory stores + Phase 6 Consolidator/Dream).
        # If an explicit MemoryManager is supplied, use it as-is.
        # Otherwise create one. Phase 7 (2026-06-19): if a provider is
        # supplied AND no explicit MemoryManager is given, build the
        # default MemoryManager with provider wired so Consolidator +
        # Dream can operate (otherwise they stay None — lazy fallback).
        if memory_manager is not None:
            self.memory_manager = memory_manager
        else:
            from llmwikify.apps.chat.memory import MemoryManager
            self.memory_manager = MemoryManager(
                self.app_db,
                wiki=None,  # Wired on first skill invocation
                data_dir=self.data_dir,
                provider=provider,
            )

        # ChatOrchestrator (SSE chat) — share the same ChatDatabase
        # instance owned by AppDatabase to avoid duplicate
        # connections on the same SQLite file.
        self.chat_service = ChatOrchestrator(
            wiki_service=self.wiki_service,
            chat_db=self.app_db.chat,
            memory_manager=self.memory_manager,
        )

        # SkillService (lazy init)
        if skill_service is not None:
            self.skill_service = skill_service
        else:
            from llmwikify.apps.chat.skills.service import SkillService
            self.skill_service = SkillService()

        # HarnessService (lazy init for eval primitives)
        if harness_service is not None:
            self.harness_service = harness_service
        else:
            from llmwikify.apps.chat.harness.service import HarnessService
            self.harness_service = HarnessService(
                config=config,
                wiki=None,  # Wired on first skill invocation
            )

        # Wire MemoryManager + WikiService into SkillService for CRUD skills
        self.skill_service.memory_manager = self.memory_manager
        self.skill_service.wiki_service = self.wiki_service
        self.chat_service.skill_service = self.skill_service

        # Phase 7 (2026-06-19): DreamScheduler lifecycle hook.
        # Holds the scheduler instance once ``start_dream_scheduler`` is
        # called; ``stop_dream_scheduler`` shuts it down. None before
        # start (so unit tests that never touch the scheduler pay zero
        # cost). Kept as a single attribute so the FastAPI lifespan
        # handler can locate it deterministically.
        self.dream_scheduler: Any = None

        # Phase 9 (2026-06-20): AutoCompact lifecycle hook. Same shape
        # as dream_scheduler: holder + lazy task. ``None`` until
        # ``start_auto_compact`` is invoked.
        self.auto_compact: Any = None
        self._auto_compact_task: Any = None

    # ─── DB facade shortcut ─────────────────────────────────────

    @property
    def db(self) -> Any:
        """Shortcut to ChatDatabase (backward compat)."""
        return self.app_db.chat

    # ─── Chat (delegated to ChatService) ───────────────────────

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
        async for event in self.chat_service.chat(
            message, session_id, wiki_id, jwt_token,
        ):
            yield event

    def reload_llm(self) -> None:
        self.wiki_service.reload_llm()

    # ─── Phase 7 DreamScheduler lifecycle (2026-06-19) ─────────

    async def start_dream_scheduler(
        self,
        cron_expression: str | None = None,
        enabled: bool = True,
        config_path: Path | str | None = None,
    ) -> Any:
        """Start the Phase 6 DreamScheduler as a background task.

        Idempotent: re-calling is a no-op if a scheduler is already
        running. Returns the scheduler instance (or None if ``dream``
        is not configured because no LLM provider was supplied).

        Args:
            cron_expression: cron string (default from
                ``~/.llmwikify/memory_config.json`` or
                ``"0 3 * * *"``).
            enabled: ``False`` short-circuits and returns None.
            config_path: optional override for the config file path;
                defaults to ``<data_dir>/memory_config.json``.
        """
        if not enabled:
            logger.info("AgentService: dream_scheduler disabled, skipping start")
            return None

        # Need a Dream instance; MemoryManager must be built with a
        # provider for consolidator/dream to exist.
        if (
            self.memory_manager is None
            or getattr(self.memory_manager, "dream", None) is None
        ):
            logger.warning(
                "AgentService: dream_scheduler start skipped — "
                "MemoryManager has no dream (provider not provided?)",
            )
            return None

        if self.dream_scheduler is not None and self.dream_scheduler.is_running:
            logger.debug("AgentService: dream_scheduler already running")
            return self.dream_scheduler

        from llmwikify.apps.chat.memory.dream_scheduler import (
            CRON_DAILY_03,
            DreamScheduler,
        )
        from llmwikify.apps.chat.memory.memory_config import (
            DEFAULT_CONFIG_FILENAME,
            load_memory_config,
            write_default_memory_config,
        )

        # Load cron from memory_config.json if not supplied
        if cron_expression is None:
            cfg_dir = (
                Path(config_path).parent
                if config_path is not None
                else self.data_dir
            )
            cfg_path = cfg_dir / DEFAULT_CONFIG_FILENAME
            # First-run convenience: write defaults ONLY if file missing.
            if not cfg_path.exists():
                write_default_memory_config(cfg_dir)
            # Pass the directory, NOT the full path (load_memory_config
            # internally appends the filename).
            mem_cfg = load_memory_config(cfg_dir)
            cron_expression = (
                mem_cfg.dream.get("cron_expression") or CRON_DAILY_03
            )
            dream_enabled = mem_cfg.dream.get("enabled", True)
            if not dream_enabled:
                logger.info(
                    "AgentService: dream_scheduler disabled in "
                    "memory_config.json, skipping start",
                )
                return None

        sched = DreamScheduler(
            dream=self.memory_manager.dream,
            cron_expression=cron_expression,
            enabled=True,
        )
        await sched.start()
        self.dream_scheduler = sched
        logger.info(
            "AgentService: dream_scheduler started (cron=%r)",
            cron_expression,
        )
        return sched

    async def stop_dream_scheduler(self) -> None:
        """Stop the running DreamScheduler (Phase 7).

        Idempotent: safe to call even if no scheduler was started.
        """
        if self.dream_scheduler is None:
            return
        try:
            await self.dream_scheduler.stop()
        except Exception:
            logger.warning(
                "AgentService: dream_scheduler stop failed",
                exc_info=True,
            )
        finally:
            self.dream_scheduler = None

    # ─── Phase 9 AutoCompact lifecycle (2026-06-20) ────────────

    async def start_auto_compact(
        self,
        ttl_minutes: int = 30,
        interval_seconds: float = 300.0,
        enabled: bool = True,
    ) -> Any:
        """Start a periodic AutoCompact tick.

        Idempotent: re-calling returns the running instance. Returns
        ``None`` when AutoCompact cannot run (no provider → no
        Consolidator) or ``enabled=False``.

        Args:
            ttl_minutes: a session is considered idle when its
                ``updated_at`` is at least this many minutes in the
                past. ``0`` disables the TTL check (no-op).
            interval_seconds: how often to wake up and call
                :meth:`AutoCompact.check_expired`. The first tick fires
                ``interval_seconds`` after start.
            enabled: short-circuits to ``None`` so callers can flip it
                off via config without restructuring lifespan code.
        """
        if not enabled:
            logger.info("AgentService: auto_compact disabled, skipping start")
            return None

        if (
            self.memory_manager is None
            or getattr(self.memory_manager, "consolidator", None) is None
        ):
            logger.warning(
                "AgentService: auto_compact start skipped — "
                "MemoryManager has no consolidator (provider not provided?)",
            )
            return None

        if self.auto_compact is not None and self._auto_compact_task is not None:
            logger.debug("AgentService: auto_compact already running")
            return self.auto_compact

        from llmwikify.apps.chat.agent.autocompact import AutoCompact

        self.auto_compact = AutoCompact(
            chat_db=self.app_db.chat,
            memory_manager=self.memory_manager,
            ttl_minutes=ttl_minutes,
        )

        async def _periodic_tick() -> None:
            import asyncio
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
                    try:
                        active = self._active_session_keys()
                        await self.auto_compact.check_expired(
                            active_session_keys=active,
                        )
                    except Exception:
                        logger.warning(
                            "AgentService: auto_compact tick failed",
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                raise

        import asyncio
        self._auto_compact_task = asyncio.create_task(_periodic_tick())
        logger.info(
            "AgentService: auto_compact started (ttl=%dm, interval=%.0fs)",
            ttl_minutes, interval_seconds,
        )
        return self.auto_compact

    async def stop_auto_compact(self) -> None:
        """Stop the running AutoCompact periodic tick (Phase 9).

        Idempotent: safe to call even if AutoCompact was never started.
        """
        if self._auto_compact_task is None:
            self.auto_compact = None
            return
        self._auto_compact_task.cancel()
        try:
            await self._auto_compact_task
        except BaseException:  # noqa: BLE001 — CancelledError + bubbled errors
            pass
        finally:
            self._auto_compact_task = None
            self.auto_compact = None

    def _active_session_keys(self) -> list[str]:
        """Return ids of sessions currently marked as active.

        Uses ``ChatOrchestrator.get_all_session_status`` so AutoCompact
        skips chats with an in-flight LLM turn or a pending
        confirmation.
        """
        try:
            from llmwikify.apps.chat.agent.autocompact import (
                active_keys_from_status_map,
            )
            status_map = self.chat_service.get_all_session_status()
            return list(active_keys_from_status_map(status_map))
        except Exception:
            logger.warning(
                "AgentService: _active_session_keys failed",
                exc_info=True,
            )
            return []

    async def approve_confirmation_and_continue(
        self,
        confirmation_id: str,
        session_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> AsyncIterator[dict]:
        async for event in self.chat_service.approve_confirmation_continue(
            confirmation_id, session_id, wiki_id, arguments,
        ):
            yield event

    # ─── WikiService delegation (wiki_dream/notify/scheduler/etc.) ─

    async def run_wiki_dream(self, wiki_id: str | None = None) -> dict:
        return await self.wiki_service.run_wiki_dream(wiki_id)

    def get_wiki_dream_log(
        self, wiki_id: str | None = None, limit: int = 20,
    ) -> list[dict]:
        return self.wiki_service.get_wiki_dream_log(wiki_id, limit)

    def get_wiki_dream_proposals(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_wiki_dream_proposals(wiki_id)

    def approve_wiki_dream_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.approve_wiki_dream_proposal(proposal_id)

    def reject_wiki_dream_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.reject_wiki_dream_proposal(proposal_id)

    def batch_approve_wiki_dream_proposals(self, proposal_ids: list[str]) -> dict:
        return self.wiki_service.batch_approve_wiki_dream_proposals(proposal_ids)

    async def apply_wiki_dream_proposals(
        self, wiki_id: str | None = None,
        proposal_ids: list[str] | None = None,
    ) -> dict:
        return await self.wiki_service.apply_wiki_dream_proposals(wiki_id, proposal_ids)

    def list_notifications(
        self, wiki_id: str | None = None, unread_only: bool = False,
    ) -> list[dict]:
        return self.wiki_service.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> dict:
        return self.wiki_service.mark_notification_read(notification_id)

    def list_confirmations(self, wiki_id: str | None = None) -> dict:
        grouped = self.wiki_service.list_confirmations(wiki_id)
        seen = {
            item.get("id")
            for items in grouped.values()
            for item in items
            if isinstance(item, dict)
        }
        chat_grouped = self.chat_service.list_confirmations(wiki_id)
        for group, items in chat_grouped.items():
            bucket = grouped.setdefault(group, [])
            for item in items:
                item_id = item.get("id") if isinstance(item, dict) else None
                if item_id and item_id in seen:
                    continue
                if item_id:
                    seen.add(item_id)
                bucket.append(item)
        return grouped

    @staticmethod
    def _is_unknown_confirmation(result: Any) -> bool:
        if not isinstance(result, dict) or result.get("status") != "error":
            return False
        error = result.get("error", "")
        return "Unknown confirmation ID" in error or "Invalid confirmation ID" in error

    async def approve_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
        arguments: dict | None = None,
        response: str = "once",
    ) -> dict:
        result = await self.chat_service.approve_confirmation(
            confirmation_id, wiki_id, arguments,
        )
        if not self._is_unknown_confirmation(result):
            return result
        return await self.wiki_service.approve_confirmation(
            confirmation_id, wiki_id, arguments, response=response,
        )

    async def reject_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
    ) -> dict:
        result = await self.chat_service.reject_confirmation(confirmation_id, wiki_id)
        if not self._is_unknown_confirmation(result):
            return result
        return await self.wiki_service.reject_confirmation(
            confirmation_id, wiki_id,
        )

    async def batch_approve_confirmations(
        self, confirmation_ids: list[str], wiki_id: str | None = None,
    ) -> dict:
        results = [
            await self.approve_confirmation(cid, wiki_id)
            for cid in confirmation_ids
        ]
        return {"approved": len(results), "results": results}

    def get_ingest_log(
        self, wiki_id: str | None = None, limit: int = 20,
    ) -> list[dict]:
        return self.wiki_service.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self.wiki_service.get_ingest_entry(ingest_id)

    def get_agent_status(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_agent_status(wiki_id)

    def get_research_run_status(self, run_id: str) -> dict:
        from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
            _artifact_counts_from_outputs,
            _format_run_not_found,
            _timeline_from_state,
        )
        from llmwikify.apps.chat.skills.workflows.run_store import RunStore

        state = RunStore.default().load(run_id)
        if state is None:
            return {
                "status": "error",
                "error": _format_run_not_found(run_id, workflow_name="autoresearch-compound"),
            }
        synthesize = state.phases.get("synthesize", {}) if state.phases else {}
        final_report = synthesize.get("output") if isinstance(synthesize, dict) else None
        outputs = {"final_report": final_report} if final_report else {}
        return {
            "run_id": state.run_id,
            "workflow_name": state.workflow_name,
            "status": state.status,
            "timeline": _timeline_from_state(state),
            "artifact_counts": _artifact_counts_from_outputs(outputs),
            "proposal_bundle": final_report,
            "writes_wiki": False,
            "proposal_only": True,
            "started_at": state.started_at,
            "last_updated": state.last_updated,
            "total_tokens_used": state.total_tokens_used,
            "total_agents_spawned": state.total_agents_spawned,
        }

    def delete_session(self, session_id: str) -> bool:
        return self.chat_service.delete_session(session_id)

    def revert_session(self, session_id: str, message_id: str) -> int:
        return self.chat_service.revert_session(session_id, message_id)

    def edit_message(self, message_id: str, new_content: str) -> bool:
        return self.chat_service.edit_message(message_id, new_content)

    def abort_session(self, session_id: str) -> bool:
        return self.chat_service.abort_session(session_id)

    def get_session_status(self, session_id: str) -> str:
        return self.chat_service.get_session_status(session_id)

    def get_all_session_status(self) -> dict[str, str]:
        return self.chat_service.get_all_session_status()

    # ─── Internal access (for backward compat) ─────────────────

    def _get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.wiki_service.get_tool_registry(wiki_id)

    def _get_llm(self) -> Any:
        return self.wiki_service.get_llm()


__all__ = ["AgentService"]
