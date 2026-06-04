"""Quality gates between research stages.

Gate results are injected as observations into the ReAct loop.
The Reasoner decides what to do based on gate observations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Quality gate check result."""
    passed: bool
    gate_name: str
    summary: str
    details: dict = field(default_factory=dict)
    suggestion: str = "proceed"


class QualityGate:
    """Stage-transition quality gates.

    Results are injected into state.observations for the Reasoner.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.min_sources = config.get("gate_min_sources", 3)
        self.min_type_diversity = config.get("gate_min_type_diversity", 2)
        self.min_analyzed = config.get("gate_min_analyzed", 2)
        self.min_avg_credibility = config.get("gate_min_avg_credibility", 5)
        self.max_knowledge_gaps = config.get("gate_max_knowledge_gaps", 3)
        self.min_reinforced_claims = config.get("gate_min_reinforced_claims", 2)

    def check_after_gathering(self, sources: list[dict], sub_queries: list[dict]) -> GateResult:
        """Check after gathering: enough sources and type diversity."""
        source_count = len(sources)

        # Type diversity
        type_set: set[str] = set()
        for s in sources:
            t = s.get("source_type", "unknown")
            type_set.add(t)
        type_diversity = len(type_set)

        # Content quality
        long_content = sum(
            1 for s in sources
            if len(s.get("content") or s.get("content_preview") or "") > 500
        )

        issues: list[str] = []
        if source_count < self.min_sources:
            issues.append(f"Need {self.min_sources}+ sources, have {source_count}")
        if type_diversity < self.min_type_diversity:
            issues.append(f"Need {self.min_type_diversity}+ source types, have {type_diversity}")
        if long_content == 0 and source_count > 0:
            issues.append("No sources with substantial content (>500 chars)")

        passed = len(issues) == 0
        summary = (
            f"{source_count} sources, {type_diversity} types, {long_content} substantial"
            if passed
            else f"{source_count} sources — {'; '.join(issues)}"
        )

        return GateResult(
            passed=passed,
            gate_name="after_gathering",
            summary=summary,
            details={
                "source_count": source_count,
                "type_diversity": type_diversity,
                "long_content_count": long_content,
            },
            suggestion="proceed" if passed else "gather_more",
        )

    def check_after_analysis(self, sources: list[dict]) -> GateResult:
        """Check after analysis: credibility is acceptable."""
        analyzed = [s for s in sources if s.get("analysis")]
        analyzed_count = len(analyzed)

        issues: list[str] = []
        avg_cred = 0.0

        if analyzed_count < self.min_analyzed:
            issues.append(f"Need {self.min_analyzed}+ analyzed sources, have {analyzed_count}")
        else:
            cred_scores = [
                s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
                for s in analyzed
            ]
            avg_cred = sum(cred_scores) / len(cred_scores) if cred_scores else 0
            if avg_cred < self.min_avg_credibility:
                issues.append(f"Avg credibility {avg_cred:.1f}/{self.min_avg_credibility}")

        passed = len(issues) == 0
        summary = (
            f"Avg credibility {avg_cred:.1f}/10, {analyzed_count} analyzed"
            if passed
            else f"{analyzed_count} analyzed — {'; '.join(issues)}"
        )

        return GateResult(
            passed=passed,
            gate_name="after_analysis",
            summary=summary,
            details={"analyzed_count": analyzed_count, "avg_credibility": avg_cred},
            suggestion="proceed" if passed else "gather_higher_quality",
        )

    def check_after_synthesis(self, synthesis: dict | None) -> GateResult:
        """Check after synthesis: enough reinforced claims, not too many gaps."""
        if not synthesis:
            return GateResult(
                passed=False,
                gate_name="after_synthesis",
                summary="No synthesis data",
                suggestion="synthesize_again",
            )

        reinforced = synthesis.get("reinforced_claims", [])
        gaps = synthesis.get("knowledge_gaps", [])

        issues: list[str] = []
        if len(reinforced) < self.min_reinforced_claims:
            issues.append(f"Need {self.min_reinforced_claims}+ reinforced claims, have {len(reinforced)}")
        if len(gaps) > self.max_knowledge_gaps:
            issues.append(f"Too many knowledge gaps: {len(gaps)} > {self.max_knowledge_gaps}")

        passed = len(issues) == 0
        summary = (
            f"{len(reinforced)} reinforced claims, {len(gaps)} gaps"
            if passed
            else f"{len(reinforced)} reinforced, {len(gaps)} gaps — {'; '.join(issues)}"
        )

        return GateResult(
            passed=passed,
            gate_name="after_synthesis",
            summary=summary,
            details={
                "reinforced_count": len(reinforced),
                "gaps_count": len(gaps),
            },
            suggestion="proceed" if passed else "replan_for_gaps",
        )

    def check_before_report(self, synthesis: dict | None, sources: list[dict]) -> GateResult:
        """Check before report: synthesis exists and enough sources."""
        issues: list[str] = []

        if not synthesis:
            issues.append("No synthesis data")
        if len(sources) < 2:
            issues.append(f"Need 2+ sources, have {len(sources)}")

        passed = len(issues) == 0
        summary = (
            f"Synthesis ready, {len(sources)} sources"
            if passed
            else f"{'; '.join(issues)}"
        )

        return GateResult(
            passed=passed,
            gate_name="before_report",
            summary=summary,
            details={"has_synthesis": synthesis is not None, "source_count": len(sources)},
            suggestion="proceed" if passed else "synthesize_again",
        )

    # ─── 6-step framework gates (step 2: evidence, step 3: reasoning) ──

    def check_evidence_quality(
        self,
        sources: list[dict],
        evidence_threshold: float = 0.5,
    ) -> GateResult:
        """6-step gate 2 (after_gathering): are sources evidence-quality?

        Uses SourceFilter.compute_evidence_score which adds traceability
        and authority dimensions on top of base quality.
        """
        if not sources:
            return GateResult(
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
        return GateResult(
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
    ) -> GateResult:
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
        # Surface top 3 issues
        top_issues = result.get("issues", [])[:3]
        return GateResult(
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
