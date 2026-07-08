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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..wiki import Wiki

from ..lint import LintEngine
from ..lint.rules import RULES

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
        # Phase 1 #3 — the 8 detection rules are now in
        # core.lint.rules. LintEngine runs all of them in one
        # place; this analyzer aggregates their results with
        # LLM-based investigations, sink warnings, etc.
        self._lint_engine = LintEngine(wiki, rules=RULES)

    def _scan_all_pages(self) -> tuple[dict[str, int], set[str]]:
        """Single filesystem pass: extract link targets + detect orphan candidates.

        Returns:
            link_counts: target page name → reference count across all pages
            orphan_candidates: set of page names with zero inbound links
        """
        link_counts: dict[str, int] = {}
        page_names: list[str] = []
        for page in self.wiki._wiki_pages():
            name = self.wiki._page_display_name(page)
            if self.wiki._should_exclude_orphan(name, page):
                continue
            page_names.append(name)
            content = page.read_text()
            for link in re.findall(r'\[\[(.*?)\]\]', content):
                target = self.wiki._parse_wikilink_target(link)
                if target not in (self.wiki._index_page_name, self.wiki._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        inbound_counts = self.wiki.index.count_inbound_for_pages(page_names)
        orphan_candidates = {name for name in page_names if not inbound_counts.get(name)}
        return link_counts, orphan_candidates

    # ── Rule-based detectors ──────────────────────────────────────────

    def _run_rule(self, rule_name: str) -> list[dict]:
        """Run a single lint rule by name. Delegates to LintEngine."""
        return self._lint_engine.run_rule(rule_name)

    def _run_all_rules(self) -> list[dict]:
        """Run all lint rules. Delegates to LintEngine."""
        return self._lint_engine.run_all()

    def _detect_dated_claims(self) -> list[dict]:
        """Run the lint rule ``dated_claim`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("dated_claim")
    def _detect_query_page_overlap(self) -> list[dict]:
        """Run the lint rule ``topic_overlap`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("topic_overlap")
    def _detect_missing_cross_refs(self) -> list[dict]:
        """Run the lint rule ``missing_cross_ref`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("missing_cross_ref")
    def _detect_potential_contradictions(self) -> list[dict]:
        """Run the lint rule ``contradiction`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("contradiction")
    def _detect_data_gaps(self) -> list[dict]:
        """Run the lint rule ``data_gap`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("data_gap")
    def _detect_outdated_pages(self) -> list[dict]:
        """Run the lint rule ``potentially_outdated`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("potentially_outdated")
    def _detect_knowledge_gaps(self) -> list[dict]:
        """Run the lint rule ``knowledge_gap`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("knowledge_gap")
    def _detect_redundancy(self) -> list[dict]:
        """Run the lint rule ``redundancy`` (Phase 1 #3: delegated to LintEngine)."""
        return self._run_rule("redundancy")
    # ── LLM-enhanced detection ────────────────────────────────────────

    def _llm_generate_investigations(
        self,
        contradictions: list[dict],
        data_gaps: list[dict],
    ) -> dict:
        """Use LLM to generate investigation suggestions."""
        try:
            from ....foundation.llm import LLMClient
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
            from ....foundation.llm import LLMClient
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

        link_counts, orphan_candidates = self._scan_all_pages()

        # Broken links: need page content to extract wikilinks
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

        # Orphans: use batch result from _scan_all_pages
        for page in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page)
            if page_name in orphan_candidates:
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

        # Phase 1 #3: lint() no longer calls each _detect_X in turn.
        # It uses _run_all_rules() to get all rule results in one
        # call, then partitions them by type into the investigation
        # categories that downstream consumers expect.
        all_rule_results = self._run_all_rules()
        contradictions = [r for r in all_rule_results if r.get("type") in
                          ("value_conflict", "year_conflict", "negation_pattern")]
        data_gaps = [r for r in all_rule_results if r.get("type") in
                     ("unsourced_claims", "vague_temporal")]
        outdated_pages = [r for r in all_rule_results if r.get("type") == "potentially_outdated"]
        knowledge_gaps = [r for r in all_rule_results if r.get("type") in
                          ("unreferenced_entity", "isolated_source")]
        redundancy_alerts = [r for r in all_rule_results if r.get("type") == "similar_page_names"]

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
        link_counts, orphan_candidates = self._scan_all_pages()

        missing_pages = []
        for target, count in link_counts.items():
            if count >= 2:
                if self.wiki._resolve_wikilink_target(target) is None:
                    missing_pages.append({
                        "page": target,
                        "reference_count": count,
                    })

        orphan_pages = [{"page": name} for name in orphan_candidates]

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

        link_counts, orphan_candidates = self._scan_all_pages()

        if orphan_candidates:
            hints.append({
                "type": "orphan",
                "priority": "medium",
                "message": f"You have {len(orphan_candidates)} orphan page(s). Consider adding cross-references to connect them.",
            })

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

        # Broken links: need page content to extract wikilinks
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
