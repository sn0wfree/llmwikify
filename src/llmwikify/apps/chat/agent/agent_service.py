"""AgentService — composition root (v0.33.0).

Per v0.33-service-refactor.md, this is the main entry point
that wires together the 5+1-service architecture:

  - AppDatabase (3-facade aggregate)
  - ChatService (SSE chat + DB + session)
  - WikiService (multi-wiki + dream/notify/scheduler/tool)
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
    ):
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator
        from llmwikify.apps.db import AppDatabase
        from llmwikify.apps.wiki.service import WikiService

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = config

        # AppDatabase (or use provided one)
        if app_db is not None:
            self.app_db = app_db
        else:
            self.app_db = AppDatabase(self.data_dir)

        # WikiService (multi-wiki registry)
        self.wiki_service = WikiService(
            wiki_registry, self.data_dir, self.app_db.chat,
        )

        # MemoryManager (6 memory stores) — must be created
        # BEFORE ChatOrchestrator so the chat layer can be wired
        # with it.
        if memory_manager is not None:
            self.memory_manager = memory_manager
        else:
            from llmwikify.apps.chat.memory import MemoryManager
            self.memory_manager = MemoryManager(
                self.app_db,
                wiki=None,  # Wired on first skill invocation
                data_dir=self.data_dir,
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

    # ─── WikiService delegation (dream/notify/scheduler/etc.) ─

    async def run_dream(self, wiki_id: str | None = None) -> dict:
        return await self.wiki_service.run_dream(wiki_id)

    def get_dream_log(
        self, wiki_id: str | None = None, limit: int = 20,
    ) -> list[dict]:
        return self.wiki_service.get_dream_log(wiki_id, limit)

    def get_dream_proposals(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_dream_proposals(wiki_id)

    def approve_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.approve_proposal(proposal_id)

    def reject_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.reject_proposal(proposal_id)

    def batch_approve_proposals(self, proposal_ids: list[str]) -> dict:
        return self.wiki_service.batch_approve_proposals(proposal_ids)

    async def apply_proposals(
        self, wiki_id: str | None = None,
        proposal_ids: list[str] | None = None,
    ) -> dict:
        return await self.wiki_service.apply_proposals(wiki_id, proposal_ids)

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
            _timeline_from_state,
        )
        from llmwikify.apps.chat.skills.workflows.run_store import RunStore

        state = RunStore.default().load(run_id)
        if state is None:
            return {"status": "error", "error": f"no run with id {run_id!r}"}
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
