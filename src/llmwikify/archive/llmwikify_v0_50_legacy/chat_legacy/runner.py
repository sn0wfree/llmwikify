"""ChatRunner — facade over ChatReActBridge + ReActEngine.

A thin wrapper that turns a :class:`ChatRunSpec` into a finished
:class:`ChatRunResult` (or, for streaming callers, yields the same
event vocabulary the existing chat SSE pipeline already consumes).

Why a facade instead of replacing the ReAct loop:

* The existing ReActEngine + ChatReActBridge already model the loop
  well (805+918 LOC of tests cover it). Replacing it is a separate,
  larger refactor (Phase B). The facade is the minimal step that
  delivers the microcompact default-on behaviour now.
* Callers that want streaming keep using ``ChatOrchestrator.chat``
  unchanged. Callers that want a synchronous "give me the final
  result" view call :meth:`ChatRunner.run_to_completion`.

Microcompact is wired by the runner into the bridge via
:meth:`microcompact.build_microcompact_fn`; the bridge stores the
original result in ``spec._compacted_results`` so callers can audit
what was compacted after the run.
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.agent.microcompact import build_microcompact_fn
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec

logger = logging.getLogger(__name__)


class ChatRunner:
    def __init__(self, chat_service: Any) -> None:
        self._chat_service = chat_service

    def build_bridge(self, spec: ChatRunSpec) -> Any:
        from llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.chat_react import (
            ChatReActBridge,
        )

        counter: dict[str, int] = {}
        microcompact_fn = build_microcompact_fn(spec, counter=counter)
        self._last_counter = counter
        bridge = ChatReActBridge(
            chat_service=self._chat_service,
            microcompact_fn=microcompact_fn,
        )
        return bridge

    async def run(
        self, spec: ChatRunSpec,
    ) -> Any:
        """Run the ReAct loop, yielding the same event dicts the SSE
        pipeline already consumes.
        """
        from llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.react_engine import (
            ReActEngine,
        )

        bridge = self.build_bridge(spec)
        config = bridge.build_config(
            session_id=spec.session_id,
            wiki_id=spec.wiki_id,
            tool_registry=spec.tool_registry,
            user_message=_last_user_content(spec.messages),
            system_prompt="",
            messages=spec.messages,
            ctx=_DummyCtx(),
            max_iterations=spec.max_iterations,
        )
        engine = ReActEngine(config)
        async for event in engine.run():
            yield event

    async def run_to_completion(self, spec: ChatRunSpec) -> ChatRunResult:
        """Drain the iterator and return the final result."""
        final_content: str | None = None
        messages = list(spec.messages)
        tools_used: list[str] = []
        usage: dict[str, int] = {}
        stop_reason = "completed"
        error: str | None = None

        try:
            async for event in self.run(spec):
                kind = event.get("type")
                if kind == "done":
                    final_content = event.get("content", final_content)
                elif kind == "error":
                    error = event.get("message") or event.get("error")
                    stop_reason = "error"
                elif kind == "action_result":
                    for r in event.get("results", []) or []:
                        tool = r.get("tool")
                        if tool and tool not in tools_used:
                            tools_used.append(tool)
                elif kind == "message_delta" and event.get("content"):
                    final_content = (final_content or "") + event["content"]
                elif kind == "confirmation_required":
                    stop_reason = "confirmation_required"
        except Exception as exc:
            logger.exception("ChatRunner.run_to_completion failed")
            error = f"{type(exc).__name__}: {exc}"
            stop_reason = "error"

        counter = getattr(self, "_last_counter", {})
        return ChatRunResult(
            final_content=final_content,
            messages=messages,
            tools_used=tools_used,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
            compacted_count=counter.get("count", 0),
            total_compacted_chars_saved=counter.get("chars_saved", 0),
        )


class _DummyCtx:
    def add_observation(self, _obs: str) -> None:
        pass

    def add_thought(self, _thought: str) -> None:
        pass

    def add_assistant_message(self, _msg: str) -> None:
        pass

    def add_user_message(self, _msg: str) -> None:
        pass


def _last_user_content(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""
