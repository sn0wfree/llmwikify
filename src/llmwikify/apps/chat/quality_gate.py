"""Quality gates between research stages.

Gate results are injected as observations into the ReAct loop.
The Reasoner decides what to do based on gate observations.

Sprint C4: the 4 base gate methods now live in
:mod:`llmwikify.apps.research.base.BaseQualityGate`. This
module adds 4 6-step-framework gates on top of the base
class: ``check_evidence_quality``, ``check_reasoning_quality``,
``check_structure_quality``, and ``check_framework_compliance``.
"""

from __future__ import annotations

from typing import Any

from llmwikify.apps.research.base import BaseGateResult, BaseQualityGate

# Public alias — preserve the original module-level name.
GateResult = BaseGateResult


class QualityGate(BaseQualityGate):
    """6-step-framework quality gates.

    Inherits the 4 base stage-transition gates from
    :class:`BaseQualityGate` and adds 4 framework-specific
    gates (evidence / reasoning / structure / framework
    compliance).
    """

    # ─── 6-step framework gates (step 2: evidence, step 3: reasoning) ──

    def check_evidence_quality(
        self,
        sources: list[dict],
        evidence_threshold: float = 0.5,
    ) -> BaseGateResult:
        """6-step gate 2 (after_gathering): are sources evidence-quality?

        Uses SourceFilter.compute_evidence_score which adds traceability
        and authority dimensions on top of base quality.
        """
        if not sources:
            return BaseGateResult(
                passed=False,
                gate_name="evidence_quality",
                summary="No sources to score",
                suggestion="gather_more",
            )
        # Lazy import to avoid circular
        from .source_filter import SourceFilter
        sf = SourceFilter()
        scored = []
        for s in sources:
            score = sf.compute_evidence_score(s)
            scored.append((s.get("title") or s.get("url") or "?", score))
        scored.sort(key=lambda x: x[1], reverse=True)
        avg = sum(s[1] for s in scored) / len(scored)
        high_quality = sum(1 for _, s in scored if s >= evidence_threshold)
        passed = avg >= evidence_threshold and high_quality >= max(1, len(sources) // 2)
        return BaseGateResult(
            passed=passed,
            gate_name="evidence_quality",
            summary=(
                f"Avg evidence score {avg:.2f} (≥{evidence_threshold}), "
                f"{high_quality}/{len(sources)} sources ≥ threshold"
            ),
            details={
                "avg_score": round(avg, 3),
                "high_quality_count": high_quality,
                "total": len(scored),
                "threshold": evidence_threshold,
                "top_sources": scored[:3],
            },
            suggestion="proceed" if passed else "gather_higher_quality",
        )

    def check_reasoning_quality(
        self,
        synthesis: str,
        evidence_sources: list[dict] | None = None,
        clarification: dict | None = None,
        reasoning_threshold: float = 0.5,
    ) -> BaseGateResult:
        """6-step gate 3 (after_synthesis): is the reasoning chain sound?

        Uses ReasoningChecker which scores 6 dimensions and computes an
        aggregate. A failed gate forces the engine to return to plan stage.
        """
        from .reasoning_checker import ReasoningChecker
        checker = ReasoningChecker()
        result = checker.check(
            synthesis=synthesis,
            evidence_sources=evidence_sources,
            clarification=clarification,
        )
        agg = result["aggregate_score"]
        passed = agg >= reasoning_threshold
        top_issues = result.get("issues", [])[:3]
        return BaseGateResult(
            passed=passed,
            gate_name="reasoning_quality",
            summary=(
                f"Reasoning aggregate {agg:.2f} (≥{reasoning_threshold}), "
                f"{len(result['issues'])} issues"
            ),
            details={
                "aggregate_score": agg,
                "per_dimension": result["scores"],
                "issues": top_issues,
                "method": result["method"],
                "threshold": reasoning_threshold,
            },
            suggestion="proceed" if passed else "replan_reasoning",
        )

    def check_structure_quality(
        self,
        report: str,
        synthesis: dict | None = None,
        evidence_sources: list[dict] | None = None,
        structure_threshold: float = 0.5,
    ) -> BaseGateResult:
        """6-step gate 4 (before_report): is the report structure sound?

        Uses StructureValidator which scores 3 layers (hierarchical support,
        section completeness, internal consistency).
        """
        from .structure_validator import StructureValidator
        validator = StructureValidator()
        result = validator.validate(
            report=report,
            synthesis=synthesis,
            evidence_sources=evidence_sources,
        )
        agg = result["aggregate_score"]
        passed = agg >= structure_threshold
        top_issues = result.get("issues", [])[:3]
        return BaseGateResult(
            passed=passed,
            gate_name="structure_quality",
            summary=(
                f"Structure aggregate {agg:.2f} (≥{structure_threshold}), "
                f"{len(result['issues'])} issues"
            ),
            details={
                "aggregate_score": agg,
                "per_layer": result["scores"],
                "issues": top_issues,
                "method": result["method"],
                "threshold": structure_threshold,
            },
            suggestion="proceed" if passed else "replan_structure",
        )

    def check_framework_compliance(
        self,
        clarification: dict | None,
        reasoning_check: dict | None,
        structure_check: dict | None,
    ) -> BaseGateResult:
        """6-step gate 5 (before_report): does the output follow the 6-step framework?

        Verifies that the three framework outputs (clarification, reasoning,
        structure) are all present and non-empty. This is a *meta* check
        that fails if any step was skipped (e.g. the report ran without
        a clarification because of resume).
        """
        issues: list[str] = []
        if not clarification or not clarification.get("context"):
            issues.append("missing clarification step 1 output")
        if not reasoning_check or reasoning_check.get("aggregate_score", 0) == 0:
            issues.append("missing reasoning step 3 check")
        if not structure_check or structure_check.get("aggregate_score", 0) == 0:
            issues.append("missing structure step 4 check")
        passed = len(issues) == 0
        return BaseGateResult(
            passed=passed,
            gate_name="framework_compliance",
            summary=(
                "All 6-step framework outputs present"
                if passed
                else f"Framework incomplete: {'; '.join(issues)}"
            ),
            details={
                "has_clarification": bool(clarification and clarification.get("context")),
                "has_reasoning_check": bool(reasoning_check),
                "has_structure_check": bool(structure_check),
            },
            suggestion="proceed" if passed else "replan_framework",
        )
