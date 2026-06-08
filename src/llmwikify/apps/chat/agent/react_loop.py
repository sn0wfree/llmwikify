"""Generic ReAct loop framework.

This is a **Python framework**, not a skill. It does not
appear in the SkillRegistry and is not exposed to the LLM
as a tool. It is the engine that drives any ReAct-style
orchestration — research, dream, dream_editor's incremental
edits, future data-analysis, future code-generation — by
combining:

  - a Reason callable (decides the next action),
  - an Act set (the actions available for execution),
  - an Observe callable (interprets the new state),
  - 7 lifecycle hooks (before/after Act, before/after
    Observe, restore/persist state, max rounds, done check).

The design refactors the existing
``apps/research/engine.py:255 _react_loop`` (112 LOC) into a
configurable 100-LOC framework. The research_skill (Phase 6)
becomes a thin wrapper that builds a ``ReactConfig`` and
delegates to ``ReactLoop.run()``.

Why this lives in apps/chat/agent/ (not apps/chat/skills/)
----------------------------------------------------------------

  - It is **not a skill**: it has no ``name``, no LLM-facing
    manifest, no actions. It is infrastructure.
  - It is a **chat-level agent** primitive: the chat layer
    reuses research/agent per the 4-layer
    ``chat-uses-research-and-agent`` contract. The ReAct
    framework is a shared tool across the chat's sub-skills
    (research, dream, dream_editor, future planners).
  - It does **not** import from apps/research/ (no
    cycles). The research_skill (Phase 6) imports THIS
    module and feeds it a config built from the research
    state machine.

Field summary (13 total, all customizable):

  Required (4):
    - ``actions``       — Act step's available SkillAction list
    - ``initial_state`` — state dict at round 0
    - ``done_condition``— predicate: should the loop exit?
    - ``reason``        — callable (state, ctx) -> {action, thought}

  Optional (9):
    - ``max_rounds``    — upper bound (default 10)
    - ``observe``       — callable (state, ctx) -> {observations}
    - ``reason_prompt`` — metadata string for the reason callable
    - ``on_before_act``  — hook: state, action_name
    - ``on_after_act``   — hook: state, action_name, SkillResult
    - ``on_before_observe`` — hook: state
    - ``on_after_observe``  — hook: state
    - ``persist_state``  — hook: state, round
    - ``restore_state``  — hook: state -> state (overrides initial)
"""

from __future__ import annotations

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


# ─── Type aliases ────────────────────────────────────────────────

# Reason returns a dict with at least {action, thought}.
# action is a string (matches one of actions[].name); thought
# is the LLM's "Thought" trace shown in the reasoning event.
ReasonCallable = Callable[[dict, SkillContext], Awaitable[dict]]

# Observe returns a dict with at least {observations: list[str]}.
# The framework folds this into state["observations"].
ObserveCallable = Callable[[dict, SkillContext], Awaitable[dict]]

# Hook signatures
OnBeforeActHook = Callable[[dict, str], None]
OnAfterActHook = Callable[[dict, str, SkillResult], None]
OnBeforeObserveHook = Callable[[dict], None]
OnAfterObserveHook = Callable[[dict], None]
PersistStateHook = Callable[[dict, int], None]
RestoreStateHook = Callable[[dict], dict]
DoneConditionHook = Callable[[dict], bool]


# ─── Event types (yielded by run()) ─────────────────────────────


EVENT_REASONING = "reasoning"      # before Act: thought + chosen action
EVENT_ACTION_ERROR = "action_error"  # action raised
EVENT_ROUND_COMPLETE = "round_complete"  # after successful round
EVENT_PHASE = "phase"               # {phase: "done"} sentinels
EVENT_OBSERVATION_ERROR = "observation_error"  # observe callable failed


# ─── ReactConfig ────────────────────────────────────────────────


