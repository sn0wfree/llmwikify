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

    async def synthesize(self, sources: list[dict[str, Any]], query: str = "") -> dict[str, Any]:
        """Run cross-source synthesis.

        High-rated sources get weighted higher in aggregation:
        - rating 5: weight 2.0x
        - rating 4: weight 1.5x
        - rating 3: weight 1.0x (default)
        - rating 2: weight 0.5x
        - rating 1: weight 0.25x
        - no rating: weight 1.0x
        """
        from llmwikify.kernel.wiki.engines.synthesis import SynthesisEngine

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

        # Cross-reference with existing wiki pages
        wiki_comparisons = []
        if query:
            try:
                wiki_results = self.wiki.search(query, limit=5)
                # Only compare with wiki sources that aren't already in gathered sources
                existing_urls = {s.get("url", "") for s in sources}
                for r in wiki_results:
                    page_name = r.get("page_name", "")
                    wiki_url = f"wiki://{page_name}"
                    if wiki_url not in existing_urls:
                        try:
                            page_content = self.wiki.read_page(page_name)
                            if page_content:
                                wiki_comparisons.append({
                                    "page_name": page_name,
                                    "snippet": r.get("snippet", ""),
                                    "content_preview": str(page_content)[:2000],
                                })
                        except Exception:
                            pass
            except Exception as e:
                logger.debug("Wiki comparison search failed: %s", e)

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

        # Serialize to readable strings for prompt consumption
        def _claim_str(item: Any) -> str:
            if isinstance(item, dict):
                claim = item.get("claim", item.get("statement", str(item)))
                conf = item.get("confidence", "")
                count = item.get("confirmed_by_count", 0)
                parts = [claim]
                if conf:
                    parts.append(f"(confidence: {conf})")
                if count:
                    parts.append(f"(confirmed by {count} source(s))")
                return " ".join(parts)
            return str(item)

        def _contradiction_str(item: Any) -> str:
            if isinstance(item, dict):
                return item.get("contradiction", item.get("observation", str(item)))
            return str(item)

        def _gap_str(item: Any) -> str:
            if isinstance(item, dict):
                return item.get("gap", item.get("observation", str(item)))
            return str(item)

        def _entity_str(item: Any) -> str:
            if isinstance(item, dict):
                name = item.get("name", "")
                etype = item.get("type", "")
                desc = item.get("suggestion", "")
                return f"{name} ({etype})" + (f" — {desc}" if desc else "")
            return str(item)

        return {
            "reinforced_claims": [_claim_str(c) for c in reinforced],
            "contradictions": [_contradiction_str(c) for c in contradictions],
            "knowledge_gaps": [_gap_str(g) for g in knowledge_gaps],
            "new_entities": [_entity_str(e) for e in new_entities],
            "suggested_updates": suggested_updates,
            "sources_analyzed": len(sources),
            "suggestions_count": len(all_suggestions),
            "wiki_comparisons": wiki_comparisons,
        }
