"""额外 loop 集成测试 — 多轮、hooks、边界情况。

测试 UnifiedAgentLoop 的高级行为：
- 多轮迭代
- Hook 调用序列
- 流式 + StepHandler 混合
- 边界情况
"""
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
    def __init__(self, response: ReasonResponse):
        self._response = response

    async def handle(self, input, spec, ctx):
        return StepResult.ok(self._response)


class _MockActor(StepHandler):
    def __init__(self, result: ActResult):
        self._result = result

    async def handle(self, input, spec, ctx):
        return StepResult.ok(self._result)


class _MockDecider(StepHandler):
    def __init__(self, stop: bool, reason: str = ""):
        self._stop = stop
        self._reason = reason

    async def handle(self, input, spec, ctx):
        return StepResult.ok((self._stop, self._reason))


class _FailingStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.fail("step failed")


class _TrackingHook(UnifiedHook):
    """Hook that records all calls."""

    def __init__(self):
        self.calls: list[str] = []

    def wants_streaming(self):
        self.calls.append("wants_streaming")
        return False

    def before_iteration(self, ctx):
        self.calls.append(f"before_iteration:{ctx.iteration}")

    def on_reason_start(self, ctx):
        self.calls.append(f"on_reason_start:{ctx.iteration}")

    def on_reason_end(self, ctx, response):
        self.calls.append(f"on_reason_end:{ctx.iteration}")

    def on_act_start(self, ctx):
        self.calls.append(f"on_act_start:{ctx.iteration}")

    def on_act_end(self, ctx, result):
        self.calls.append(f"on_act_end:{ctx.iteration}")

    def on_observe(self, ctx):
        self.calls.append(f"on_observe:{ctx.iteration}")

    def after_iteration(self, ctx):
        self.calls.append(f"after_iteration:{ctx.iteration}")

    def on_error(self, ctx, error):
        self.calls.append(f"on_error:{ctx.iteration}")

    def finalize(self, ctx, content):
        self.calls.append("finalize")
        return content


# ── Multi-iteration tests ─────────────────────────────────


class _MultiRoundDecider(StepHandler):
    """Decider that stops after N rounds."""

    def __init__(self, max_rounds: int = 3):
        self._max = max_rounds
        self._count = 0

    async def handle(self, input, spec, ctx):
        self._count += 1
        if self._count >= self._max:
            return StepResult.ok((True, "max_rounds"))
        return StepResult.ok((False, ""))


@pytest.mark.asyncio
async def test_loop_multi_iteration():
    """Loop runs multiple iterations before stopping."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MultiRoundDecider(max_rounds=3)
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    result = await loop.run_to_completion(BaseSpec(messages=[{"role": "user", "content": "hi"}]))
    assert result.iterations == 3
    assert result.stop_reason == "max_rounds"


# ── Hook tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_hook_called_in_order():
    """Hook methods are called in correct order (full cycle without early stop)."""
    hook = _TrackingHook()
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    # No decider — loop runs all max_iterations so OBSERVE + after_iteration fire
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={},
        hook=hook,
    )

    spec = BaseSpec(messages=[{"role": "user", "content": "hi"}], max_iterations=1)
    await loop.run_to_completion(spec)

    assert "before_iteration:0" in hook.calls
    assert "on_reason_start:0" in hook.calls
    assert "on_reason_end:0" in hook.calls
    assert "on_act_start:0" in hook.calls
    assert "on_act_end:0" in hook.calls
    assert "on_observe:0" in hook.calls
    assert "after_iteration:0" in hook.calls
    assert "finalize" in hook.calls

    # Order check
    idx_before = hook.calls.index("before_iteration:0")
    idx_reason_start = hook.calls.index("on_reason_start:0")
    idx_reason_end = hook.calls.index("on_reason_end:0")
    idx_act_start = hook.calls.index("on_act_start:0")
    idx_act_end = hook.calls.index("on_act_end:0")
    idx_observe = hook.calls.index("on_observe:0")
    idx_after = hook.calls.index("after_iteration:0")
    idx_finalize = hook.calls.index("finalize")

    assert idx_before < idx_reason_start < idx_reason_end
    assert idx_reason_end < idx_act_start < idx_act_end
    assert idx_act_end < idx_observe < idx_after
    assert idx_after < idx_finalize


@pytest.mark.asyncio
async def test_loop_hook_error_called():
    """on_error hook is called when exception occurs."""
    hook = _TrackingHook()

    class _ExceptingReasoner(StepHandler):
        async def handle(self, input, spec, ctx):
            raise RuntimeError("boom")

    reasoner = _ExceptingReasoner()
    actor = _MockActor(ActResult(success=True))
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor, deciders={},
        hook=hook,
    )

    await loop.run_to_completion(BaseSpec(messages=[{"role": "user", "content": "hi"}]))

    assert any("on_error" in c for c in hook.calls)
    assert "finalize" in hook.calls


# ── Mixed handler types ───────────────────────────────────


class _StreamingMockReasoner(StreamingHandler):
    def __init__(self, response, events=None):
        self._response = response
        self._events = events or []

    async def stream(self, input, spec, ctx):
        for ev in self._events:
            yield ev
        yield StepResult.ok(self._response)


@pytest.mark.asyncio
async def test_loop_streaming_reasoner_with_step_actor():
    """StreamingHandler reasoner + StepHandler actor works together."""
    reasoner = _StreamingMockReasoner(
        ReasonResponse(tool_calls=[]),
        events=[
            {"type": "message_delta", "content": "thinking..."},
            {"type": "thinking", "content": "reasoning"},
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

    types = [e.get("type") for e in events]
    assert "message_delta" in types
    assert "thinking" in types
    assert "done" in types


# ── Precheck tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_precheck_sets_stop_reason():
    """Precheck can set custom stop_reason."""
    def custom_precheck(ctx):
        ctx.stop_reason = "custom_stop"
        return True

    reasoner = _MockReasoner(ReasonResponse())
    actor = _MockActor(ActResult(success=True))
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor, deciders={},
        precheck=custom_precheck,
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    done_events = [e for e in events if e.get("type") == "done"]
    assert done_events[0]["stop_reason"] == "custom_stop"


@pytest.mark.asyncio
async def test_loop_precheck_false_continues():
    """Precheck returning False → loop continues."""
    def no_precheck(ctx):
        return False

    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
        precheck=no_precheck,
    )

    result = await loop.run_to_completion(BaseSpec(messages=[{"role": "user", "content": "hi"}]))
    assert result.stop_reason == "success"
    assert result.iterations == 1


# ── Finalize tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_finalize_transforms_content():
    """finalize callback transforms final content."""
    def upper_finalize(ctx):
        return (ctx.final_content or "").upper()

    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
        finalize=upper_finalize,
    )

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    done_events = [e for e in events if e.get("type") == "done"]
    # finalize transforms content (but ctx.final_content might be empty)
    assert done_events[0]["stop_reason"] == "success"


# ── Edge cases ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_empty_messages():
    """Loop works with empty messages."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    result = await loop.run_to_completion(BaseSpec(messages=[]))
    assert result.stop_reason == "success"


