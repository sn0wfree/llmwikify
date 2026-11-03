"""Differential guard for the research pipeline on the shared runtime.

The research loop used to carry its own driver (a ``for`` loop with
its own iteration counter, stop conditions and error handling). It now
runs on the shared ``AgentRuntime`` with a ``_ResearchPlan``.

The *semantics* must not have moved. These tests pin the observable
behaviour of the old loop, event for event:

* the exact event sequence of a normal round;
* the order in which the hooks are called;
* every error path (unknown action, raising action, raising reason);
* every terminal path (timeout, done condition, reason says done,
  cancelled, paused) — including the fact that a terminal phase event
  suppresses the "finished" one.
"""

from __future__ import annotations

from typing import Any

import pytest

from llmwikify.apps.chat.agent.research_runner import (
    EVENT_ACTION_ERROR,
    EVENT_OBSERVATION_ERROR,
    EVENT_PHASE,
    EVENT_REASONING,
    EVENT_ROUND_COMPLETE,
    ReactConfig,
    ReactLoop,
)
from llmwikify.apps.chat.skills.base import SkillAction, SkillResult


def _action(name: str, handler) -> SkillAction:
    return SkillAction(name=name, description=name, handler=handler)


def _config(**kw: Any) -> ReactConfig:
    base: dict[str, Any] = {
        "actions": [],
        "initial_state": {},
        "max_rounds": 3,
    }
    base.update(kw)
    return ReactConfig(**base)


async def _run(config: ReactConfig, ctx: Any = None, emit=None) -> list[dict]:
    loop = ReactLoop(config)
    return [ev async for ev in loop.run(ctx if ctx is not None else {}, emit)]


# ── a normal round ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_normal_round_emits_the_expected_events() -> None:
    """One round: reasoning → round_complete."""

    async def act(state, ctx):
        return SkillResult.ok({"step": 1})

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": "t"},
        max_rounds=1,
    )
    events = await _run(config)
    assert [e["type"] for e in events] == [
        EVENT_REASONING,
        EVENT_ROUND_COMPLETE,
        EVENT_PHASE,
    ]
    assert events[0]["action"] == "plan"
    assert events[0]["thought"] == "t"
    assert events[0]["round"] == 0
    assert events[1]["round"] == 0
    assert events[1]["action"] == "plan"
    # the terminal phase carries the final state
    assert events[2]["phase"] == "done"
    assert events[2]["final_state"]["step"] == 1


@pytest.mark.asyncio
async def test_the_state_is_folded_between_rounds() -> None:
    """The action result lands in the state and the next round sees it."""
    seen: list[Any] = []
    counter = {"n": 0}

    async def act(state, ctx):
        counter["n"] += 1
        return SkillResult.ok({"step": counter["n"]})

    def reason(state, ctx):
        seen.append(state.get("step"))
        if len(seen) >= 2:
            return {"action": "done", "thought": ""}
        return {"action": "plan", "thought": ""}

    config = _config(
        actions=[_action("plan", act)],
        initial_state={"step": 0},
        reason=reason,
        max_rounds=3,
    )
    events = await _run(config)
    assert seen == [0, 1]
    types = [e["type"] for e in events]
    # round 0 ran the action; round 1 the reasoner ended the pipeline
    assert types.count(EVENT_ROUND_COMPLETE) == 1


# ── hooks ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_hooks_are_called_in_order() -> None:
    """The hook order of the old loop is preserved exactly."""
    calls: list[str] = []

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    async def on_before_act(state, action_name):
        calls.append("before_act")

    async def on_after_act(state, action_name, result):
        calls.append("after_act")

    async def on_before_observe(state, result):
        calls.append("before_observe")

    async def on_after_observe(state, result):
        calls.append("after_observe")

    async def observe(state, ctx):
        calls.append("observe")

    async def persist(state, round_idx):
        calls.append(f"persist:{round_idx}")

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        on_before_act=on_before_act,
        on_after_act=on_after_act,
        on_before_observe=on_before_observe,
        on_after_observe=on_after_observe,
        observe=observe,
        persist_state=persist,
        max_rounds=1,
    )
    await _run(config)
    assert calls == [
        "before_act",
        "after_act",
        "before_observe",
        "observe",
        "after_observe",
        "persist:0",
    ]


