"""Research Observer — refresh state from DB after each action.

Phase 2 #5 / C3 — extracted from ResearchEngine (~565 LOC
after C2, now ~500 after C3) to ``observer.py``.

The Observer encapsulates the 1 method that runs after
every action to refresh state from the DB and generate
interpreted observations for the reasoner:

  - ``observe(state)`` — reload sources / sub_queries /
       knowledge_gaps from DB and build human-readable
       observation lines (source quality distribution,
       failed sub-queries, source type distribution,
       wiki vs web ratio, etc.)

The engine keeps a 1-line delegator
(``_observe(state)``) for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmwikify.autoresearch.engine import ResearchEngine
    from llmwikify.autoresearch.state import ResearchState

logger = logging.getLogger(__name__)


class ResearchObserver:
    """ReAct Observe step — refresh state and build observations.

    Runs at the end of every loop iteration (after ACT) to:
      1. Reload state from DB (sources, sub_queries, synthesis
         knowledge gaps, contradictions).
      2. Build human-readable observation lines that the
         reasoner can use in the next Thought step.
    """

    def __init__(self, engine: "ResearchEngine"):
        self._engine = engine
        # Cached for direct access in hot paths.
        self._db = engine.db

    def observe(self, state: "ResearchState") -> None:
        """Refresh state from DB and generate interpreted observations."""
        state.sources = self._db.get_sources(state.session_id) or []
        state.sub_queries_raw = self._db.get_sub_queries(state.session_id) or []

        # Rebuild sub_queries list from DB
        state.sub_queries = [
            {
                "id": sq["id"],
                "query": sq["query"],
                "source_type": sq["source_type"],
                "url": sq.get("url"),
                "status": sq.get("status", "pending"),
            }
            for sq in state.sub_queries_raw
        ]

        state.total_sources = len(state.sources)
        state.total_sub_queries = len(state.sub_queries)

        # Extract knowledge gaps from synthesis
        if state.synthesis:
            state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
            state.contradictions = state.synthesis.get("contradictions", [])

        # Generate interpreted observations for the reasoner
        state.observations = []

        # Source quality distribution
        analyzed = [s for s in state.sources if s.get("analysis")]
        if analyzed:
            scores = [
                s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
                for s in analyzed
            ]
            avg = sum(scores) / len(scores) if scores else 0
            state.observations.append(
                f"Average source credibility: {avg:.1f}/10 "
                f"({len(analyzed)}/{len(state.sources)} analyzed)"
            )

        # Failed sub-queries
        failed = [sq for sq in state.sub_queries if sq.get("status") == "failed"]
        if failed:
            state.observations.append(
                f"{len(failed)} sub-queries failed: "
                f"{[sq['query'] for sq in failed[:3]]}"
            )

        # Source type distribution
        type_counts: dict[str, int] = {}
        for s in state.sources:
            t = s.get("source_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        if type_counts:
            state.observations.append(f"Source types: {type_counts}")

        # Wiki vs web ratio
        wiki_count = type_counts.get("wiki", 0)
        web_count = type_counts.get("web", 0)
        if wiki_count + web_count > 0:
            state.observations.append(
                f"Local wiki: {wiki_count} sources, Web: {web_count} sources"
            )

        # Key quality assessment
        analyzed = [s for s in state.sources if s.get("analysis")]
        if analyzed:
            cred_scores = [
                s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
                for s in analyzed
            ]
            avg_cred = sum(cred_scores) / len(cred_scores)
            if avg_cred < 5:
                state.observations.append(
                    f"⚠ 平均可信度偏低 ({avg_cred:.1f}/10)，"
                    f"建议获取更高质量源"
                )
            elif avg_cred >= 7:
                state.observations.append(
                    f"✓ 源质量良好 (平均 {avg_cred:.1f}/10)"
                )

        if len(state.knowledge_gaps) > 3:
            state.observations.append(
                f"⚠ {len(state.knowledge_gaps)} 个知识缺口，"
                f"可能影响报告完整性"
            )
