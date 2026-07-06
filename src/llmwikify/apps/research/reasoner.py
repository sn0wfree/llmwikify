"""Research Reasoner — ReAct Thought step.

Phase 2 #5 / C1 — extracted from ResearchEngine (885 LOC
monolith) to ``reasoner.py``. The Reasoner encapsulates the
3 methods that decide the next action in the ReAct loop:

  - ``reason(state)``         — async entry point (LLM first,
                                 rule-based fallback)
  - ``rule_based(state)``     — deterministic fallback decision
  - ``_llm_reason(state)``    — LLM-based reasoning via run_prompt

The engine keeps 1-line delegator methods
(``_reason`` / ``_rule_based_reason`` / ``_llm_reason``) for
backward compatibility with existing tests and any external
callers that reach into the engine internals.

Architecture:
  ┌──────────────────────────────────────────────────────────┐
  │  ResearchEngine                                          │
  │  ├─ self.reasoner = ResearchReasoner(self)               │
  │  ├─ _reason(state)       → self.reasoner.reason(state)  │
  │  ├─ _rule_based_reason() → self.reasoner.rule_based()   │
  │  └─ _llm_reason(state)   → self.reasoner._llm_reason()  │
  └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .llm_step import run_prompt

if TYPE_CHECKING:
    from llmwikify.apps.chat.state import ResearchState

    from .engine import ResearchEngine

logger = logging.getLogger(__name__)

# Set of actions the reasoner is allowed to return. Anything
# outside this set falls back to ``done`` (safe default).
VALID_ACTIONS: set[str] = {
    "plan", "gather", "analyze", "synthesize",
    "report", "review", "revise", "done",
}


class ResearchReasoner:
    """ReAct Thought step — decide the next action.

    The Reasoner composes two strategies:
      1. LLM-based reasoning (primary) — uses ``run_prompt`` with
         the ``research_reason`` prompt template. The LLM returns
         ``{action, thought}`` after a chain-of-thought pass.
      2. Rule-based reasoning (fallback) — deterministic decision
         tree based on ``state.phase``, ``state.sub_queries``,
         ``state.sources``, ``state.synthesis``, etc.

    The async entry point ``reason()`` tries LLM first, falls
    back to rules on persistent LLM failure. The LLM path itself
    has a defensive fallback (the YAML template may emit the
    sentinel ``__rule_based__``) which routes through
    ``rule_based()`` for parity with the legacy code path.
    """

    def __init__(self, engine: ResearchEngine):
        self._engine = engine
        # Cached for direct access in hot paths.
        self._db = engine.db
        self._config = engine.config
        self._action_ctx = engine._action_ctx
        self._max_replan = engine._max_replan

    async def reason(self, state: ResearchState) -> str:
        """Decide the next action based on current state.

        Returns one of: ``plan`` / ``gather`` / ``analyze`` /
        ``synthesize`` / ``report`` / ``review`` / ``revise`` /
        ``done``.

        LLM-based reasoning is attempted first. On failure,
        falls back to the deterministic rule-based decision
        tree. The LLM path also has a defensive ``__rule_based__``
        sentinel that routes back here for parity.
        """
        try:
            return await self._llm_reason(state)
        except Exception as e:
            logger.warning(
                "LLM reasoning failed: %s, using rule-based fallback", e
            )
            return self.rule_based(state) or "done"

    def rule_based(self, state: ResearchState) -> str | None:
        """Deterministic decision tree as fallback.

        Walks the state in canonical order:
          error → done
          consecutive plan loop break → gather (or report) (anti-spin)
          no clarification → plan (defensive; normally
                              handled before the loop)
          no sub-queries → plan
          ungathered sub-queries → gather
          unanalyzed sources → analyze
          no synthesis → synthesize
          knowledge gaps + budget → replan
          no report → report
          no review → review
          review approved → done
          review failed + rounds left → revise
          else → done

        Anti-spin guard:
            When the same state has been returning ``plan`` for
            ``_max_replan`` consecutive rounds, the next ``plan``
            decision is suppressed. Control falls through to the
            gather/analyze/synthesize/report cascade so the engine
            makes forward progress. Without this, the engine spins
            on the planning→planning transition and the UI looks
            frozen.
        """
        # Error state → done (let LLM override if it wants to retry)
        if state.phase == "error":
            return "done"

        # ─── 6-step framework: if no clarification yet, redo clarify ───
        if state.clarification is None:
            return "plan"  # In the new flow this path is unreachable
                           # (clarify runs before the loop) but keep
                           # for resume safety

        # No sub-queries yet → plan
        if not state.sub_queries:
            return "plan"

        # Not all gathered → gather (skip failed sub-queries)
        gathered_ids = {s.get("sub_query_id") for s in state.sources}
        ungathered = [
            sq for sq in state.sub_queries
            if sq["id"] not in gathered_ids and sq.get("status") != "failed"
        ]
        if ungathered:
            return "gather"

        # Not all analyzed → analyze
        sources = self._db.get_sources(state.session_id)
        unanalyzed = [s for s in sources if not s.get("analysis")]
        if unanalyzed:
            return "analyze"

        # No synthesis yet → synthesize
        if state.synthesis is None:
            return "synthesize"

        # Knowledge gaps detected + budget allows + replan attempts
        # left → replan.
        # Once a report has been written, replanning only produces
        # 0 new sub-queries (all deduped) and the engine spins on
        # the planning→planning transition. The correct path after
        # the report exists is report→review→done (or revise on
        # review failure).
        #
        # Anti-spin: if the previous N rounds all returned "plan"
        # (where N == _max_replan), the replan budget is effectively
        # exhausted. Suppress this branch so control falls through
        # to "report" (or "review" / "done" depending on state).
        consecutive_plan = getattr(state, "_consecutive_plan", 0)
        if (state.knowledge_gaps
                and state.budget_remaining > 0.15
                and state.round < self._max_replan + 1
                and state.report_md is None
                and consecutive_plan < self._max_replan):
            return "plan"
        if consecutive_plan >= self._max_replan and state.report_md is None:
            logger.info(
                "Plan anti-spin: %d consecutive plan rounds (limit=%d); "
                "falling through to 'report'",
                consecutive_plan, self._max_replan,
            )

        # No report yet → report
        if state.report_md is None:
            return "report"

        # Report exists, not reviewed → review
        if state.review is None:
            return "review"

        # Review passed → done
        if state.review and state.review.get("approved"):
            return "done"

        # Review failed + rounds remaining → revise
        if state.round < state.max_rounds:
            return "revise"

        # Default → done
        return "done"

    async def _llm_reason(self, state: ResearchState) -> str:
        """Use LLM to decide next action with chain-of-thought reasoning.

        Migrated to use ``run_prompt``. Falls back to the
        rule-based reasoner on persistent LLM failure.
        """
        from llmwikify.apps.chat.prompts import _reason_fallback

        analyzed_count = sum(1 for s in state.sources if s.get("analysis"))
        failed_sq = sum(
            1 for sq in state.sub_queries if sq.get("status") == "failed"
        )

        # Build observation context from interpreted observations
        obs_text = (
            "\n".join(f"  - {o}" for o in state.observations)
            if state.observations
            else "  (none)"
        )

        # Build vars dict for the YAML template (research_reason.yaml
        # does not exist yet, but the call layer falls back gracefully
        # and the rule-based fallback is triggered by the sentinel).
        vars_dict = {
            "query": state.query,
            "round": state.round,
            "max_rounds": state.max_rounds,
            "phase": state.phase or "starting",
            "quality_score": state.quality_score,
            "budget_remaining": state.budget_remaining,
            "sub_queries_count": len(state.sub_queries),
            "failed_sq": failed_sq,
            "sources_count": len(state.sources),
            "analyzed_count": analyzed_count,
            "report_exists": state.report_md is not None,
            "review_exists": state.review is not None,
            "observations_text": obs_text,
        }

        try:
            result = await run_prompt(self._action_ctx, "research_reason", **vars_dict)
        except Exception as e:
            logger.warning("LLM reason failed: %s, applying rule-based fallback", e)
            result = _reason_fallback(error=e)

        # If the fallback returned the rule-based sentinel, fall
        # through to the legacy rule-based logic for parity.
        if result.get("action") == "__rule_based__":
            return self.rule_based(state)

        action = result.get("action", "done")
        thought = result.get("thought", "")

        # Anti-spin guard for the LLM path: if the LLM keeps returning
        # ``plan`` after a report already exists, that means the
        # prompt is misguiding the model into replanning forever.
        # Force a rule-based decision so the engine makes progress
        # (gather → analyze → synthesize → report → review → done).
        if action == "plan" and state.report_md is not None:
            logger.info(
                "LLM reason returned 'plan' but report exists; "
                "applying rule-based fallback to break the loop"
            )
            return self.rule_based(state)

        # Validate against the allow-list (defensive).
        if action not in VALID_ACTIONS:
            action = "done"

        # Store thought for SSE event (set on state so _react_loop
        # can yield it).
        state._last_thought = thought

        return action
