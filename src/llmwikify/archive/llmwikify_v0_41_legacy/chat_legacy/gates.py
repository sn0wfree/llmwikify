"""Research Gates — framework & quality compliance + control signals.

Phase 2 #5 / C2 — extracted from ResearchEngine (885 LOC
monolith, now ~635 after C1) to ``gates.py``.

The Gates module encapsulates 6 methods that gate the
engine's transition into the ``done`` phase and respond
to control signals from the API layer:

  - ``check_control_signals(state)``     — DB-driven
       cancel/pause signals
  - ``check_framework_compliance(state)`` — 6-step framework
       fields presence
  - ``check_quality_compliance(state)``  — layered check:
       framework + quality thresholds
  - ``can_replan(state)``                — budget check
  - ``evaluate_gate(state)``             — per-phase base
       gate + 6-step framework gate
  - ``synthesis_to_text(synthesis)``     — flatten synthesis
       dict to text (static, also exposed as engine method)

The engine keeps 1-line delegator methods for backward
compatibility with existing tests and any external code
that may call them via ``engine._check_*()`` etc.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy import actions

if TYPE_CHECKING:
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine import ResearchEngine
    from llmwikify.apps.chat.state import ResearchState

logger = logging.getLogger(__name__)


class ResearchGates:
    """Framework & quality compliance gates.

    Two layers of gating:
      1. Framework presence — all 6 framework steps
         (clarify → evidence → reasoning → structure →
         report → review) have data.
      2. Quality thresholds — review approved, quality
         score above threshold, knowledge gaps below
         cap, sources above minimum.

    Plus per-phase base gates (gathering / analyzing /
    synthesizing / reporting / reviewing) that check
    domain-specific invariants (e.g., evidence quality
    after gathering, structure quality before report).
    """

    def __init__(self, engine: "ResearchEngine"):
        self._engine = engine
        # Cached for direct access in hot paths.
        self._db = engine.db
        self._config = engine.config
        self._quality_gate = engine._quality_gate

    def check_control_signals(self, state: "ResearchState") -> None:
        """Check DB for cancel/pause signals from API layer."""
        try:
            session = self._db.get_research_session(state.session_id)
            if session:
                db_status = session.get("status", "")
                if db_status == "cancelling":
                    state.cancelled = True
                elif db_status == "pausing":
                    state.paused = True
        except Exception as e:
            logger.debug("Control signal check failed: %s", e)

    def check_framework_compliance(self, state: "ResearchState") -> dict | None:
        """Return None if all 6-step framework fields are present, else
        {missing: action_name, reason: human_readable}.

        Used to prevent the engine from marking a session 'done' when
        the 6-step framework (clarify→evidence→reasoning→structure→
        report→review) has skipped steps. The 'missing' field is the
        next action the engine should take to fix the gap.

        Maps to the 6 framework steps in the README:
        - 1. clarify       → state.clarification
        - 2. evidence      → state.evidence_scores (populated by gather)
        - 3. reasoning     → state.reasoning_check (populated by synthesize)
        - 4. structure     → state.structure_check (populated by report)
        - 5. report        → state.report_md
        - 6. review        → state.review
        """
        if state.clarification is None:
            return {"missing": "clarify", "reason": "step 1 (clarification) missing"}
        if not state.evidence_scores:
            return {"missing": "gather", "reason": "step 2 (evidence scoring) missing"}
        if state.synthesis is None:
            return {"missing": "synthesize", "reason": "step 5 (synthesis) missing"}
        if state.reasoning_check is None:
            # reasoning_check is part of synthesize action
            return {"missing": "synthesize", "reason": "step 3 (reasoning check) missing"}
        if state.report_md is None:
            return {"missing": "report", "reason": "step 5 (report) missing"}
        if state.structure_check is None:
            # structure_check is part of report action
            return {"missing": "report", "reason": "step 4 (structure check) missing"}
        if state.review is None:
            return {"missing": "review", "reason": "step 6 (review) missing"}
        return None

    def check_quality_compliance(self, state: "ResearchState") -> dict | None:
        """Layered check: 6-step presence + quality thresholds.

        Used by the strict_exit gate (v6) to prevent the engine from
        marking a session 'done' with low-quality output. Returns the
        first failing check as {missing: action_name, reason: str}.

        Layer 1 (delegates to check_framework_compliance):
            - All 6 framework fields present.

        Layer 2 (quality thresholds):
            - state.review.approved == True
            - state.quality_score >= config.quality_threshold
            - len(state.knowledge_gaps) <= config.gate_max_knowledge_gaps
            - len(state.sources) >= config.gate_min_sources

        Returns None only when all checks pass.
        """
        # Layer 1: framework presence
        missing = self.check_framework_compliance(state)
        if missing is not None:
            return missing

        # Layer 2: quality thresholds
        review = state.review or {}
        # A review that was skipped (LLM failed) must NOT be treated
        # as approved. The `skipped` flag is set by `action_review` /
        # `action_revise` when the LLM call raises. Sending the
        # engine to `revise` here is honest: revise is also LLM-
        # bound and will fall into `incomplete` if it also fails.
        if review.get("skipped"):
            return {
                "missing": "revise",
                "reason": f"review was skipped (LLM failed): {review.get('skip_reason', '')}",
            }
        if not review.get("approved"):
            return {
                "missing": "revise",
                "reason": f"review not approved (score={state.quality_score})",
            }

        threshold = self._config.get("quality_threshold", 7)
        if state.quality_score < threshold:
            return {
                "missing": "revise",
                "reason": f"quality_score={state.quality_score} < threshold={threshold}",
            }

        max_gaps = self._config.get("gate_max_knowledge_gaps", 3)
        if len(state.knowledge_gaps) > max_gaps:
            # Redirect to `plan` (gap-replan path), NOT `synthesize`.
            # Re-running synthesis with the same sources would just
            # reproduce the same gaps and burn the round budget.
            return {
                "missing": "plan",
                "reason": f"knowledge_gaps={len(state.knowledge_gaps)} > max={max_gaps}",
            }

        min_sources = self._config.get("gate_min_sources", 3)
        if len(state.sources) < min_sources:
            return {
                "missing": "gather",
                "reason": f"sources={len(state.sources)} < min={min_sources}",
            }

        return None

    def can_replan(self, state: "ResearchState") -> bool:
        """Return True if the engine has budget for one more action.

        Used by the framework compliance gate to decide between
        'redirect to missing action' vs 'mark incomplete'.
        """
        if state.budget_remaining <= 0.10:
            return False
        if state.round >= state.max_rounds:
            return False
        return True

    def evaluate_gate(self, state: "ResearchState"):
        """Evaluate quality gate based on current phase.

        Each phase invokes its base gate plus the 6-step framework gate.
        The 6-step gate is layered ON TOP of the base gate (both must pass
        for the engine to proceed; any failure triggers a replan).
        Returns a combined GateResult (or the first failing one).

        Mapping (per plan:162-166):
            gathering    → check_after_gathering       + check_evidence_quality
            analyzing    → check_after_analysis
            synthesizing → check_after_synthesis       + check_reasoning_quality
            reporting    → check_before_report         + check_structure_quality
            reviewing    →                              check_framework_compliance
        """
        gate = self._quality_gate
        evidence_enabled = self._config.get("evidence_scoring_enabled", True)
        reasoning_enabled = self._config.get("reasoning_check_enabled", True)
        structure_enabled = self._config.get("structure_check_enabled", True)
        framework_enabled = self._config.get("framework_check_enabled", True)

        if state.phase == "gathering":
            base = gate.check_after_gathering(state.sources, state.sub_queries)
            if not base.passed:
                return base
            if evidence_enabled:
                ev = gate.check_evidence_quality(
                    state.sources,
                    evidence_threshold=self._config.get("gate_min_evidence_score", 0.5),
                )
                if not ev.passed:
                    return ev
            return base
        elif state.phase == "analyzing":
            return gate.check_after_analysis(state.sources)
        elif state.phase == "synthesizing":
            base = gate.check_after_synthesis(state.synthesis)
            if not base.passed:
                return base
            if reasoning_enabled:
                # Build a synthesis text from synthesis dict
                # (synthesizer stores structured output)
                synth_text = self.synthesis_to_text(state.synthesis)
                rs = gate.check_reasoning_quality(
                    synth_text,
                    evidence_sources=state.sources,
                    clarification=state.clarification,
                    reasoning_threshold=self._config.get("gate_min_reasoning_score", 0.5) / 10.0,
                )
                if not rs.passed:
                    return rs
            return base
        elif state.phase == "reporting":
            base = gate.check_before_report(state.synthesis, state.sources)
            if not base.passed:
                return base
            if structure_enabled and state.report_md:
                st = gate.check_structure_quality(
                    state.report_md,
                    synthesis=state.synthesis,
                    evidence_sources=state.sources,
                    structure_threshold=self._config.get("gate_min_structure_score", 0.5),
                )
                if not st.passed:
                    return st
            return base
        elif state.phase == "reviewing" and framework_enabled:
            return gate.check_framework_compliance(
                clarification=state.clarification,
                reasoning_check=state.reasoning_check,
                structure_check=state.structure_check,
            )
        return None

    @staticmethod
    def synthesis_to_text(synthesis: dict | None) -> str:
        """Flatten synthesis dict to plain text for gate scoring.

        Delegates to ``actions.synthesis_to_text`` (extracted
        in earlier refactor commit 5b/5c).
        """
        return actions.synthesis_to_text(synthesis)