@dataclass
class ReactConfig:
    """13-field ReAct loop configuration.

    All 4 required fields are positional/keyword-arg only;
    the 9 optional fields have safe defaults so a minimal
    config is::

        ReactConfig(
            actions=[...],
            initial_state={...},
            done_condition=lambda s: s.get("done"),
            reason=my_reason_fn,
        )

    The framework does no schema validation on the state
    dict (the act-step handlers receive the entire state and
    are free to pick what they need). The ``actions`` list
    is the only structured input; the rest is metadata for
    hooks.
    """

    # ── Required (4) ────────────────────────────────────────
    actions: list[SkillAction]
    initial_state: dict
    done_condition: DoneConditionHook
    reason: ReasonCallable

    # ── Optional (9) ────────────────────────────────────────
    max_rounds: int = 10
    observe: ObserveCallable | None = None
    reason_prompt: str = ""
    on_before_act: OnBeforeActHook | None = None
    on_after_act: OnAfterActHook | None = None
    on_before_observe: OnBeforeObserveHook | None = None
    on_after_observe: OnAfterObserveHook | None = None
    persist_state: PersistStateHook | None = None
    restore_state: RestoreStateHook | None = None

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("ReactConfig.actions must be non-empty")
        if self.max_rounds < 1:
            raise ValueError(
                f"ReactConfig.max_rounds must be >= 1, got {self.max_rounds}"
            )
        if self.done_condition is None:
            raise ValueError("ReactConfig.done_condition is required")
        if self.reason is None:
            raise ValueError("ReactConfig.reason is required")
        # Build the action lookup once.
        self._action_map: dict[str, SkillAction] = {
            a.name: a for a in self.actions
        }
        # Detect duplicate action names early.
        if len(self._action_map) != len(self.actions):
            seen: set[str] = set()
            dups: set[str] = set()
            for a in self.actions:
                if a.name in seen:
                    dups.add(a.name)
                seen.add(a.name)
            raise ValueError(
                f"ReactConfig.actions has duplicate names: {sorted(dups)}"
            )

    @property
    def action_map(self) -> dict[str, SkillAction]:
        """Read-only view of name → SkillAction (built in __post_init__)."""
        return dict(self._action_map)


# ─── ReactLoop ──────────────────────────────────────────────────


