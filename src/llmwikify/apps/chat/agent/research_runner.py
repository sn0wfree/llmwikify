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

from llmwikify.apps.chat.agent import events as chat_events
from llmwikify.apps.chat.skills.base import (
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.foundation.llm.errors import LLMError
from llmwikify.foundation.llm.streamable import LLMRequestError
from llmwikify.foundation.utils import maybe_await as _maybe_await
from llmwikify.kernel.agent.runtime import (
    PHASE_AFTER_REASON,
    RUNTIME,
    AgentPlan,
    RuntimeContext,
)

logger = logging.getLogger(__name__)


# ─── Event constants (compatible with v0.50) ──────────────────────


EVENT_REASONING = "reasoning"
EVENT_ACTION_ERROR = "action_error"
EVENT_OBSERVATION_ERROR = "observation_error"
EVENT_ROUND_COMPLETE = "round_complete"
EVENT_TIMEOUT = "timeout"

# The phase event is shared with the chat vocabulary — same wire name,
# same ``phase`` field; the research runner adds ``round`` / ``reason``
# / ``final_state`` on top (see the PHASE spec in ``events.py``).
EVENT_PHASE = chat_events.PHASE


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

        plan = _ResearchPlan(self, ctx, emit)
        runtime_ctx = RuntimeContext()
        async for event in RUNTIME.run_stream(runtime_ctx, plan):
            yield event

    def _check_timeout(self) -> bool:
        if not self._config.timeout_seconds:
            return False
        import time

        return (time.monotonic() - self._start_time) > self._config.timeout_seconds

    def _check_done(self) -> bool:
        try:
            return bool(self._config.done_condition(self._state))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning("done_condition raised %s: %s", type(e).__name__, e)
            return False
        except Exception:
            logger.exception("done_condition raised unexpected error")
            return False


# ─── The plan ───────────────────────────────────────────────────────


class _ResearchPlan(AgentPlan):
    """The research pipeline as a plan on the shared runtime.

    The stages are the old loop body, moved one for one — the event
    order, the error semantics and the hook calls are unchanged. Only
    the driver is shared now.
    """

    def __init__(
        self,
        loop: ReactLoop,
        ctx: Any,
        emit: Callable[[dict], Awaitable[None] | None] | None,
    ) -> None:
        self._loop = loop
        self._ctx = ctx
        self._emit = emit
        self.max_iterations = loop._config.max_rounds
        # The loop ended before it ran out of rounds — a terminal phase
        # event was emitted, or the reasoner failed. The old loop
        # returned in both cases without the closing "done" event, so
        # ``finalize`` must not add one.
        self._ended_early = False

    @property
    def _config(self) -> ReactConfig:
        return self._loop._config

    @property
    def _state(self) -> Any:
        return self._loop._state

    async def _emit_event(self, ev: dict) -> None:
        if self._emit is not None:
            await _maybe_await(self._emit(ev))

    # ── ROUND SETUP ───────────────────────────────────────────────

    async def before_iteration(self, ctx: Any) -> None:
        """Number the round and mirror it into the state."""
        self._loop._round = ctx.iteration
        _state_update(self._state, {"round": ctx.iteration})

    # ── PRECHECK ──────────────────────────────────────────────────

    async def precheck(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Timeout and done condition — both end the loop."""
        if self._loop._check_timeout():
            yield {"type": EVENT_PHASE, "phase": "timeout"}
            ctx.stop = True
            self._ended_early = True
            return
        if self._loop._check_done():
            yield {"type": EVENT_PHASE, "phase": "done"}
            ctx.stop = True
            self._ended_early = True
            return

    # ── REASON ────────────────────────────────────────────────────

    async def reason(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Ask the reasoner for the next action."""
        try:
            reason_fn = self._config.reason
            if reason_fn is None:
                decision = {"action": "done", "thought": "no reason fn"}
            else:
                # Wrap reason to accept (state, ctx) or (state, ctx, emit)
                # by inspecting the signature.
                sig = inspect.signature(reason_fn)
                n_params = sum(
                    1
                    for p in sig.parameters.values()
                    if p.kind
                    not in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    )
                )
                if n_params <= 2:
                    decision = await _maybe_await(reason_fn(self._state, self._ctx))
                else:
                    decision = await _maybe_await(
                        reason_fn(self._state, self._ctx, lambda e: None)
                    )
        except (LLMError, TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("reason failed")
            yield {
                "type": EVENT_ACTION_ERROR,
                "action": "<reason>",
                "error": str(e),
            }
            # The old loop returned here — no closing "done" event.
            self._ended_early = True
            return
        except Exception as e:
            logger.exception("reason failed with unexpected error")
            yield {
                "type": EVENT_ACTION_ERROR,
                "action": "<reason>",
                "error": str(e),
            }
            # The old loop returned here — no closing "done" event.
            self._ended_early = True
            return

        action_name = decision.get("action", "done")
        thought = decision.get("thought", "")
        reasoning_event = {
            "type": EVENT_REASONING,
            "thought": thought,
            "action": action_name,
            "round": ctx.iteration,
        }
        await self._emit_event(reasoning_event)
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

        ctx.decision = {"action": action_name, "thought": thought}

    # ── DECIDE after REASON ───────────────────────────────────────

    async def decide(
        self, ctx: Any, phase: str, payload: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """The reasoner may end the pipeline by itself."""
        if phase != PHASE_AFTER_REASON:
            return
        action_name = payload.get("action", "done")
        if action_name == "done":
            yield {
                "type": EVENT_PHASE,
                "phase": "done",
                "round": ctx.iteration,
                "reason": "reason_returned_done",
            }
            ctx.stop = True
            self._ended_early = True
            return
        if _state_get(self._state, "cancelled", False):
            yield {"type": EVENT_PHASE, "phase": "cancelled"}
            ctx.stop = True
            self._ended_early = True
            return
        if _state_get(self._state, "paused", False):
            yield {"type": EVENT_PHASE, "phase": "paused"}
            ctx.stop = True
            self._ended_early = True
            return

    # ── ACT ───────────────────────────────────────────────────────

    async def act(self, ctx: Any, decision: Any) -> AsyncIterator[dict[str, Any]]:
        """Run the action handler."""
        action_name = decision.get("action", "done")
        action = self._loop._action_map.get(action_name)
        if action is None:
            yield {
                "type": EVENT_ACTION_ERROR,
                "action": action_name,
                "error": f"Unknown action: {action_name}",
            }
            return

        # on_before_act hook
        if self._config.on_before_act is not None:
            await _maybe_await(
                self._config.on_before_act(self._state, action_name),
            )

        try:
            if hasattr(action, "handler"):
                result = await _maybe_await(action.handler(self._state, self._ctx))
            else:
                result = await _maybe_await(action(self._state, self._ctx))
        except (LLMError, LLMRequestError, OSError, ValueError, TypeError) as e:
            logger.warning("Action %s raised: %s", action_name, e, exc_info=True)
            yield {
                "type": EVENT_ACTION_ERROR,
                "action": action_name,
                "error": str(e),
            }
            return
        except Exception as e:
            logger.exception("Action %s raised unexpected error: %s", action_name, e)
            yield {
                "type": EVENT_ACTION_ERROR,
                "action": action_name,
                "error": str(e),
            }
            return

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

        ctx.result = result

    # ── OBSERVE ───────────────────────────────────────────────────

    async def observe(
        self, ctx: Any, result: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Fold the result into the state."""
        if self._config.on_before_observe is not None:
            try:
                await _maybe_await(
                    self._config.on_before_observe(self._state, result)
                )
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
                    self._config.observe(self._state, self._ctx)
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
                await _maybe_await(
                    self._config.on_after_observe(self._state, result)
                )
            except Exception as e:
                yield {
                    "type": EVENT_OBSERVATION_ERROR,
                    "error": str(e),
                }

    # ── PERSIST + round_complete ─────────────────────────────────

    async def after_iteration(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Save the state, then close the round."""
        if self._config.persist_state is not None:
            try:
                await _maybe_await(
                    self._config.persist_state(self._state, ctx.iteration),
                )
            except Exception as e:
                logger.debug("persist_state failed: %s", e)

        yield {
            "type": EVENT_ROUND_COMPLETE,
            "round": ctx.iteration,
            "action": (ctx.decision or {}).get("action", ""),
        }

    # ── FINALIZE ──────────────────────────────────────────────────

    async def finalize(self, ctx: Any) -> AsyncIterator[dict[str, Any]]:
        """The terminal phase event (unless one was already emitted)."""
        if not self._ended_early:
            yield {
                "type": EVENT_PHASE,
                "phase": "done",
                "final_state": _state_snapshot(self._state),
            }


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
