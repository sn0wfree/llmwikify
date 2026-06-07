"""Agent Runner - Execution loop with context injection and tool orchestration.

Adapted from Nanobot Runner concepts, customized for Wiki workflows.
Supports confirmation flow for write operations.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


class ActionType(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    BULK = "bulk"
    EXTERNAL = "external"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    action_type: ActionType = ActionType.READ
    requires_confirmation: bool = False


@dataclass
class ActionResult:
    tool_name: str
    success: bool
    result: Any = None
    error: str | None = None
    confirmation_id: str | None = None
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ"))


@dataclass
class AgentMessage:
    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_result: ActionResult | None = None


@dataclass
class RunResult:
    state: RunState
    messages: list[AgentMessage] = field(default_factory=list)
    actions: list[ActionResult] = field(default_factory=list)
    confirmation_pending: ToolCall | None = None
    error: str | None = None


class WikiContextInjector:
    """Injects wiki context into LLM prompts."""

    def __init__(self, wiki: Any):
        self.wiki = wiki

    def build_system_prompt(self) -> str:
        parts = [
            "You are a wiki maintenance agent. Your job is to help maintain and improve a knowledge base.",
            "",
            "## Current Wiki State",
            f"- Pages: {self.wiki._get_page_count()}",
            f"- Index summary: {self.wiki._get_index_summary()}",
            f"- Recent log: {self.wiki._get_recent_log(3)}",
        ]

        wiki_md = self.wiki.root / "wiki.md"
        if wiki_md.exists():
            schema = wiki_md.read_text()[:2000]
            parts.extend(["", "## Wiki Schema (conventions)", schema])

        parts.extend([
            "",
            "## Rules",
            "- READ operations: execute automatically",
            "- WRITE operations (>100 chars): require user confirmation",
            "- DELETE operations: require user confirmation",
            "- BULK operations (>5 pages): require user confirmation",
            "- EXTERNAL API calls: require user confirmation",
            "- NEVER delete pages without explicit user command",
            "- NEVER modify wiki.md or config files without explicit command",
        ])

        return "\n".join(parts)

    def build_context_for_tool(self, tool_call: ToolCall) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if tool_call.action_type == ActionType.WRITE:
            context["existing_pages"] = self.wiki._get_existing_page_names()
        return context


class AgentRunner:
    """Core agent execution loop.

    Manages:
    - Context preparation with wiki state
    - Tool execution with audit logging
    - Confirmation flow for sensitive operations
    - State management
    """

    def __init__(self, wiki: Any, tool_registry: Any | None = None):
        self.wiki = wiki
        self.tool_registry = tool_registry
        self.context_injector = WikiContextInjector(wiki)
        self.state = RunState.IDLE
        self.history: list[AgentMessage] = []
        self.action_log: list[ActionResult] = []
        self._hooks: dict[str, list[Callable]] = {
            "pre_run": [],
            "post_run": [],
            "pre_tool": [],
            "post_tool": [],
            "on_confirmation": [],
            "on_error": [],
        }

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def _fire_hooks(self, event: str, **kwargs) -> None:
        for callback in self._hooks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                logger.warning(f"Hook {event} failed: {e}")

    def reset(self) -> None:
        self.state = RunState.IDLE
        self.history = []
        self.action_log = []

    def prepare_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        system_prompt = self.context_injector.build_system_prompt()
        return [{"role": "system", "content": system_prompt}] + messages

    async def execute_tool(self, tool_call: ToolCall) -> ActionResult:
        self._fire_hooks("pre_tool", tool_call=tool_call)

        try:
            if self.tool_registry:
                result = await self.tool_registry.execute(tool_call.name, tool_call.arguments)

                # Check if confirmation is required
                if isinstance(result, dict) and result.get("status") == "confirmation_required":
                    self.state = RunState.WAITING_CONFIRMATION
                    action_result = ActionResult(
                        tool_name=tool_call.name,
                        success=False,
                        result=result,
                        confirmation_id=result.get("confirmation_id"),
                    )
                    self._fire_hooks("on_confirmation", tool_call=tool_call, result=action_result)
                else:
                    action_result = ActionResult(
                        tool_name=tool_call.name,
                        success=True,
                        result=result,
                    )
            else:
                result = self._execute_local_tool(tool_call)
                action_result = ActionResult(
                    tool_name=tool_call.name,
                    success=True,
                    result=result,
                )
        except Exception as e:
            action_result = ActionResult(
                tool_name=tool_call.name,
                success=False,
                error=str(e),
            )
            self._fire_hooks("on_error", tool_call=tool_call, error=e)

        self.action_log.append(action_result)
        self._fire_hooks("post_tool", tool_call=tool_call, result=action_result)
        return action_result

    def _execute_local_tool(self, tool_call: ToolCall) -> Any:
        tool_map = {
            "wiki_read_page": lambda args: self.wiki.read_page(args.get("page_name", "")),
            "wiki_search": lambda args: self.wiki.search(args.get("query", ""), args.get("limit", 10)),
            "wiki_status": lambda args: self.wiki.status(),
            "wiki_write_page": lambda args: self.wiki.write_page(
                args.get("page_name", ""), args.get("content", "")
            ),
        }
        handler = tool_map.get(tool_call.name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_call.name}")
        return handler(tool_call.arguments)

    async def confirm_action(self, confirmation_id: str) -> ActionResult:
        """Confirm and execute a pending action by confirmation ID."""
        if self.state != RunState.WAITING_CONFIRMATION:
            logger.warning(f"Confirming action while not in WAITING_CONFIRMATION state (state={self.state})")

        self.state = RunState.EXECUTING

        if self.tool_registry:
            result = self.tool_registry.confirm_execution(confirmation_id)
            return ActionResult(
                tool_name=result.get("confirmation_id", "unknown"),
                success=result.get("status") == "executed",
                result=result.get("result"),
                error=result.get("error"),
            )
        else:
            return ActionResult(
                tool_name="unknown",
                success=False,
                error="No tool registry available for confirmation",
            )

    async def confirm_batch(self, confirmation_ids: list[str]) -> list[ActionResult]:
        """Confirm and execute multiple pending actions."""
        self.state = RunState.EXECUTING

        results = []
        if self.tool_registry:
            batch_results = self.tool_registry.confirm_batch(confirmation_ids)
            for r in batch_results:
                results.append(ActionResult(
                    tool_name=r.get("confirmation_id", "unknown"),
                    success=r.get("status") == "executed",
                    result=r.get("result"),
                    error=r.get("error"),
                ))
        return results

    def get_pending_confirmations(self) -> list[dict]:
        """Get all pending confirmations from tool registry."""
        if self.tool_registry:
            return self.tool_registry.get_pending_confirmations()
        return []

    def get_pending_by_group(self) -> dict[str, list[dict]]:
        """Get pending confirmations grouped by page type."""
        if self.tool_registry:
            return self.tool_registry.get_pending_by_group()
        return {}

    async def run(self, messages: list[dict[str, str]]) -> RunResult:
        self.state = RunState.RUNNING
        self._fire_hooks("pre_run", messages=messages)

        context_messages = self.prepare_context(messages)
        self.history.extend(
            AgentMessage(role=m["role"], content=m["content"]) for m in context_messages
        )

        try:
            result = RunResult(state=self.state, messages=self.history[:], actions=self.action_log[:])
            self._fire_hooks("post_run", result=result)
            return result
        except Exception as e:
            self.state = RunState.ERROR
            self._fire_hooks("on_error", error=e)
            return RunResult(state=RunState.ERROR, error=str(e))

    def stop(self) -> None:
        self.state = RunState.STOPPED

    def get_action_log(self) -> list[dict]:
        return [
            {
                "tool": a.tool_name,
                "success": a.success,
                "error": a.error,
                "confirmation_id": a.confirmation_id,
                "timestamp": a.timestamp,
            }
            for a in self.action_log
        ]
