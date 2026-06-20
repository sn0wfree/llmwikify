"""subagent_manager — Phase 10-E in-process Subagent (2026-06-20).

Borrowed from nanobot v0.2.1 ``agent/subagent.py`` (392 LOC). Lets the
main LLM spawn an isolated child :class:`ChatRunnerV2` via a tool call
to investigate a sub-goal in detail without polluting the main
conversation history.

Coexists with the existing subprocess subagent runner
(``apps/chat/skills/workflows/subagent_runner.py``):

  - **subprocess** path — workflow DAG executor (YAML-triggered,
    heavy isolation, ~1s startup, JSON wire format)
  - **in-process** path (this module) — LLM tool-call dynamic
    branching (~50ms startup, in-memory dicts)

Both paths are useful; this module does NOT replace the subprocess
runner.

Anti-runaway guardrails
-----------------------

1. ``asyncio.Semaphore(max_concurrent)`` caps the number of active
   children. Default = 2.
2. The child :class:`ChatRunSpec` does **not** include
   ``spawn_subagent`` in its ``tool_registry`` — children cannot
   spawn grandchildren (no infinite nesting). The caller is
   responsible for stripping this tool when it's wiring children.
3. ``timeout_seconds`` wraps ``run_to_completion`` in
   :func:`asyncio.wait_for`; on timeout the manager returns
   ``status="timeout"`` rather than raising.
4. The child does **not** receive the parent's ``MemoryManager``
   (no recursive consolidation).
5. The child uses :class:`NoOpHook` so SSE events do not bubble up
   into the parent's event stream.

This module deliberately exposes a small surface (one dataclass
spec, one dataclass result, one async ``run`` method). Higher-level
SkillAction wrappers live in
``apps/chat/skills/crud/subagent_skill.py``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
from llmwikify.apps.chat.agent.spec import ChatRunSpec
from llmwikify.foundation.callback import NoOpHook

logger = logging.getLogger(__name__)


@dataclass
class SubagentSpec:
    """What the parent asks a subagent to investigate.

    The minimal contract: a ``goal`` (one-line objective written into
    the child system prompt) plus ``initial_messages`` (typically a
    single ``user`` message that tells the child what to do). The
    parent supplies a ``tool_registry`` — usually a subset of its own
    tools, **without** ``spawn_subagent`` to prevent infinite
    nesting.
    """

    goal: str
    initial_messages: list[dict[str, Any]]
    tool_registry: Any
    parent_session_id: str
    max_iterations: int = 5
    inherit_wiki_id: str | None = None
    timeout_seconds: float = 120.0


@dataclass
class SubagentResult:
    """What the subagent returns to the parent."""

    status: str  # "ok" | "error" | "timeout"
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    state_trace: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "completed"


class SubagentManager:
    """In-process subagent dispatcher.

    Owns a semaphore (caps concurrent children) and reuses the
    parent runner's collaborators (``chat_service``,
    ``prompt_builder``, ``tool_executor``, ``config``) so children
    inherit LLM connectivity without re-wiring providers.
    """

    def __init__(
        self,
        parent_runner: ChatRunnerV2,
        max_concurrent: int = 2,
    ) -> None:
        self._parent = parent_runner
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    async def run(self, spec: SubagentSpec) -> SubagentResult:
        """Run a single subagent to completion.

        Returns a populated :class:`SubagentResult`. Never raises:
        timeouts and runner errors are reported via ``status``.
        """
        async with self._semaphore:
            child_spec = self._build_child_spec(spec)
            child_runner = ChatRunnerV2(
                chat_service=self._parent._chat_service,
                tool_executor=self._parent._tool_executor,
                prompt_builder=self._parent._prompt_builder,
                config=self._parent._config,
                hook=NoOpHook(),
                memory_manager=None,
            )
            try:
                result = await asyncio.wait_for(
                    child_runner.run_to_completion(child_spec),
                    timeout=spec.timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Subagent timed out after %.1fs (goal=%r)",
                    spec.timeout_seconds,
                    spec.goal[:80],
                )
                return SubagentResult(
                    status="timeout",
                    error=(
                        f"subagent exceeded timeout_seconds="
                        f"{spec.timeout_seconds}"
                    ),
                    stop_reason="timeout",
                )
            except Exception as exc:
                logger.exception("Subagent crashed (goal=%r)", spec.goal[:80])
                return SubagentResult(
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    stop_reason="error",
                )

            status = "ok" if result.error is None else "error"
            return SubagentResult(
                status=status,
                final_content=result.final_content,
                tools_used=list(result.tools_used or []),
                usage=dict(result.usage or {}),
                error=result.error,
                state_trace=list(result.state_trace or []),
                stop_reason=result.stop_reason,
            )

    def _build_child_spec(self, spec: SubagentSpec) -> ChatRunSpec:
        """Translate a SubagentSpec into a ChatRunSpec.

        Injects a one-line system message with the goal so the child
        always sees its objective, regardless of what the parent
        prompt builder might or might not include.
        """
        system_line = (
            f"You are an isolated subagent. Your single objective:\n\n"
            f"  {spec.goal.strip()}\n\n"
            "Stay strictly within this objective. Do not start new "
            "tangents. When you have a final answer, return it and "
            "stop."
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_line},
            *spec.initial_messages,
        ]
        return ChatRunSpec(
            messages=messages,
            tool_registry=spec.tool_registry,
            session_id=f"subagent::{spec.parent_session_id}",
            wiki_id=spec.inherit_wiki_id,
            max_iterations=spec.max_iterations,
            microcompact=True,
            # Children are not subject to the parent's goal_state.
            goal_active_predicate=None,
        )


__all__ = [
    "SubagentManager",
    "SubagentResult",
    "SubagentSpec",
]
