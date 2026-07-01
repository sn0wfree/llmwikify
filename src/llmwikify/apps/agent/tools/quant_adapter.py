"""Adapter that exposes QuantNodes agent tools to the Chat Agent.

Wraps OperatorLookupTool (and future QuantNodes tools) into the
registry interface expected by CompositeToolRegistry.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class QuantToolAdapter:
    """Registry adapter for QuantNodes agent tools.

    Currently exposes:
    - operator_lookup: discover 162 operators, get metadata, validate formulas

    All tools are read-only — no confirmation flow needed.
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Any] = {}
        self._init_tools()

    def _init_tools(self) -> None:
        try:
            from QuantNodes.agent.tools.operator_lookup import OperatorLookupTool

            tool = OperatorLookupTool()
            self._handlers[tool.name] = tool
            self._tools[tool.name] = {
                "description": tool.description,
                "action_type": "read",
                "requires_confirmation": False,
                "parameters": tool.parameters,
            }
        except ImportError:
            logger.warning("QuantNodes not available, QuantToolAdapter disabled")

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": info["description"],
                "action_type": info["action_type"],
                "requires_confirmation": info["requires_confirmation"],
                "parameters": info["parameters"],
            }
            for name, info in self._tools.items()
        ]

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self._tools.get(name)

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            available = ", ".join(sorted(self._handlers.keys()))
            raise ValueError(
                f"Unknown quant tool: {name!r}. Available: [{available}]"
            )
        return await handler.execute(**arguments)

    def confirm_execution(self, confirmation_id: str, arguments: dict | None = None) -> Any:
        return {"status": "error", "error": "Unknown confirmation ID"}

    def reject_execution(self, confirmation_id: str) -> dict[str, Any]:
        return {"status": "error", "error": "Unknown confirmation ID"}

    def confirm_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [{"status": "error", "error": "Unknown confirmation ID"} for _ in confirmation_ids]

    def reject_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [{"status": "error", "error": "Unknown confirmation ID"} for _ in confirmation_ids]

    def get_pending_confirmations(self) -> list[dict[str, Any]]:
        return []

    def get_pending_by_group(self) -> dict[str, list[dict[str, Any]]]:
        return {}
