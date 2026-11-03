"""Tests for the shared agent runtime (``kernel/agent/runtime.py``).

The runtime is the one execution skeleton every agent loop in the
project is built on. These tests pin the **skeleton**: the order of
the stages, where the loop stops, and what happens when a stage
fails. The plans keep their own semantics; the runtime keeps the flow.
"""

from __future__ import annotations

from typing import Any

import pytest

from llmwikify.kernel.agent.runtime import (
    PHASE_AFTER_ACT,
    PHASE_AFTER_OBSERVE,
    PHASE_AFTER_REASON,
    AgentPlan,
    AgentRuntime,
)


class Ctx:
    """A minimal context — the runtime only touches a few attributes."""

    def __init__(self) -> None:
        self.iteration = -1
        self.decision: Any = None
        self.result: Any = None
        self.stop = False
        self.stop_reason = ""


class RecordingPlan(AgentPlan):
    """A plan that records the stage order and can fail on demand."""

    def __init__(self, *, fail_reason: bool = False, fail_act: bool = False):
        self.calls: list[str] = []
        self.fail_reason = fail_reason
        self.fail_act = fail_act
        self.max_iterations = 3

    async def before_iteration(self, ctx: Any) -> None:
        self.calls.append("before_iteration")

    async def precheck(self, ctx: Any):
        self.calls.append("precheck")
        return
        yield {}  # pragma: no cover

    async def reason(self, ctx: Any):
        self.calls.append("reason")
        yield {"type": "reasoning"}
        if self.fail_reason:
            return
        ctx.decision = {"action": "go"}

    async def act(self, ctx: Any, decision: Any):
        self.calls.append("act")
        yield {"type": "tool_call_start"}
        if self.fail_act:
            return
        ctx.result = {"done": True}

    async def observe(self, ctx: Any, result: Any):
        self.calls.append("observe")
        yield {"type": "round_complete"}

    async def decide(self, ctx: Any, phase: str, payload: Any):
        self.calls.append(f"decide:{phase}")
        return
        yield {}  # pragma: no cover

    async def after_iteration(self, ctx: Any):
        self.calls.append("after_iteration")
        yield {"type": "after"}

    async def finalize(self, ctx: Any):
        self.calls.append("finalize")
        yield {"type": "done"}


async def _drive(plan: AgentPlan, ctx: Ctx | None = None) -> list[dict[str, Any]]:
    ctx = ctx or Ctx()
    return [event async for event in AgentRuntime().run_stream(ctx, plan)]


def _stop_at(phase: str, events: list[dict[str, Any]] | None = None):
    """A ``decide`` that stops at ``phase`` and yields ``events``."""

    async def decide(ctx: Any, p: str, payload: Any):
        if p == phase:
            ctx.stop = True
            ctx.stop_reason = "stopped_by_plan"
            for ev in events or []:
                yield ev
        return
        yield {}  # pragma: no cover

    return decide


@pytest.mark.asyncio
async def test_the_stage_order_is_fixed() -> None:
    """One round runs the stages in the documented order."""
    plan = RecordingPlan()
    await _drive(plan)
    assert plan.calls[:11] == [
        "before_iteration",
        "precheck",
        "reason",
        "decide:after_reason",
        "act",
        "decide:after_act",
        "observe",
        "decide:after_observe",
        "after_iteration",
        "before_iteration",
        "precheck",
    ]


@pytest.mark.asyncio
async def test_events_are_passed_through_in_order() -> None:
    """The plan's events reach the caller unchanged and in order."""
    plan = RecordingPlan()
    events = await _drive(plan)
    assert [e["type"] for e in events[:5]] == [
        "reasoning",
        "tool_call_start",
        "round_complete",
        "after",
        "reasoning",
    ]
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_finalize_runs_after_the_loop() -> None:
    """The terminal events come last, after every round."""
    plan = RecordingPlan()
    await _drive(plan)
    assert plan.calls[-1] == "finalize"


@pytest.mark.asyncio
async def test_max_iterations_bounds_the_loop() -> None:
    """The loop runs at most ``max_iterations`` rounds."""
    plan = RecordingPlan()
    await _drive(plan)
    assert plan.calls.count("reason") == 3


@pytest.mark.asyncio
async def test_precheck_stops_before_the_round() -> None:
    """A precheck that sets ``ctx.stop`` ends the loop before REASON."""

    async def precheck(ctx: Any):
        ctx.stop = True
        yield {"type": "phase", "phase": "timeout"}

    plan = RecordingPlan()
    plan.precheck = precheck  # type: ignore[assignment]
    events = await _drive(plan)
    assert "reason" not in plan.calls
    assert plan.calls[-1] == "finalize"
    assert events[0] == {"type": "phase", "phase": "timeout"}


