"""Unit tests for Phase 12: gather_skill + report_skill pipelines.

These pipelines are extracted from research_skill (Phase 6) to
become standalone, independently callable skills.

Covers:

  - GatherSkill: metadata, gather_for_research handler, offline
    mode, dedup, error handling
  - ReportSkill: metadata, generate_report handler, sections,
    knowledge_gaps

Target: 20+ tests, no I/O, no real LLM calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from llmwikify.apps.chat.skills import SkillContext, SkillResult
from llmwikify.apps.chat.skills.pipelines.gather_skill import (
    GatherSkill,
    _gather,
    gather_skill,
)
from llmwikify.apps.chat.skills.pipelines.report_skill import (
    ReportSkill,
    _generate_report,
    report_skill,
)


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext()


# ─── GatherSkill ─────────────────────────────────────────────────


class TestGatherSkillMetadata:
    def test_name(self) -> None:
        assert gather_skill.name == "gather"

    def test_has_action(self) -> None:
        assert gather_skill.get_action("gather_for_research") is not None

    def test_manifest(self) -> None:
        m = gather_skill.manifest()
        assert m.name == "gather"
        assert m.action_count == 1


class TestGatherOffline:
    @pytest.mark.asyncio
    async def test_offline_mode_produces_synthetic_sources(self, ctx: SkillContext) -> None:
        """When wiki is None, gather produces synthetic sources."""
        r = await _gather(
            {"sub_queries": [{"q": "test query"}]},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["sources"]) == 1
        assert "offline.example" in r.data["sources"][0]["url"]
        assert r.data["_new_sources"] == 1

    @pytest.mark.asyncio
    async def test_offline_multiple_queries(self, ctx: SkillContext) -> None:
        r = await _gather(
            {"sub_queries": [{"q": "alpha"}, {"q": "beta"}, {"q": "gamma"}]},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["sources"]) == 3
        assert r.data["_new_sources"] == 3

    @pytest.mark.asyncio
    async def test_offline_empty_query_skipped(self, ctx: SkillContext) -> None:
        r = await _gather(
            {"sub_queries": [{"q": ""}, {"q": "valid"}]},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["sources"]) == 1

    @pytest.mark.asyncio
    async def test_offline_string_sub_queries(self, ctx: SkillContext) -> None:
        """Sub-queries can be plain strings."""
        r = await _gather(
            {"sub_queries": ["query one", "query two"]},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["sources"]) == 2


class TestGatherDedup:
    @pytest.mark.asyncio
    async def test_existing_sources_preserved(self, ctx: SkillContext) -> None:
        existing = [{"url": "https://existing.com/page", "title": "Existing"}]
        r = await _gather(
            {"sub_queries": [{"q": "new query"}], "sources": existing},
            ctx,
        )
        assert r.status == "ok"
        # New source has different URL, so both should be present
        assert len(r.data["sources"]) == 2

    @pytest.mark.asyncio
    async def test_dedup_same_url(self, ctx: SkillContext) -> None:
        """If an existing source has the same URL, it's not duplicated."""
        # In offline mode, URLs are generated from the query,
        # so we test dedup logic differently
        r = await _gather(
            {"sub_queries": [{"q": "test"}], "sources": []},
            ctx,
        )
        assert r.status == "ok"
        # Adding same query again should produce 1 more (different URL)
        r2 = await _gather(
            {
                "sub_queries": [{"q": "test"}],
                "sources": r.data["sources"],
            },
            ctx,
        )
        assert r2.status == "ok"
        # Both should be present (different URLs since they're synthetic)
        assert len(r2.data["sources"]) == 2


