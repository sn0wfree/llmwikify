"""ChatRunner v2 — unified chat agent loop (Plan B Step B-1).

Skeleton only. The 5-step state machine and full implementation land
in B-2 (core loop + hooks + microcompact). This file establishes the
public API shape and the ``_RunContext`` so downstream callers (and
tests) can be written against a stable surface.

Public surface (locked in B-1):

  ChatRunnerV2(chat_service, tool_executor, prompt_builder, config, hook)
      .run_stream(spec)        -> AsyncIterator[dict]
      .run_to_completion(spec) -> ChatRunResult

Replaces (after B-5):
  - ChatReActBridge (711 LOC, chat_react.py)
  - ReActEngine    (687 LOC, react_engine.py)
  - ChatReActState (in chat_react.py)

See ``docs/poc/plan-b-refactor.md`` for the full design.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.foundation.callback import AgentHook, NoOpHook

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _RunContext:
    spec: ChatRunSpec
    messages: list[dict[str, Any]]
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    final_content: str | None = None
    stop_reason: str = "in_progress"
    error: str | None = None
    compacted_count: int = 0
    chars_saved: int = 0
    cancelled: bool = False
    paused: bool = False
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


class ChatRunnerV2:
    """Unified chat agent loop.

    B-1 only ships the skeleton (constructor, 5 step stubs, public
    API). B-2 fills in the 5 steps with real logic + CompositeHook
    integration + microcompact.
    """

    def __init__(
        self,
        chat_service: Any,
        tool_executor: Any,
        prompt_builder: Any,
        config: dict | None = None,
        hook: AgentHook | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder
        self._config = config or {}
        self._hook = hook or NoOpHook()

    async def run_stream(
        self, spec: ChatRunSpec,
    ) -> Any:
        """Yield SSE-compatible events for one chat turn.

        B-1 stub: yields a single ``done`` event. B-2 replaces this
        body with the 5-step loop.
        """
        ctx = _RunContext(spec=spec, messages=list(spec.messages))
        await asyncio.sleep(0)
        yield {"type": "done", "content": "", "_v2": True, "_ctx": ctx.stop_reason}
        return

    async def run_to_completion(self, spec: ChatRunSpec) -> ChatRunResult:
        """Drain ``run_stream`` and aggregate into a ``ChatRunResult``."""
        final_content: str | None = None
        tools_used: list[str] = []
        usage: dict[str, int] = {}
        stop_reason = "completed"
        error: str | None = None
        compacted_count = 0
        chars_saved = 0
        try:
            async for event in self.run_stream(spec):
                kind = event.get("type")
                if kind == "done":
                    final_content = event.get("content", final_content)
                elif kind == "error":
                    error = event.get("message") or event.get("error")
                    stop_reason = "error"
                elif kind == "tool_call_end":
                    tool = event.get("tool")
                    if tool and tool not in tools_used:
                        tools_used.append(tool)
                elif kind == "message_delta" and event.get("content"):
                    final_content = (final_content or "") + event["content"]
                elif kind == "compacted":
                    compacted_count += 1
                    chars_saved += int(event.get("chars_saved", 0))
                elif kind == "confirmation_required":
                    stop_reason = "confirmation_required"
        except Exception as exc:
            logger.exception("ChatRunnerV2.run_to_completion failed")
            error = f"{type(exc).__name__}: {exc}"
            stop_reason = "error"

        return ChatRunResult(
            final_content=final_content,
            messages=list(spec.messages),
            tools_used=tools_used,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
            compacted_count=compacted_count,
            total_compacted_chars_saved=chars_saved,
        )
