"""ConfirmationManager — extracted from ChatOrchestrator (Phase 5).

Owns the lifecycle of pending tool-execution confirmations:

  - ``list_confirmations`` — enumerate pending by tool group
  - ``approve_confirmation`` — confirm and execute
  - ``reject_confirmation`` — decline and free the slot
  - ``batch_approve_confirmations`` — bulk approve
  - ``is_unknown_confirmation`` — helper to detect stale IDs

The manager holds no mutable state of its own; it reads
``tool_registries`` (a dict keyed by ``(session_id, wiki_id)``)
provided by the orchestrator at construction time. This keeps the
manager stateless and easy to test in isolation.

Public API mirrors the previous ChatOrchestrator methods 1:1 so
external callers (e.g. ``AgentService`` and ``chat_sse.py``) do not
need to change. ChatOrchestrator delegates to the manager.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConfirmationManager:
    """Approval / rejection flow for tool-execution confirmations."""

    def __init__(self, tool_registries: dict[tuple[str, str], Any]) -> None:
        self._tool_registries = tool_registries

    @staticmethod
    def is_unknown_confirmation(result: Any) -> bool:
        """Return True when ``result`` is a stale/unknown confirmation error."""
        if not isinstance(result, dict) or result.get("status") != "error":
            return False
        error = result.get("error", "")
        return "Unknown confirmation ID" in error or "Invalid confirmation ID" in error

    def list_confirmations(self, wiki_id: str | None = None) -> dict[str, list[dict]]:
        """Group all pending confirmations by tool group, optionally filtered by wiki."""
        grouped: dict[str, list[dict]] = {}
        for (_, cached_wiki_id), registry in self._tool_registries.items():
            if wiki_id and cached_wiki_id != wiki_id:
                continue
            for group, items in registry.get_pending_by_group().items():
                grouped.setdefault(group, []).extend(items)
        return grouped

    async def approve_confirmation(
        self,
        confirmation_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        """Approve a confirmation. Returns the tool execution result dict."""
        for (_, cached_wiki_id), registry in self._tool_registries.items():
            if wiki_id and cached_wiki_id != wiki_id:
                continue
            result = registry.confirm_execution(confirmation_id, arguments)
            if not self.is_unknown_confirmation(result):
                return result
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    async def reject_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
    ) -> dict:
        """Reject a pending confirmation."""
        for (_, cached_wiki_id), registry in self._tool_registries.items():
            if wiki_id and cached_wiki_id != wiki_id:
                continue
            result = registry.reject_execution(confirmation_id)
            if not self.is_unknown_confirmation(result):
                return result
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    async def batch_approve_confirmations(
        self, confirmation_ids: list[str], wiki_id: str | None = None,
    ) -> dict:
        """Approve a list of confirmations sequentially and aggregate results."""
        results = [
            await self.approve_confirmation(cid, wiki_id) for cid in confirmation_ids
        ]
        return {"approved": len(results), "results": results}
