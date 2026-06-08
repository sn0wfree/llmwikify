"""6-step framework step 4: structure integrity validator.

Verifies the synthesized analysis has a sound, well-supported structure.
No LLM call is required for the rule-based path.

Three layers of structure:
1. Hierarchical support — does the top-level claim have ≥2 supporting
   sub-claims, and do sub-claims have ≥1 evidence reference each?
2. Section completeness — are the standard sections present (background,
   analysis, evidence, conclusion)?
3. Internal consistency — are key terms used consistently throughout?

Output: dict with per-layer scores, aggregate score, and issue list.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class StructureValidator:
    """Rule-based structure integrity validator."""

    LAYERS = (
        "hierarchical_support",
        "section_completeness",
        "internal_consistency",
    )

    # Default expected sections (multilingual). At least 2 of these must
    # appear as markdown headers.
    EXPECTED_SECTIONS = (
        r"^#+\s*(?:背景|Background|引言|Introduction)",
        r"^#+\s*(?:分析|Analysis|方法|Methods|技术|Technical)",
        r"^#+\s*(?:证据|Evidence|数据|Data|来源|Source)",
        r"^#+\s*(?:结论|Conclusion|总结|Summary|小结|小结|结果|Result)",
    )

    def validate(
        self,
        report: str,
        synthesis: dict | None = None,
        evidence_sources: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Run the rule-based structure check.

        Args:
            report: The final markdown report.
            synthesis: Optional synthesis dict with claims/reinforced_claims.
            evidence_sources: Optional list of source dicts.

        Returns:
            Dict with: per-layer scores, aggregate_score, issues, method.
        """
        synthesis = synthesis or {}
        sources = evidence_sources or []

        scores: dict[str, float] = {}
        issues: list[dict[str, str]] = []

        scores["hierarchical_support"] = self._check_hierarchy(report, synthesis, sources, issues)
        scores["section_completeness"] = self._check_sections(report, issues)
        scores["internal_consistency"] = self._check_consistency(report, issues)

        aggregate = sum(scores.values()) / max(1, len(self.LAYERS))

        return {
            "scores": scores,
            "aggregate_score": round(aggregate, 3),
            "issues": issues,
            "method": "rule_based",
        }

    # ─── layer scorers ──────────────────────────────────────────────

    def _check_hierarchy(
        self,
        report: str,
        synthesis: dict,
        sources: list[dict],
        issues: list[dict[str, str]],
    ) -> float:
        # A well-supported structure has claims → evidence → conclusion.
        # Heuristics:
        # - Count distinct claims (sentences with claim markers)
        # - Count evidence references ([[Source:...]])
        # - Count claims per evidence reference
        claim_markers = re.compile(
            r"(?:^|\n)\s*[-*]\s+|"  # bullet
            r"(?:因此|所以|表明|说明|thus|therefore|conclude)",
            re.IGNORECASE,
        )
        cite_pattern = re.compile(r"\[\[Source:[^\]]+\]\]")

        claims = claim_markers.findall(report)
        citations = cite_pattern.findall(report)
        reinforced = synthesis.get("reinforced_claims") or []

        n_claims = max(len(claims), len(reinforced), 1)
        n_cites = len(citations)
        # Ratio: claims per citation. ≥1 means most claims cite something.
        cite_ratio = min(1.0, n_cites / n_claims) if n_claims else 0.0

        # Has at least 2 distinct sources?
        unique_sources = set(re.findall(r"\[\[Source:([^\]]+)\]\]", report))
        n_unique = len(unique_sources)

        score = 0.0
        if n_claims >= 3:
            score += 0.3
        if n_cites >= 2:
            score += 0.3
        if n_unique >= 2:
            score += 0.4
        if not score:
            issues.append({
                "layer": "hierarchical_support",
                "severity": "warning",
                "message": "结构支撑不足：需要 ≥3 个声明 + ≥2 个引用 + ≥2 个不同来源",
            })
        return min(1.0, score)

    def _check_sections(
        self,
        report: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Count how many expected sections are present
        present = sum(
            1 for pattern in self.EXPECTED_SECTIONS
            if re.search(pattern, report, re.MULTILINE | re.IGNORECASE)
        )
        coverage = present / len(self.EXPECTED_SECTIONS)
        if coverage < 0.5:
            issues.append({
                "layer": "section_completeness",
                "severity": "info",
                "message": (
                    f"仅检测到 {present}/{len(self.EXPECTED_SECTIONS)} 必要章节，"
                    "建议补充 背景/分析/证据/结论"
                ),
            })
        return min(1.0, coverage * 1.25)  # 80% sections → 1.0

    def _check_consistency(
        self,
        report: str,
        issues: list[dict[str, str]],
    ) -> float:
        # Identify key noun phrases (≥3 chars) and check that the top ones
        # are used consistently (not just mentioned once).
        words = re.findall(r"[\w\u4e00-\u9fff]{3,}", report.lower())
        if not words:
            return 0.0
        counter = Counter(words)
        top = counter.most_common(5)
        if not top:
            return 0.0
        # Each top word should appear ≥2 times for consistency
        consistent = sum(1 for _, count in top if count >= 2)
        ratio = consistent / len(top)
        if ratio < 0.4:
            issues.append({
                "layer": "internal_consistency",
                "severity": "info",
                "message": "核心术语复用率较低，建议关键概念在多段重复出现",
            })
        return min(1.0, ratio * 1.5)
