"""Cross-source synthesis using Wiki.suggest_synthesis() or SynthesisEngine."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResearchSynthesizer:
    """Generates cross-source synthesis with rating-weighted prioritization."""

    def __init__(self, wiki: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.config = config

    async def synthesize(self, sources: list[dict[str, Any]]) -> dict[str, Any]:
        """Run cross-source synthesis.

        High-rated sources are prioritized in synthesis.
        """
        from ....core.synthesis_engine import SynthesisEngine

        # Sort by rating (highest first) for weighted consideration
        rated_sources = sorted(sources, key=lambda s: s.get("rating") or 0, reverse=True)

        engine = SynthesisEngine(self.wiki)
        all_suggestions = []

        for src in rated_sources:
            analysis = src.get("analysis")
            if not analysis or analysis.get("status") in ("error", "skipped", None):
                continue

            try:
                suggestion = engine.analyze_new_source(analysis, src.get("title", ""))
                all_suggestions.append(suggestion)
            except Exception as e:
                logger.warning("Synthesis failed for source %s: %s", src.get("id"), e)

        # Aggregate results
        reinforced = []
        contradictions = []
        knowledge_gaps = []
        new_entities = []
        suggested_updates = []

        for s in all_suggestions:
            reinforced.extend(s.get("reinforced_claims", []))
            contradictions.extend(s.get("new_contradictions", []))
            knowledge_gaps.extend(s.get("knowledge_gaps", []))
            new_entities.extend(s.get("new_entities", []))
            suggested_updates.extend(s.get("suggested_updates", []))

        return {
            "reinforced_claims": reinforced,
            "contradictions": contradictions,
            "knowledge_gaps": knowledge_gaps,
            "new_entities": new_entities,
            "suggested_updates": suggested_updates,
            "sources_analyzed": len(sources),
            "suggestions_count": len(all_suggestions),
        }
