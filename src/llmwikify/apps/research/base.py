"""Base classes shared by ``apps/research/`` and ``apps/chat/``.

Sprint C4 of the 4-layer refactor (design doc
``docs/designs/refactor-4layer-architecture.md``) consolidates
the duplicated code that used to live in both packages. The
canonical home is ``apps/research/base.py`` because:

- ``apps/chat/`` is allowed to import from ``apps/research/``
  (the only allowed L3→L3 direction, per design decision D7).
- Putting the base class in either L3 package would create a
  circular import (each package wanting to import the base
  from the other). ``apps/research/`` is the natural anchor
  because ``apps/chat/`` already imports helpers from it
  (e.g. ``apps.research.web_search``).

This file currently hosts ``BaseResearchConfig``. Future
batches (Step 2-4 of C4) will add ``BaseQualityGate``,
``BaseResearchTaskManager``, and ``BaseReportGenerator``
alongside it.

Backward compatibility
-----------------------
Every public symbol exposed by the base class is also
re-exported from the per-package module (e.g.
``apps.research.config.DEFAULT_RESEARCH_CONFIG``). External
callers, the 14 ``agent/backend/research.*.py`` shim files,
and ``_legacy/autoresearch.py`` all continue to work without
any import-path change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class BaseResearchConfig:
    """Shared default config keys + merge helper for both packages.

    The 31 keys defined here were duplicated verbatim between
    ``apps/research/config.py::DEFAULT_RESEARCH_CONFIG`` and
    ``apps/chat/config.py::DEFAULT_SIX_STEP_CONFIG``. The chat
    side has 30+ additional keys for the 6-step framework
    (clarify, evidence, structure, etc.); see
    ``apps/chat/config.py::_SIX_STEP_EXTRAS``.

    Subclasses and consumers must treat ``DEFAULT`` as
    read-only. Use :meth:`merge` (or the per-package
    ``merge_*_config`` thin wrappers) to produce a runtime
    config dict.
    """

    DEFAULT: dict[str, Any] = {
        "max_sub_queries": 20,
        "max_source_content_length": 500000,
        "research_timeout_minutes": 30,
        "max_parallel_gathering": 5,
        "web_search_results_per_query": 5,
        "max_retry_attempts": 3,
        "similarity_threshold": 0.92,
        "max_review_rounds": 2,
        "planning_model": None,
        "report_model": None,
        "llm_call_timeout_seconds": 120,
        # Search provider config
        "search_provider": "auto",       # "auto", "searxng", "minimax", "tavily", "duckduckgo"
        "searxng_url": None,             # e.g. "http://localhost:8888"
        "minimax_api_key": None,         # MiniMax Token Plan API key
        "minimax_api_host": "https://api.minimaxi.com",  # domestic endpoint
        "tavily_api_key": None,          # e.g. "tvly-xxxxx"
        # ReAct config
        "max_react_rounds": 10,          # Max ReAct loop iterations
        "quality_threshold": 7,          # Score >= 7 is approved
        "max_replan_attempts": 2,        # Max replanning for knowledge gaps
        "parallel_wiki_search": True,    # Search local wiki alongside web results
        # Source filter config
        "source_filter_enabled": True,   # Enable rule-based source pre-filter
        "source_min_content_length": 100,  # Min content length to keep
        "source_min_quality_score": 0.3,   # Min quality score to keep
        # Report content budget
        "report_max_per_source": 4000,     # Max chars per source in report prompt
        "report_max_total_content": 60000, # Max total source chars in report prompt
        # Quality gate config (base 4 gates)
        "gate_enabled": True,            # Enable quality gates
        "gate_min_sources": 3,           # Min sources after gathering
        "gate_min_type_diversity": 2,    # Min source type diversity
        "gate_min_analyzed": 2,          # Min analyzed sources
        "gate_min_avg_credibility": 5,   # Min avg credibility after analysis
        "gate_max_knowledge_gaps": 3,    # Max knowledge gaps after synthesis
        "gate_min_reinforced_claims": 2, # Min reinforced claims after synthesis
    }

    @classmethod
    def merge(cls, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a fresh copy of :attr:`DEFAULT` with overrides applied.

        Override keys that are not present in ``DEFAULT`` are
        silently ignored (this matches the v0.30.1 behavior of
        both packages' ``merge_*_config`` helpers — see
        ``test_merge_ignores_unknown_keys``).
        """
        config = dict(cls.DEFAULT)
        if overrides:
            for k, v in overrides.items():
                if k in config and v is not None:
                    config[k] = v
        return config


@dataclass
class BaseGateResult:
    """Quality gate check result.

    Used by both :class:`BaseQualityGate` and the per-package
    subclasses in ``apps.research.quality_gate`` and
    ``apps.chat.quality_gate``. The ``details`` field carries
    a free-form dict for gate-specific debugging info.
    """

    passed: bool
    gate_name: str
    summary: str
    details: dict = field(default_factory=dict)
    suggestion: str = "proceed"


class BaseQualityGate:
    """Stage-transition quality gates (4 base methods).

    Results are injected into ``state.observations`` for the
    Reasoner to consume. The 4 methods here were duplicated
    verbatim between ``apps/research/quality_gate.py`` and
    ``apps/chat/quality_gate.py``; the chat subclass adds
    four 6-step-framework gates (``check_evidence_quality``,
    ``check_reasoning_quality``, ``check_structure_quality``,
    ``check_framework_compliance``).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.min_sources = config.get("gate_min_sources", 3)
        self.min_type_diversity = config.get("gate_min_type_diversity", 2)
        self.min_analyzed = config.get("gate_min_analyzed", 2)
        self.min_avg_credibility = config.get("gate_min_avg_credibility", 5)
        self.max_knowledge_gaps = config.get("gate_max_knowledge_gaps", 3)
        self.min_reinforced_claims = config.get("gate_min_reinforced_claims", 2)

    def check_after_gathering(self, sources: list[dict], sub_queries: list[dict]) -> BaseGateResult:
        """Check after gathering: enough sources and type diversity."""
        source_count = len(sources)

        type_set: set[str] = set()
        for s in sources:
            t = s.get("source_type", "unknown")
            type_set.add(t)
        type_diversity = len(type_set)

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

        return BaseGateResult(
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

    def check_after_analysis(self, sources: list[dict]) -> BaseGateResult:
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

        return BaseGateResult(
            passed=passed,
            gate_name="after_analysis",
            summary=summary,
            details={"analyzed_count": analyzed_count, "avg_credibility": avg_cred},
            suggestion="proceed" if passed else "gather_higher_quality",
        )

    def check_after_synthesis(self, synthesis: dict | None) -> BaseGateResult:
        """Check after synthesis: enough reinforced claims, not too many gaps."""
        if not synthesis:
            return BaseGateResult(
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

        return BaseGateResult(
            passed=passed,
            gate_name="after_synthesis",
            summary=summary,
            details={
                "reinforced_count": len(reinforced),
                "gaps_count": len(gaps),
            },
            suggestion="proceed" if passed else "replan_for_gaps",
        )

    def check_before_report(self, synthesis: dict | None, sources: list[dict]) -> BaseGateResult:
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

        return BaseGateResult(
            passed=passed,
            gate_name="before_report",
            summary=summary,
            details={"has_synthesis": synthesis is not None, "source_count": len(sources)},
            suggestion="proceed" if passed else "synthesize_again",
        )

