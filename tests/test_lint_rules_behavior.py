"""Behavior tests for the 4 lint rules that previously had zero coverage.

Covers DataGapsRule / OutdatedPagesRule / KnowledgeGapsRule /
PotentialContradictionsRule with concrete trigger and no-trigger cases.
The old test_06_lint_rules.py only asserted ``"issues" in result``
(always true — lint() always returns that key), so these rules could
silently stop firing without any test failing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from llmwikify.kernel.wiki.lint.rules.data_gaps import DataGapsRule
from llmwikify.kernel.wiki.lint.rules.knowledge_gaps import KnowledgeGapsRule
from llmwikify.kernel.wiki.lint.rules.outdated_pages import OutdatedPagesRule
from llmwikify.kernel.wiki.lint.rules.potential_contradictions import (
    PotentialContradictionsRule,
)

# ─── DataGapsRule ──────────────────────────────────────────────────


class TestDataGapsRule:
    def _detect(self, content: str, wiki=None) -> list[dict]:
        results: list[dict] = []
        DataGapsRule().detect("test-page", content, wiki, results)
        return results

    def test_unsourced_claims_fires(self):
        # 3+ assertion lines, each > 21 chars, no Sources section
        content = (
            "# Report\n\n"
            "The market grew by fifteen percent last quarter alone.\n"
            "Revenue reached ten billion dollars across all segments.\n"
            "Analysts expect further consolidation in the coming months.\n"
        )
        results = self._detect(content)
        types = [r["type"] for r in results]
        assert "unsourced_claims" in types
        gap = next(r for r in results if r["type"] == "unsourced_claims")
        assert gap["assertion_count"] >= 3

    def test_unsourced_claims_not_fired_with_sources_section(self):
        content = (
            "# Report\n\n"
            "The market grew by fifteen percent last quarter alone.\n"
            "Revenue reached ten billion dollars across all segments.\n"
            "Analysts expect further consolidation in the coming months.\n\n"
            "## Sources\n\n- (raw/report.pdf)\n"
        )
        assert not any(
            r["type"] == "unsourced_claims" for r in self._detect(content)
        )

    def test_unsourced_claims_not_fired_with_few_assertions(self):
        # Only 1 long line — below MIN_ASSERTIONS_FOR_GAP (3)
        content = "# T\n\nOnly one long assertion line here for sure.\n"
        assert not any(
            r["type"] == "unsourced_claims" for r in self._detect(content)
        )

    def test_vague_temporal_fires(self):
        content = "# Page\n\nRecently the team decided to pivot.\n"
        results = self._detect(content)
        vague = [r for r in results if r["type"] == "vague_temporal"]
        assert vague, "expected vague_temporal for 'Recently'"
        assert "recently" in vague[0]["vague_references"]

    def test_vague_temporal_not_fired_without_vague_words(self):
        content = "# Page\n\nIn Q1 2026 the team decided to pivot.\n"
        assert not any(
            r["type"] == "vague_temporal" for r in self._detect(content)
        )


# ─── OutdatedPagesRule ─────────────────────────────────────────────


class TestOutdatedPagesRule:
    def _detect(self, content: str, wiki=None) -> list[dict]:
        results: list[dict] = []
        OutdatedPagesRule().detect("test-page", content, wiki, results)
        return results

    def test_fires_when_source_year_too_old(self):
        current = datetime.now(timezone.utc).year
        old_year = current - 5
        content = f"# Page\n\nData from (raw/old.pdf) mentions {old_year}.\n"
        results = self._detect(content)
        assert results, "expected potentially_outdated"
        assert results[0]["type"] == "potentially_outdated"
        assert results[0]["latest_year_mentioned"] == old_year

    def test_not_fired_without_source_refs(self):
        current = datetime.now(timezone.utc).year
        old_year = current - 5
        # Year present but no (raw/...) reference
        content = f"# Page\n\nData mentions {old_year} in the text.\n"
        assert self._detect(content) == []

    def test_not_fired_when_year_recent(self):
        current = datetime.now(timezone.utc).year
        content = f"# Page\n\nData from (raw/new.pdf) mentions {current}.\n"
        assert self._detect(content) == []


# ─── KnowledgeGapsRule ─────────────────────────────────────────────


class TestKnowledgeGapsRule:
    def test_isolated_source_fires(self, wiki_instance):
        # sources/ page with no wikilinks → isolated_source
        wiki_instance.write_page(
            "sources/lonely", "# Lonely\n\nSome raw content without links.\n"
        )
        gaps = KnowledgeGapsRule().run(wiki_instance)
        isolated = [g for g in gaps if g["type"] == "isolated_source"]
        assert isolated, f"expected isolated_source, got {gaps}"
        assert isolated[0]["page"] == "sources/lonely"

    def test_source_with_wikilinks_not_flagged(self, wiki_instance):
        wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
        wiki_instance.write_page(
            "sources/linked", "# Linked\n\nAbout [[Foo]] here.\n"
        )
        gaps = KnowledgeGapsRule().run(wiki_instance)
        assert not any(
            g["type"] == "isolated_source" and g.get("page") == "sources/linked"
            for g in gaps
        )

    def test_no_sources_dir_returns_empty(self, wiki_instance):
        # No sources/ directory → no isolated_source issues
        wiki_instance.write_page("concepts/Only", "# Only\n\nContent.\n")
        gaps = KnowledgeGapsRule().run(wiki_instance)
        assert not any(g["type"] == "isolated_source" for g in gaps)


# ─── PotentialContradictionsRule ───────────────────────────────────


class TestPotentialContradictionsRule:
    def _detect(self, pages: dict[str, str], wiki=None) -> list[dict]:
        results: list[dict] = []
        PotentialContradictionsRule().detect_all(pages, wiki, results)
        return results

    def test_value_conflict_fires(self):
        pages = {
            "entities/A": "# A\n\nstatus: active\n",
            "entities/B": "# B\n\nstatus: deprecated\n",
        }
        results = self._detect(pages)
        conflicts = [r for r in results if r["type"] == "value_conflict"]
        assert conflicts, f"expected value_conflict, got {results}"
        assert conflicts[0]["attribute"] == "status"

    def test_value_conflict_not_fired_when_same_value(self):
        pages = {
            "entities/A": "# A\n\nstatus: active\n",
            "entities/B": "# B\n\nstatus: active\n",
        }
        assert not any(
            r["type"] == "value_conflict" for r in self._detect(pages)
        )

    def test_year_conflict_fires(self):
        pages = {
            "entities/A": "# A\n\nAcme was founded in 2010.\n",
            "entities/B": "# B\n\nAcme was founded in 2015.\n",
        }
        results = self._detect(pages)
        year = [r for r in results if r["type"] == "year_conflict"]
        assert year, f"expected year_conflict, got {results}"

    def test_negation_pattern_fires(self):
        pages = {
            "entities/A": "# A\n\nThe service is active.\n",
            "entities/B": "# B\n\nThe service is not active.\n",
        }
        results = self._detect(pages)
        neg = [r for r in results if r["type"] == "negation_pattern"]
        assert neg, f"expected negation_pattern, got {results}"

    def test_no_contradiction_on_clean_wiki(self):
        pages = {
            "concepts/Foo": "# Foo\n\nA clean concept page with prose.\n",
            "concepts/Bar": "# Bar\n\nAnother clean page, no conflicts.\n",
        }
        assert self._detect(pages) == []


# ─── Weak-assertion regression: lint() must surface rule types ────


class TestLintSurfacesRuleTypes:
    """wiki.lint() must actually route rule hits into the result dict.

    The old scenario tests only checked ``"issues" in result`` — a key
    that is always present. These assert the rule-specific buckets.
    """

    def test_data_gaps_appear_in_lint_result(self, wiki_instance):
        wiki_instance.write_page(
            "report",
            "# Report\n\n"
            "The market grew by fifteen percent last quarter alone.\n"
            "Revenue reached ten billion dollars across all segments.\n"
            "Analysts expect further consolidation in the coming months.\n",
        )
        result = wiki_instance.lint(force=True)
        # data_gaps are routed under investigations, not top-level
        inv = result.get("investigations") or {}
        data_gaps = inv.get("data_gaps") or []
        types = {g.get("type") for g in data_gaps}
        assert "unsourced_claims" in types, f"investigations={inv}"

    def test_outdated_pages_appear_in_investigations(self, wiki_instance):
        current = datetime.now(timezone.utc).year
        old_year = current - 5
        wiki_instance.write_page(
            "old-data",
            f"# Old\n\nFigures from (raw/old.pdf) cite {old_year}.\n",
        )
        result = wiki_instance.lint(force=True)
        outdated = (result.get("investigations") or {}).get("outdated_pages") or []
        assert outdated, f"investigations={result.get('investigations')}"

    def test_brief_mode_returns_issue_count(self, wiki_instance):
        wiki_instance.write_page("p", "# P\n\nContent.\n")
        result = wiki_instance.lint(mode="brief", force=True)
        assert "issue_count" in result
        assert isinstance(result["issue_count"], int)
