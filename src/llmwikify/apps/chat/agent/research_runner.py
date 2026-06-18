"""ResearchRunner — ReAct state machine for the 7-step research pipeline.

Plan B v2 design: a self-contained 5-step state machine that drives the
research_skill (plan → gather → analyze → synthesize → score → revise → report)
without the v0.50 ReAct engine dependency. Uses v2-style hook points
(PRECHECK / REASON / ACT / OBSERVE / COMPLETE) and yields v2-compatible
events that can be translated to the frontend SSE vocabulary.

Compatibility layer
-------------------

The :class:`ReactConfig` + :class:`ReactLoop` API mirrors the v0.50
``ReActConfig`` / ``ReActEngine`` interface (formerly at
``llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.react_engine``,
removed in B-7) so ``research_skill.py``, ``v0.41 engine.py`` and their
tests can keep the same public surface without the archive import.

Why a custom state machine (not ChatRunnerV2)?
------------------------------------------------

``ChatRunnerV2`` is LLM-driven (Reason → stream LLM → parse ``[TOOL_CALL]``
blocks → act). The research pipeline is rule-based: a ``reason`` function
maps current state to one of 7 action names without LLM involvement.
Bridging that gap via a "headless chat service" would add ~150 lines of
adapter code for marginal reuse. A direct 5-step state machine is
~200 lines and clearer.

Plan B v2 alignment
-------------------

  * 5-step state machine: PRECHECK → REASON → ACT → OBSERVE → COMPLETE
    (mirrors ``runner_v2.py`` structure).
  * Hook signature matches ``AgentHook`` (sync + async via ``_maybe_await``).
  * Event vocabulary: ``EVENT_REASONING`` / ``EVENT_ACTION_ERROR`` /
    ``EVENT_OBSERVATION_ERROR`` / ``EVENT_PHASE`` / ``EVENT_ROUND_COMPLETE``
    (compatible with v0.50 archive + the existing ``research_skill`` tests).
  * State is a plain ``dict`` (15+ fields per research state spec).
"""
from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.skills.base import (
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Event constants (compatible with v0.50) ──────────────────────


EVENT_REASONING = "reasoning"
EVENT_ACTION_ERROR = "action_error"
EVENT_OBSERVATION_ERROR = "observation_error"
EVENT_ROUND_COMPLETE = "round_complete"
EVENT_PHASE = "phase"
EVENT_TIMEOUT = "timeout"


# ─── Hook type aliases ─────────────────────────────────────────────

ReasonCallable = Callable[[dict, Any], Awaitable[dict] | dict]
ActionCallable = Callable[[dict, Any], Awaitable[Any] | Any]
HookCallable = Callable[..., Awaitable[None] | None]


# ─── ReactConfig ──────────────────────────────────────────────────


@dataclass
class ReactConfig:
    """Configuration for a single ReAct session (research pipeline).

    Mirrors the v0.50 archive ``ReactConfig`` so callers (research_skill.py
    + 52 tests) work without modification.
    """

    actions: list[Any]
    initial_state: dict[str, Any]
    reason_prompt: str = ""
    done_condition: Callable[[dict], bool] = field(
        default=lambda s: s.get("phase") == "done",
    )
    reason: ReasonCallable | None = None
    observe: HookCallable | None = None
    max_rounds: int = 5
    timeout_seconds: float = 0
    on_before_act: HookCallable | None = None
    on_after_act: HookCallable | None = None
    on_before_observe: HookCallable | None = None
    on_after_observe: HookCallable | None = None
    persist_state: HookCallable | None = None
    restore_state: Callable[[dict], dict] | None = None


# ─── _maybe_await helper ──────────────────────────────────────────


async def _maybe_await(value: Any) -> Any:
    """Await value if it's awaitable; return as-is otherwise.

    Mirrors ``runner_v2.py:_maybe_await`` so hooks may be sync or async.
    """
    if inspect.isawaitable(value):
        return await value
    return value


# ─── State helpers (v0.50 compat: dict + dataclass) ───────────────


def _is_dataclass(obj: Any) -> bool:
    """Check if obj is a dataclass instance (not the class itself)."""
    import dataclasses
    return dataclasses.is_dataclass(obj) and not isinstance(obj, type)


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    """Get a value from state, supporting both dict and dataclass."""
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _state_update(state: Any, data: dict) -> None:
    """Update state with data, supporting both dict and dataclass."""
    if isinstance(state, dict):
        state.update(data)
    else:
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)


