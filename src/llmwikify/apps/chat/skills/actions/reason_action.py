"""reason_skill — ReAct reasoning (decide next action).

  Action: ``reason(state)``
  Returns: ``{"action": str, "thought": str}``

The action_name is one of the actions registered in
SkillRegistry. The framework (apps/chat/agent/react_loop.py)
invokes this action in the Reason step of each ReAct round.

This is one of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1. The actual LLM-driven
reasoning lives in ``apps/research/engine.py::_llm_reason``
(Phase 6 will migrate it into this action's handler).

The Phase 5 implementation provides a **rule-based fallback**
that decides based on the state of the research. It is
deliberately simple so unit tests don't need a real LLM.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


def _rule_based_reason(state: dict) -> dict:
    """Rule-based fallback for reasoning.

    Decision tree (mimics the production LLM logic with
    simpler heuristics — good enough for unit tests and
    offline operation):

      1. If no sub_queries → "plan"
      2. If sub_queries but no sources → "gather"
      3. If sources but no synthesis → "analyze"
      4. If synthesis but no report → "synthesize"
      5. If report and score < 0.5 → "revise"
      6. Otherwise → "done"
    """
    if not state.get("sub_queries"):
        return {"action": "plan", "thought": "no sub_queries yet"}
    if not state.get("sources"):
        return {"action": "gather", "thought": "need sources for sub_queries"}
    if not state.get("analysis"):
        return {"action": "analyze", "thought": "analyze gathered sources"}
    if not state.get("synthesis"):
        return {"action": "synthesize", "thought": "synthesize analyzed claims"}
    if not state.get("report_md"):
        return {"action": "report", "thought": "write report from synthesis"}
    if state.get("score", 1.0) < 0.5:
        return {"action": "revise", "thought": "score below threshold"}
    return {"action": "done", "thought": "all phases complete"}


async def _reason(args: dict, ctx: SkillContext) -> SkillResult:
    """Decide the next ReAct action based on current state.

    Args:
        args: ``{"state": dict}`` — the research state
        ctx:  SkillContext (unused for rule-based; LLM uses ctx.llm_client)

    Returns:
        ``{"action": str, "thought": str}`` where action is one
        of the registered action names ("plan", "gather", etc.)
        or "done".
    """
    state = args.get("state", {})
    if not isinstance(state, dict):
        return SkillResult.fail("state must be a dict")
    # Phase 5: rule-based only. Phase 6 will try
    # ctx.llm_client first and fall back to rule-based.
    decision = _rule_based_reason(state)
    return SkillResult.ok(decision)


class ReasonSkill(Skill):
    """Action wrapper for ReAct reasoning (decide next action)."""

    name = "reason"
    description = "ReAct reasoning: decide the next action from current state"
    actions = {
        "reason_research": SkillAction(
            name="reason_research",
            description=(
                "Decide the next ReAct action based on the current "
                "state dict. Returns ``{action, thought}`` where "
                "action is one of the registered action names or "
                "'done'. The framework invokes this in the Reason "
                "step of every ReAct round."
            ),
            handler=_reason,
            input_schema={
                "type": "object",
                "properties": {
                    "state": {
                        "type": "object",
                        "description": (
                            "Current research state dict (sub_queries, "
                            "sources, synthesis, report_md, score, ...)"
                        ),
                    },
                },
                "required": ["state"],
            },
        ),
    }


reason_skill = ReasonSkill()


__all__ = ["ReasonSkill", "reason_skill", "_rule_based_reason"]
