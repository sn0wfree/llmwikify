"""AgentRuntime — the single execution skeleton for every agent loop.

The project used to drive its agent loops from four different places:

- ``apps/chat/agent/runner_v2.py`` — the chat ReAct loop (LLM driven)
- ``apps/chat/agent/research_runner.py`` — the research pipeline (rule driven)
- ``apps/chat/base.py::aask_with_tools`` — a plain OpenAI tool loop
- ``apps/chat/skills/workflows/subagent_worker.py`` — the subagent tool loop

They all had the same shape — *for each round: check, decide, act,
observe, repeat* — but every copy had its own iteration counter, its own
stop conditions, its own error handling and its own hook points. A
change to "what happens when the model asks for a tool" had to be made
in as many places as there were loops.

This module is that shape, written once. A loop is a **plan**: the
declarative configuration of the stages. The runtime drives the stages
in a fixed order and owns the bookkeeping (the iteration counter, the
stop handling, the event pass-through).

The plans own the *semantics*; the runtime owns the *skeleton*. That
split is what makes the behaviour of a migrated loop auditable: the
plan is a small, readable adapter over the old code, and the old
event order is preserved event for event.

The skeleton::

    for iteration in range(plan.max_iterations):
        before_iteration
        PRECHECK            → stop?
        REASON              → ctx.decision
        DECIDE after_reason → stop?
        ACT                 → ctx.result
        DECIDE after_act    → stop?
        OBSERVE
        DECIDE after_observe → stop?
        after_iteration
    FINALIZE

Stage contract
--------------

* every stage is an async generator — the events it produces are
  yielded straight through to the caller;
* ``reason`` must set ``ctx.decision`` (or leave it ``None`` — which
  means "the reason stage failed", it already emitted the error, and
  the loop stops);
* ``act`` must set ``ctx.result`` (or leave it ``None`` — which means
  "the action failed", it already emitted the error, and the loop
  continues with the next round);
* ``precheck`` and ``decide`` stop the loop by setting
  ``ctx.stop = True`` (and usually ``ctx.stop_reason``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

#: The phases a plan can decide on.
PHASE_AFTER_REASON = "after_reason"
PHASE_AFTER_ACT = "after_act"
PHASE_AFTER_OBSERVE = "after_observe"


class AgentPlan:
    """The declarative configuration of one agent loop.

    Subclasses override the stages they need; every stage has a
    do-nothing default so a plan only spells out what it does. The
    order the runtime calls them in is fixed (see the module
    docstring) — a plan never controls the flow, only the steps.
    """

    #: How many rounds the loop may run.
    max_iterations: int = 10

    async def before_iteration(self, ctx: Any) -> None:
        """Called before each round (hooks, timers)."""

    async def precheck(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Check before the round starts; set ``ctx.stop`` to stop."""
        return
        yield {}  # pragma: no cover — makes this an async generator

    async def reason(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Produce the next decision.

        Must set ``ctx.decision``; leaving it ``None`` means the stage
        failed (the plan emitted the error) and the loop stops.
        """
        raise NotImplementedError
        yield {}  # pragma: no cover — makes this an async generator

    async def act(self, ctx: Any, decision: Any) -> AsyncIterator[dict[str, Any]]:
        """Execute the decision.

        Must set ``ctx.result``; leaving it ``None`` means the action
        failed (the plan emitted the error) and the loop continues with
        the next round.
        """
        raise NotImplementedError
        yield {}  # pragma: no cover — makes this an async generator

    async def observe(self, ctx: Any, result: Any) -> AsyncIterator[dict[str, Any]]:
        """Fold the result into the state."""
        return
        yield {}  # pragma: no cover — makes this an async generator

    async def decide(
        self, ctx: Any, phase: str, payload: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Decide whether the loop stops after ``phase``.

        Set ``ctx.stop = True`` (and usually ``ctx.stop_reason``) to
        stop.
        """
        return
        yield {}  # pragma: no cover — makes this an async generator

    async def after_iteration(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Called after each completed round."""
        return
        yield {}  # pragma: no cover — makes this an async generator

    async def finalize(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Produce the terminal events."""
        return
        yield {}  # pragma: no cover — makes this an async generator


class AgentRuntime:
    """The one execution skeleton.

    Stateless — a runtime can be shared. Every loop in the project is
    this runtime plus a plan.
    """

    async def run_stream(
        self, ctx: Any, plan: AgentPlan
    ) -> AsyncIterator[dict[str, Any]]:
        """Drive ``plan`` and yield its events.

        The context is the plan's own state carrier: the runtime only
        reads ``ctx.iteration``, ``ctx.decision``, ``ctx.result`` and
        writes ``ctx.stop`` / ``ctx.stop_reason``.
        """
        for iteration in range(plan.max_iterations):
            ctx.iteration = iteration
            await plan.before_iteration(ctx)

            # ── PRECHECK ──
            ctx.stop = False
            async for event in plan.precheck(ctx):
                yield event
            if ctx.stop:
                break

            # ── REASON ──
            ctx.decision = None
            async for event in plan.reason(ctx):
                yield event
            if getattr(ctx, "decision", None) is None:
                # The reason stage failed and already emitted the error.
                break

            ctx.stop = False
            async for event in plan.decide(ctx, PHASE_AFTER_REASON, ctx.decision):
                yield event
            if ctx.stop:
                break

            # ── ACT ──
            ctx.result = None
            async for event in plan.act(ctx, ctx.decision):
                yield event
            if getattr(ctx, "result", None) is None:
                # The action failed and already emitted the error —
                # continue with the next round.
                continue

            ctx.stop = False
            async for event in plan.decide(ctx, PHASE_AFTER_ACT, ctx.result):
                yield event
            if ctx.stop:
                break

            # ── OBSERVE ──
            async for event in plan.observe(ctx, ctx.result):
                yield event

            ctx.stop = False
            async for event in plan.decide(ctx, PHASE_AFTER_OBSERVE, ctx.result):
                yield event
            if ctx.stop:
                break

            async for event in plan.after_iteration(ctx):
                yield event

        # ── FINALIZE ──
        async for event in plan.finalize(ctx):
            yield event


#: The shared runtime instance — the runtime is stateless.
RUNTIME = AgentRuntime()


__all__ = [
    "AgentPlan",
    "AgentRuntime",
    "RUNTIME",
    "PHASE_AFTER_REASON",
    "PHASE_AFTER_ACT",
    "PHASE_AFTER_OBSERVE",
]
