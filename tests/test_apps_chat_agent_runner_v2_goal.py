"""Phase 10 (2026-06-20): goal_active_predicate tests for ChatRunnerV2.

Borrowed from nanobot v0.2.1 ``AgentRunSpec.goal_active_predicate``:
PRECHECK calls the predicate once per iteration; returning False stops
the runner with ``stop_reason="goal_abandoned"``. Exceptions are
swallowed (don't kill the loop on a transient DB hiccup).

Cases:
  1. predicate=None → no constraint (Phase 8 back-compat)
  2. predicate always returns True → loop proceeds
  3. predicate returns False → _precheck returns True with
     stop_reason="goal_abandoned"
  4. predicate raises → loop continues (defensive)
  5. mid-run flip: True for N iterations then False → stops cleanly
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2, _RunContext
from llmwikify.apps.chat.agent.spec import ChatRunSpec


class _StubService:
    config: dict = {}


class _StubExecutor:
    pass


class _StubPromptBuilder:
    pass


def _make_runner() -> ChatRunnerV2:
    return ChatRunnerV2(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )


def _make_ctx(predicate=None) -> _RunContext:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=None,
        session_id="s1",
        goal_active_predicate=predicate,
    )
    return _RunContext(spec=spec, messages=[])


@pytest.mark.asyncio
async def test_precheck_predicate_none_is_phase8_backcompat() -> None:
    runner = _make_runner()
    ctx = _make_ctx(predicate=None)
    should_break = await runner._precheck(ctx)
    assert should_break is False
    assert ctx.stop_reason == "in_progress"


@pytest.mark.asyncio
async def test_precheck_predicate_returns_true_continues() -> None:
    runner = _make_runner()
    ctx = _make_ctx(predicate=lambda: True)
    should_break = await runner._precheck(ctx)
    assert should_break is False
    assert ctx.stop_reason == "in_progress"


@pytest.mark.asyncio
async def test_precheck_predicate_returns_false_stops_with_goal_abandoned() -> None:
    runner = _make_runner()
    ctx = _make_ctx(predicate=lambda: False)
    should_break = await runner._precheck(ctx)
    assert should_break is True
    assert ctx.stop_reason == "goal_abandoned"


@pytest.mark.asyncio
async def test_precheck_predicate_exception_does_not_kill_loop() -> None:
    """A predicate that raises (e.g. transient DB error) should be
    treated as 'continue': we don't want a one-time hiccup to abort
    every chat session in flight."""
    runner = _make_runner()

    def _raises() -> bool:
        raise RuntimeError("simulated DB hiccup")

    ctx = _make_ctx(predicate=_raises)
    should_break = await runner._precheck(ctx)
    assert should_break is False
    assert ctx.stop_reason == "in_progress"


@pytest.mark.asyncio
async def test_precheck_predicate_flips_to_false_after_active_iterations() -> None:
    """Simulate /goal done mid-run: predicate returns True for the
    first 2 iterations, then False. Ensures stop fires on the flip,
    not later."""
    runner = _make_runner()
    flips = {"calls": 0}

    def _pred() -> bool:
        flips["calls"] += 1
        return flips["calls"] <= 2

    ctx = _make_ctx(predicate=_pred)
    # Iteration 1
    assert await runner._precheck(ctx) is False
    assert ctx.stop_reason == "in_progress"
    # Iteration 2
    assert await runner._precheck(ctx) is False
    assert ctx.stop_reason == "in_progress"
    # Iteration 3 — flip
    assert await runner._precheck(ctx) is True
    assert ctx.stop_reason == "goal_abandoned"
    assert flips["calls"] == 3
