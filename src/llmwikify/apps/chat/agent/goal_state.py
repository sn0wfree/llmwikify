"""Goal state — sustained per-session objective (Phase 8).

Borrowed from nanobot v0.2.1 ``session/goal_state.py`` (see
``docs/poc/nanobot-framework.md`` §3 for the long-goal skill rationale)
but adapted to llmwikify:

  - Source of truth is the ``metadata`` JSON column on ``chat_sessions``
    (added in this Phase 8 migration), NOT a ``Session.metadata`` dict.
  - Reads / writes go through :class:`ChatSessionRepository` so the
    same SQLite connection / write path is used by all callers.
  - System prompt injection lives in ``PromptBuilder`` (it queries
    :func:`goal_state_runtime_lines` once per build).

Lifecycle (mirrors nanobot ``long_task`` / ``complete_goal``):

  1. ``goal.start_long_task`` writes ``{status: "active", objective,
     ui_summary, started_at}`` to session metadata.
  2. Each chat turn the PromptBuilder appends
     ``goal_state_runtime_lines`` so compaction cannot hide it.
  3. ``goal.complete_goal`` flips status to ``"completed"`` and stores
     ``completed_at`` + ``recap``.

Phase 8 (2026-06-20). See AGENTS.md "AutoResearch / Track B" guidance
for why long-running research benefits from persisted objectives.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

GOAL_STATE_KEY = "goal_state"
_MAX_OBJECTIVE_IN_RUNTIME = 4000


def parse_goal_state(blob: Any) -> dict[str, Any] | None:
    """Best-effort parse of a stored goal blob into a dict.

    Accepts ``None`` (no goal), a ``dict`` (already parsed), or a JSON
    string. Returns ``None`` for any malformed input so callers can
    treat "no active goal" and "corrupt blob" the same way.
    """
    if blob is None:
        return None
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def goal_state_raw(metadata: Mapping[str, Any] | None) -> Any:
    """Return the raw goal blob from session metadata or ``None``."""
    if not metadata:
        return None
    return metadata.get(GOAL_STATE_KEY)


def sustained_goal_active(metadata: Mapping[str, Any] | None) -> bool:
    """True when this session has an active sustained objective."""
    goal = parse_goal_state(goal_state_raw(metadata))
    return isinstance(goal, dict) and goal.get("status") == "active"


def goal_state_runtime_lines(metadata: Mapping[str, Any] | None) -> list[str]:
    """Lines appended inside the system prompt when a goal is active.

    Format mirrors nanobot's Runtime Context block::

        Goal (active):
        <objective text, truncated to 4000 chars>
        Summary: <ui_summary if present>

    Returns an empty list when no active goal exists.
    """
    if not metadata:
        return []
    goal = parse_goal_state(goal_state_raw(metadata))
    if not isinstance(goal, dict) or goal.get("status") != "active":
        return []
    objective = str(goal.get("objective") or "").strip()
    if not objective:
        return ["Goal: active (no objective text stored)."]
    if len(objective) > _MAX_OBJECTIVE_IN_RUNTIME:
        objective = objective[:_MAX_OBJECTIVE_IN_RUNTIME].rstrip() + "\n… (truncated)"
    out = ["Goal (active):", objective]
    hint = str(goal.get("ui_summary") or "").strip()
    if hint:
        out.append(f"Summary: {hint}")
    return out


def goal_state_summary(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compact JSON-safe view used by UI / API endpoints.

    Returns ``{"active": False}`` when there is no active goal so
    callers can rely on the ``active`` key existing.
    """
    goal = parse_goal_state(goal_state_raw(metadata)) if metadata else None
    if not isinstance(goal, dict) or goal.get("status") != "active":
        return {"active": False}
    objective = str(goal.get("objective") or "").strip()
    summary = str(goal.get("ui_summary") or "").strip()[:120]
    out: dict[str, Any] = {"active": True}
    if objective:
        out["objective"] = (
            objective[:600].rstrip() + "…" if len(objective) > 600 else objective
        )
    if summary:
        out["ui_summary"] = summary
    started_at = goal.get("started_at")
    if started_at:
        out["started_at"] = started_at
    return out


__all__ = [
    "GOAL_STATE_KEY",
    "parse_goal_state",
    "goal_state_raw",
    "sustained_goal_active",
    "goal_state_runtime_lines",
    "goal_state_summary",
]
