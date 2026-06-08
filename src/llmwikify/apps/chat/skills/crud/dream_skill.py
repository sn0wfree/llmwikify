"""dream_skill — CRUD: run/get_proposals/approve/reject dream proposals.

Thin wrapper around ``apps/agent/dream_editor/`` (DreamEditor +
ProposalManager). The editor is passed via
``ctx.config['dream_editor']``.

Actions:

  - ``run()`` — run the dream engine, generate new proposals
  - ``get_proposals(status)`` — list proposals (pending/approved/rejected)
  - ``approve(proposal_id)`` — approve a pending proposal
  - ``reject(proposal_id, reason)`` — reject a pending proposal

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#31)
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


def _get_editor(ctx: SkillContext) -> Any | SkillResult:
    editor = ctx.config.get("dream_editor") if ctx.config else None
    if editor is None:
        return SkillResult.fail("dream_editor not configured in ctx.config")
    return editor


# ─── Action handlers ──────────────────────────────────────────────


async def _run(args: dict, ctx: SkillContext) -> SkillResult:
    editor = _get_editor(ctx)
    if isinstance(editor, SkillResult):
        return editor
    try:
        result = editor.run_dream()
        return SkillResult.ok(result)
    except Exception as e:
        return SkillResult.fail(f"dream run failed: {e!r}")


async def _get_proposals(args: dict, ctx: SkillContext) -> SkillResult:
    editor = _get_editor(ctx)
    if isinstance(editor, SkillResult):
        return editor
    status = args.get("status", "pending")
    try:
        proposals = editor.proposals.get_proposals(status=status)
        return SkillResult.ok({"proposals": proposals, "count": len(proposals)})
    except Exception as e:
        return SkillResult.fail(f"get_proposals failed: {e!r}")


async def _approve(args: dict, ctx: SkillContext) -> SkillResult:
    editor = _get_editor(ctx)
    if isinstance(editor, SkillResult):
        return editor
    pid = args.get("proposal_id", "")
    if not pid:
        return SkillResult.fail("proposal_id is required")
    try:
        ok = editor.proposals.approve(pid)
        if not ok:
            return SkillResult.fail(f"proposal {pid!r} not found or not pending")
        return SkillResult.ok({"approved": True, "proposal_id": pid})
    except Exception as e:
        return SkillResult.fail(f"approve failed: {e!r}")


async def _reject(args: dict, ctx: SkillContext) -> SkillResult:
    editor = _get_editor(ctx)
    if isinstance(editor, SkillResult):
        return editor
    pid = args.get("proposal_id", "")
    if not pid:
        return SkillResult.fail("proposal_id is required")
    reason = args.get("reason", "")
    try:
        ok = editor.proposals.reject(pid, reason=reason)
        if not ok:
            return SkillResult.fail(f"proposal {pid!r} not found or not pending")
        return SkillResult.ok({"rejected": True, "proposal_id": pid, "reason": reason})
    except Exception as e:
        return SkillResult.fail(f"reject failed: {e!r}")


# ─── Skill declaration ─────────────────────────────────────────


class DreamSkill(Skill):
    """CRUD: run/get_proposals/approve/reject dream proposals."""

    name = "dream"
    description = "Manage dream proposals (run engine, approve/reject proposals)"
    actions = {
        "run": SkillAction(
            name="run",
            description="Run the dream engine to generate new edit proposals",
            handler=_run,
            input_schema={"type": "object", "properties": {}},
            action_type="write",
        ),
        "get_proposals": SkillAction(
            name="get_proposals",
            description="List dream proposals filtered by status",
            handler=_get_proposals,
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter: 'pending' (default), 'approved', 'rejected', or 'all'",
                        "default": "pending",
                    },
                },
            },
        ),
        "approve": SkillAction(
            name="approve",
            description="Approve a pending dream proposal",
            handler=_approve,
            input_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Proposal ID to approve"},
                },
                "required": ["proposal_id"],
            },
            action_type="write",
        ),
        "reject": SkillAction(
            name="reject",
            description="Reject a pending dream proposal with a reason",
            handler=_reject,
            input_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Proposal ID to reject"},
                    "reason": {"type": "string", "description": "Rejection reason"},
                },
                "required": ["proposal_id"],
            },
            action_type="write",
        ),
    }


dream_skill = DreamSkill()


__all__ = ["DreamSkill", "dream_skill"]
