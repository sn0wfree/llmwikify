"""Unit tests for the ReAct loop framework (Phase 8).

Covers:

  - ``ReactConfig``    - 13-field config + validation
  - ``ReactLoop``      - the 11-step round structure
                          (done check, reason, on_before_act,
                           act invoke, on_after_act, observe,
                           on_before_observe, observe result,
                           on_after_observe, persist_state,
                           round_complete)
  - 9 hook points      - all 9 lifecycle hooks fire correctly
                          (restore_state, done_condition,
                           on_before_act, on_after_act,
                           on_before_observe, on_after_observe,
                           persist_state, max_rounds,
                           reason_prompt metadata)
  - 4 event types      - reasoning, action_error, round_complete,
                          phase
  - Edge cases         - unknown action, "done" reason, sync/async
                          handlers, handler returns dict vs
                          SkillResult, exception in reason vs
                          exception in action, observation_error

Target: 50+ tests, no I/O, no network, no real LLM calls.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.react_loop import (
    EVENT_ACTION_ERROR,
    EVENT_OBSERVATION_ERROR,
    EVENT_PHASE,
    EVENT_REASONING,
    EVENT_ROUND_COMPLETE,
    ReactConfig,
    ReactLoop,
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
    """Build a list of SkillActions that return ``{"called_<name>": True}``."""
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
    """Build a sync handler that records its name in the result."""
    def handler(args: dict, ctx: SkillContext) -> SkillResult:
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
) -> ReactConfig:
    """Build a ReactConfig with a deterministic reason that
    alternates ``reason_action`` for ``done_after`` rounds then 'done'."""
    call_count = {"n": 0}

    async def reason(state: dict, ctx: SkillContext) -> dict:
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

    return ReactConfig(
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
    )


# ─── ReactConfig ──────────────────────────────────────────────────


class TestReactConfig:
    def test_minimal_config(self) -> None:
        async def r(s, c):
            return {"action": "a", "thought": ""}
        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
            initial_state={},
            done_condition=lambda s: False,
            reason=r,
        )
        assert cfg.max_rounds == 10
        assert cfg.observe is None
        assert cfg.reason_prompt == ""
        assert cfg.action_map == {"a": cfg.actions[0]}

    @pytest.mark.skip(reason="v0.38: ReActConfig relaxes validation (empty actions OK in action_handler mode)")
    def test_actions_required(self) -> None:
        async def r(s, c):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="actions must be non-empty"):
            ReactConfig(
                actions=[],
                initial_state={},
                done_condition=lambda s: False,
                reason=r,
            )

    def test_max_rounds_must_be_positive(self) -> None:
        async def r(s, c):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="max_rounds must be >= 1"):
            ReactConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                done_condition=lambda s: False,
                reason=r,
                max_rounds=0,
            )

    @pytest.mark.skip(reason="v0.38: ReActConfig has default done_condition")
    def test_done_condition_required(self) -> None:
        async def r(s, c):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="done_condition is required"):
            ReactConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                done_condition=None,  # type: ignore[arg-type]
                reason=r,
            )

    def test_reason_required(self) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            ReactConfig(
                actions=[SkillAction(name="a", description="a", handler=_sync_handler)],
                initial_state={},
                done_condition=lambda s: False,
                reason=None,  # type: ignore[arg-type]
            )

    def test_duplicate_action_names_rejected(self) -> None:
        async def r(s, c):
            return {"action": "", "thought": ""}
        with pytest.raises(ValueError, match="duplicate names"):
            ReactConfig(
                actions=[
                    SkillAction(name="a", description="x", handler=_sync_handler),
                    SkillAction(name="a", description="y", handler=_sync_handler),
                ],
                initial_state={},
                done_condition=lambda s: False,
                reason=r,
            )

    def test_action_map_built(self) -> None:
        async def r(s, c):
            return {"action": "", "thought": ""}
        cfg = ReactConfig(
            actions=[
                SkillAction(name="a", description="x", handler=_sync_handler),
                SkillAction(name="b", description="y", handler=_sync_handler),
            ],
            initial_state={},
            done_condition=lambda s: False,
            reason=r,
        )
        assert set(cfg.action_map.keys()) == {"a", "b"}


# ─── Reason: synchronous + async ────────────────────────────────


class TestReason:
    @pytest.mark.asyncio
    async def test_basic_round_trip(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        # Round 0: reasoning + round_complete (action "a" ran)
        # Round 1: reasoning(done) + phase(done) (reason returned "done")
        # Terminal: phase(done)
        assert types == [
            EVENT_REASONING,
            EVENT_ROUND_COMPLETE,
            EVENT_REASONING,
            EVENT_PHASE,
            EVENT_PHASE,
        ]
        # Last event is the terminal phase
        assert events[-1]["type"] == EVENT_PHASE
        assert "final_state" in events[-1]

    @pytest.mark.asyncio
    async def test_initial_state_copied_not_aliased(self, ctx: SkillContext) -> None:
        state = {"k": 1}
        cfg = make_simple_config(initial_state=state, done_after=1)
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        # Caller's dict is untouched (we copied in __init__).
        assert state == {"k": 1}

    @pytest.mark.asyncio
    async def test_state_merged_from_action_data(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        loop = ReactLoop(cfg)
        snapshots: list[dict] = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["called_a"] is True

    @pytest.mark.asyncio
    async def test_reason_callable_propagates_exception(self, ctx: SkillContext) -> None:
        async def bad_reason(s, c):
            raise ValueError("reason broken")

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            done_condition=lambda s: False,
            reason=bad_reason,
            max_rounds=1,
        )
        loop = ReactLoop(cfg)
        with pytest.raises(ValueError, match="reason broken"):
            async for _ in loop.run(ctx):
                pass


# ─── done_condition ─────────────────────────────────────────────


class TestDoneCondition:
    @pytest.mark.asyncio
    async def test_done_after_zero_rounds(self, ctx: SkillContext) -> None:
        """With done_after=0, the reason immediately returns 'done'."""
        cfg = make_simple_config(done_after=0, max_rounds=5)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        types = [e["type"] for e in events]
        # reason returns "done" on first call → reasoning + phase(done via reason)
        # then terminal phase(done)
        assert types == [EVENT_REASONING, EVENT_PHASE, EVENT_PHASE]
        # Mid-loop phase has reason='reason_returned_done'
        assert events[1]["reason"] == "reason_returned_done"
        # Terminal phase has final_state
        assert "final_state" in events[2]

    @pytest.mark.asyncio
    async def test_max_rounds_terminates(self, ctx: SkillContext) -> None:
        """When done never returns True and reason always picks 'a'."""
        call_count = {"n": 0}

        async def always_a(s, c):
            call_count["n"] += 1
            return {"action": "a", "thought": "loop"}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            done_condition=lambda s: False,
            reason=always_a,
            max_rounds=3,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        # 3 reasoning + 3 round_complete + 1 phase(done) = 7 events
        assert len(events) == 7
        assert events[-1]["type"] == EVENT_PHASE
        assert events[-1]["phase"] == "done"
        assert call_count["n"] == 3


# ─── Action dispatch ────────────────────────────────────────────


class TestActionDispatch:
    @pytest.mark.asyncio
    async def test_handler_receives_state_as_args(self, ctx: SkillContext) -> None:
        seen: dict = {}

        def handler(args: dict, c: SkillContext) -> SkillResult:
            seen["args"] = dict(args)
            return SkillResult.ok({})

        # Reason returns "a" on first call, then "done" — so the
        # handler runs exactly once before the loop exits.
        call = {"n": 0}

        async def reason(s, c):
            call["n"] += 1
            if call["n"] >= 2:
                return {"action": "done", "thought": ""}
            return {"action": "a", "thought": ""}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=handler)],
            initial_state={"x": 1, "y": 2},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=5,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert seen["args"] == {"x": 1, "y": 2}

    @pytest.mark.asyncio
    async def test_handler_returning_dict_normalized_to_skillresult(self, ctx: SkillContext) -> None:
        def dict_handler(args, c):
            return {"raw": "dict", "n": 42}

        # reason returns "a" then "done"
        call = {"n": 0}
        async def reason(s, c):
            call["n"] += 1
            if call["n"] >= 2:
                return {"action": "done", "thought": ""}
            return {"action": "a", "thought": ""}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=dict_handler)],
            initial_state={},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=1,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                events.append(ev)
        assert events[0]["state_snapshot"]["raw"] == "dict"
        assert events[0]["state_snapshot"]["n"] == 42

    @pytest.mark.asyncio
    async def test_async_handler_invoked(self, ctx: SkillContext) -> None:
        async def async_h(args, c):
            return SkillResult.ok({"async": True})

        call = {"n": 0}
        async def reason(s, c):
            call["n"] += 1
            if call["n"] >= 2:
                return {"action": "done", "thought": ""}
            return {"action": "a", "thought": ""}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=async_h)],
            initial_state={},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=1,
        )
        loop = ReactLoop(cfg)
        snapshots = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["async"] is True

    @pytest.mark.asyncio
    async def test_action_error_event_on_exception(self, ctx: SkillContext) -> None:
        async def boom(args, c):
            raise ValueError("kaboom")

        call = {"n": 0}
        async def reason(s, c):
            call["n"] += 1
            if call["n"] >= 2:
                return {"action": "done", "thought": ""}
            return {"action": "a", "thought": ""}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=boom)],
            initial_state={},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=2,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        err = [e for e in events if e["type"] == EVENT_ACTION_ERROR]
        assert len(err) == 1
        assert err[0]["action"] == "a"
        assert "kaboom" in err[0]["error"]

    @pytest.mark.asyncio
    async def test_unknown_action_skipped(self, ctx: SkillContext) -> None:
        call = {"n": 0}

        async def reason(s, c):
            call["n"] += 1
            if call["n"] == 1:
                return {"action": "nope", "thought": "bad"}
            return {"action": "done", "thought": ""}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=5,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        # Should still complete with terminal phase=done
        assert events[-1]["type"] == EVENT_PHASE
        assert events[-1]["phase"] == "done"

    @pytest.mark.asyncio
    async def test_done_reason_emits_phase_event(self, ctx: SkillContext) -> None:
        call = {"n": 0}

        async def reason(s, c):
            call["n"] += 1
            return {"action": "done", "thought": "finished"}

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=_sync_handler)],
            initial_state={},
            done_condition=lambda s: s.get("done", False),
            reason=reason,
            max_rounds=5,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        done = [e for e in events if e["type"] == EVENT_PHASE and e.get("reason") == "reason_returned_done"]
        assert len(done) == 1

    @pytest.mark.asyncio
    async def test_wrong_return_type_skipped_with_warning(self, ctx: SkillContext, caplog) -> None:
        def bad(args, c):
            return "not a dict or SkillResult"

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=bad)],
            initial_state={},
            done_condition=lambda s: True,
            reason=lambda s, c: _async_return({"action": "a", "thought": ""}),
            max_rounds=1,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        # round_complete never fires (the action's bad return is skipped)
        complete = [e for e in events if e["type"] == EVENT_ROUND_COMPLETE]
        assert complete == []


# ─── Hooks: all 9 hook points ────────────────────────────────────


class TestHooks:
    @pytest.mark.asyncio
    async def test_restore_state_override(self, ctx: SkillContext) -> None:
        """restore_state takes precedence over initial_state at run() start."""
        def restore(s):
            return {"restored": True, "round": 99}

        cfg = make_simple_config(
            done_after=1,
            restore_state=restore,
        )
        loop = ReactLoop(cfg)
        # Before run(): state is the initial copy
        assert loop.state == {"counter": 0}
        # After run() starts, restore_state is applied
        snapshots = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["restored"] is True
        assert snapshots[0]["round"] == 99

    @pytest.mark.skip(reason="v0.38: ReActEngine skips hooks for done action (done_condition checked first)")
    @pytest.mark.asyncio
    async def test_on_before_act_fires(self, ctx: SkillContext) -> None:
        seen: list[tuple[dict, str]] = []

        def hook(state, action_name):
            seen.append((dict(state), action_name))

        cfg = make_simple_config(done_after=3, on_before_act=hook)
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        # done_after=3 → reason returns "a" 3 times then "done"
        # on_before_act fires 4 times: 3 for "a" + 1 for "done"
        assert len(seen) == 4
        assert sum(1 for s in seen if s[1] == "a") == 3
        assert sum(1 for s in seen if s[1] == "done") == 1

    @pytest.mark.asyncio
    async def test_on_after_act_fires_with_result(self, ctx: SkillContext) -> None:
        seen: list[tuple[dict, str, SkillResult]] = []

        def hook(state, action_name, result):
            seen.append((dict(state), action_name, result))

        cfg = make_simple_config(done_after=2, on_after_act=hook)
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert len(seen) == 2
        assert all(s[1] == "a" for s in seen)
        assert all(s[2].status == "ok" for s in seen)

    @pytest.mark.asyncio
    async def test_on_after_act_can_mutate_state(self, ctx: SkillContext) -> None:
        """Gate intervention: hook injects a flag into state."""
        def gate(state, action_name, result):
            if action_name == "a" and result.status == "ok":
                state["gate_passed"] = True

        cfg = make_simple_config(done_after=1, on_after_act=gate)
        loop = ReactLoop(cfg)
        snapshots: list[dict] = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["gate_passed"] is True

    @pytest.mark.asyncio
    async def test_on_before_observe_fires(self, ctx: SkillContext) -> None:
        seen: list[dict] = []

        def hook(state):
            seen.append(dict(state))

        async def observe(s, c):
            return {"observations": ["obs1"]}

        cfg = make_simple_config(
            done_after=1,
            observe=observe,
            on_before_observe=hook,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_on_after_observe_fires(self, ctx: SkillContext) -> None:
        seen: list[dict] = []

        def hook(state):
            seen.append(dict(state))

        async def observe(s, c):
            return {"observations": ["obs1"]}

        cfg = make_simple_config(
            done_after=1,
            observe=observe,
            on_after_observe=hook,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert len(seen) == 1
        # observations are already in state when this hook fires
        assert seen[0]["observations"] == ["obs1"]

    @pytest.mark.asyncio
    async def test_persist_state_fires_each_round(self, ctx: SkillContext) -> None:
        seen: list[tuple[dict, int]] = []

        def hook(state, round_idx):
            seen.append((dict(state), round_idx))

        cfg = make_simple_config(done_after=3, persist_state=hook)
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert len(seen) == 3
        assert [r for _, r in seen] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_observation_error_event(self, ctx: SkillContext) -> None:
        async def observe(s, c):
            raise RuntimeError("observe broken")

        cfg = make_simple_config(done_after=1, observe=observe)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        err = [e for e in events if e["type"] == EVENT_OBSERVATION_ERROR]
        assert len(err) == 1
        assert "observe broken" in err[0]["error"]
        # round_complete still fires (loop continues)
        assert any(e["type"] == EVENT_ROUND_COMPLETE for e in events)

    @pytest.mark.asyncio
    async def test_observation_folded_into_state(self, ctx: SkillContext) -> None:
        async def observe(s, c):
            return {"observations": ["obs-A", "obs-B"]}

        cfg = make_simple_config(done_after=1, observe=observe)
        loop = ReactLoop(cfg)
        snapshots = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["observations"] == ["obs-A", "obs-B"]

    @pytest.mark.asyncio
    async def test_observation_without_observations_key_ignored(self, ctx: SkillContext) -> None:
        async def observe(s, c):
            return {"something_else": 42}  # no 'observations' key

        cfg = make_simple_config(done_after=1, observe=observe)
        loop = ReactLoop(cfg)
        snapshots = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert "observations" not in snapshots[0]

    @pytest.mark.asyncio
    async def test_reason_prompt_stored_as_metadata(self) -> None:
        cfg = make_simple_config(done_after=0, reason_prompt="you are a planner")
        assert cfg.reason_prompt == "you are a planner"

    @pytest.mark.asyncio
    async def test_done_condition_uses_current_state(self, ctx: SkillContext) -> None:
        """The done_condition is called every round with the current state."""
        seen_states: list[dict] = []

        def done(s):
            seen_states.append(dict(s))
            return s.get("counter", 0) >= 2

        async def add_one(state, c):
            state["counter"] = state.get("counter", 0) + 1
            return SkillResult.ok({})

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=add_one)],
            initial_state={"counter": 0},
            done_condition=done,
            reason=lambda s, c: _async_return({"action": "a", "thought": ""}),
            max_rounds=10,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        # seen each round's state via the lambda
        assert any(s.get("counter", 0) >= 2 for s in seen_states)

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_break_loop(self, ctx: SkillContext) -> None:
        def bad_hook(state, action_name):
            raise RuntimeError("hook boom")

        cfg = make_simple_config(
            done_after=1,
            on_before_act=bad_hook,
        )
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        # round_complete still fires
        assert any(e["type"] == EVENT_ROUND_COMPLETE for e in events)


# ─── Event structure ────────────────────────────────────────────


class TestEventStructure:
    @pytest.mark.asyncio
    async def test_reasoning_event_shape(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        r = events[0]
        assert r["type"] == EVENT_REASONING
        assert r["action"] == "a"
        assert r["thought"] == "round 1"
        assert r["round"] == 0

    @pytest.mark.asyncio
    async def test_round_complete_includes_snapshot(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=1)
        loop = ReactLoop(cfg)
        snapshots = []
        async for ev in loop.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                snapshots.append(ev["state_snapshot"])
        assert snapshots[0]["called_a"] is True
        # snapshot is a copy
        snapshots[0]["mutated"] = True
        loop2 = ReactLoop(cfg)
        async for ev in loop2.run(ctx):
            if ev["type"] == EVENT_ROUND_COMPLETE:
                assert "mutated" not in ev["state_snapshot"]

    @pytest.mark.asyncio
    async def test_terminal_phase_done_always_emitted(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=0, max_rounds=3)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        assert events[-1]["type"] == EVENT_PHASE
        assert events[-1]["phase"] == "done"
        assert "final_state" in events[-1]

    @pytest.mark.asyncio
    async def test_max_rounds_terminal_emits_final_state(self, ctx: SkillContext) -> None:
        cfg = make_simple_config(done_after=999, max_rounds=2)
        loop = ReactLoop(cfg)
        events: list[dict] = []
        async for ev in loop.run(ctx):
            events.append(ev)
        final = events[-1]
        assert final["type"] == EVENT_PHASE
        assert final["phase"] == "done"
        assert "final_state" in final
        # called_a was set in 2 rounds
        assert final["final_state"]["called_a"] is True


# ─── Multi-round integration ─────────────────────────────────────


class TestMultiRound:
    @pytest.mark.asyncio
    async def test_two_rounds_increment_state(self, ctx: SkillContext) -> None:
        async def bump(args, c):
            return SkillResult.ok({"counter": args.get("counter", 0) + 1})

        cfg = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=bump)],
            initial_state={"counter": 0},
            done_condition=lambda s: s.get("counter", 0) >= 2,
            reason=lambda s, c: _async_return({"action": "a", "thought": ""}),
            max_rounds=10,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        assert loop.state["counter"] == 2

    @pytest.mark.asyncio
    async def test_persist_then_restore_round_trip(self, ctx: SkillContext) -> None:
        """Persist saves state, then a fresh loop restores it."""
        saved: dict = {}

        def persist(state, round_idx):
            saved.update(state)

        async def bump(args, c):
            return SkillResult.ok({"counter": args.get("counter", 0) + 1})

        # First loop: persist
        cfg1 = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=bump)],
            initial_state={"counter": 0},
            done_condition=lambda s: s.get("counter", 0) >= 3,
            reason=lambda s, c: _async_return({"action": "a", "thought": ""}),
            max_rounds=10,
            persist_state=persist,
        )
        loop1 = ReactLoop(cfg1)
        async for _ in loop1.run(ctx):
            pass
        assert saved["counter"] == 3

        # Second loop: restore the saved state
        def restore(s):
            return dict(saved)

        cfg2 = ReactConfig(
            actions=[SkillAction(name="a", description="x", handler=bump)],
            initial_state={"counter": 0},
            done_condition=lambda s: s.get("counter", 0) >= 5,
            reason=lambda s, c: _async_return({"action": "a", "thought": ""}),
            max_rounds=10,
            restore_state=restore,
        )
        loop2 = ReactLoop(cfg2)
        async for _ in loop2.run(ctx):
            pass
        # Started at 3, ran 2 more rounds
        assert loop2.state["counter"] == 5

    @pytest.mark.skip(reason="v0.38: ReActEngine skips hooks for done action (done_condition checked first)")
    @pytest.mark.asyncio
    async def test_full_hook_chain_fires_once_per_round(self, ctx: SkillContext) -> None:
        calls: list[str] = []

        def on_b(state, name):
            calls.append(f"before_act:{name}")

        def on_a(state, name, result):
            calls.append(f"after_act:{name}")

        def on_bo(state):
            calls.append("before_obs")

        def on_ao(state):
            calls.append("after_obs")

        def persist(state, round_idx):
            calls.append(f"persist:{round_idx}")

        async def observe(s, c):
            calls.append("observe")
            return {"observations": ["o1"]}

        cfg = make_simple_config(
            done_after=2,
            observe=observe,
            on_before_act=on_b,
            on_after_act=on_a,
            on_before_observe=on_bo,
            on_after_observe=on_ao,
            persist_state=persist,
        )
        loop = ReactLoop(cfg)
        async for _ in loop.run(ctx):
            pass
        # 2 "a" rounds then 1 "done" round (no hooks fire for done since
        # the framework short-circuits before on_after_act for unknown/done)
        # Order per round: before_act, after_act, before_obs, observe, after_obs, persist
        # Round 0 (a): full chain
        # Round 1 (a): full chain
        # Round 2 (done): on_before_act fires, then short-circuit (no act, no obs)
        assert calls == [
            "before_act:a", "after_act:a", "before_obs", "observe", "after_obs", "persist:0",
            "before_act:a", "after_act:a", "before_obs", "observe", "after_obs", "persist:1",
            "before_act:done",
        ]


# ─── Helpers ─────────────────────────────────────────────────────


async def _async_return(value: Any) -> Any:
    return value
