"""subagent_skill — Phase 10-E LLM-facing tool wrapping SubagentManager.

Borrowed from nanobot v0.2.1 ``agent/subagent.py`` skill surface. The
parent LLM calls ``spawn_subagent(goal=..., max_iterations=...)`` to
delegate a sub-task to an in-process child runner; the child returns
its ``final_content`` plus telemetry, and the parent decides what to
do with the answer.

The :class:`SubagentManager` instance must be supplied via
``ctx.config['subagent_manager']``. The orchestrator wires this
attachment lazily (managers are created the first time chat starts —
they hold a ref to the parent runner). If the attachment is missing
the action returns a :meth:`SkillResult.fail` instead of crashing.

Why this is a separate skill (not co-located with goal_skill):

  - goal_skill operates on session metadata (DB state)
  - this skill spawns a *runtime* (LLM + tools) and returns text
  - keeping them apart makes the LLM tool surface easier to reason
    about and lets us register only one or the other in restricted
    deployments.
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


_DEFAULT_MAX_ITERATIONS = 5
_HARD_MAX_ITERATIONS = 10
_HARD_MAX_TIMEOUT_SECONDS = 300.0


def _get_manager(ctx: SkillContext) -> Any | SkillResult:
    mgr = ctx.config.get("subagent_manager") if ctx.config else None
    if mgr is None:
        return SkillResult.fail(
            "subagent_manager not configured in ctx.config; "
            "the orchestrator did not wire the SubagentManager.",
        )
    return mgr


def _resolve_tool_registry(ctx: SkillContext, drop_subagent: bool) -> Any:
    """Pick the tool registry exposed to the child.

    Prefers ``ctx.config['child_tool_registry']`` (parent-supplied
    explicit child surface), falling back to the parent's own
    registry minus ``spawn_subagent`` (defensive: keeps children
    from spawning grandchildren). ``drop_subagent`` is honoured even
    in the fallback path.
    """
    if ctx.config:
        explicit = ctx.config.get("child_tool_registry")
        if explicit is not None:
            return explicit
    parent_registry = (
        ctx.config.get("tool_registry") if ctx.config else None
    )
    if parent_registry is None:
        return None
    if drop_subagent and hasattr(parent_registry, "without"):
        try:
            return parent_registry.without("spawn_subagent")
        except Exception:
            return parent_registry
    return parent_registry


async def _spawn_subagent(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr

    goal = (args.get("goal") or "").strip()
    if not goal:
        return SkillResult.fail("goal is required")
    if len(goal) > 4000:
        return SkillResult.fail(
            f"goal too long ({len(goal)} chars); keep ≤4000",
        )

    max_iterations = int(args.get("max_iterations", _DEFAULT_MAX_ITERATIONS))
    if max_iterations < 1:
        max_iterations = 1
    if max_iterations > _HARD_MAX_ITERATIONS:
        max_iterations = _HARD_MAX_ITERATIONS

    timeout_seconds = float(args.get("timeout_seconds", 120.0))
    if timeout_seconds <= 0:
        timeout_seconds = 120.0
    if timeout_seconds > _HARD_MAX_TIMEOUT_SECONDS:
        timeout_seconds = _HARD_MAX_TIMEOUT_SECONDS

    parent_session_id = ctx.session_id or args.get("parent_session_id") or ""
    if not parent_session_id:
        return SkillResult.fail(
            "parent_session_id is required (ctx.session_id was empty)",
        )

    from llmwikify.apps.chat.agent.subagent_manager import SubagentSpec

    spec = SubagentSpec(
        goal=goal,
        initial_messages=[{"role": "user", "content": goal}],
        tool_registry=_resolve_tool_registry(ctx, drop_subagent=True),
        parent_session_id=parent_session_id,
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
    )

    result = await mgr.run(spec)
    payload = {
        "status": result.status,
        "final_content": result.final_content or "",
        "tools_used": result.tools_used,
        "usage": result.usage,
        "stop_reason": result.stop_reason,
    }
    if result.status == "ok":
        return SkillResult.ok(payload)
    return SkillResult.fail(
        result.error or f"subagent ended with status={result.status}",
        **payload,
    )


_SPAWN_DESCRIPTION = (
    "Spawn an isolated child assistant to investigate a sub-goal "
    "in detail. Use when you need to dig deep into one specific "
    "topic without polluting the main conversation. The child "
    "runs in-process with its own messages / tools / budget and "
    "returns a single final_content string. The child cannot "
    "spawn grandchildren. Pick max_iterations conservatively "
    "(default 5, hard cap 10)."
)


class SubagentSkill(Skill):
    """LLM-facing wrapper around :class:`SubagentManager`."""

    name = "subagent"
    description = (
        "Spawn isolated in-process child assistants for sub-goals."
    )
    actions = {
        "spawn_subagent": SkillAction(
            name="spawn_subagent",
            description=_SPAWN_DESCRIPTION,
            handler=_spawn_subagent,
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": (
                            "One-line objective for the child "
                            "(≤4000 chars). State desired output, "
                            "boundaries, and done-ness."
                        ),
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": (
                            "Child runner iteration cap. "
                            "Default 5, hard cap 10."
                        ),
                        "minimum": 1,
                        "maximum": _HARD_MAX_ITERATIONS,
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": (
                            "Soft timeout for the child run. "
                            "Default 120s, hard cap "
                            f"{_HARD_MAX_TIMEOUT_SECONDS}s."
                        ),
                    },
                },
                "required": ["goal"],
            },
            action_type="write",
        ),
    }


subagent_skill = SubagentSkill()


__all__ = ["SubagentSkill", "subagent_skill"]
