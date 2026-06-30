"""Unit tests for gather_skill (v0.39 enable_web_search fallback).

Covers the new ``enable_web_search`` parameter in
``gather_for_research`` action:

  - Default behavior unchanged (wiki-only, no web fallback)
  - When wiki returns results, web search is NOT invoked
  - When wiki returns 0 results AND enable_web_search=True,
    web search is invoked and its results are appended
  - Web search errors are logged but don't fail the gather

Target: 6 tests, all use mocks for wiki and WebSearch (no I/O).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmwikify.apps.chat.skills import SkillContext, SkillResult
from llmwikify.apps.chat.skills.pipelines.gather_skill import (
    _gather,
    gather_skill,
)
from llmwikify.apps.research.web_search import SearchResult


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext(config={"web_search_results_per_query": 3})


def _make_wiki_mock(search_return: list) -> MagicMock:
    """Build a wiki mock where ``wiki.search()`` returns the given list."""
    wiki = MagicMock()
    wiki.search = MagicMock(return_value=search_return)
    return wiki


# ─── Schema ──────────────────────────────────────────────────────


class TestSchema:
    def test_schema_has_enable_web_search(self) -> None:
        schema = gather_skill.actions["gather_for_research"].input_schema
        assert "enable_web_search" in schema["properties"]
        assert schema["properties"]["enable_web_search"]["type"] == "boolean"
        assert schema["properties"]["enable_web_search"]["default"] is False


# ─── Default behavior (no web fallback) ─────────────────────────


class TestDefaultBehavior:
    @pytest.mark.asyncio
    async def test_wiki_results_only_no_web_search_called(
        self, ctx: SkillContext,
    ) -> None:
        """Default behavior: web_search NOT invoked even if available."""
        wiki = _make_wiki_mock([
            {"url": "https://wiki/x", "title": "X"},
            {"url": "https://wiki/y", "title": "Y"},
        ])
        ctx = ctx.with_overrides(wiki=wiki)

        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            r = await _gather(
                {"sub_queries": [{"q": "test"}], "enable_web_search": False},
                ctx,
            )

        assert r.status == "ok"
        assert r.data["_new_sources"] == 2
        # WebSearch was NOT constructed
        MockSearch.assert_not_called()

    @pytest.mark.asyncio
    async def test_wiki_results_with_enable_flag_still_skips_web(
        self, ctx: SkillContext,
    ) -> None:
        """When wiki has results, web_search is skipped even with flag=True."""
        wiki = _make_wiki_mock([{"url": "https://wiki/x", "title": "X"}])
        ctx = ctx.with_overrides(wiki=wiki)

        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            r = await _gather(
                {"sub_queries": [{"q": "test"}], "enable_web_search": True},
                ctx,
            )

        assert r.status == "ok"
        # Wiki gave us 1 source, no need to fall back
        assert r.data["_new_sources"] == 1
        MockSearch.assert_not_called()


# ─── Fallback behavior ──────────────────────────────────────────


class TestWebSearchFallback:
    @pytest.mark.asyncio
    async def test_wiki_empty_triggers_web_search(
        self, ctx: SkillContext,
    ) -> None:
        """When wiki returns 0 results and flag is True, web_search is called."""
        wiki = _make_wiki_mock([])  # wiki returns nothing
        ctx = ctx.with_overrides(wiki=wiki)

        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[
                SearchResult("Web1", "https://example.com/1", "snippet1"),
                SearchResult("Web2", "https://example.com/2", "snippet2"),
            ])
            MockSearch.return_value = instance

            r = await _gather(
                {
                    "sub_queries": [{"q": "test"}],
                    "enable_web_search": True,
                    "max_sources_per_query": 5,
                },
                ctx,
            )

        assert r.status == "ok"
        assert r.data["_new_sources"] == 2
        # WebSearch was invoked with our query
        instance.search.assert_called_once()
        call_args = instance.search.call_args
        query_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("query", "")
        assert query_arg == "test"
        # Sources have source_type='web'
        web_sources = [s for s in r.data["sources"] if s.get("source_type") == "web"]
        assert len(web_sources) == 2

    @pytest.mark.asyncio
    async def test_wiki_empty_no_flag_keeps_synthetic_offline_path(
        self, ctx: SkillContext,
    ) -> None:
        """Wiki=None path: synthetic offline source (existing behavior preserved)."""
        ctx = ctx.with_overrides(wiki=None)

        r = await _gather(
            {"sub_queries": [{"q": "test"}], "enable_web_search": False},
            ctx,
        )

        assert r.status == "ok"
        # Synthetic offline source added
        assert r.data["_new_sources"] == 1
        assert r.data["sources"][0]["source_type"] == "web"
        assert "offline.example" in r.data["sources"][0]["url"]

    @pytest.mark.asyncio
    async def test_web_search_exception_is_swallowed(
        self, ctx: SkillContext,
    ) -> None:
        """WebSearch exception does NOT fail the overall gather."""
        wiki = _make_wiki_mock([])  # wiki returns nothing
        ctx = ctx.with_overrides(wiki=wiki)

        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(
                side_effect=RuntimeError("all providers failed"),
            )
            MockSearch.return_value = instance

            r = await _gather(
                {"sub_queries": [{"q": "test"}], "enable_web_search": True},
                ctx,
            )

        # Gather still succeeds; web search failure is logged+swallowed
        assert r.status == "ok"
        assert r.data["_new_sources"] == 0

    @pytest.mark.asyncio
    async def test_web_search_dedups_against_existing_sources(
        self, ctx: SkillContext,
    ) -> None:
        """WebSearch URLs already in existing sources are skipped."""
        wiki = _make_wiki_mock([])
        ctx = ctx.with_overrides(wiki=wiki)

        # Pre-existing source with URL that web_search will return
        existing_url = "https://example.com/already-there"

        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[
                SearchResult("Dup", existing_url, "x"),
                SearchResult("New", "https://example.com/new", "y"),
            ])
            MockSearch.return_value = instance

            r = await _gather(
                {
                    "sub_queries": [{"q": "test"}],
                    "enable_web_search": True,
                    "sources": [{"url": existing_url, "source_type": "wiki"}],
                },
                ctx,
            )

        # Only the new URL should be added
        new_sources = [s for s in r.data["sources"] if s.get("url") != existing_url]
        assert len(new_sources) == 1
        assert new_sources[0]["url"] == "https://example.com/new"
