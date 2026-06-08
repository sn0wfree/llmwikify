"""AgentBackend Service — DEPRECATED wrapper.

.. deprecated::
    Use ``ChatService`` + ``WikiService`` instead.
    This module is scheduled for removal in v0.33.0.

All methods delegate to ChatService or WikiService.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


class AgentService:
    """DEPRECATED: Use ChatService + WikiService instead.

    This wrapper delegates all methods to ChatService and
    WikiService. Will be removed in v0.33.0.
    """

    def __init__(self, wiki_registry: Any, data_dir: Path):
        warnings.warn(
            "AgentService is deprecated. Use ChatService + WikiService instead. "
            "This wrapper will be removed in v0.33.0.",
            DeprecationWarning,
            stacklevel=2,
        )

        from llmwikify.apps.chat.db import ChatDatabase
        from llmwikify.apps.chat.agent.service import ChatService
        from llmwikify.apps.wiki.service import WikiService

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = ChatDatabase(self.data_dir)
        self.wiki_service = WikiService(wiki_registry, self.data_dir, self.db)
        self.chat_service = ChatService(self.wiki_service, self.data_dir)

    # ─── Delegated: Chat ─────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
        async for event in self.chat_service.chat(
            message, session_id, wiki_id, jwt_token
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
            confirmation_id, session_id, wiki_id, arguments
        ):
            yield event

    # ─── Delegated: WikiService methods ──────────────────────────

    async def run_dream(self, wiki_id: str | None = None) -> dict:
        return await self.wiki_service.run_dream(wiki_id)

    def get_dream_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
        return self.wiki_service.get_dream_log(wiki_id, limit)

    def get_dream_proposals(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_dream_proposals(wiki_id)

    def approve_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.approve_proposal(proposal_id)

    def reject_proposal(self, proposal_id: str) -> dict:
        return self.wiki_service.reject_proposal(proposal_id)

    def batch_approve_proposals(self, proposal_ids: list[str]) -> dict:
        return self.wiki_service.batch_approve_proposals(proposal_ids)

    async def apply_proposals(self, wiki_id: str | None = None, proposal_ids: list[str] | None = None) -> dict:
        return await self.wiki_service.apply_proposals(wiki_id, proposal_ids)

    def list_notifications(self, wiki_id: str | None = None, unread_only: bool = False) -> list[dict]:
        return self.wiki_service.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> dict:
        return self.wiki_service.mark_notification_read(notification_id)

    def list_confirmations(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.list_confirmations(wiki_id)

    async def approve_confirmation(self, confirmation_id: str, wiki_id: str | None = None, arguments: dict | None = None) -> dict:
        return await self.wiki_service.approve_confirmation(confirmation_id, wiki_id, arguments)

    async def reject_confirmation(self, confirmation_id: str, wiki_id: str | None = None) -> dict:
        return await self.wiki_service.reject_confirmation(confirmation_id, wiki_id)

    async def batch_approve_confirmations(self, confirmation_ids: list[str], wiki_id: str | None = None) -> dict:
        return await self.wiki_service.batch_approve_confirmations(confirmation_ids, wiki_id)

    def get_ingest_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
        return self.wiki_service.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self.wiki_service.get_ingest_entry(ingest_id)

    def get_agent_status(self, wiki_id: str | None = None) -> dict:
        return self.wiki_service.get_agent_status(wiki_id)

    # ─── Internal access (for backward compat) ───────────────────

    def _get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.wiki_service.get_tool_registry(wiki_id)

    def _get_llm(self) -> Any:
        return self.wiki_service.get_llm()
