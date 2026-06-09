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
wrapper at ``apps/agent/core/service.py`` is kept for
backward compat and will be removed in v0.34.0.
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
        from llmwikify.apps.db import AppDatabase
        from llmwikify.apps.chat.agent.service import ChatService
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

        # ChatService (SSE chat)
        self.chat_service = ChatService(self.wiki_service, self.data_dir)

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

        # MemoryManager (6 memory stores)
        if memory_manager is not None:
            self.memory_manager = memory_manager
        else:
            from llmwikify.apps.chat.memory import MemoryManager
            self.memory_manager = MemoryManager(
                self.app_db,
                wiki=None,  # Wired on first skill invocation
                data_dir=self.data_dir,
            )

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
        return self.wiki_service.list_confirmations(wiki_id)

    async def approve_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        return await self.wiki_service.approve_confirmation(
            confirmation_id, wiki_id, arguments,
        )

    async def reject_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
    ) -> dict:
        return await self.wiki_service.reject_confirmation(
            confirmation_id, wiki_id,
        )

    async def batch_approve_confirmations(
        self, confirmation_ids: list[str], wiki_id: str | None = None,
    ) -> dict:
        return await self.wiki_service.batch_approve_confirmations(
            confirmation_ids, wiki_id,
        )

    def get_ingest_log(
        self, wiki_id: str | None = None, limit: int = 20,
    ) -> list[dict]:
        return self.wiki_service.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self.wiki_service.get_ingest_entry(ingest_id)

    def get_agent_status(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_agent_status(wiki_id)

    # ─── Internal access (for backward compat) ─────────────────

    def _get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.wiki_service.get_tool_registry(wiki_id)

    def _get_llm(self) -> Any:
        return self.wiki_service.get_llm()


__all__ = ["AgentService"]