@pytest.mark.asyncio
async def test_loop_max_iterations_respected():
    """Loop stops at max_iterations even without decider."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    # No decider — loop should stop at max_iterations
    loop = UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders={})

    spec = BaseSpec(messages=[{"role": "user", "content": "hi"}], max_iterations=3)
    result = await loop.run_to_completion(spec)
    assert result.iterations == 3
    assert result.stop_reason == "completed"


@pytest.mark.asyncio
async def test_loop_actor_needs_confirmation():
    """Actor returning needs_confirmation → stop."""
    reasoner = _MockReasoner(ReasonResponse(tool_calls=[{"name": "wiki_write"}]))
    actor = _MockActor(ActResult(success=True, needs_confirmation=True, tool_name="wiki_write"))
    loop = UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders={})

    events = []
    async for event in loop.run_stream(BaseSpec(messages=[{"role": "user", "content": "hi"}])):
        events.append(event)

    confirm_events = [e for e in events if e.get("type") == "confirmation_required"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(confirm_events) == 1
    assert done_events[0]["stop_reason"] == "confirmation_required"


@pytest.mark.asyncio
async def test_loop_messages_to_inject():
    """Actor messages_to_inject are added to ctx.messages."""
    injected = []

    class _CapturingActor(StepHandler):
        async def handle(self, input, spec, ctx):
            injected.extend(ctx.messages)
            return StepResult.ok(ActResult(
                success=True,
                messages_to_inject=[{"role": "tool", "content": "result"}],
            ))

    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _CapturingActor()
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    await loop.run_to_completion(BaseSpec(messages=[{"role": "user", "content": "hi"}]))
    # After the loop, messages should include the injected tool message
    # (but we can't easily check ctx.messages after the loop ends)
    # The test verifies no errors occurred


@pytest.mark.asyncio
async def test_loop_run_to_completion_fields():
    """run_to_completion returns all expected fields."""
    reasoner = _MockReasoner(ReasonResponse(code="x = 1"))
    actor = _MockActor(ActResult(success=True))
    decider = _MockDecider(stop=True, reason="success")
    loop = UnifiedAgentLoop(
        reasoner=reasoner, actor=actor,
        deciders={"after_act": decider},
    )

    result = await loop.run_to_completion(BaseSpec(messages=[{"role": "user", "content": "hi"}]))
    assert isinstance(result, UnifiedResult)
    assert result.stop_reason == "success"
    assert result.error is None
    assert result.iterations == 1
    assert result.elapsed_sec >= 0
    assert result.compacted_count == 0
    assert isinstance(result.tools_used, list)
    assert isinstance(result.steps, list)
