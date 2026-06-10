"""ReActEngine — unified ReAct (Reason → Act → Observe) engine.

This is the **single canonical** ReAct implementation for the
entire codebase.  It replaces the three parallel loops that
previously coexisted (the "Triple ReAct Loop" problem
identified in v0.33):

  1. ``ReactLoop``     (agent/react_loop.py)  — generic framework
  2. ``ResearchEngine._react_loop`` (apps/chat/engine.py) — research-specific
  3. ``apps/research/engine.py::ResearchEngine._react_loop`` — legacy

All three now delegate to this engine. ``ReactLoop`` is a thin
backward-compat wrapper; ``ResearchEngine`` in both ``apps/chat/``
and ``apps/research/`` builds a ``ReActConfig`` via
``_build_react_config()`` and drives ``ReActEngine.run()``.

Design goals
------------

- **Superset of ReactLoop**: everything ReactLoop does,
  ReActEngine does too, plus timeout, cancel/pause, and
  richer hooks.
- **Two action dispatch modes**:

  *Skill-action mode* (research, dream, etc.):
    ``config.actions`` lists ``SkillAction`` objects.
    The engine calls ``action.handler(state, ctx)``.

  *Custom handler mode* (chat):
    ``config.action_handler`` is an async callable
    ``(action_name, state, ctx, emit) → SkillResult``.
    The caller controls how actions are executed.

- **Streaming reason**: the ``reason`` callback receives an
  ``emit`` async callable so it can yield intermediate SSE
  events (e.g. streaming LLM tokens to the client) while
  deciding the next action.

- **Built-in timeout**: ``config.timeout_seconds`` is checked
  every round; emits ``EVENT_TIMEOUT`` and breaks.

- **Cancel / pause as first-class events**: the engine emits
  ``EVENT_PHASE`` with ``phase="cancelled"`` or
  ``phase="paused"`` and stops.

Exception policy
----------------

- **Reason** exceptions propagate (programming error).
- **Action** exceptions are caught → ``EVENT_ACTION_ERROR``,
  loop continues.
- **Observe** exceptions are caught → ``EVENT_OBSERVATION_ERROR``,
  loop continues.
- **Timeout** → ``EVENT_TIMEOUT``, loop breaks.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.skills.base import (
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Type aliases ────────────────────────────────────────────────

# Reason callable: (state, ctx, emit) → {action, thought}
# ``emit`` is an async callable that yields SSE events into the
# stream (used by chat to stream LLM tokens during reasoning).
ReasonCallable = Callable[
    [dict, SkillContext, Callable],
    Awaitable[dict],
]

# Observe callable: (state, ctx) → {observations: list[str]}
ObserveCallable = Callable[
    [dict, SkillContext],
    Awaitable[dict],
]

# Action handler (custom mode): (action_name, state, ctx, emit) → SkillResult
ActionHandler = Callable[
    [str, dict, SkillContext, Callable],
    Awaitable[SkillResult],
]

# Hook signatures
OnBeforeActHook = Callable[[dict, str], Any]
OnAfterActHook = Callable[[dict, str, SkillResult], Any]
OnBeforeObserveHook = Callable[[dict], Any]
OnAfterObserveHook = Callable[[dict], Any]
PersistStateHook = Callable[[dict, int], Any]
RestoreStateHook = Callable[[dict], dict]
DoneConditionHook = Callable[[dict], bool]


# ─── Event types ────────────────────────────────────────────────

EVENT_REASONING = "reasoning"
EVENT_ACTION_ERROR = "action_error"
EVENT_ROUND_COMPLETE = "round_complete"
EVENT_PHASE = "phase"
EVENT_OBSERVATION_ERROR = "observation_error"
EVENT_TIMEOUT = "timeout"


# ─── ReActConfig ────────────────────────────────────────────────


@dataclass
class ReActConfig:
    """Configuration for a ReAct engine instance.

    Required fields (3):
      ``actions``        — available SkillAction list (skill mode)
      ``initial_state``  — state dict at round 0
      ``reason``         — async (state, ctx, emit) → {action, thought}

    Optional fields:
      ``max_rounds``     — upper bound (default 10)
      ``done_condition`` — predicate: should the loop exit?
      ``timeout_seconds`` — 0 = no timeout (default 0)
      ``observe``        — async (state, ctx) → {observations}
      ``action_handler`` — custom action executor (chat mode)
      7 lifecycle hooks: on_before_act, on_after_act,
        on_before_observe, on_after_observe, persist_state,
        restore_state, reason_prompt

    Action dispatch modes
    ---------------------
    The engine supports two mutually exclusive action dispatch
    modes:

    1. **Skill-action mode** (default):
       ``actions`` is a non-empty list of ``SkillAction``.
       The engine looks up ``action_map[action_name]`` and
       calls ``.handler(state, ctx)``.

    2. **Custom handler mode**:
       ``action_handler`` is set.  ``actions`` may be empty
       (the handler decides what to do).  The engine calls
       ``action_handler(action_name, state, ctx, emit)``.
    """

    # ── Required (3) ────────────────────────────────────────
    actions: list[SkillAction]
    initial_state: dict
    reason: ReasonCallable

    # ── Control ─────────────────────────────────────────────
    max_rounds: int = 10
    done_condition: DoneConditionHook = field(
        default=lambda s: s.get("phase") == "done",
    )
    timeout_seconds: float = 0

    # ── Optional ────────────────────────────────────────────
    observe: ObserveCallable | None = None
    action_handler: ActionHandler | None = None
    reason_prompt: str = ""

    # ── Lifecycle hooks (7) ─────────────────────────────────
    on_before_act: OnBeforeActHook | None = None
    on_after_act: OnAfterActHook | None = None
    on_before_observe: OnBeforeObserveHook | None = None
    on_after_observe: OnAfterObserveHook | None = None
    persist_state: PersistStateHook | None = None
    restore_state: RestoreStateHook | None = None

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError(
                f"ReActConfig.max_rounds must be >= 1, got {self.max_rounds}"
            )
        if self.timeout_seconds < 0:
            raise ValueError(
                f"ReActConfig.timeout_seconds must be >= 0, got {self.timeout_seconds}"
            )
        if self.reason is None:
            raise ValueError("ReActConfig.reason is required")
        # Build action lookup (may be empty in custom handler mode).
        self._action_map: dict[str, SkillAction] = {
            a.name: a for a in self.actions
        }
        if self.actions and len(self._action_map) != len(self.actions):
            seen: set[str] = set()
            dups: set[str] = set()
            for a in self.actions:
                if a.name in seen:
                    dups.add(a.name)
                seen.add(a.name)
            raise ValueError(
                f"ReActConfig.actions has duplicate names: {sorted(dups)}"
            )

    @property
    def action_map(self) -> dict[str, SkillAction]:
        """Read-only view of name → SkillAction."""
        return dict(self._action_map)


# ─── ReActEngine ────────────────────────────────────────────────


class ReActEngine:
    """Unified ReAct loop executor.

    Construct with a ``ReActConfig``; call ``.run(ctx)`` to
    drive the loop.  ``run()`` is an async generator yielding
    structured events compatible with the SSE event contract.

    Each round:

      1. Timeout check → emit EVENT_TIMEOUT, break.
      2. Cancel/pause check → emit EVENT_PHASE, break.
      3. ``done_condition(state)`` → emit phase=done, break.
      4. ``reason(state, ctx, emit)`` → {action, thought}.
         The ``emit`` callable forwards SSE events from the
         reason callback into the stream (for streaming LLM
         output during reasoning).
      5. ``on_before_act(state, action_name)`` hook.
      6. Execute action (SkillAction.handler or action_handler).
         On exception → EVENT_ACTION_ERROR, continue.
      7. Merge ``result.data`` into state.
      8. ``on_after_act(state, action_name, result)`` hook.
      9. ``observe(state, ctx)`` → fold observations.
         On exception → EVENT_OBSERVATION_ERROR, continue.
     10. ``on_after_observe(state)`` hook.
     11. ``persist_state(state, round)`` hook.
     12. Emit round_complete.

    After the loop ends, emit a final ``phase=done`` event
    with ``final_state``.
    """

    def __init__(self, config: ReActConfig) -> None:
        self.config = config
        # Support both dict and dataclass states.
        # For dataclasses, keep the original instance (not a copy)
        # so mutations are visible to the caller.
        initial = config.initial_state
        if _is_dataclass(initial) and not isinstance(initial, dict):
            self.state = initial
        else:
            self.state = dict(initial)
        self._start_time: float = 0.0
        # Wrap reason for backward compat (2-arg → 3-arg signature)
        self._reason = _wrap_reason_for_compat(config.reason)

    # ── public API ──────────────────────────────────────────

    async def run(self, ctx: SkillContext) -> AsyncIterator[dict[str, Any]]:
        """Drive the ReAct loop, yielding SSE events."""
        self._start_time = time.monotonic()

        # Hook: restore state (resume scenario)
        if self.config.restore_state is not None:
            self.state = self.config.restore_state(self.state)

        action_map = self.config.action_map

        for round_idx in range(self.config.max_rounds):
            # ── 1. Timeout check ──
            if self.config.timeout_seconds > 0:
                elapsed = time.monotonic() - self._start_time
                if elapsed > self.config.timeout_seconds:
                    yield {
                        "type": EVENT_TIMEOUT,
                        "elapsed": elapsed,
                        "limit": self.config.timeout_seconds,
                        "round": round_idx,
                    }
                    yield {
                        "type": EVENT_PHASE,
                        "phase": "timeout",
                        "round": round_idx,
                        "final_state": _state_snapshot(self.state),
                    }
                    return

            # ── 2. Cancel / pause check ──
            if _state_get(self.state, "cancelled"):
                yield {
                    "type": EVENT_PHASE,
                    "phase": "cancelled",
                    "round": round_idx,
                    "final_state": _state_snapshot(self.state),
                }
                return
            if _state_get(self.state, "paused"):
                yield {
                    "type": EVENT_PHASE,
                    "phase": "paused",
                    "round": round_idx,
                    "final_state": _state_snapshot(self.state),
                }
                return

            # ── 3. Termination check ──
            if self.config.done_condition(self.state):
                yield {
                    "type": EVENT_PHASE,
                    "phase": "done",
                    "round": round_idx,
                    "reason": "done_condition",
                }
                break

            # ── 4. Reason: choose next action ──
            async def _emit(ev: dict[str, Any]) -> None:
                """Forward events from reason callback into the stream."""
                # We yield via a side-channel list because an async
                # generator cannot yield from inside a called coroutine.
                _pending_events.append(ev)

            _pending_events: list[dict[str, Any]] = []

            try:
                reason_output = await self._reason(
                    self.state, ctx, _emit,
                )
            except Exception as e:
                logger.error(
                    "Reason callable failed at round %d: %s",
                    round_idx, e, exc_info=True,
                )
                raise

            # Forward any events the reason callback emitted.
            for ev in _pending_events:
                yield ev
            _pending_events.clear()

            action_name = str(reason_output.get("action", ""))
            thought = str(reason_output.get("thought", ""))

            # Check if reason returned done
            if action_name == "done":
                yield {
                    "type": EVENT_REASONING,
                    "action": "done",
                    "thought": thought,
                    "round": round_idx,
                }
                yield {
                    "type": EVENT_PHASE,
                    "phase": "done",
                    "round": round_idx,
                    "reason": "reason_returned_done",
                }
                break

            yield {
                "type": EVENT_REASONING,
                "action": action_name,
                "thought": thought,
                "round": round_idx,
            }

            # ── 5. on_before_act hook ──
            if self.config.on_before_act is not None:
                try:
                    result = self.config.on_before_act(self.state, action_name)
                    if _isawaitable(result):
                        await result
                except Exception as e:
                    logger.warning(
                        "on_before_act hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 6. Act: invoke handler ──
            skill_result = await self._execute_action(
                action_name, action_map, ctx, _emit, round_idx,
            )

            if skill_result is None:
                # Action was skipped (unknown action or done).
                continue

            # Handle action failure sentinel
            if isinstance(skill_result, _ActionFailed):
                yield {
                    "type": EVENT_ACTION_ERROR,
                    "action": skill_result.action_name,
                    "error": str(skill_result.error),
                    "round": round_idx,
                }
                continue

            # Forward any events from action execution.
            for ev in _pending_events:
                yield ev
            _pending_events.clear()

            # ── 7. Merge result.data into state ──
            if skill_result.status == "ok" and skill_result.data:
                # Forward events from action handlers (collected by
                # _make_action_handler in ResearchEngine).
                nested_events = skill_result.data.pop("_events", None)
                if nested_events:
                    for ne in nested_events:
                        yield ne
                _state_update(self.state, skill_result.data)

            # ── 8. on_after_act hook ──
            if self.config.on_after_act is not None:
                try:
                    result = self.config.on_after_act(
                        self.state, action_name, skill_result,
                    )
                    if _isawaitable(result):
                        await result
                except Exception as e:
                    logger.warning(
                        "on_after_act hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 9-11. Observe step ──
            if self.config.observe is not None:
                if self.config.on_before_observe is not None:
                    try:
                        result = self.config.on_before_observe(self.state)
                        if _isawaitable(result):
                            await result
                    except Exception as e:
                        logger.warning(
                            "on_before_observe hook raised at round %d: %s",
                            round_idx, e, exc_info=True,
                        )

                try:
                    observe_output = await self.config.observe(self.state, ctx)
                except Exception as e:
                    logger.error(
                        "Observe callable failed at round %d: %s",
                        round_idx, e, exc_info=True,
                    )
                    yield {
                        "type": EVENT_OBSERVATION_ERROR,
                        "error": str(e),
                        "round": round_idx,
                    }
                else:
                    # Merge the full observe output into state (not
                    # just ``observations``). This allows custom
                    # observe callables to surface additional
                    # fields like ``observations_summary`` to the
                    # next reasoning step.
                    if observe_output:
                        _state_update(self.state, dict(observe_output))

                if self.config.on_after_observe is not None:
                    try:
                        result = self.config.on_after_observe(self.state)
                        if _isawaitable(result):
                            await result
                    except Exception as e:
                        logger.warning(
                            "on_after_observe hook raised at round %d: %s",
                            round_idx, e, exc_info=True,
                        )

            # ── 12. persist_state hook ──
            if self.config.persist_state is not None:
                try:
                    result = self.config.persist_state(self.state, round_idx)
                    if _isawaitable(result):
                        await result
                except Exception as e:
                    logger.warning(
                        "persist_state hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 13. round_complete ──
            yield {
                "type": EVENT_ROUND_COMPLETE,
                "round": round_idx,
                "action": action_name,
                "state_snapshot": _state_snapshot(self.state),
            }

        # Terminal event (always emitted)
        yield {
            "type": EVENT_PHASE,
            "phase": "done",
            "final_state": _state_snapshot(self.state),
        }

    # ── Action execution ────────────────────────────────────

    async def _execute_action(
        self,
        action_name: str,
        action_map: dict[str, SkillAction],
        ctx: SkillContext,
        emit: Callable,
        round_idx: int,
    ) -> SkillResult | _ActionFailed | None:
        """Execute an action and return the result.

        Returns None if the action was skipped, or _ActionFailed
        if the action raised an exception.
        """
        # Custom handler mode
        if self.config.action_handler is not None:
            try:
                result = await self.config.action_handler(
                    action_name, self.state, ctx, emit,
                )
                if isinstance(result, SkillResult):
                    return result
                if isinstance(result, dict):
                    return SkillResult.ok(result)
                logger.warning(
                    "action_handler returned %s for action %r",
                    type(result).__name__, action_name,
                )
                return None
            except Exception as e:
                logger.error(
                    "action_handler failed for %r at round %d: %s",
                    action_name, round_idx, e, exc_info=True,
                )
                return _ActionFailed(action_name, e)

        # Skill-action mode
        action = action_map.get(action_name)
        if action is None or action.handler is None:
            if action_name == "done":
                return None
            logger.warning(
                "Unknown action %r at round %d, skipping",
                action_name, round_idx,
            )
            return None

        try:
            result = action.handler(self.state, ctx)
            if _isawaitable(result):
                result = await result
            if isinstance(result, SkillResult):
                return result
            if isinstance(result, dict):
                return SkillResult.ok(result)
            logger.warning(
                "Action %r returned %s, expected SkillResult or dict",
                action_name, type(result).__name__,
            )
            return None
        except Exception as e:
            logger.error(
                "Action %r failed at round %d: %s",
                action_name, round_idx, e, exc_info=True,
            )
            return _ActionFailed(action_name, e)


# ─── Action failure sentinel ─────────────────────────────────


class _ActionFailed:
    """Internal sentinel returned by _execute_action on failure.

    Carries the action name and exception so the caller (run())
    can emit an ACTION_ERROR event and continue the loop.
    """

    __slots__ = ("action_name", "error")

    def __init__(self, action_name: str, error: Exception) -> None:
        self.action_name = action_name
        self.error = error


# ─── helpers ──────────────────────────────────────────────────


def _isawaitable(obj: Any) -> bool:
    """Return True if ``obj`` is awaitable."""
    return hasattr(obj, "__await__")


def _is_dataclass(obj: Any) -> bool:
    """Return True if ``obj`` is a dataclass instance."""
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


def _wrap_reason_for_compat(reason: ReasonCallable) -> ReasonCallable:
    """Wrap a 2-arg reason callback to accept the 3-arg (emit) signature.

    Existing callers (``research_skill.py``, ``reason_action.py``)
    define ``reason(state, ctx) → dict``.  The new ReActEngine
    calls ``reason(state, ctx, emit)``.  This wrapper bridges the
    gap by detecting the old signature and ignoring ``emit``.
    """
    try:
        sig = inspect.signature(reason)
        params = [
            p for p in sig.parameters.values()
            if p.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ]
        if len(params) <= 2:
            # Old 2-arg signature: wrap to accept (state, ctx, emit)
            async def _wrapped(
                state: dict, ctx: SkillContext, emit: Callable,
            ) -> dict:
                return await reason(state, ctx)  # type: ignore[misc]
            return _wrapped
    except (ValueError, TypeError):
        pass
    return reason


# ─── Backward-compatible type aliases ─────────────────────────

# These aliases let existing code that imports from react_loop
# continue to work after react_loop delegates to ReActEngine.
ReactConfig = ReActConfig
ReactLoop = ReActEngine


__all__ = [
    "ReActConfig",
    "ReActEngine",
    "ReactConfig",
    "ReactLoop",
    "ReasonCallable",
    "ObserveCallable",
    "ActionHandler",
    "OnBeforeActHook",
    "OnAfterActHook",
    "OnBeforeObserveHook",
    "OnAfterObserveHook",
    "PersistStateHook",
    "RestoreStateHook",
    "DoneConditionHook",
    "EVENT_REASONING",
    "EVENT_ACTION_ERROR",
    "EVENT_ROUND_COMPLETE",
    "EVENT_PHASE",
    "EVENT_OBSERVATION_ERROR",
    "EVENT_TIMEOUT",
]