@pytest.mark.asyncio
async def test_the_emit_callback_receives_the_reasoning_event() -> None:
    """The side-channel emit callback gets the reasoning event."""

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    emitted: list[dict] = []
    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": "hello"},
        max_rounds=1,
    )
    await _run(config, emit=emitted.append)
    assert [e["type"] for e in emitted] == [EVENT_REASONING]


# ── error paths ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_action_reports_and_continues() -> None:
    """An unknown action is an error event, and the loop continues."""
    config = _config(
        actions=[],
        reason=lambda state, ctx: {"action": "nope", "thought": ""},
        max_rounds=2,
    )
    events = await _run(config)
    types = [e["type"] for e in events]
    assert types.count(EVENT_ACTION_ERROR) == 2
    errors = [e for e in events if e["type"] == EVENT_ACTION_ERROR]
    assert "Unknown action: nope" in errors[0]["error"]
    # the loop still ends with the terminal phase
    assert events[-1]["type"] == EVENT_PHASE


@pytest.mark.asyncio
async def test_a_raising_action_reports_and_continues() -> None:
    """A raising action is an error event, and the loop continues."""

    async def act(state, ctx):
        raise ValueError("boom")

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        max_rounds=2,
    )
    events = await _run(config)
    errors = [e for e in events if e["type"] == EVENT_ACTION_ERROR]
    assert len(errors) == 2
    assert "boom" in errors[0]["error"]


@pytest.mark.asyncio
async def test_a_raising_reason_stops_the_loop() -> None:
    """A raising reasoner is an error event, and the loop stops."""

    def reason(state, ctx):
        raise ValueError("no reason")

    config = _config(
        actions=[],
        reason=reason,
        max_rounds=3,
    )
    events = await _run(config)
    assert len(events) == 1
    assert events[0]["type"] == EVENT_ACTION_ERROR
    assert events[0]["action"] == "<reason>"
    assert "no reason" in events[0]["error"]


@pytest.mark.asyncio
async def test_a_raising_observe_hook_reports_but_continues() -> None:
    """An observation error is reported and the round still completes."""

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    async def observe(state, ctx):
        raise RuntimeError("observe failed")

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        observe=observe,
        max_rounds=1,
    )
    events = await _run(config)
    types = [e["type"] for e in events]
    assert EVENT_OBSERVATION_ERROR in types
    assert EVENT_ROUND_COMPLETE in types


@pytest.mark.asyncio
async def test_a_raising_persist_hook_is_swallowed() -> None:
    """A failing persist must not break the round."""

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    async def persist(state, round_idx):
        raise RuntimeError("disk full")

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        persist_state=persist,
        max_rounds=1,
    )
    events = await _run(config)
    assert [e["type"] for e in events][-2:] == [EVENT_ROUND_COMPLETE, EVENT_PHASE]


# ── terminal paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reasoner_can_end_the_pipeline() -> None:
    """``action == "done"`` ends the loop with a phase event."""

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "done", "thought": ""},
        max_rounds=3,
    )
    events = await _run(config)
    assert [e["type"] for e in events] == [EVENT_REASONING, EVENT_PHASE]
    assert events[1]["phase"] == "done"
    assert events[1]["reason"] == "reason_returned_done"
    assert events[1]["round"] == 0


@pytest.mark.asyncio
async def test_the_done_condition_ends_the_pipeline() -> None:
    """A satisfied done condition ends the loop before the first round."""
    config = _config(
        actions=[],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        done_condition=lambda state: True,
        max_rounds=3,
    )
    events = await _run(config)
    assert [e["type"] for e in events] == [EVENT_PHASE]
    assert events[0]["phase"] == "done"