class ReactLoop:
    """Configurable ReAct loop executor.

    Construct with a ``ReactConfig``; call ``.run(ctx)`` to
    drive the loop. ``run()`` is an async generator yielding
    structured events the caller can stream to clients
    (SSE, WebSocket, etc.) or log.

    Each round:

      1. Check ``done_condition(state)`` → emit phase=done, break.
      2. ``reason(state, ctx)`` → choose action_name, emit reasoning.
      3. ``on_before_act(state, action_name)`` hook.
      4. Look up action in config.action_map; invoke handler.
         On exception: emit action_error, continue to next round.
      5. Merge result.data into state (only if status == "ok").
      6. ``on_after_act(state, action_name, result)`` hook
         (gate intervention happens here).
      7. ``on_before_observe(state)`` hook.
      8. ``observe(state, ctx)`` → fold observations into state.
         On exception: emit observation_error, continue.
      9. ``on_after_observe(state)`` hook.
     10. ``persist_state(state, round)`` hook.
     11. Emit round_complete.

    After the loop ends (either done, max_rounds, or external
    stop), emit a final phase=done event with ``final_state``.

    Exception policy
    ----------------
    - Reason callable exceptions propagate (these are
      programming errors; the user must fix the reason
      function).
    - Action handler exceptions are caught and surfaced as
      ``action_error`` events; the loop continues.
    - Observe callable exceptions are caught and surfaced as
      ``observation_error`` events; the loop continues.

    This split matches the existing ``apps/research/engine.py
    _react_loop`` behavior (line 1303-1306 in the design).
    """

    def __init__(self, config: ReactConfig) -> None:
        self.config = config
        # Shallow copy so caller mutations of initial_state
        # after construction don't leak into the loop.
        self.state: dict = dict(config.initial_state)

    # ── public API ──────────────────────────────────────────

    async def run(self, ctx: SkillContext) -> AsyncIterator[dict[str, Any]]:
        """Drive the loop, yielding events for each step.

        Always emits a final ``{"type": "phase", "phase": "done",
        "final_state": ...}`` event before returning, so the
        caller can rely on a terminal signal.
        """
        # Hook: restore state (resume scenario)
        if self.config.restore_state is not None:
            self.state = self.config.restore_state(self.state)

        action_map = self.config.action_map

        for round_idx in range(self.config.max_rounds):
            # ── 1. Termination check ──
            if self.config.done_condition(self.state):
                yield {
                    "type": EVENT_PHASE,
                    "phase": "done",
                    "round": round_idx,
                    "reason": "done_condition",
                }
                break

            # ── 2. Reason: choose next action ──
            try:
                reason_output = await self.config.reason(self.state, ctx)
            except Exception as e:
                logger.error(
                    "Reason callable failed at round %d: %s", round_idx, e,
                    exc_info=True,
                )
                raise

            action_name = str(reason_output.get("action", ""))
            thought = str(reason_output.get("thought", ""))
            yield {
                "type": EVENT_REASONING,
                "action": action_name,
                "thought": thought,
                "round": round_idx,
            }

            # ── 3. on_before_act hook ──
            if self.config.on_before_act is not None:
                try:
                    self.config.on_before_act(self.state, action_name)
                except Exception as e:
                    logger.warning(
                        "on_before_act hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 4. Act: invoke handler ──
            action = action_map.get(action_name)
            if action is None or action.handler is None:
                # Reason may pick an action not in the config
                # (e.g. "done"). Skip silently.
                if action_name == "done":
                    yield {
                        "type": EVENT_PHASE,
                        "phase": "done",
                        "round": round_idx,
                        "reason": "reason_returned_done",
                    }
                    break
                logger.warning(
                    "Unknown action %r at round %d, skipping",
                    action_name, round_idx,
                )
                continue

            try:
                result = action.handler(self.state, ctx)
                if _isawaitable(result):
                    result = await result  # type: ignore[assignment]
                # Normalize: handler may return SkillResult or a dict
                if isinstance(result, SkillResult):
                    skill_result: SkillResult = result
                elif isinstance(result, dict):
                    skill_result = SkillResult.ok(result)
                else:
                    logger.warning(
                        "Action %r returned %s, expected SkillResult or dict",
                        action_name, type(result).__name__,
                    )
                    continue
            except Exception as e:
                logger.error(
                    "Action %r failed at round %d: %s",
                    action_name, round_idx, e, exc_info=True,
                )
                yield {
                    "type": EVENT_ACTION_ERROR,
                    "action": action_name,
                    "error": str(e),
                    "round": round_idx,
                }
                continue

            # ── 5. Merge result.data into state ──
            if skill_result.status == "ok" and skill_result.data:
                self.state.update(skill_result.data)

            # ── 6. on_after_act hook (gate intervention) ──
            if self.config.on_after_act is not None:
                try:
                    self.config.on_after_act(self.state, action_name, skill_result)
                except Exception as e:
                    logger.warning(
                        "on_after_act hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 7-9. Observe step (optional) ──
            if self.config.observe is not None:
                if self.config.on_before_observe is not None:
                    try:
                        self.config.on_before_observe(self.state)
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
                    observations = observe_output.get("observations")
                    if observations is not None:
                        self.state["observations"] = observations

                if self.config.on_after_observe is not None:
                    try:
                        self.config.on_after_observe(self.state)
                    except Exception as e:
                        logger.warning(
                            "on_after_observe hook raised at round %d: %s",
                            round_idx, e, exc_info=True,
                        )

            # ── 10. persist_state hook ──
            if self.config.persist_state is not None:
                try:
                    self.config.persist_state(self.state, round_idx)
                except Exception as e:
                    logger.warning(
                        "persist_state hook raised at round %d: %s",
                        round_idx, e, exc_info=True,
                    )

            # ── 11. round_complete ──
            yield {
                "type": EVENT_ROUND_COMPLETE,
                "round": round_idx,
                "action": action_name,
                "state_snapshot": dict(self.state),
            }

        # Terminal event (always emitted, even on max_rounds exit)
        yield {
            "type": EVENT_PHASE,
            "phase": "done",
            "final_state": dict(self.state),
        }


# ─── helpers ──────────────────────────────────────────────────


def _isawaitable(obj: Any) -> bool:
    """Return True if ``obj`` is awaitable (coroutine, Future, Task)."""
    return hasattr(obj, "__await__")


__all__ = [
    "ReactConfig",
    "ReactLoop",
    "ReasonCallable",
    "ObserveCallable",
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
]
