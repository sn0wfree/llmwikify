"""Wiki health check, lint detection, and recommendation engine.

This module extracts the detection/lint/recommend/hint logic from Wiki
into a standalone class. It uses composition (takes a Wiki instance)
rather than inheritance, making it independently testable and maintainable.

Design principle: read-only analysis — never modifies wiki state.
"""

import json
import logging
import re
import warnings
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .constants import (
    JACCARD_OVERLAP_THRESHOLD,
    MAX_CONTRADICTIONS,
    MAX_CROSS_REF_HINTS,
    MAX_DATED_CLAIM_HINTS,
    MAX_MISSING_DISPLAY,
    MAX_QUERY_OVERLAP_HINTS,
    MAX_SUMMARY_ITEMS,
    MIN_ASSERTION_LENGTH,
    MIN_ASSERTIONS_FOR_GAP,
    MIN_KEYWORD_LENGTH,
    MIN_MISSING_REF_COUNT,
    MIN_YEAR_THRESHOLD,
    OUTDATED_YEAR_GAP,
    STOP_WORDS,
    YEAR_GAP_THRESHOLD,
)

if TYPE_CHECKING:
    from .wiki import Wiki

logger = logging.getLogger(__name__)


class WikiAnalyzer:
    """Health check, lint detection, and recommendation engine for Wiki.

    Usage:
        analyzer = WikiAnalyzer(wiki)
        result = analyzer.lint()
        recommendations = analyzer.recommend()
    """

    def __init__(self, wiki: "Wiki"):
        self.wiki = wiki

    # ── Rule-based detectors ──────────────────────────────────────────

    def _detect_dated_claims(self) -> list[dict]:
        """Find year mentions in pages that predate latest raw source by 3+ years."""
        hints = []
        now = datetime.now(timezone.utc)
        current_year = now.year

        latest_source_year = 0
        if self.wiki.raw_dir.exists():
            for src in self.wiki.raw_dir.rglob("*"):
                if not src.is_file():
                    continue
                content = src.read_text(errors="ignore")
                years = re.findall(r'\b(20\d{2})\b', content)
                if years:
                    latest_source_year = max(latest_source_year, max(int(y) for y in years))

        if latest_source_year == 0:
            return hints

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            if page_name.startswith("Query:"):
                continue

            content = page.read_text()
            years_in_page = re.findall(r'\b(20\d{2})\b', content)

            for year_str in years_in_page:
                year = int(year_str)
                if MIN_YEAR_THRESHOLD <= year <= current_year - YEAR_GAP_THRESHOLD:
                    if latest_source_year - year >= YEAR_GAP_THRESHOLD:
                        hints.append({
                            "type": "dated_claim",
                            "page": page_name,
                            "file": str(page),
                            "claim_year": year,
                            "latest_source_year": latest_source_year,
                            "gap_years": latest_source_year - year,
                            "observation": (
                                f"'{page_name}' references {year}, but the latest raw source is from {latest_source_year}. "
                                f"The gap is {latest_source_year - year} years. "
                                f"Content may be outdated."
                            ),
                        })
                        break

            if len(hints) >= MAX_DATED_CLAIM_HINTS:
                break

        return hints[:MAX_DATED_CLAIM_HINTS]

    def _detect_query_page_overlap(self) -> list[dict]:
        """Find Query: pages with >=85% keyword Jaccard overlap."""
        hints = []
        if not self.wiki.wiki_dir.exists():
            return hints

        query_pages = []
        for page in self.wiki.wiki_dir.rglob("*.md"):
            if '.sink' in str(page):
                continue
            page_name = page.stem
            if not page_name.startswith("Query:"):
                continue

            keywords = {
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in STOP_WORDS and len(w) > MIN_KEYWORD_LENGTH
            }

            if keywords:
                query_pages.append({
                    "page_name": page_name,
                    "keywords": keywords,
                    "file": str(page),
                })

        seen_pairs = set()
        for i in range(len(query_pages)):
            for j in range(i + 1, len(query_pages)):
                p1 = query_pages[i]
                p2 = query_pages[j]

                union = len(p1["keywords"] | p2["keywords"])
                if union == 0:
                    continue

                overlap = len(p1["keywords"] & p2["keywords"])
                jaccard = overlap / union

                if jaccard >= JACCARD_OVERLAP_THRESHOLD:
                    pair_key = tuple(sorted([p1["page_name"], p2["page_name"]]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        hints.append({
                            "type": "topic_overlap",
                            "page_a": p1["page_name"],
                            "page_b": p2["page_name"],
                            "jaccard_score": round(jaccard, 3),
                            "shared_keywords": sorted(p1["keywords"] & p2["keywords"]),
                            "observation": (
                                f"'{p1['page_name']}' and '{p2['page_name']}' share {len(p1['keywords'] & p2['keywords'])} keywords "
                                f"(Jaccard: {jaccard:.0%}). They may cover overlapping topics."
                            ),
                        })

            if len(hints) >= MAX_QUERY_OVERLAP_HINTS:
                break

        return hints[:MAX_QUERY_OVERLAP_HINTS]

    def _detect_missing_cross_refs(self) -> list[dict]:
        """Find concepts mentioned in 2+ pages but not wikilinked."""
        hints = []

        if not self.wiki.wiki_dir.exists():
            return hints

        existing_pages = set()
        for page in self.wiki._wiki_pages():
            existing_pages.add(self.wiki._page_display_name(page))

        concept_mentions: dict[str, list[str]] = {}

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)

            content = page.read_text()

            wikilinks = set()
            for link in re.findall(r'\[\[(.*?)\]\]', content):
                target = self.wiki._parse_wikilink_target(link)
                wikilinks.add(target)

            content_text = re.sub(r'\[\[.*?\]\]', '', content)

            for candidate in existing_pages:
                if candidate == page_name:
                    continue
                if candidate in wikilinks:
                    continue

                pattern = r'\b' + re.escape(candidate) + r'\b'
                if re.search(pattern, content_text, re.IGNORECASE):
                    if candidate not in concept_mentions:
                        concept_mentions[candidate] = []
                    concept_mentions[candidate].append(page_name)

        for concept, pages in sorted(concept_mentions.items(), key=lambda x: -len(x[1])):
            if len(pages) >= MIN_MISSING_REF_COUNT:
                hints.append({
                    "type": "missing_cross_ref",
                    "concept": concept,
                    "mentioning_pages": pages[:MAX_MISSING_DISPLAY],
                    "mention_count": len(pages),
                    "observation": (
                        f"'{concept}' is mentioned in {len(pages)} pages ({', '.join(pages[:3])}"
                        f"{'...' if len(pages) > 3 else ''}) but not linked. "
                        f"Consider adding [[{concept}]] wikilinks."
                    ),
                })

            if len(hints) >= MAX_CROSS_REF_HINTS:
                break

        return hints[:MAX_CROSS_REF_HINTS]

    def _detect_potential_contradictions(self) -> list[dict]:
        """Scan wiki pages for potential contradictions."""
        contradictions = []
        seen_pairs = set()

        if not self.wiki.wiki_dir.exists():
            return contradictions

        pages_content = {}
        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            pages_content[page_name] = page.read_text()

        entity_facts: dict[str, dict[str, list[tuple]]] = {}
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                line = line.strip().lstrip('- ').strip()
                if ':' in line and not line.startswith('#') and not line.startswith('http'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        if len(key) >= 2 and len(key) <= 30 and len(value) >= 2 and len(value) <= 50:
                            if key not in entity_facts:
                                entity_facts[key] = {}
                            if page_name not in entity_facts[key]:
                                entity_facts[key][page_name] = []
                            entity_facts[key][page_name].append(value)

        for attr, page_values in entity_facts.items():
            if len(page_values) < 2:
                continue
            all_values = []
            for page_name, values in page_values.items():
                for v in values:
                    all_values.append((page_name, v))

            unique_values = {str(v).lower() for _, v in all_values}
            if len(unique_values) >= 2:
                pair_key = tuple(sorted([p for p, _ in all_values]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    values_str = ", ".join(f"{p}={v}" for p, v in all_values[:3])
                    contradictions.append({
                        "type": "value_conflict",
                        "attribute": attr,
                        "pages": [{"page": p, "value": v} for p, v in all_values[:4]],
                        "observation": f"Pages reference different values for '{attr}': {values_str}",
                    })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        year_claims: dict[str, list[dict]] = {}
        year_pattern = re.compile(
            r'([^\n]{3,30}?)\s+(?:launched|founded|started|established|created|born|died|closed|shutdown|ended)\s+(?:in\s+)?(20\d{2}|19\d{2})',
            re.IGNORECASE
        )
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                for match in year_pattern.finditer(line):
                    entity = match.group(1).strip()
                    year = match.group(2)
                    if entity and len(entity) <= 30:
                        if entity not in year_claims:
                            year_claims[entity] = []
                        year_claims[entity].append({"page": page_name, "year": year})

        for entity, claims in year_claims.items():
            years = {c["year"] for c in claims}
            if len(years) >= 2:
                claims_str = ", ".join(f"{c['page']}={c['year']}" for c in claims[:3])
                contradictions.append({
                    "type": "year_conflict",
                    "entity": entity,
                    "claims": claims,
                    "observation": f"'{entity}' has conflicting year claims: {claims_str}",
                })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        negation_claims: dict[str, list[dict]] = {}
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                assertion_pattern = re.compile(
                    r'([\w\s]{3,25}?)\s+(?:is|are|was|were)\s+(?:not\s+|no\s+longer\s+)?([\w\s]{3,30}?)(?:\.|,|;|$)',
                    re.IGNORECASE
                )
                for match in assertion_pattern.finditer(line):
                    subject = match.group(1).strip()
                    predicate = match.group(2).strip()
                    full_match = match.group(0).lower()
                    is_negated = bool(re.search(r'\b(?:is|are|was|were)\s+(?:not|no longer)', full_match))

                    key = subject.lower()
                    if key not in negation_claims:
                        negation_claims[key] = []
                    negation_claims[key].append({
                        "page": page_name,
                        "predicate": predicate,
                        "negated": is_negated,
                    })

        for subject, claims in negation_claims.items():
            has_positive = any(not c["negated"] for c in claims)
            has_negative = any(c["negated"] for c in claims)
            if has_positive and has_negative:
                contradictions.append({
                    "type": "negation_pattern",
                    "subject": subject,
                    "claims": claims,
                    "observation": f"'{subject}' has both affirmative and negative claims across pages",
                })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        return contradictions[:MAX_CONTRADICTIONS]

    def _detect_data_gaps(self) -> list[dict]:
        """Detect potential data gaps in wiki pages."""
        gaps = []

        if not self.wiki.wiki_dir.exists():
            return gaps

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            if page_name.startswith("Query:"):
                continue

            content = page.read_text()

            has_sources_section = bool(re.search(r'^#{1,3}\s+Sources', content, re.MULTILINE | re.IGNORECASE))
            has_inline_citations = bool(re.search(r'\[Source[^\]]*\]\(', content))

            lines = content.split('\n')
            assertion_lines = [
                line.strip() for line in lines
                if line.strip()
                and not line.startswith('#')
                and not line.startswith('---')
                and not line.startswith('[')
                and len(line.strip()) > MIN_ASSERTION_LENGTH
            ]

            if len(assertion_lines) >= MIN_ASSERTIONS_FOR_GAP and not has_sources_section and not has_inline_citations:
                gaps.append({
                    "type": "unsourced_claims",
                    "page": page_name,
                    "assertion_count": len(assertion_lines),
                    "observation": (
                        f"'{page_name}' contains {len(assertion_lines)} assertion(s) "
                        f"without cited sources"
                    ),
                })

            if len(gaps) >= MAX_CONTRADICTIONS:
                break

            vague_time_words = re.findall(
                r'\b(recently|soon|upcoming|former|previous|last year|next year|in the past|currently|nowadays|these days)\b',
                content, re.IGNORECASE
            )
            if vague_time_words:
                gaps.append({
                    "type": "vague_temporal",
                    "page": page_name,
                    "vague_references": list({w.lower() for w in vague_time_words})[:MAX_SUMMARY_ITEMS],
                    "observation": (
                        f"'{page_name}' uses vague temporal references: "
                        f"{', '.join({w.lower() for w in vague_time_words[:3]})}"
                    ),
                })

            if len(gaps) >= MAX_CONTRADICTIONS:
                break

        return gaps[:MAX_CONTRADICTIONS]

    def _detect_outdated_pages(self) -> list[dict]:
        """Detect pages that may be outdated based on source dates."""
        outdated = []
        current_year = datetime.now(timezone.utc).year

        if not self.wiki.wiki_dir.exists():
            return outdated

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            if page_name.startswith("Query:"):
                continue

            content = page.read_text()

            source_refs = re.findall(r'\(raw/([^)]+)\)', content)
            if source_refs:
                years_in_page = re.findall(r'\b(20\d{2})\b', content)
                if years_in_page:
                    latest_year = max(int(y) for y in years_in_page)
                    if current_year - latest_year >= OUTDATED_YEAR_GAP:
                        outdated.append({
                            "type": "potentially_outdated",
                            "page": page_name,
                            "latest_year_mentioned": latest_year,
                            "current_year": current_year,
                            "observation": (
                                f"'{page_name}' references {latest_year} as latest date. "
                                f"May need review with newer sources."
                            ),
                        })

            if len(outdated) >= MAX_CONTRADICTIONS:
                break

        return outdated[:MAX_CONTRADICTIONS]

    def _detect_knowledge_gaps(self) -> list[dict]:
        """Detect knowledge gaps across the wiki."""
        gaps = []

        if not self.wiki.wiki_dir.exists():
            return gaps

        try:
            engine = self.wiki.get_relation_engine()
            orphan_concepts = engine.find_orphan_concepts()
            for concept in orphan_concepts[:3]:
                gaps.append({
                    "type": "unreferenced_entity",
                    "concept": concept,
                    "observation": f"'{concept}' is in the knowledge graph but has no wiki page",
                    "suggestion": f"Consider creating a page for '{concept}'",
                })
        except Exception as e:
            logger.warning("Relation engine orphan detection failed: %s", e)

        sources_dir = self.wiki.wiki_dir / "sources"
        if sources_dir.exists():
            for source_page in sources_dir.rglob("*.md"):
                page_name = self.wiki._page_display_name(source_page)
                content = source_page.read_text()
                wikilinks = re.findall(r'\[\[(.*?)\]\]', content)
                if not wikilinks:
                    gaps.append({
                        "type": "isolated_source",
                        "page": page_name,
                        "observation": f"Source page '{page_name}' has no wikilinks to other pages",
                        "suggestion": "Consider adding cross-references to related concepts/entities",
                    })

                if len(gaps) >= 3:
                    break

        return gaps[:3]

    def _detect_redundancy(self) -> list[dict]:
        """Detect potentially redundant or overlapping content."""
        redundancy = []
        pages = self.wiki._wiki_pages()

        if not pages:
            return redundancy

        page_names = [self.wiki._page_display_name(p) for p in pages]
        for i, name1 in enumerate(page_names):
            for name2 in page_names[i+1:]:
                if (name1.lower() in name2.lower() or name2.lower() in name1.lower()):
                    if len(name1) > 5 and len(name2) > 5:
                        redundancy.append({
                            "type": "similar_page_names",
                            "page_a": name1,
                            "page_b": name2,
                            "observation": (
                                f"Pages '{name1}' and '{name2}' have similar names. "
                                f"Consider merging if they cover the same topic."
                            ),
                        })

            if len(redundancy) >= 2:
                break

        return redundancy[:2]

    # ── LLM-enhanced detection ────────────────────────────────────────

    def _llm_generate_investigations(
        self,
        contradictions: list[dict],
        data_gaps: list[dict],
    ) -> dict:
        """Use LLM to generate investigation suggestions."""
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.wiki.config)
        except (ImportError, ValueError, OSError):
            return {
                "suggested_questions": [],
                "suggested_sources": [],
                "warning": "LLM client not available",
            }

        registry = self.wiki._get_prompt_registry()

        total_pages = len(self.wiki._wiki_pages()) if self.wiki.wiki_dir.exists() else 0

        variables = {
            "contradictions_json": json.dumps(contradictions, indent=2),
            "data_gaps_json": json.dumps(data_gaps, indent=2),
            "total_pages": total_pages,
        }

        messages = registry.get_messages("investigate_lint", **variables)
        params = registry.get_params("investigate_lint")

        try:
            result = client.chat_json(messages, **params)
            if isinstance(result, dict):
                return {
                    "suggested_questions": result.get("suggested_questions", []),
                    "suggested_sources": result.get("suggested_sources", []),
                }
        except (ConnectionError, TimeoutError, ValueError, OSError):
            pass

        return {
            "suggested_questions": [],
            "suggested_sources": [],
            "warning": "LLM investigation generation failed",
        }

    def _build_lint_context(self, limit: int = 20) -> str:
        """Build minimal context for LLM lint analysis."""
        parts = []

        if self.wiki.wiki_md_file.exists():
            parts.append(f"=== WIKI SCHEMA (wiki.md) ===\n{self.wiki.wiki_md_file.read_text()}")

        pages = self.wiki._get_existing_page_names()
        pages_section = f"\n=== EXISTING PAGES ({len(pages)} total) ===\n"
        for p in sorted(pages)[:100]:
            pages_section += f"  - {p}\n"
        if len(pages) > 100:
            pages_section += f"  ... and {len(pages) - 100} more\n"
        parts.append(pages_section)

        raw_files = list(self.wiki.raw_dir.rglob("*")) if self.wiki.raw_dir.exists() else []
        raw_files = [f for f in raw_files if f.is_file()]
        if raw_files:
            src_section = f"\n=== SOURCE ANALYSIS ({len(raw_files)} total) ===\n"
            not_analyzed = []

            for f in sorted(raw_files)[:limit]:
                rel = str(f.relative_to(self.wiki.root))
                source_page = self.wiki._find_source_summary_page(rel)

                if source_page and source_page.exists():
                    cached = self.wiki._get_cached_source_analysis(source_page)
                    if cached:
                        data = cached.get('data', {})
                        entities = [e["name"] for e in data.get("entities", [])[:5]]
                        suggested = [f'{s["name"]}({s["type"]})' for s in data.get("suggested_pages", [])[:3]]
                        src_section += f"  - {rel}\n"
                        if entities:
                            src_section += f"    Entities: {', '.join(entities)}\n"
                        if suggested:
                            src_section += f"    Suggested pages: {', '.join(suggested)}\n"
                    else:
                        src_section += f"  - {rel} [NOT ANALYZED]\n"
                        not_analyzed.append(rel)
                else:
                    src_section += f"  - {rel} [NO SOURCE PAGE]\n"
                    not_analyzed.append(rel)

            if len(raw_files) > limit:
                src_section += f"  ... and {len(raw_files) - limit} more\n"

            if not_analyzed:
                src_section += f"\n=== UNANALYZED SOURCES ({len(not_analyzed)}) ===\n"
                src_section += "Run: wiki_analyze_source(source_path) or CLI: llmwikify analyze-source --all\n"

            parts.append(src_section)

        try:
            engine = self.wiki.get_relation_engine()
            orphans = engine.find_orphan_concepts()
            if orphans:
                orphan_section = "\n=== ORPHAN CONCEPTS (in relations but no wiki page) ===\n"
                for c in orphans[:20]:
                    orphan_section += f"  - {c}\n"
                if len(orphans) > 20:
                    orphan_section += f"  ... and {len(orphans) - 20} more\n"
                parts.append(orphan_section)
        except Exception as e:
            logger.warning("Failed to load orphan concepts for lint context: %s", e)

        return "\n\n".join(parts)

    def _llm_detect_gaps(self, context: str) -> list[dict]:
        """Call LLM to detect gaps between wiki schema and current state."""
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.wiki.config)
        except (ImportError, ValueError, OSError):
            return self._fallback_detect_gaps()

        registry = self.wiki._get_prompt_registry()

        try:
            messages = registry.get_messages("direct_lint", lint_context=context)
            params = registry.get_api_params("direct_lint")
            result = client.chat_json(messages, **params)

            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "gaps" in result:
                return result["gaps"]
        except (ConnectionError, TimeoutError, ValueError, OSError):
            pass

        return self._fallback_detect_gaps()

    def _fallback_detect_gaps(self) -> list[dict]:
        """Basic gap detection without LLM."""
        gaps = []

        try:
            engine = self.wiki.get_relation_engine()
            for concept in engine.find_orphan_concepts():
                gaps.append({
                    "type": "orphan_concept",
                    "concept": concept,
                    "note": "Detected without LLM",
                })
        except Exception as e:
            logger.warning("Fallback gap detection failed: %s", e)

        gaps.extend(self._detect_missing_cross_refs())

        return gaps

    # ── Orchestration ─────────────────────────────────────────────────

    def lint(
        self,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        generate_investigations: bool = False,
    ) -> dict:
        """Health check the wiki with schema-aware gap detection.

        Args:
            mode: "check" (detect only) or "fix" (reserved for future auto-repair).
            limit: Max LLM-detected issues to return.
            force: Force re-detection (reserved for future cache bypass).
            generate_investigations: If True, use LLM to suggest investigations.

        Note:
            mode="fix" and force=True are reserved for future implementation.
        """
        issues = []

        for page in self.wiki._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = self.wiki._parse_wikilink_target(link)
                if target in (self.wiki._index_page_name, self.wiki._log_page_name):
                    continue
                if self.wiki._resolve_wikilink_target(target) is None:
                    issues.append({
                        "type": "broken_link",
                        "page": self.wiki._page_display_name(page),
                        "link": target,
                        "file": str(page),
                    })

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)

            if self.wiki._should_exclude_orphan(page_name, page):
                continue

            inbound = self.wiki.index.get_inbound_links(page_name)
            if not inbound:
                issues.append({
                    "type": "orphan_page",
                    "page": page_name,
                    "file": str(page),
                })

        sink_status = self.wiki.query_sink.status()
        sink_warnings = []

        if isinstance(sink_status, dict) and 'sinks' in sink_status:
            for sink in sink_status['sinks']:
                if sink.get('urgency') in ('stale', 'aging'):
                    sink_warnings.append({
                        "type": "stale_sink",
                        "page_name": sink['page_name'],
                        "entry_count": sink['entry_count'],
                        "days_old": sink.get('days_since_last_entry', 0),
                        "urgency": sink['urgency'],
                        "suggestion": f"Review and merge {sink['entry_count']} pending entries",
                    })

        context = self._build_lint_context()
        llm_gaps = self._llm_detect_gaps(context)
        llm_gaps = llm_gaps[:limit]

        all_issues = issues + llm_gaps

        critical_hints = self._detect_dated_claims()
        informational_hints = []
        informational_hints.extend(self._detect_query_page_overlap())
        informational_hints.extend(self._detect_missing_cross_refs())

        critical_hints = critical_hints[:3]
        informational_hints = informational_hints[:5]

        contradictions = self._detect_potential_contradictions()
        data_gaps = self._detect_data_gaps()

        outdated_pages = self._detect_outdated_pages()
        knowledge_gaps = self._detect_knowledge_gaps()
        redundancy_alerts = self._detect_redundancy()

        investigations = {
            "contradictions": contradictions,
            "data_gaps": data_gaps,
            "outdated_pages": outdated_pages,
            "knowledge_gaps": knowledge_gaps,
            "redundancy_alerts": redundancy_alerts,
        }

        if generate_investigations:
            llm_suggestions = self._llm_generate_investigations(contradictions, data_gaps)
            investigations.update(llm_suggestions)

        result = {
            "total_pages": len(self.wiki._wiki_pages()),
            "issue_count": len(all_issues),
            "issues": all_issues,
            "mode": mode,
            "schema_source": "wiki.md (direct)",
            "hints": {
                "critical": critical_hints,
                "informational": informational_hints,
            },
            "investigations": investigations,
            "sink_status": sink_status,
            "sink_warnings": sink_warnings,
        }

        if mode == "fix":
            fix_result = self.wiki.fix_wikilinks(dry_run=False)
            self.wiki._update_index_file()

            result["auto_fix"] = {
                "wikilinks_fixed": fix_result["fixed"],
                "wikilinks_skipped": fix_result["skipped"],
                "wikilinks_ambiguous": fix_result["ambiguous"],
                "wikilink_changes": fix_result["changes"][:20],
                "index_updated": True,
            }

        return result

    def recommend(self) -> dict:
        """Generate smart recommendations."""
        missing_pages = []
        orphan_pages = []

        link_counts = {}
        for page in self.wiki._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = self.wiki._parse_wikilink_target(link)
                if target not in (self.wiki._index_page_name, self.wiki._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        for target, count in link_counts.items():
            if count >= 2:
                if self.wiki._resolve_wikilink_target(target) is None:
                    missing_pages.append({
                        "page": target,
                        "reference_count": count,
                    })

        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)

            if self.wiki._should_exclude_orphan(page_name, page):
                continue

            inbound = self.wiki.index.get_inbound_links(page_name)
            if not inbound:
                orphan_pages.append({"page": page_name})

        return {
            "missing_pages": missing_pages,
            "orphan_pages": orphan_pages,
            "summary": {
                "total_missing_pages": len(missing_pages),
                "total_orphans": len(orphan_pages),
            },
        }

    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement.

        Deprecated: Use `lint(format="brief")` instead.
        """
        warnings.warn(
            "hint() is deprecated; use wiki.lint(format='brief') instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._generate_hints()

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        hints = []

        orphan_count = 0
        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            if self.wiki._should_exclude_orphan(page_name, page):
                continue
            inbound = self.wiki.index.get_inbound_links(page_name)
            if not inbound:
                orphan_count += 1

        if orphan_count > 0:
            hints.append({
                "type": "orphan",
                "priority": "medium",
                "message": f"You have {orphan_count} orphan page(s). Consider adding cross-references to connect them.",
            })

        link_counts = {}
        for page in self.wiki._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = self.wiki._parse_wikilink_target(link)
                if target not in (self.wiki._index_page_name, self.wiki._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        missing = []
        for target, count in link_counts.items():
            if count >= 2:
                if self.wiki._resolve_wikilink_target(target) is None:
                    missing.append(target)

        if missing:
            hints.append({
                "type": "missing",
                "priority": "high",
                "message": f"Pages referenced but don't exist: {', '.join(missing[:5])}",
            })

        page_count = len(self.wiki._wiki_pages())
        if page_count < 5:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is small. Consider ingesting more sources to build knowledge.",
            })
        elif page_count < 20:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is growing well. Consider running lint to check health.",
            })

        broken_count = 0
        for page in self.wiki._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = self.wiki._parse_wikilink_target(link)
                if target in (self.wiki._index_page_name, self.wiki._log_page_name):
                    continue
                if self.wiki._resolve_wikilink_target(target) is None:
                    broken_count += 1

        if broken_count > 0:
            hints.append({
                "type": "broken_links",
                "priority": "high",
                "message": f"Found {broken_count} broken link(s). Consider fixing or removing them.",
            })

        return {
            "hints": hints,
            "summary": {
                "total_hints": len(hints),
                "high_priority": sum(1 for h in hints if h['priority'] == 'high'),
            }
        }
