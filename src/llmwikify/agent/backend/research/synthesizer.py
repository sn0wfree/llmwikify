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

        High-rated sources get weighted higher in aggregation:
        - rating 5: weight 2.0x
        - rating 4: weight 1.5x
        - rating 3: weight 1.0x (default)
        - rating 2: weight 0.5x
        - rating 1: weight 0.25x
        - no rating: weight 1.0x
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
                # Weight by rating
                rating = src.get("rating") or 3
                weight = {5: 2.0, 4: 1.5, 3: 1.0, 2: 0.5, 1: 0.25}.get(rating, 1.0)
                suggestion["_rating"] = rating
                suggestion["_weight"] = weight
                all_suggestions.append(suggestion)
            except Exception as e:
                logger.warning("Synthesis failed for source %s: %s", src.get("id"), e)

        # Aggregate results with rating weighting
        reinforced = []
        contradictions = []
        knowledge_gaps = []
        new_entities = []
        suggested_updates = []

        for s in all_suggestions:
            weight = s.get("_weight", 1.0)
            # Weight reinforced claims and suggested updates (more subjective)
            for item in s.get("reinforced_claims", []):
                if isinstance(item, dict):
                    item["_weight"] = weight
                reinforced.append(item)
            for item in s.get("suggested_updates", []):
                if isinstance(item, dict):
                    item["_weight"] = weight
                suggested_updates.append(item)
            # Contradictions and knowledge gaps are not weighted (they are factual)
            contradictions.extend(s.get("new_contradictions", []))
            knowledge_gaps.extend(s.get("knowledge_gaps", []))
            new_entities.extend(s.get("new_entities", []))

        # Sort reinforced claims by weight (highest-rated sources first)
        reinforced.sort(key=lambda x: x.get("_weight", 0) if isinstance(x, dict) else 0, reverse=True)
        suggested_updates.sort(key=lambda x: x.get("_weight", 0) if isinstance(x, dict) else 0, reverse=True)

        return {
            "reinforced_claims": reinforced,
            "contradictions": contradictions,
            "knowledge_gaps": knowledge_gaps,
            "new_entities": new_entities,
            "suggested_updates": suggested_updates,
            "sources_analyzed": len(sources),
            "suggestions_count": len(all_suggestions),
        }