def _state_snapshot(state: Any) -> dict:
    """Snapshot state as a dict, supporting both dict and dataclass."""
    if isinstance(state, dict):
        return dict(state)
    import dataclasses
    if dataclasses.is_dataclass(state):
        return dataclasses.asdict(state)
    return dict(vars(state))


# ─── ReactLoop ────────────────────────────────────────────────────


class ReactLoop:
    """5-step ReAct state machine driver (research pipeline).

    Per-round flow (mirrors Plan B runner_v2 5-step state machine):
      1. PRECHECK  — check done_condition + timeout
      2. REASON    — call reason(state, ctx) → {action, thought}
      3. ACT       — call action handler(state, ctx) → SkillResult
      4. OBSERVE   — fold result.data into state, emit observation
      5. PERSIST   — save state via persist_state hook

    Events yielded each round:
      - {"type": "reasoning", "thought": ..., "action": ...}
      - {"type": "action_error", "action": ..., "error": ...}
        (if action raised)
      - {"type": "observation_error", "error": ...}
        (if observe hooks raised)
      - {"type": "round_complete", "round": N, "state": ...}
      - {"type": "phase", "phase": "done" | "cancelled" | "paused" | "timeout" | "incomplete"}
    """

    def __init__(self, config: ReactConfig) -> None:
        self._config = config
        # Support both dict and dataclass states (v0.50 compat).
        # For dataclasses, keep the original instance (not a copy) so
        # mutations are visible to the caller.
        import dataclasses
        initial = config.initial_state
        if dataclasses.is_dataclass(initial) and not isinstance(initial, dict):
            self._state = initial
        else:
            self._state = dict(initial)
        self._round: int = 0
        self._cancelled: bool = False
        self._paused: bool = False
        self._start_time: float = 0
        # Map action name → handler
        self._action_map: dict[str, Any] = {
            a.name: a for a in config.actions if hasattr(a, "name")
        }
        # Optional restore_state hook at construction time (per v0.50)
        if config.restore_state is not None:
            self._state = config.restore_state(self._state) or self._state

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    async def run(
        self,
        ctx: Any,
        emit: Callable[[dict], Awaitable[None] | None] | None = None,
    ) -> AsyncIterator[dict]:
        """Drive the state machine. Yields events.

        Args:
            ctx: arbitrary context (passed to reason and action handlers).
            emit: optional callback for side-channel events (e.g. SSE).
                If provided, events are both yielded AND passed to emit.
        """
        import time
        self._start_time = time.monotonic()

        async def _emit(ev: dict) -> None:
            if emit is not None:
                await _maybe_await(emit(ev))

        for round_idx in range(self._config.max_rounds):
            self._round = round_idx
            _state_update(self._state, {"round": round_idx})

            # 1. PRECHECK: done_condition + timeout
            if self._check_timeout():
                yield {"type": EVENT_PHASE, "phase": "timeout"}
                return
            if self._check_done():
                yield {"type": EVENT_PHASE, "phase": "done"}
                return

            # 2. REASON: decide next action
            try:
                reason_fn = self._config.reason
                if reason_fn is None:
                    decision = {"action": "done", "thought": "no reason fn"}
                else:
                    # Wrap reason to accept (state, ctx) or (state, ctx, emit)
                    # by inspecting the signature.
                    sig = inspect.signature(reason_fn)
                    n_params = sum(
                        1 for p in sig.parameters.values()
                        if p.kind not in (
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        )
                    )
                    if n_params <= 2:
                        decision = await _maybe_await(reason_fn(self._state, ctx))
                    else:
                        decision = await _maybe_await(
                            reason_fn(self._state, ctx, lambda e: None)
                        )
            except Exception as e:
                logger.exception("reason failed")
                yield {"type": EVENT_ACTION_ERROR, "action": "<reason>", "error": str(e)}
                return

            action_name = decision.get("action", "done")
            thought = decision.get("thought", "")
            reasoning_event = {
                "type": EVENT_REASONING,
                "thought": thought,
                "action": action_name,
                "round": round_idx,
            }
            await _emit(reasoning_event)
            yield reasoning_event

            # Honour forced next action from on_after_act
            forced = _state_get(self._state, "_forced_next_action")
            if forced is not None:
                if isinstance(self._state, dict):
                    self._state.pop("_forced_next_action", None)
                else:
                    try:
                        delattr(self._state, "_forced_next_action")
                    except AttributeError:
                        pass
                action_name = forced

            if action_name == "done":
                yield {
                    "type": EVENT_PHASE,
                    "phase": "done",
                    "round": round_idx,
                    "reason": "reason_returned_done",
                }
                return
            if _state_get(self._state, "cancelled", False):
                yield {"type": EVENT_PHASE, "phase": "cancelled"}
                return
            if _state_get(self._state, "paused", False):
                yield {"type": EVENT_PHASE, "phase": "paused"}
                return

            # 3. ACT: invoke the action handler
            action = self._action_map.get(action_name)
            if action is None:
                yield {
                    "type": EVENT_ACTION_ERROR,
                    "action": action_name,
                    "error": f"Unknown action: {action_name}",
                }
                continue

            # on_before_act hook
            if self._config.on_before_act is not None:
                await _maybe_await(
                    self._config.on_before_act(self._state, action_name),
                )

            try:
                if hasattr(action, "handler"):
                    result = await _maybe_await(action.handler(self._state, ctx))
                else:
                    result = await _maybe_await(action(self._state, ctx))
            except Exception as e:
                logger.warning("Action %s raised: %s", action_name, e, exc_info=True)
                yield {
                    "type": EVENT_ACTION_ERROR,
                    "action": action_name,
                    "error": str(e),
                }
                continue

            # on_after_act hook
            if self._config.on_after_act is not None:
                await _maybe_await(
                    self._config.on_after_act(self._state, action_name, result),
                )

            # Forward nested events from action handlers (v0.50 compat).
            # v0.41 engine's _make_action_handler collects dispatch
            # events into result.data["_events"]; we yield them
            # inline so the caller sees them.
            if result is not None and getattr(result, "status", None) == "ok":
                data = getattr(result, "data", None) or {}
                if isinstance(data, dict):
                    nested = data.pop("_events", None)
                    if nested:
                        for ne in nested:
                            yield ne

            # 4. OBSERVE: fold result.data + observe() output into state (per v0.50)
            if self._config.on_before_observe is not None:
                try:
                    await _maybe_await(self._config.on_before_observe(self._state, result))
                except Exception as e:
                    yield {
                        "type": EVENT_OBSERVATION_ERROR,
                        "error": str(e),
                    }
            if result is not None and getattr(result, "data", None):
                data = result.data
                if isinstance(data, dict):
                    _state_update(self._state, data)

            # v0.50 observe callable (separate from on_*_observe hooks)
            if self._config.observe is not None:
                try:
                    observe_output = await _maybe_await(
                        self._config.observe(self._state, ctx)
                    )
                    if observe_output:
                        _state_update(self._state, dict(observe_output))
                except Exception as e:
                    yield {
                        "type": EVENT_OBSERVATION_ERROR,
                        "error": str(e),
                    }

            if self._config.on_after_observe is not None:
                try:
                    await _maybe_await(self._config.on_after_observe(self._state, result))
                except Exception as e:
                    yield {
                        "type": EVENT_OBSERVATION_ERROR,
                        "error": str(e),
                    }

            # 5. PERSIST: save state via hook
            if self._config.persist_state is not None:
                try:
                    await _maybe_await(
                        self._config.persist_state(self._state, round_idx),
                    )
                except Exception as e:
                    logger.debug("persist_state failed: %s", e)

            yield {
                "type": EVENT_ROUND_COMPLETE,
                "round": round_idx,
                "action": action_name,
            }

        # Terminal phase event (always emitted, per v0.50 compatibility)
        yield {
            "type": EVENT_PHASE,
            "phase": "done",
            "final_state": _state_snapshot(self._state),
        }

    def _check_timeout(self) -> bool:
        if not self._config.timeout_seconds:
            return False
        import time
        return (time.monotonic() - self._start_time) > self._config.timeout_seconds

    def _check_done(self) -> bool:
        try:
            return bool(self._config.done_condition(self._state))
        except Exception:
            return False


__all__ = [
    "ReactConfig",
    "ReactLoop",
    "ReActConfig",
    "ReActLoop",
    "EVENT_REASONING",
    "EVENT_ACTION_ERROR",
    "EVENT_OBSERVATION_ERROR",
    "EVENT_ROUND_COMPLETE",
    "EVENT_PHASE",
    "EVENT_TIMEOUT",
]


# v0.50 backward-compat aliases (ReActConfig/ReActLoop are the v0.50 names;
# ReactConfig/ReactLoop are the canonical Plan B v2 names).
ReActConfig = ReactConfig
ReActLoop = ReactLoop
ReActEngine = ReactLoop

# Re-export v0.50 Skill types so legacy imports work after
# the v0.50 archive is removed (B-7). v0.41 engine.py imports
# these names; their semantics are unchanged from apps/chat/skills/base.py.
SkillContext = SkillContext
SkillAction = SkillAction
SkillResult = SkillResult
