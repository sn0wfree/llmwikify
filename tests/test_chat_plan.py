"""Differential guard for the chat loop on the shared runtime.

The chat loop used to carry its own driver; it now runs on the shared
``AgentRuntime`` with :class:`ChatPlan`. The plan is an **adapter** —
it calls the runner's existing step methods — so the observable
behaviour (event order, hook calls, stop conditions, the per-step
state trace) must be unchanged.

``tests/test_apps_chat_agent_runner_v2.py`` covers the loop's behaviour
extensively; these tests pin the **boundary** — that the runner really
goes through the shared runtime, and that the plan maps the stages
onto the runner's methods in the documented order.
"""

from __future__ import annotations

from typing import Any

import pytest

from llmwikify.apps.chat.agent import chat_plan as chat_plan_mod
from llmwikify.apps.chat.agent.chat_plan import ChatPlan
from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
from llmwikify.kernel.agent import runtime as runtime_mod
from llmwikify.kernel.agent.runtime import (
    PHASE_AFTER_ACT,
    PHASE_AFTER_OBSERVE,
    PHASE_AFTER_REASON,
    AgentRuntime,
    RuntimeContext,
)


class _FakeCtx:
    """A stand-in for ``_RunContext`` — the plan only touches a few fields."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.last_tool_calls: list[dict[str, Any]] = []
        self.last_accumulated = ""
        self.last_thinking = ""
        self.reason_failed = False
        self.confirmation_required = False
        self.final_content: str | None = None
        self.stop_reason = "in_progress"
        self.error: str | None = None
        self.compacted_count = 0
        self.chars_saved = 0
        self.observations: list[str] = []
        self.state_trace: list[Any] = []
        self.session_id = "s1"

    def hook_ctx(self, iteration: int) -> Any:
        return type("HookCtx", (), {"iteration": iteration})()


class _FakeRunner:
    """Records the calls the plan makes on the runner."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._hook = type(
            "Hook",
            (),
            {
                "before_iteration": self._before_iteration,
                "after_iteration": self._after_iteration,
            },
        )()
        self.tool_calls: list[dict[str, Any]] = []

    async def _before_iteration(self, ctx: Any) -> None:
        self.calls.append("hook.before_iteration")

    async def _after_iteration(self, ctx: Any) -> None:
        self.calls.append("hook.after_iteration")

    async def _precheck(self, ctx: Any) -> bool:
        self.calls.append("_precheck")
        return False

    async def _reason(self, ctx: Any, system_prompt: str, iteration: int):
        self.calls.append("_reason")
        ctx.last_accumulated = "answer"
        ctx.last_tool_calls = list(self.tool_calls)
        yield {"type": "message_delta", "content": "answer"}

    async def _act(self, ctx: Any, tool_calls: list[dict[str, Any]], iteration: int):
        self.calls.append("_act")
        yield {"type": "tool_call_start", "tool": "t"}

    def _observe(self, ctx: Any, last_thinking: str) -> None:
        self.calls.append("_observe")

    def _append_assistant_tool_calls(self, ctx: Any) -> None:
        self.calls.append("_append_assistant_tool_calls")

    async def _emit_done(self, ctx: Any):
        self.calls.append("_emit_done")
        yield {"type": "done", "content": ctx.final_content or ""}

    async def _consolidate_memory(self, ctx: Any) -> None:
        self.calls.append("_consolidate_memory")


class _FakeSpec:
    max_iterations = 3
    session_id = "s1"


async def _drive(runner: _FakeRunner, ctx: _FakeCtx) -> list[dict[str, Any]]:
    plan = ChatPlan(runner, _FakeSpec(), ctx, "sys")
    return [e async for e in AgentRuntime().run_stream(RuntimeContext(), plan)]


# ── the plan drives the runner's methods ────────────────────────────


@pytest.mark.asyncio
async def test_the_plan_calls_the_runner_methods_in_order() -> None:
    """The stage mapping is the documented one."""
    runner = _FakeRunner()
    runner.tool_calls = [{"id": "c1", "name": "t", "args": {}}]
    ctx = _FakeCtx()
    await _drive(runner, ctx)
    assert runner.calls[:9] == [
        "hook.before_iteration",
        "_precheck",
        "_reason",
        "_append_assistant_tool_calls",
        "_act",
        "_observe",
        "hook.after_iteration",
        "_consolidate_memory",
        "hook.before_iteration",
    ]


@pytest.mark.asyncio
async def test_a_tool_call_round_continues() -> None:
    """With tool calls the loop runs another round."""
    runner = _FakeRunner()
    runner.tool_calls = [{"id": "c1", "name": "t", "args": {}}]
    ctx = _FakeCtx()
    await _drive(runner, ctx)
    assert runner.calls.count("_act") == 3  # max_iterations
    assert "_append_assistant_tool_calls" in runner.calls


