"""Tests for unified/loop.py — UnifiedAgentLoop。"""
from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.agent.unified.core import (
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedContext,
    UnifiedHook,
)
from llmwikify.apps.chat.agent.unified.loop import UnifiedAgentLoop
from llmwikify.apps.chat.agent.unified.spec import (
    ActResult,
    BaseSpec,
    ReasonResponse,
    UnifiedResult,
)


# ── Mock handlers ─────────────────────────────────────────


class _MockReasoner(StepHandler):
    """Returns a fixed ReasonResponse."""

    def __init__(self, response: ReasonResponse):
        self._response = response

    async def handle(self, input, spec, ctx):
        return StepResult.ok(self._response)


class _MockActor(StepHandler):
    """Returns a fixed ActResult."""

    def __init__(self, result: ActResult):
        self._result = result

    async def handle(self, input, spec, ctx):
        return StepResult.ok(self._result)


class _MockDecider(StepHandler):
    """Returns a fixed (stop, reason) tuple."""

    def __init__(self, stop: bool, reason: str = ""):
        self._stop = stop
        self._reason = reason

    async def handle(self, input, spec, ctx):
        return StepResult.ok((self._stop, self._reason))


class _FailingReasoner(StepHandler):
    """Always fails."""

    async def handle(self, input, spec, ctx):
        return StepResult.fail("reasoner failed")


class _StreamingMockReasoner(StreamingHandler):
    """StreamingHandler that yields events then a result."""

    def __init__(self, response: ReasonResponse, events: list[dict] | None = None):
        self._response = response
        self._events = events or []

    async def stream(self, input, spec, ctx):
        for ev in self._events:
            yield ev
        yield StepResult.ok(self._response)


# ── Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_step_handler_flow():
    """StepHandler reasoner + actor → done event."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True, output="result"))
    loop = UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders={})

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "completed"


@pytest.mark.asyncio
async def test_loop_streaming_handler_flow():
    """StreamingHandler reasoner → events + done."""
    reasoner = _StreamingMockReasoner(
        ReasonResponse(tool_calls=[]),
        events=[
            {"type": "message_delta", "content": "hello"},
            {"type": "thinking", "content": "reasoning..."},
        ],
    )
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="no_tool_calls")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_reason": decider},
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    delta_events = [e for e in events if e.get("type") == "message_delta"]
    thinking_events = [e for e in events if e.get("type") == "thinking"]
    done_events = [e for e in events if e.get("type") == "done"]

    assert len(delta_events) == 1
    assert len(thinking_events) == 1
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "no_tool_calls"


@pytest.mark.asyncio
async def test_loop_decide_after_reason():
    """after_reason decider stops the loop."""
    reasoner = _MockReasoner(ReasonResponse(tool_calls=[]))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="no_tool_calls")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_reason": decider},
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "no_tool_calls"


@pytest.mark.asyncio
async def test_loop_decide_after_act():
    """after_act decider stops the loop."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "success"


@pytest.mark.asyncio
async def test_loop_precheck_timeout():
    """precheck triggers → stop."""
    def timeout_precheck(ctx):
        ctx.stop_reason = "timeout"
        return True

    reasoner = _MockReasoner(ReasonResponse())
    actor = _MockActor(ActResult(success=True))
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor, deciders={},
        precheck=timeout_precheck,
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    phase_events = [e for e in events if e.get("type") == "phase"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(phase_events) == 1
    assert phase_events[0]["phase"] == "timeout"
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_loop_error_handling():
    """Handler exception → error event."""
    reasoner = _FailingReasoner()
    actor = _MockActor(ActResult(success=True))
    loop = UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders={})

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    error_events = [e for e in events if e.get("type") == "error"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(error_events) == 1
    assert "reasoner failed" in error_events[0]["message"]
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "error"


@pytest.mark.asyncio
async def test_loop_run_to_completion():
    """drain stream → UnifiedResult."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True, output="result"))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    spec = BaseSpec(messages=[{"role": "user", "content": "hi"}])
    result = await loop.run_to_completion(spec)

    assert isinstance(result, UnifiedResult)
    assert result.stop_reason == "success"
    assert result.iterations == 1
    assert result.error is None


def test_loop_execution_context():
    """execution_context returns AgentExecutionContext."""
    reasoner = _MockReasoner(ReasonResponse())
    actor = _MockActor(ActResult(success=True))
    loop = UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders={})

    ctx = loop.execution_context()
    assert ctx is not None
    assert hasattr(ctx, "chat_service")
    assert hasattr(ctx, "tool_executor")
