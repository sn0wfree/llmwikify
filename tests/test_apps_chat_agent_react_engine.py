"""Unit tests for ReActEngine — unified ReAct loop framework.

Covers:

  - ReActConfig validation (required fields, timeout, duplicates)
  - ReActEngine.run() 13-step round structure
  - Timeout support
  - Cancel / pause signals
  - Custom action_handler mode (chat mode)
  - 7 lifecycle hooks
  - Event types: reasoning, action_error, round_complete, phase,
    observation_error, timeout
  - Backward compat: 2-arg reason callback auto-wrapping
  - Edge cases: unknown action, "done" reason, handler types,
    exception propagation

Target: 50+ tests, no I/O, no network, no real LLM calls.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from llmwikify.apps.chat.agent.react_engine import (
    EVENT_ACTION_ERROR,
    EVENT_OBSERVATION_ERROR,
    EVENT_PHASE,
    EVENT_REASONING,
    EVENT_ROUND_COMPLETE,
    EVENT_TIMEOUT,
    ReActConfig,
    ReActEngine,
    _wrap_reason_for_compat,
)
from llmwikify.apps.chat.skills.base import (
    SkillAction,
    SkillContext,
    SkillResult,
)


# ─── Fixtures & helpers ───────────────────────────────────────────


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext(session_id="sess-1", config={"k": "v"})


def make_actions(*names: str) -> list[SkillAction]:
    """Build SkillActions that return ``{"called_<name>": True}``."""
    out: list[SkillAction] = []
    for n in names:
        out.append(SkillAction(
            name=n,
            description=f"Action {n}",
            handler=_name_handler(n),
            input_schema={"type": "object", "properties": {}, "required": []},
        ))
    return out


def _sync_handler(args: dict, ctx: SkillContext) -> SkillResult:
    return SkillResult.ok({"called": True, "args_echo": dict(args)})


def _name_handler(name: str):
    def handler(args: dict, ctx: SkillContext) -> SkillResult:
        return SkillResult.ok({f"called_{name}": True, "args_echo": dict(args)})
    return handler


def _async_handler(name: str):
    async def handler(args: dict, ctx: SkillContext) -> SkillResult:
        return SkillResult.ok({f"called_{name}": True, "args_echo": dict(args)})
    return handler


def make_simple_config(
    *,
    actions: list[SkillAction] | None = None,
    initial_state: dict | None = None,
    done_after: int = 1,
    max_rounds: int = 5,
    reason_action: str = "a",
    observe=None,
    reason_prompt: str = "",
    on_before_act=None,
    on_after_act=None,
    on_before_observe=None,
    on_after_observe=None,
    persist_state=None,
    restore_state=None,
    timeout_seconds: float = 0,
    action_handler=None,
) -> ReActConfig:
    """Build a ReActConfig with a deterministic reason that
    alternates ``reason_action`` for ``done_after`` rounds then 'done'."""
    call_count = {"n": 0}

    async def reason(state: dict, ctx: SkillContext, emit) -> dict:
        call_count["n"] += 1
        if call_count["n"] >= done_after + 1:
            return {"action": "done", "thought": "finished"}
        return {"action": reason_action, "thought": f"round {call_count['n']}"}

    if actions is None:
        actions = [
            SkillAction(
                name="a",
                description="Action a",
                handler=_name_handler("a"),
            ),
        ]

    return ReActConfig(
        actions=actions,
        initial_state=initial_state or {"counter": 0},
        done_condition=lambda s: s.get("done", False),
        reason=reason,
        max_rounds=max_rounds,
        observe=observe,
        reason_prompt=reason_prompt,
        on_before_act=on_before_act,
        on_after_act=on_after_act,
        on_before_observe=on_before_observe,
        on_after_observe=on_after_observe,
        persist_state=persist_state,
        restore_state=restore_state,
        timeout_seconds=timeout_seconds,
        action_handler=action_handler,
    )


# ─── ReActConfig ──────────────────────────────────────────────────


class TestReActConfig:
    def test_minimal_config(self) -> None:
        async def r(s, c, emit):
            return {"action": "a", "thought": ""}
        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
            initial_state={},
            reason=r,
        )
        assert cfg.max_rounds == 10
        assert cfg.timeout_seconds == 0
        assert cfg.observe is None
        assert cfg.reason_prompt == ""
        assert cfg.action_handler is None
        assert cfg.action_map == {"a": cfg.actions[0]}

    def test_max_rounds_must_be_positive(self) -> None:
        async def r(s, c, emit):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="max_rounds must be >= 1"):
            ReActConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                reason=r,
                max_rounds=0,
            )

    def test_timeout_must_be_non_negative(self) -> None:
        async def r(s, c, emit):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="timeout_seconds must be >= 0"):
            ReActConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                reason=r,
                timeout_seconds=-1,
            )

    def test_reason_required(self) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            ReActConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                reason=None,  # type: ignore[arg-type]
            )

    def test_duplicate_action_names_rejected(self) -> None:
        async def r(s, c, emit):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="duplicate names"):
            ReActConfig(
                actions=[
                    SkillAction(name="a", description="x", handler=_sync_handler),
                    SkillAction(name="a", description="y", handler=_sync_handler),
                ],
                initial_state={},
                reason=r,
            )

    def test_empty_actions_allowed_with_handler(self) -> None:
        async def r(s, c, emit):
            return {"action": "x", "thought": ""}
        async def handler(name, state, ctx, emit):
            return SkillResult.ok({})
        cfg = ReActConfig(
            actions=[],
            initial_state={},
            reason=r,
            action_handler=handler,
        )
        assert cfg.action_map == {}

    def test_default_done_condition(self) -> None:
        async def r(s, c, emit):
            return {"action": "a", "thought": ""}
        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
            initial_state={"phase": "done"},
            reason=r,
        )
        # Default done_condition checks phase == "done"
        assert cfg.done_condition({"phase": "done"}) is True
        assert cfg.done_condition({"phase": "running"}) is False


# ─── Reason: basic round trip ─────────────────────────────────────


class TestReason:
    @pytest.mark.asyncio
    async def test_basic_round_trip(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        # Round 0: reasoning + round_complete
        # Round 1: reasoning(done) + phase(done)
        # Terminal: phase(done)
        assert types == [
            EVENT_REASONING,
            EVENT_ROUND_COMPLETE,
            EVENT_REASONING,
            EVENT_PHASE,
            EVENT_PHASE,
        ]
        assert events[-1]["type"] == EVENT_PHASE
        assert "final_state" in events[-1]

    @pytest.mark.asyncio
    async def test_initial_state_copied_not_aliased(self, ctx: SkillContext) -> None:
        state = {"k": 1}
        cfg = make_simple_config(initial_state=state, done_after=1)
        engine = ReActEngine(cfg)
        async for _ in engine.run(ctx):
            pass
        assert state == {"k": 1}

    @pytest.mark.asyncio
    async def test_state_merged_from_action_data(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        engine = ReActEngine(cfg)
        snapshots: list[dict] = []
        async for ev in engine.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["called_a"] is True

    @pytest.mark.asyncio
    async def test_reason_exception_propagates(self, ctx: SkillContext) -> None:
        async def bad_reason(s, c, emit):
            raise ValueError("reason broken")

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=bad_reason,
        )
        engine = ReActEngine(cfg)
        with pytest.raises(ValueError, match="reason broken"):
            async for _ in engine.run(ctx):
                pass

    @pytest.mark.asyncio
    async def test_reason_returning_done_ends_loop(self, ctx: SkillContext) -> None:
        async def done_reason(s, c, emit):
            return {"action": "done", "thought": "all done"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=done_reason,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        assert types == [EVENT_REASONING, EVENT_PHASE, EVENT_PHASE]
        assert events[0]["action"] == "done"
        assert events[1]["reason"] == "reason_returned_done"


# ─── Done condition ───────────────────────────────────────────────


class TestDoneCondition:
    @pytest.mark.asyncio
    async def test_done_condition_triggers(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(
            done_after=99,  # never naturally done
            initial_state={"done": True},
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        # done_condition triggers → phase(done), then terminal phase(done)
        assert types == [EVENT_PHASE, EVENT_PHASE]
        assert events[0]["phase"] == "done"
        assert events[0]["reason"] == "done_condition"


# ─── Timeout ──────────────────────────────────────────────────────


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_triggers(self, ctx: SkillContext) -> None:
        async def slow_reason(s, c, emit):
            await asyncio.sleep(0.1)
            return {"action": "a", "thought": "slow"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=slow_reason,
            timeout_seconds=0.05,
            max_rounds=100,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        assert EVENT_TIMEOUT in types
        # After timeout, a phase event with phase="timeout" is emitted
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert any(e.get("phase") == "timeout" for e in phase_events)

    @pytest.mark.asyncio
    async def test_no_timeout_when_zero(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=2, timeout_seconds=0)
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        assert EVENT_TIMEOUT not in types


# ─── Cancel / Pause ───────────────────────────────────────────────


class TestCancelPause:
    @pytest.mark.asyncio
    async def test_cancel_stops_loop(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(
            done_after=99,
            initial_state={"cancelled": True},
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert any(e.get("phase") == "cancelled" for e in phase_events)

    @pytest.mark.asyncio
    async def test_pause_stops_loop(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(
            done_after=99,
            initial_state={"paused": True},
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert any(e.get("phase") == "paused" for e in phase_events)

    @pytest.mark.asyncio
    async def test_cancel_mid_loop(self, ctx: SkillContext) -> None:
        """Cancel set by an action's on_after_act hook."""
        call_count = {"n": 0}

        async def reason(s, c, emit):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                return {"action": "done", "thought": "done"}
            return {"action": "a", "thought": f"round {call_count['n']}"}

        def cancel_hook(state, action_name, result):
            if call_count["n"] == 2:
                state["cancelled"] = True

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_name_handler("a"))],
            initial_state={},
            reason=reason,
            on_after_act=cancel_hook,
            max_rounds=10,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert any(e.get("phase") == "cancelled" for e in phase_events)