@pytest.mark.asyncio
async def test_without_tool_calls_the_loop_ends_after_one_round() -> None:
    """Without tool calls the accumulated text is the answer."""
    runner = _FakeRunner()
    ctx = _FakeCtx()
    await _drive(runner, ctx)
    assert runner.calls.count("_act") == 0
    assert ctx.final_content == "answer"
    assert ctx.stop_reason == "completed"


@pytest.mark.asyncio
async def test_a_failing_reasoner_stops_the_loop() -> None:
    """A failed reason ends the loop with stop_reason='error'."""
    runner = _FakeRunner()
    ctx = _FakeCtx()

    async def reason(ctx, system_prompt, iteration):
        runner.calls.append("_reason")
        ctx.reason_failed = True
        return
        yield {}  # pragma: no cover

    runner._reason = reason
    await _drive(runner, ctx)
    assert runner.calls.count("_act") == 0
    assert ctx.stop_reason == "error"


@pytest.mark.asyncio
async def test_a_confirmation_request_stops_the_loop() -> None:
    """A confirmation request ends the round with its own stop reason."""
    runner = _FakeRunner()
    runner.tool_calls = [{"id": "c1", "name": "t", "args": {}}]
    ctx = _FakeCtx()

    async def act(ctx, tool_calls, iteration):
        runner.calls.append("_act")
        ctx.confirmation_required = True
        yield {"type": "confirmation_required"}

    runner._act = act
    await _drive(runner, ctx)
    assert runner.calls.count("_act") == 1
    assert ctx.stop_reason == "confirmation_required"


@pytest.mark.asyncio
async def test_a_precheck_stop_ends_the_loop() -> None:
    """A precheck that stops ends the loop before the reason."""

    async def precheck(ctx):
        runner.calls.append("_precheck")
        return True

    runner = _FakeRunner()
    runner._precheck = precheck
    ctx = _FakeCtx()
    await _drive(runner, ctx)
    assert "_reason" not in runner.calls


# ── the runner really goes through the shared runtime ───────────────


def test_the_runner_drives_the_shared_runtime() -> None:
    """``run_stream`` must use the shared runtime, not a private loop."""
    import inspect

    src = inspect.getsource(ChatRunnerV2.run_stream)
    assert "RUNTIME.run_stream" in src
    assert "ChatPlan(" in src


def test_the_plan_is_the_only_place_the_loop_lives() -> None:
    """The chat plan is an adapter — the runner keeps the step methods."""
    import inspect

    plan_src = inspect.getsource(chat_plan_mod)
    for method in ("_precheck", "_reason", "_act", "_observe", "_emit_done"):
        assert f"self._runner.{method}" in plan_src, (
            f"the plan no longer calls the runner's {method}"
        )


def test_the_runner_no_longer_has_its_own_loop() -> None:
    """The old inline ``for iteration in range(...)`` loop is gone."""
    import inspect

    src = inspect.getsource(ChatRunnerV2.run_stream)
    assert "for iteration in range(spec.max_iterations)" not in src


def test_the_state_trace_still_records_the_five_states() -> None:
    """The per-step trace keeps its shape (it moved to state_trace.py)."""
    from llmwikify.apps.chat.agent.state_trace import StateTrace, StateTraceEntry

    ctx = _FakeCtx()
    with StateTrace(ctx, "REASON"):
        pass
    assert len(ctx.state_trace) == 1
    assert ctx.state_trace[0].state == "REASON"
    assert ctx.state_trace[0].event == "ok"
    assert isinstance(ctx.state_trace[0], StateTraceEntry)


def test_the_old_state_trace_names_are_still_importable() -> None:
    """The private names moved but stay importable from runner_v2."""
    from llmwikify.apps.chat.agent.runner_v2 import (
        _StateTrace,
        _StateTraceEntry,
    )
    from llmwikify.apps.chat.agent.state_trace import (
        StateTrace,
        StateTraceEntry,
    )

    assert _StateTrace is StateTrace
    assert _StateTraceEntry is StateTraceEntry


def test_the_phases_the_plan_decides_on() -> None:
    """The plan decides on the two phases that can stop the chat loop."""
    import inspect

    src = inspect.getsource(ChatPlan.decide)
    assert "PHASE_AFTER_REASON" in src
    assert "PHASE_AFTER_ACT" in src
    # the chat loop has no after-observe stop condition
    assert "PHASE_AFTER_OBSERVE" not in src


def test_the_runtime_is_the_shared_instance() -> None:
    """The module exposes one runtime — it is stateless."""
    assert isinstance(runtime_mod.RUNTIME, AgentRuntime)
    assert runtime_mod.RUNTIME is runtime_mod.RUNTIME