@pytest.mark.asyncio
async def test_a_timeout_ends_the_pipeline() -> None:
    """A timeout ends the loop before the first round."""
    import time

    async def act(state, ctx):
        return SkillResult.ok({"x": 1})

    async def slow_reason(state, ctx):
        # The round takes longer than the timeout — the *next* round's
        # precheck is where the timeout fires (the old loop checked at
        # the top of every round too).
        time.sleep(0.02)
        return {"action": "plan", "thought": ""}

    config = _config(
        actions=[_action("plan", act)],
        reason=slow_reason,
        timeout_seconds=0.005,
        max_rounds=3,
    )
    events = await _run(config)
    types = [e["type"] for e in events]
    # one round ran, then the timeout ended the loop
    assert types.count(EVENT_ROUND_COMPLETE) == 1
    assert events[-1]["type"] == EVENT_PHASE
    assert events[-1]["phase"] == "timeout"
    # the timeout suppresses the closing "done" event
    assert [e for e in events if e["type"] == EVENT_PHASE].__len__() == 1


@pytest.mark.asyncio
async def test_a_cancelled_state_ends_the_pipeline() -> None:
    """A cancelled state ends the loop after the reason."""
    config = _config(
        actions=[],
        initial_state={"cancelled": True},
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        max_rounds=3,
    )
    events = await _run(config)
    assert [e["type"] for e in events] == [EVENT_REASONING, EVENT_PHASE]
    assert events[1]["phase"] == "cancelled"


@pytest.mark.asyncio
async def test_a_paused_state_ends_the_pipeline() -> None:
    """A paused state ends the loop after the reason."""
    config = _config(
        actions=[],
        initial_state={"paused": True},
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        max_rounds=3,
    )
    events = await _run(config)
    assert events[-1]["phase"] == "paused"


@pytest.mark.asyncio
async def test_a_terminal_phase_suppresses_the_final_one() -> None:
    """A terminal phase is emitted once, not twice."""
    config = _config(
        actions=[],
        reason=lambda state, ctx: {"action": "done", "thought": ""},
        max_rounds=3,
    )
    events = await _run(config)
    phases = [e for e in events if e["type"] == EVENT_PHASE]
    assert len(phases) == 1


# ── forced next action ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_forced_next_action_overrides_the_reasoner() -> None:
    """``on_after_act`` can force the next action."""

    rounds: list[str] = []

    async def act(state, ctx):
        rounds.append("plan")
        return SkillResult.ok({"x": 1})

    def reason(state, ctx):
        # The reasoner wants to stop, but the previous round forced the
        # action — the forced action wins.
        if not rounds:
            return {"action": "plan", "thought": ""}
        return {"action": "done", "thought": ""}

    def on_after_act(state, action_name, result):
        state["_forced_next_action"] = "plan"

    config = _config(
        actions=[_action("plan", act)],
        reason=reason,
        on_after_act=on_after_act,
        max_rounds=2,
    )
    events = await _run(config)
    # the forced action ran a second time instead of ending the loop
    assert rounds == ["plan", "plan"]
    assert [e["type"] for e in events].count(EVENT_ROUND_COMPLETE) == 2


# ── nested events ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nested_action_events_are_forwarded() -> None:
    """Events collected by the action handler reach the caller."""

    async def act(state, ctx):
        return SkillResult.ok({"_events": [{"type": "progress", "text": "x"}]})

    config = _config(
        actions=[_action("plan", act)],
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        max_rounds=1,
    )
    events = await _run(config)
    assert {"type": "progress", "text": "x"} in events


# ── the state carrier ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_dataclass_state_is_supported() -> None:
    """The pipeline also works with a dataclass state."""

    from dataclasses import dataclass

    @dataclass
    class State:
        step: int = 0

    async def act(state, ctx):
        return SkillResult.ok({"step": state.step + 1})

    config = _config(
        actions=[_action("plan", act)],
        initial_state=State(),
        reason=lambda state, ctx: {"action": "plan", "thought": ""},
        max_rounds=1,
    )
    events = await _run(config)
    assert events[-1]["final_state"]["step"] == 1


@pytest.mark.asyncio
async def test_the_restore_state_hook_runs_at_construction() -> None:
    """``restore_state`` is applied when the loop is built."""
    config = _config(
        actions=[],
        initial_state={"step": 0},
        restore_state=lambda state: {"step": 99},
    )
    loop = ReactLoop(config)
    assert loop.state["step"] == 99
