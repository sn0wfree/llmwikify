"""6-step framework step 3: reasoning chain integrity checker.

Validates the logical coherence of the synthesized analysis. No LLM call is
required for the rule-based path; an optional LLM judge can be plugged in to
improve scoring but the rule path always returns a structured result.

Six dimensions (0.0-1.0 each):
1. conclusion_evidence_alignment — does each conclusion cite evidence?
2. logical_contradiction — are there mutually-contradictory claims?
3. causal_coverage — does the analysis explain cause→effect?
4. premise_evidence_alignment — are stated premises actually supported?
5. assumption_visibility — are unstated assumptions called out?
6. uncertainty_quantification — does the analysis quantify uncertainty?

Output: dict with per-dimension scores, aggregate score, and a list of
issues that can be fed to the gate.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ReasoningChecker:
    """Rule-based reasoning chain integrity scorer."""

    DIMENSIONS = (
        "conclusion_evidence_alignment",
        "logical_contradiction",
        "causal_coverage",
        "premise_evidence_alignment",
        "assumption_visibility",
        "uncertainty_quantification",
    )

    def check(
        self,
        synthesis: str,
        evidence_sources: list[dict[str, Any]] | None = None,
        clarification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the rule-based reasoning check.

        Args:
            synthesis: The synthesized analysis text (markdown).
            evidence_sources: List of source dicts with at least 'id'/'url'.
            clarification: The output of ResearchClarifier (with premises).

        Returns:
            Dict with keys: per-dimension scores, aggregate_score, issues.
        """
        sources = evidence_sources or []
        clarification = clarification or {}

        scores: dict[str, float] = {}
        issues: list[dict[str, str]] = []

        scores["conclusion_evidence_alignment"] = self._check_alignment(synthesis, sources, issues)
        scores["logical_contradiction"] = self._check_contradiction(synthesis, issues)
        scores["causal_coverage"] = self._check_causal(synthesis, issues)
        scores["premise_evidence_alignment"] = self._check_premises(
            synthesis, sources, clarification, issues
        )
        scores["assumption_visibility"] = self._check_assumptions(synthesis, issues)
        scores["uncertainty_quantification"] = self._check_uncertainty(synthesis, issues)

        # Weighted aggregate. 6 dimensions get equal weight by default.
        aggregate = sum(scores.values()) / max(1, len(self.DIMENSIONS))

        return {
            "scores": scores,
            "aggregate_score": round(aggregate, 3),
            "issues": issues,
            "method": "rule_based",
        }

    # ─── dimension scorers ─────────────────────────────────────────

    def _check_alignment(
        self,
        synthesis: str,
        sources: list[dict[str, Any]],
        issues: list[dict[str, str]],
    ) -> float:
        # Heuristic: count sentences with explicit citation markers
        sentences = re.split(r"[.!?。\n]+", synthesis)
        sentences = [s for s in sentences if s.strip()]
        if not sentences:
            return 0.0
        # Citation patterns: [[Source:id]], [Source: ...], (Source: ...), (Ref: ...)
        cite_pattern = re.compile(
            r"\[\[Source:[^\]]+\]\]|"
            r"\[Source:|\[Ref:|"
            r"\(Source:|\(Ref:"
        )
        cited = sum(1 for s in sentences if cite_pattern.search(s))
        ratio = cited / len(sentences)
        if ratio < 0.3 and sources:
            issues.append({
                "dimension": "conclusion_evidence_alignment",
                "severity": "warning",
                "message": f"仅 {cited}/{len(sentences)} 句子引用证据（{ratio:.0%}），建议提升至 ≥30%",
            })
        return min(1.0, ratio * 2)  # 50% sentences cited → score 1.0

    def _check_contradiction(
        self,
        synthesis: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Heuristic: look for explicit contradiction markers.
        # marker_pattern reserved for future use; current scoring focuses on
        # reconciliation/nuance words (see below).
        # We can't detect *logical* contradictions without semantics, so we
        # score "no contradiction markers present" as 0.7 (neutral) and
        # "explicit reconciliation present" as 1.0.
        if not synthesis.strip():
            return 0.0
        # Count explicit reconciliation/nuance words
        reconcile = re.findall(
            r"综合|平衡|折中|权衡|reconcil|on balance|in summary",
            synthesis,
            re.IGNORECASE,
        )
        if reconcile:
            return 1.0
        return 0.7

    def _check_causal(
        self,
        synthesis: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Causal markers: "因为…所以", "导致", "because", "leads to", "results in"
        causal_pattern = re.compile(
            r"因为|所以|因此|导致|造成|引起|"
            r"because|leads to|results in|causes|therefore|thus|hence",
            re.IGNORECASE,
        )
        matches = causal_pattern.findall(synthesis)
        if not matches:
            issues.append({
                "dimension": "causal_coverage",
                "severity": "info",
                "message": "未检测到因果连接词，建议补充 '因为...所以' / 'because...therefore' 等说明",
            })
            return 0.3
        # Map: 0 matches=0.3, 1-2=0.6, 3+=1.0
        if len(matches) <= 2:
            return 0.6
        return 1.0

    def _check_premises(
        self,
        synthesis: str,
        sources: list[dict[str, Any]],
        clarification: dict[str, Any],
        issues: list[dict[str, str]],
    ) -> float:
        premises = clarification.get("premises") or []
        if not premises:
            # No stated premises → can't validate
            return 0.8
        # If we have premises, look for them or their key terms in synthesis
        synthesis_lower = synthesis.lower()
        covered = 0
        for p in premises:
            # Look for ≥5-char token overlap
            tokens = [t for t in re.split(r"\W+", p.lower()) if len(t) >= 5]
            if any(t in synthesis_lower for t in tokens):
                covered += 1
        ratio = covered / max(1, len(premises))
        if ratio < 0.5:
            issues.append({
                "dimension": "premise_evidence_alignment",
                "severity": "warning",
                "message": f"仅 {covered}/{len(premises)} 前提在分析中被讨论（{ratio:.0%}）",
            })
        return min(1.0, ratio * 1.25)

    def _check_assumptions(
        self,
        synthesis: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Assumption markers: "假设", "假定", "assuming", "presume", "given that"
        assumption_pattern = re.compile(
            r"假设|假定|假设条件|前提|"
            r"assume|assuming|presume|given that|provided that",
            re.IGNORECASE,
        )
        if assumption_pattern.search(synthesis):
            return 1.0
        issues.append({
            "dimension": "assumption_visibility",
            "severity": "info",
            "message": "未显式标注假设，建议添加 '假设: ...' 段",
        })
        return 0.5

    def _check_uncertainty(
        self,
        synthesis: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Uncertainty markers: "可能", "大约", "估计", "或许", "likely", "approximately"
        uncertainty_pattern = re.compile(
            r"可能|也许|或许|大概|估计|大约|"
            r"likely|probably|approximately|roughly|may|might|could",
            re.IGNORECASE,
        )
        matches = uncertainty_pattern.findall(synthesis)
        if len(matches) >= 2:
            return 1.0
        if len(matches) == 1:
            return 0.7
        issues.append({
            "dimension": "uncertainty_quantification",
            "severity": "info",
            "message": "未量化不确定性，建议在结论旁标注置信度（如 '可能'/'likely'）",
        })
        return 0.4