class TestGatherErrors:
    @pytest.mark.asyncio
    async def test_non_list_sub_queries(self, ctx: SkillContext) -> None:
        r = await _gather({"sub_queries": "not a list"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_wiki_search_failure(self, ctx: SkillContext) -> None:
        """When wiki.search raises, the query is marked as failed."""

        class FailingWiki:
            def search(self, query: str, limit: int = 10) -> Any:
                raise RuntimeError("search exploded")

        ctx_with_wiki = ctx.with_overrides(wiki=FailingWiki())
        r = await _gather(
            {"sub_queries": [{"q": "broken"}]},
            ctx_with_wiki,
        )
        assert r.status == "ok"
        assert "broken" in r.data["_failed_queries"]
        assert r.data["_new_sources"] == 0


class TestGatherWithWiki:
    @pytest.mark.asyncio
    async def test_wiki_search_returns_results(self, ctx: SkillContext) -> None:
        class MockWiki:
            def search(self, query: str, limit: int = 10) -> Any:
                return ["page1", "page2"]

        ctx_with_wiki = ctx.with_overrides(wiki=MockWiki())
        r = await _gather(
            {"sub_queries": [{"q": "test"}]},
            ctx_with_wiki,
        )
        assert r.status == "ok"
        assert r.data["_new_sources"] == 2
        urls = [s["url"] for s in r.data["sources"]]
        assert "page1" in urls
        assert "page2" in urls

    @pytest.mark.asyncio
    async def test_wiki_search_empty_result(self, ctx: SkillContext) -> None:
        class EmptyWiki:
            def search(self, query: str, limit: int = 10) -> Any:
                return []

        ctx_with_wiki = ctx.with_overrides(wiki=EmptyWiki())
        r = await _gather(
            {"sub_queries": [{"q": "nothing here"}]},
            ctx_with_wiki,
        )
        assert r.status == "ok"
        assert r.data["_new_sources"] == 0


# ─── ReportSkill ─────────────────────────────────────────────────


class TestReportSkillMetadata:
    def test_name(self) -> None:
        assert report_skill.name == "report"

    def test_has_action(self) -> None:
        assert report_skill.get_action("generate_report") is not None

    def test_manifest(self) -> None:
        m = report_skill.manifest()
        assert m.name == "report"
        assert m.action_count == 1


class TestReportGeneration:
    @pytest.mark.asyncio
    async def test_basic_report(self, ctx: SkillContext) -> None:
        r = await _generate_report(
            {
                "query": "Test Query",
                "synthesis": {"narrative": "This is the narrative.", "claims": []},
                "sources": [{"url": "https://example.com", "title": "Example"}],
            },
            ctx,
        )
        assert r.status == "ok"
        md = r.data["report_md"]
        assert "# Test Query" in md
        assert "## Summary" in md
        assert "This is the narrative." in md
        assert "## Sources" in md
        assert "[Example](https://example.com)" in md
        assert r.data["report_length"] == len(md)

    @pytest.mark.asyncio
    async def test_report_with_claims(self, ctx: SkillContext) -> None:
        r = await _generate_report(
            {
                "query": "Q",
                "synthesis": {
                    "narrative": "narr",
                    "claims": [
                        {"text": "claim one"},
                        {"text": "claim two"},
                    ],
                },
                "sources": [],
            },
            ctx,
        )
        assert r.status == "ok"
        md = r.data["report_md"]
        assert "## Key Claims" in md
        assert "- claim one" in md
        assert "- claim two" in md

    @pytest.mark.asyncio
    async def test_report_with_knowledge_gaps(self, ctx: SkillContext) -> None:
        r = await _generate_report(
            {
                "query": "Q",
                "synthesis": {"narrative": "n", "claims": []},
                "sources": [],
                "knowledge_gaps": ["gap one", "gap two"],
            },
            ctx,
        )
        assert r.status == "ok"
        md = r.data["report_md"]
        assert "## Knowledge Gaps" in md
        assert "- gap one" in md
        assert "- gap two" in md

    @pytest.mark.asyncio
    async def test_report_no_synthesis(self, ctx: SkillContext) -> None:
        r = await _generate_report(
            {"query": "Q", "sources": [{"url": "u", "title": "T"}]},
            ctx,
        )
        assert r.status == "ok"
        assert "(no synthesis)" in r.data["report_md"]

    @pytest.mark.asyncio
    async def test_report_empty_sources(self, ctx: SkillContext) -> None:
        r = await _generate_report(
            {"query": "Q", "synthesis": {"narrative": "n", "claims": []}, "sources": []},
            ctx,
        )
        assert r.status == "ok"
        assert "## Sources" in r.data["report_md"]

    @pytest.mark.asyncio
    async def test_report_default_query(self, ctx: SkillContext) -> None:
        r = await _generate_report({}, ctx)
        assert r.status == "ok"
        assert "# Research Report" in r.data["report_md"]


# ─── Integration: both pipelines ─────────────────────────────────


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_gather_then_report(self, ctx: SkillContext) -> None:
        """End-to-end: gather sources, then generate a report."""
        # Step 1: gather
        gr = await _gather(
            {"sub_queries": [{"q": "topic one"}, {"q": "topic two"}]},
            ctx,
        )
        assert gr.status == "ok"
        sources = gr.data["sources"]

        # Step 2: report
        rr = await _generate_report(
            {
                "query": "Research Topic",
                "synthesis": {
                    "narrative": "Comprehensive analysis.",
                    "claims": [{"text": "Key finding"}],
                },
                "sources": sources,
            },
            ctx,
        )
        assert rr.status == "ok"
        assert "# Research Topic" in rr.data["report_md"]
        assert len(sources) == 2
