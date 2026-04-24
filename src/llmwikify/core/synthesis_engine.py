"""Cross-source synthesis engine — compares new sources against existing wiki knowledge.

Design principle: "LLM does analysis, human makes decisions"
- Automatically analyzes new sources against existing content
- Returns suggestions only, never auto-executes
- Respects "stay involved" principle from LLM Wiki Principles
"""

import re
from pathlib import Path

from .constants import (
    CLAIM_OVERLAP_THRESHOLD,
    CONTRADICTION_OVERLAP_THRESHOLD,
    MAX_SUGGESTED_UPDATES,
)


class SynthesisEngine:
    """Analyze new sources against existing wiki content and generate suggestions.

    Usage:
        engine = SynthesisEngine(wiki)
        suggestions = engine.analyze_new_source(new_analysis, source_name)
        # suggestions contains: reinforced_claims, new_contradictions,
        # knowledge_gaps, suggested_updates
    """

    def __init__(self, wiki):
        self.wiki = wiki

    def analyze_new_source(
        self,
        new_analysis: dict,
        source_name: str,
    ) -> dict:
        """Analyze a new source against existing wiki content.

        Args:
            new_analysis: Output from analyze_source (entities, claims, topics, etc.)
            source_name: Name of the new source file

        Returns:
            Dict with suggestions (not auto-executed):
            - reinforced_claims: claims confirmed by multiple sources
            - new_contradictions: conflicts with existing wiki
            - knowledge_gaps: topics needing more information
            - suggested_updates: pages that should be updated
            - new_entities: entities not yet in wiki
            - synthesis_summary: human-readable summary
        """
        existing_sources = self._get_existing_source_analyses()
        existing_entities = self._get_existing_entities()
        existing_topics = self._get_existing_topics()

        result = {
            "source_name": source_name,
            "reinforced_claims": self._find_reinforced_claims(new_analysis, existing_sources),
            "new_contradictions": self._find_new_contradictions(new_analysis, existing_sources),
            "knowledge_gaps": self._find_knowledge_gaps(new_analysis, existing_sources),
            "suggested_updates": self._find_suggested_updates(new_analysis, existing_sources),
            "new_entities": self._find_new_entities(new_analysis, existing_entities),
            "topic_overlap": self._find_topic_overlap(new_analysis, existing_topics),
            "synthesis_summary": self._generate_summary(new_analysis, existing_sources),
        }

        return result

    def _get_existing_source_analyses(self) -> list[dict]:
        """Get analysis data from existing Source pages."""
        analyses = []
        sources_dir = self.wiki.wiki_dir / "sources"
        if not sources_dir.exists():
            return analyses

        for source_page in sources_dir.rglob("*.md"):
            content = source_page.read_text()
            analysis = self._extract_analysis_from_page(content)
            if analysis:
                analysis["_source_file"] = str(source_page.relative_to(self.wiki.wiki_dir))
                analyses.append(analysis)

        return analyses

    def _extract_analysis_from_page(self, content: str) -> dict | None:
        """Extract structured analysis from a Source page.

        Tries to find:
        - HTML comment cache (llmwikify:analysis)
        - Key Claims section
        - Key Entities section
        - Topics
        """
        # Try cached analysis first
        cached = self.wiki._get_cached_source_analysis(
            self.wiki._find_source_summary_page("") or Path("")
        )
        if cached:
            return cached.get("data")

        # Fallback: parse from page content
        analysis = {
            "claims": [],
            "entities": [],
            "topics": [],
        }

        # Extract claims
        claims_match = re.findall(
            r'-\s+(.+?)\s+\(confidence:\s*(high|medium|low)\)',
            content
        )
        analysis["claims"] = [
            {"statement": stmt, "confidence": conf}
            for stmt, conf in claims_match
        ]

        # Extract entities
        entities_match = re.findall(
            r'-\s+\*\*(.+?)\*\*\s+\((\w+)\):\s*(.+)',
            content
        )
        analysis["entities"] = [
            {"name": name, "type": etype, "description": desc}
            for name, etype, desc in entities_match
        ]

        return analysis if (analysis["claims"] or analysis["entities"]) else None

    def _get_existing_entities(self) -> set[str]:
        """Get all entity names from existing wiki pages."""
        entities = set()
        entities_dir = self.wiki.wiki_dir / "entities"
        if not entities_dir.exists():
            return entities

        for page in entities_dir.rglob("*.md"):
            page_name = str(page.relative_to(self.wiki.wiki_dir))[:-3]
            entities.add(page_name)

            # Also extract entities from content
            content = page.read_text()
            for match in re.findall(r'\*\*(.+?)\*\*\s+\(\w+\)', content):
                entities.add(match)

        return entities

    def _get_existing_topics(self) -> set[str]:
        """Get all topics covered in existing wiki pages."""
        topics = set()
        for page in self.wiki._wiki_pages():
            content = page.read_text()
            # Extract from headings
            for match in re.findall(r'^#+\s+(.+)$', content, re.MULTILINE):
                if len(match) > 3:
                    topics.add(match.lower().strip())

        return topics

    def _find_reinforced_claims(
        self,
        new_analysis: dict,
        existing_sources: list[dict],
    ) -> list[dict]:
        """Find claims in the new source that are confirmed by existing sources."""
        reinforced = []
        new_claims = new_analysis.get("claims", [])

        for new_claim in new_claims:
            new_statement = new_claim.get("statement", "").lower()
            match_count = 0
            matching_sources = []

            for existing in existing_sources:
                existing_claims = existing.get("claims", [])
                for existing_claim in existing_claims:
                    existing_statement = existing_claim.get("statement", "").lower()
                    # Simple keyword overlap matching
                    new_words = set(new_statement.split())
                    existing_words = set(existing_statement.split())
                    # Filter out common words
                    stop_words = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or"}
                    new_words = new_words - stop_words
                    existing_words = existing_words - stop_words

                    if new_words and existing_words:
                        overlap = len(new_words & existing_words) / max(len(new_words | existing_words), 1)
                        if overlap >= CLAIM_OVERLAP_THRESHOLD:  # keyword overlap threshold
                            match_count += 1
                            matching_sources.append(existing.get("_source_file", "unknown"))
                            break

            if match_count > 0:
                reinforced.append({
                    "claim": new_claim.get("statement"),
                    "confidence": new_claim.get("confidence"),
                    "confirmed_by_count": match_count,
                    "confirmed_by_sources": matching_sources,
                    "observation": f"This claim is supported by {match_count} other source(s)",
                })

        return reinforced

    def _find_new_contradictions(
        self,
        new_analysis: dict,
        existing_sources: list[dict],
    ) -> list[dict]:
        """Find contradictions between new source and existing wiki."""
        contradictions = []

        # Check explicit contradictions from analysis
        new_contradictions = new_analysis.get("potential_contradictions", [])
        if new_contradictions:
            contradictions.extend([
                {
                    "contradiction": c,
                    "source": new_analysis.get("_source_file", "new source"),
                    "type": "explicit",
                    "observation": f"New source flags potential contradiction: {c}",
                }
                for c in new_contradictions
            ])

        # Check for conflicting claims (same topic, opposite statements)
        new_claims = new_analysis.get("claims", [])
        for new_claim in new_claims:
            new_statement = new_claim.get("statement", "").lower()

            # Look for negation patterns
            negation_words = ["not", "no", "never", "unlikely", "fails", "contradicts", "opposes"]
            is_negated = any(word in new_statement for word in negation_words)

            for existing in existing_sources:
                for existing_claim in existing.get("claims", []):
                    existing_statement = existing_claim.get("statement", "").lower()
                    existing_is_negated = any(word in existing_statement for word in negation_words)

                    # Check if same topic but opposite stance
                    new_words = set(new_statement.split()) - {"not", "no", "never"}
                    existing_words = set(existing_statement.split()) - {"not", "no", "never"}
                    overlap = len(new_words & existing_words) / max(len(new_words | existing_words), 1)

                    if overlap >= CONTRADICTION_OVERLAP_THRESHOLD and is_negated != existing_is_negated:
                        contradictions.append({
                            "new_claim": new_claim.get("statement"),
                            "existing_claim": existing_claim.get("statement"),
                            "existing_source": existing.get("_source_file", "unknown"),
                            "type": "implicit_conflict",
                            "observation": "Claims on same topic have opposing stances",
                        })

        return contradictions

    def _find_knowledge_gaps(
        self,
        new_analysis: dict,
        existing_sources: list[dict],
    ) -> list[dict]:
        """Identify knowledge gaps that need more information."""
        gaps = []

        # Gaps from new source
        new_gaps = new_analysis.get("data_gaps", [])
        if new_gaps:
            gaps.extend([
                {
                    "gap": g,
                    "source": "new source",
                    "type": "explicit_gap",
                    "observation": f"Source identifies gap: {g}",
                }
                for g in new_gaps
            ])

        # Topics mentioned but not covered in wiki
        new_topics = new_analysis.get("topics", [])
        existing_topics = self._get_existing_topics()

        for topic in new_topics:
            topic_lower = topic.lower()
            if topic_lower not in existing_topics and len(topic) > 3:
                gaps.append({
                    "gap": f"Topic '{topic}' is mentioned but not covered in wiki",
                    "source": "topic analysis",
                    "type": "missing_coverage",
                    "observation": f"Consider creating a page for '{topic}'",
                })

        return gaps

    def _find_suggested_updates(
        self,
        new_analysis: dict,
        existing_sources: list[dict],
    ) -> list[dict]:
        """Suggest existing wiki pages that should be updated."""
        updates = []

        # Entities that exist in wiki but have new information
        new_entities = new_analysis.get("entities", [])
        existing_entities = self._get_existing_entities()

        for entity in new_entities:
            entity_name = entity.get("name", "")
            if entity_name in existing_entities:
                updates.append({
                    "page": f"entities/{entity_name}",
                    "reason": f"New information about existing entity: {entity_name}",
                    "type": "entity_update",
                    "new_attributes": entity.get("attributes", {}),
                })

        # Topics with new claims
        new_claims = new_analysis.get("claims", [])
        for claim in new_claims:
            if claim.get("confidence") == "high":
                updates.append({
                    "page": "relevant concept pages",
                    "reason": f"New high-confidence claim: {claim.get('statement')[:80]}",
                    "type": "claim_addition",
                })

        return updates[:MAX_SUGGESTED_UPDATES]  # Limit suggestions

    def _find_new_entities(
        self,
        new_analysis: dict,
        existing_entities: set[str],
    ) -> list[dict]:
        """Find entities in new source that don't have wiki pages."""
        new_entities = []

        for entity in new_analysis.get("entities", []):
            entity_name = entity.get("name", "")
            if entity_name and entity_name not in existing_entities:
                new_entities.append({
                    "name": entity_name,
                    "type": entity.get("type", "unknown"),
                    "attributes": entity.get("attributes", {}),
                    "suggestion": f"Consider creating entities/{entity_name}.md",
                })

        return new_entities

    def _find_topic_overlap(
        self,
        new_analysis: dict,
        existing_topics: set[str],
    ) -> list[dict]:
        """Find overlap between new source topics and existing wiki."""
        overlaps = []

        for topic in new_analysis.get("topics", []):
            topic_lower = topic.lower()
            if topic_lower in existing_topics:
                overlaps.append({
                    "topic": topic,
                    "observation": f"Topic '{topic}' is already covered in wiki",
                    "suggestion": "Consider updating existing pages rather than creating new ones",
                })

        return overlaps

    def _generate_summary(
        self,
        new_analysis: dict,
        existing_sources: list[dict],
    ) -> str:
        """Generate a human-readable synthesis summary."""
        parts = []

        new_entities = len(new_analysis.get("entities", []))
        new_claims = len(new_analysis.get("claims", []))
        new_topics = len(new_analysis.get("topics", []))

        parts.append(f"New source analysis: {new_entities} entities, {new_claims} claims, {new_topics} topics")

        if existing_sources:
            parts.append(f"Compared against {len(existing_sources)} existing source(s)")

            reinforced = len(self._find_reinforced_claims(new_analysis, existing_sources))
            contradictions = len(self._find_new_contradictions(new_analysis, existing_sources))

            if reinforced > 0:
                parts.append(f"  ✅ {reinforced} claim(s) reinforced by existing sources")
            if contradictions > 0:
                parts.append(f"  ⚠️ {contradictions} potential contradiction(s) detected")

        return "\n".join(parts)
