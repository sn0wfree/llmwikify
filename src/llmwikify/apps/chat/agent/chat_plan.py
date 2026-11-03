"""ChatPlan — the chat ReAct loop as a plan on the shared runtime.

The chat loop used to carry its own driver: a ``for`` loop with its
own iteration counter, its own stop conditions and its own per-step
timing. It now runs on :class:`llmwikify.kernel.agent.runtime.AgentRuntime`
with this plan.

The plan is an **adapter**, not a rewrite: every stage calls the
runner's existing step method, so the event order, the hook calls and
the error semantics are the ones the runner had before. Only the
driver is shared now — with the research pipeline
(:mod:`llmwikify.apps.chat.agent.research_runner`) and, later, the
subagent loop.

Stage mapping
-------------

=============  ==========================================================
runtime stage  runner method
=============  ==========================================================
before_iteration  ``hook.before_iteration``
precheck       ``_precheck`` (timeout / goal predicate / cancelled)
reason         ``_reason`` (the LLM stream + tool-call parsing)
decide         the tool-call bookkeeping and the stop conditions
act            ``_act`` (tool execution + microcompact)
observe        ``_observe`` (the truncated thinking note)
after_iteration ``hook.after_iteration`` + the memory consolidation
finalize       ``_emit_done``
=============  ==========================================================
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from llmwikify.foundation.utils import maybe_await as _maybe_await
from llmwikify.kernel.agent.runtime import (
    PHASE_AFTER_ACT,
    PHASE_AFTER_REASON,
    AgentPlan,
)

from .state_trace import StateTrace

if TYPE_CHECKING:  # pragma: no cover
    from .runner_v2 import ChatRunnerV2, _RunContext
    from .spec import ChatRunSpec

logger = logging.getLogger(__name__)


class ChatPlan(AgentPlan):
    """The chat agent loop as a plan on the shared runtime."""

    def __init__(
        self,
        runner: ChatRunnerV2,
        spec: ChatRunSpec,
        ctx: _RunContext,
        system_prompt: str,
    ) -> None:
        self._runner = runner
        self._spec = spec
        self._ctx = ctx
        self._system_prompt = system_prompt
        self.max_iterations = spec.max_iterations

    # ── before_iteration ───────────────────────────────────────────

    async def before_iteration(self, rctx: Any) -> None:
        await _maybe_await(
            self._runner._hook.before_iteration(self._ctx.hook_ctx(rctx.iteration))
        )

    # ── PRECHECK ────────────────────────────────────────────────────

    async def precheck(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Timeout / goal predicate / cancelled / paused."""
        with StateTrace(self._ctx, "PRECHECK") as tr:
            should_break = await self._runner._precheck(self._ctx)
        if should_break:
            tr.event = "skipped"
            rctx.stop = True
            rctx.stop_reason = self._ctx.stop_reason
        return
        yield {}  # pragma: no cover — makes this an async generator

    # ── REASON ─────────────────────────────────────────────────────

    async def reason(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """The LLM stream and the tool-call parsing."""
        with StateTrace(self._ctx, "REASON"):
            async for ev in self._runner._reason(
                self._ctx, self._system_prompt, rctx.iteration
            ):
                yield ev

        if self._ctx.reason_failed:
            # The old loop broke out with stop_reason="error".
            self._ctx.stop_reason = "error"
            rctx.decision = None
            return

        rctx.decision = self._ctx.last_tool_calls

    # ── DECIDE ─────────────────────────────────────────────────────

    async def decide(
        self, rctx: Any, phase: str, payload: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """The tool-call bookkeeping and the two stop conditions."""
        if phase == PHASE_AFTER_REASON:
            if self._ctx.last_tool_calls:
                # The assistant message has to carry the tool calls
                # before the tool results are appended.
                self._runner._append_assistant_tool_calls(self._ctx)
                return
            # No tool calls → the accumulated text is the answer.
            self._ctx.final_content = self._ctx.last_accumulated
            if self._ctx.stop_reason not in {"cancelled", "paused", "timeout"}:
                self._ctx.stop_reason = "completed"
            rctx.stop = True
            rctx.stop_reason = self._ctx.stop_reason
            return

        if phase == PHASE_AFTER_ACT:
            if self._ctx.confirmation_required:
                self._ctx.stop_reason = "confirmation_required"
                rctx.stop = True
                rctx.stop_reason = self._ctx.stop_reason
            return

        return
        yield {}  # pragma: no cover — makes this an async generator

    # ── ACT ────────────────────────────────────────────────────────

    async def act(self, rctx: Any, decision: Any) -> AsyncIterator[dict[str, Any]]:
        """The tool execution."""
        with StateTrace(self._ctx, "ACT"):
            async for ev in self._runner._act(
                self._ctx, decision, rctx.iteration
            ):
                yield ev
        # The chat loop has no "action failed" path — a failing tool
        # yields a tool_call_error event and the round continues.
        rctx.result = self._ctx

    # ── OBSERVE ────────────────────────────────────────────────────

    async def observe(
        self, rctx: Any, result: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """The truncated thinking note."""
        with StateTrace(self._ctx, "OBSERVE"):
            self._runner._observe(self._ctx, self._ctx.last_thinking)
        return
        yield {}  # pragma: no cover — makes this an async generator

    # ── after_iteration ─────────────────────────────────────────────

    async def after_iteration(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """The after-iteration hook, then the memory consolidation."""
        await _maybe_await(
            self._runner._hook.after_iteration(self._ctx.hook_ctx(rctx.iteration))
        )
        await self._runner._consolidate_memory(self._ctx)
        return
        yield {}  # pragma: no cover — makes this an async generator

    # ── FINALIZE ───────────────────────────────────────────────────

    async def finalize(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """The terminal events."""
        with StateTrace(self._ctx, "FINALIZE"):
            async for ev in self._runner._emit_done(self._ctx):
                yield ev


__all__ = ["ChatPlan"]