# ─── Action dispatch ──────────────────────────────────────────────


class TestActionDispatch:
    @pytest.mark.asyncio
    async def test_unknown_action_skipped(self, ctx: SkillContext) -> None:
        async def reason(s, c, emit):
            return {"action": "nonexistent", "thought": "oops"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=reason,
            max_rounds=3,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        # Unknown action is skipped, no round_complete for it
        action_events = [e for e in events if e["type"] == EVENT_REASONING]
        assert all(e["action"] == "nonexistent" for e in action_events)

    @pytest.mark.asyncio
    async def test_action_exception_emits_error(self, ctx: SkillContext) -> None:
        def broken_handler(args, ctx):
            raise RuntimeError("tool broken")

        async def reason(s, c, emit):
            return {"action": "a", "thought": "try"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=broken_handler)],
            initial_state={},
            reason=reason,
            max_rounds=3,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        error_events = [e for e in events if e["type"] == EVENT_ACTION_ERROR]
        assert len(error_events) >= 1
        assert "tool broken" in error_events[0]["error"]

    @pytest.mark.asyncio
    async def test_async_handler_works(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(
            actions=[SkillAction(
                name="a", description="x", handler=_async_handler("a"),
            )],
            done_after=1,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        snapshots = [e["state_snapshot"] for e in events if e["type"] == EVENT_ROUND_COMPLETE]
        assert snapshots[0]["called_a"] is True

    @pytest.mark.asyncio
    async def test_dict_handler_normalized_to_skill_result(self, ctx: SkillContext) -> None:
        def dict_handler(args, ctx):
            return {"status": "ok", "data": {"x": 1}}

        async def reason(s, c, emit):
            return {"action": "a", "thought": "test"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=dict_handler)],
            initial_state={},
            reason=reason,
            max_rounds=1,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        snapshots = [e["state_snapshot"] for e in events if e["type"] == EVENT_ROUND_COMPLETE]
        # The raw dict is wrapped as SkillResult.ok(dict), so the entire
        # dict becomes the data merged into state.
        assert snapshots[0].get("data") == {"x": 1}


# ─── Custom action_handler mode ───────────────────────────────────


class TestCustomActionHandler:
    @pytest.mark.asyncio
    async def test_custom_handler_called(self, ctx: SkillContext) -> None:
        handler_calls: list[str] = []

        async def my_handler(action_name, state, ctx, emit):
            handler_calls.append(action_name)
            return SkillResult.ok({f"did_{action_name}": True})

        call_count = {"n": 0}

        async def reason(s, c, emit):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                return {"action": "done", "thought": "done"}
            return {"action": "search", "thought": "searching"}

        cfg = ReActConfig(
            actions=[],
            initial_state={},
            reason=reason,
            action_handler=my_handler,
            max_rounds=5,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        assert handler_calls == ["search"]
        snapshots = [e["state_snapshot"] for e in events if e["type"] == EVENT_ROUND_COMPLETE]
        assert snapshots[0]["did_search"] is True

    @pytest.mark.asyncio
    async def test_custom_handler_exception(self, ctx: SkillContext) -> None:
        async def bad_handler(action_name, state, ctx, emit):
            raise ValueError("handler broken")

        async def reason(s, c, emit):
            return {"action": "x", "thought": "test"}

        cfg = ReActConfig(
            actions=[],
            initial_state={},
            reason=reason,
            action_handler=bad_handler,
            max_rounds=3,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        error_events = [e for e in events if e["type"] == EVENT_ACTION_ERROR]
        assert len(error_events) >= 1
        assert "handler broken" in error_events[0]["error"]


# ─── Hooks ────────────────────────────────────────────────────────


class TestHooks:
    @pytest.mark.asyncio
    async def test_hook_call_order(self, ctx: SkillContext) -> None:
        calls: list[str] = []

        def before_act(state, action_name):
            calls.append(f"before_act:{action_name}")

        def after_act(state, action_name, result):
            calls.append(f"after_act:{action_name}")

        def before_observe(state):
            calls.append("before_observe")

        def after_observe(state):
            calls.append("after_observe")

        def persist(state, round_idx):
            calls.append(f"persist:{round_idx}")

        cfg = make_simple_config(
            done_after=1,
            on_before_act=before_act,
            on_after_act=after_act,
            on_before_observe=before_observe,
            on_after_observe=after_observe,
            persist_state=persist,
            observe=lambda s, c: {"observations": ["obs1"]},
        )
        engine = ReActEngine(cfg)
        async for _ in engine.run(ctx):
            pass
        assert calls == [
            "before_act:a",
            "after_act:a",
            "before_observe",
            "after_observe",
            "persist:0",
        ]

    @pytest.mark.asyncio
    async def test_persist_restore_round_trip(self, ctx: SkillContext) -> None:
        saved_state: dict = {}

        def persist(state, round_idx):
            saved_state.update(state)

        def restore(state):
            return {**state, **saved_state}

        # First engine: run one round
        cfg1 = make_simple_config(done_after=1, persist_state=persist, restore_state=restore)
        engine1 = ReActEngine(cfg1)
        async for _ in engine1.run(ctx):
            pass

        # Second engine: should restore the persisted state
        cfg2 = make_simple_config(done_after=1, persist_state=persist, restore_state=restore)
        engine2 = ReActEngine(cfg2)
        events: list[dict] = []
        async for ev in engine2.run(ctx):
            events.append(ev)
        # The restored state should have the data from the first run
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        final_state = phase_events[-1].get("final_state", {})
        assert final_state.get("called_a") is True

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_crash(self, ctx: SkillContext) -> None:
        def bad_hook(state, action_name):
            raise RuntimeError("hook broken")

        cfg = make_simple_config(
            done_after=1,
            on_before_act=bad_hook,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        # Should still complete despite hook exception
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert len(phase_events) >= 1


# ─── Observation ──────────────────────────────────────────────────


class TestObservation:
    @pytest.mark.asyncio
    async def test_observe_folds_observations(self, ctx: SkillContext) -> None:
        async def my_observe(state, ctx):
            return {"observations": ["found 5 sources", "gaps detected"]}

        cfg = make_simple_config(done_after=1, observe=my_observe)
        engine = ReActEngine(cfg)
        snapshots: list[dict] = []
        async for ev in engine.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["observations"] == ["found 5 sources", "gaps detected"]

    @pytest.mark.asyncio
    async def test_observe_exception_emits_error(self, ctx: SkillContext) -> None:
        async def bad_observe(state, ctx):
            raise RuntimeError("observe broken")

        cfg = make_simple_config(done_after=1, observe=bad_observe)
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        error_events = [e for e in events if e["type"] == EVENT_OBSERVATION_ERROR]
        assert len(error_events) >= 1
        assert "observe broken" in error_events[0]["error"]


# ─── Emit callback ────────────────────────────────────────────────


class TestEmitCallback:
    @pytest.mark.asyncio
    async def test_reason_can_emit_events(self, ctx: SkillContext) -> None:
        async def reason_with_emit(state, ctx, emit):
            await emit({"type": "thinking", "content": "analyzing..."})
            return {"action": "a", "thought": "done thinking"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=reason_with_emit,
            max_rounds=1,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        thinking_events = [e for e in events if e.get("type") == "thinking"]
        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "analyzing..."


# ─── Backward compat ──────────────────────────────────────────────


class TestBackwardCompat:
    def test_2_arg_reason_wrapped(self) -> None:
        async def old_reason(state, ctx):
            return {"action": "a", "thought": "old style"}

        wrapped = _wrap_reason_for_compat(old_reason)
        # Wrapped should accept 3 args
        result = asyncio.run(
            wrapped({}, SkillContext(), lambda e: None)
        )
        assert result["action"] == "a"

    def test_3_arg_reason_not_wrapped(self) -> None:
        async def new_reason(state, ctx, emit):
            return {"action": "a", "thought": "new style"}

        wrapped = _wrap_reason_for_compat(new_reason)
        # Should be the same function (no wrapping needed)
        assert wrapped is new_reason

    @pytest.mark.asyncio
    async def test_old_2_arg_reason_works_in_engine(self, ctx: SkillContext) -> None:
        """Old-style reason(state, ctx) works via auto-wrapping."""
        call_count = {"n": 0}

        async def old_reason(state, ctx):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                return {"action": "done", "thought": "done"}
            return {"action": "a", "thought": "old"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=old_reason,
            max_rounds=5,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        # Should work: reasoning + round_complete + reasoning(done) + phase(done) + phase(done)
        types = [e["type"] for e in events]
        assert types == [
            EVENT_REASONING,
            EVENT_ROUND_COMPLETE,
            EVENT_REASONING,
            EVENT_PHASE,
            EVENT_PHASE,
        ]


# ─── Max rounds ───────────────────────────────────────────────────


class TestMaxRounds:
    @pytest.mark.asyncio
    async def test_max_rounds_exits(self, ctx: SkillContext) -> None:
        async def never_done(s, c, emit):
            return {"action": "a", "thought": "keep going"}

        cfg = ReActConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            reason=never_done,
            max_rounds=3,
        )
        engine = ReActEngine(cfg)
        events: list[dict] = []
        async for ev in engine.run(ctx):
            events.append(ev)
        round_events = [e for e in events if e["type"] == EVENT_ROUND_COMPLETE]
        assert len(round_events) == 3
        # Terminal phase is emitted
        phase_events = [e for e in events if e["type"] == EVENT_PHASE]
        assert phase_events[-1]["phase"] == "done"


# ─── Backward-compat aliases ──────────────────────────────────────


class TestAliases:
    def test_react_config_alias(self) -> None:
        assert ReActConfig is not None
        from llmwikify.apps.chat.agent.react_engine import ReactConfig
        assert ReactConfig is ReActConfig

    def test_react_loop_alias(self) -> None:
        from llmwikify.apps.chat.agent.react_engine import ReactLoop
        assert ReactLoop is ReActEngine