@pytest.mark.asyncio
async def test_a_failed_reason_stops_the_loop() -> None:
    """REASON that leaves no decision ends the loop (it emitted the error)."""
    plan = RecordingPlan(fail_reason=True)
    await _drive(plan)
    assert plan.calls.count("reason") == 1
    assert "act" not in plan.calls


@pytest.mark.asyncio
async def test_a_failed_act_continues_with_the_next_round() -> None:
    """ACT that leaves no result continues — the action failed, not the loop."""
    plan = RecordingPlan(fail_act=True)
    await _drive(plan)
    assert plan.calls.count("reason") == 3
    assert plan.calls.count("act") == 3
    assert "observe" not in plan.calls


@pytest.mark.asyncio
async def test_decide_after_reason_can_stop() -> None:
    """A plan may stop right after REASON."""
    plan = RecordingPlan()
    plan.decide = _stop_at(PHASE_AFTER_REASON)  # type: ignore[assignment]
    await _drive(plan)
    assert "act" not in plan.calls


@pytest.mark.asyncio
async def test_decide_after_act_can_stop() -> None:
    """A plan may stop right after ACT (the confirmation case)."""
    plan = RecordingPlan()
    plan.decide = _stop_at(PHASE_AFTER_ACT)  # type: ignore[assignment]
    await _drive(plan)
    assert "observe" not in plan.calls


@pytest.mark.asyncio
async def test_decide_after_observe_can_stop() -> None:
    """A plan may stop right after OBSERVE."""
    plan = RecordingPlan()
    plan.decide = _stop_at(PHASE_AFTER_OBSERVE)  # type: ignore[assignment]
    await _drive(plan)
    assert "after_iteration" not in plan.calls


@pytest.mark.asyncio
async def test_decide_may_yield_events() -> None:
    """A stage that stops may still emit its terminal event."""
    plan = RecordingPlan()
    plan.decide = _stop_at(  # type: ignore[assignment]
        PHASE_AFTER_REASON, [{"type": "phase", "phase": "done"}]
    )
    events = await _drive(plan)
    assert {"type": "phase", "phase": "done"} in events


@pytest.mark.asyncio
async def test_the_stop_reason_is_written_to_the_context() -> None:
    """A plan's stop reason lands on ``ctx.stop_reason``."""
    plan = RecordingPlan()
    plan.decide = _stop_at(PHASE_AFTER_ACT)  # type: ignore[assignment]
    ctx = Ctx()
    await _drive(plan, ctx)
    assert ctx.stop_reason == "stopped_by_plan"


@pytest.mark.asyncio
async def test_the_iteration_is_written_to_the_context() -> None:
    """The runtime numbers the rounds."""
    seen: list[int] = []

    class Plan(RecordingPlan):
        async def before_iteration(self, ctx: Any) -> None:
            seen.append(ctx.iteration)

    plan = Plan()
    await _drive(plan)
    assert seen == [0, 1, 2]


@pytest.mark.asyncio
async def test_the_stop_flag_is_reset_between_stages() -> None:
    """A stage that stops does not leak the flag into the next round."""
    plan = RecordingPlan()
    ctx = Ctx()
    await _drive(plan, ctx)
    # the last round set stop=False before each decide; the loop ran to
    # max_iterations, so stop is False at the end
    assert ctx.stop is False


@pytest.mark.asyncio
async def test_the_runtime_is_stateless_and_reusable() -> None:
    """One runtime can drive many runs."""
    runtime = AgentRuntime()
    plan = RecordingPlan()
    first = [e async for e in runtime.run_stream(Ctx(), plan)]
    second = [e async for e in runtime.run_stream(Ctx(), plan)]
    assert first == second


@pytest.mark.asyncio
async def test_the_default_plan_stages_are_no_ops() -> None:
    """A plan only spells out what it does."""

    class Minimal(AgentPlan):
        async def reason(self, ctx: Any):
            ctx.decision = 1
            return
            yield {}  # pragma: no cover

        async def act(self, ctx: Any, decision: Any):
            ctx.result = 2
            return
            yield {}  # pragma: no cover

    ctx = Ctx()
    events = [e async for e in AgentRuntime().run_stream(ctx, Minimal())]
    assert events == []
    assert ctx.decision == 1


@pytest.mark.asyncio
async def test_the_plan_base_class_requires_reason_and_act() -> None:
    """``reason`` / ``act`` are abstract by convention."""
    plan = AgentPlan()

    async def _drain() -> None:
        async for _ in plan.reason(Ctx()):
            pass

    with pytest.raises(NotImplementedError):
        await _drain()
