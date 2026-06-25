"""Unit tests for web_search_skill (v0.39, #24th base Skill).

Covers the three actions exposed by the web_search Skill:

  - search_web     — general web search via provider fallback chain
  - search_youtube — YouTube search via ``site:youtube.com`` routing
  - search_news    — News search via ``site:news.google.com`` routing

Implementation is a thin wrapper over
``llmwikify.apps.research.web_search.WebSearch``. We mock
``WebSearch.search`` to avoid real network calls.

Target: 10 tests covering happy path, validation errors,
provider failure, and skill registration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmwikify.apps.chat.skills import (
    SkillContext,
    SkillRegistry,
    SkillResult,
    SkillRuntime,
)
from llmwikify.apps.chat.skills.actions import (
    ALL_ACTIONS,
    register_all_actions,
    unregister_all_actions,
    web_search_skill,
)
from llmwikify.apps.research.web_search import SearchResult


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext(config={"web_search_results_per_query": 5})


@pytest.fixture
def fresh_registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def populated_registry(fresh_registry: SkillRegistry) -> SkillRegistry:
    register_all_actions(fresh_registry)
    return fresh_registry


@pytest.fixture
def runtime(populated_registry: SkillRegistry) -> SkillRuntime:
    return SkillRuntime(populated_registry)


def _mock_search_results() -> list[SearchResult]:
    return [
        SearchResult(
            title="Result 1",
            url="https://example.com/1",
            snippet="Snippet 1",
        ),
        SearchResult(
            title="Result 2",
            url="https://example.com/2",
            snippet="Snippet 2",
        ),
    ]


# ─── Skill inventory ────────────────────────────────────────────


class TestSkillInventory:
    def test_skill_name_is_web_search(self) -> None:
        assert web_search_skill.name == "web_search"

    def test_skill_has_three_actions(self) -> None:
        assert set(web_search_skill.actions.keys()) == {
            "search_web",
            "search_youtube",
            "search_news",
        }

    def test_skill_in_all_actions(self) -> None:
        assert web_search_skill in ALL_ACTIONS

    def test_skill_registerable(self, fresh_registry: SkillRegistry) -> None:
        n = register_all_actions(fresh_registry)
        assert n == 25
        assert fresh_registry.has("web_search")
        # Three qualified actions should be exposed
        qualified = [
            f"{s.name}.{a.name}"
            for s in fresh_registry
            for a in s.actions.values()
        ]
        assert "web_search.search_web" in qualified
        assert "web_search.search_youtube" in qualified
        assert "web_search.search_news" in qualified


# ─── Input validation ───────────────────────────────────────────


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_search_web_missing_query(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute("web_search", "search_web", {}, ctx)
        assert r.status == "error"
        assert "query" in r.error.lower()

    @pytest.mark.asyncio
    async def test_search_web_empty_query(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_search", "search_web", {"query": "   "}, ctx,
        )
        assert r.status == "error"
        assert "query" in r.error.lower()

    @pytest.mark.asyncio
    async def test_search_web_num_results_too_small(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_search", "search_web",
            {"query": "x", "num_results": 0}, ctx,
        )
        assert r.status == "error"
        assert "num_results" in r.error

    @pytest.mark.asyncio
    async def test_search_web_num_results_too_large(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_search", "search_web",
            {"query": "x", "num_results": 100}, ctx,
        )
        assert r.status == "error"
        assert "num_results" in r.error


# ─── Happy path: each action returns structured payload ────────


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_search_web_returns_results(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=_mock_search_results())
            MockSearch.return_value = instance

            r = await runtime.execute(
                "web_search", "search_web",
                {"query": "python"}, ctx,
            )

        assert r.status == "ok"
        d = r.data
        assert d["count"] == 2
        assert d["query"] == "python"
        assert d["source_prefix"] == "web"
        assert len(d["results"]) == 2
        assert d["results"][0]["title"] == "Result 1"
        assert d["results"][0]["url"] == "https://example.com/1"
        assert d["results"][0]["snippet"] == "Snippet 1"

    @pytest.mark.asyncio
    async def test_search_youtube_routes_with_site_prefix(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[
                SearchResult("YT Video", "https://youtube.com/watch?v=1", "..."),
            ])
            MockSearch.return_value = instance

            r = await runtime.execute(
                "web_search", "search_youtube",
                {"query": "machine learning"}, ctx,
            )

        assert r.status == "ok"
        # Verify the call included the site: prefix
        call_args = instance.search.call_args
        assert "site:youtube.com" in call_args.kwargs.get(
            "query", call_args.args[0] if call_args.args else "",
        ) or "site:youtube.com" in (
            call_args.args[0] if call_args.args else ""
        )
        assert r.data["source_prefix"] == "youtube"

    @pytest.mark.asyncio
    async def test_search_news_routes_with_news_prefix(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[
                SearchResult("News", "https://news.example.com/1", "..."),
            ])
            MockSearch.return_value = instance

            r = await runtime.execute(
                "web_search", "search_news",
                {"query": "AI breakthrough"}, ctx,
            )

        assert r.status == "ok"
        # Verify site:news.google.com prefix
        call_args = instance.search.call_args
        query_used = (
            call_args.args[0] if call_args.args
            else call_args.kwargs.get("query", "")
        )
        assert "site:news.google.com" in query_used
        assert r.data["source_prefix"] == "news"

    @pytest.mark.asyncio
    async def test_search_web_empty_results(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[])
            MockSearch.return_value = instance

            r = await runtime.execute(
                "web_search", "search_web",
                {"query": "obscure"}, ctx,
            )

        assert r.status == "ok"
        assert r.data["count"] == 0
        assert r.data["results"] == []


# ─── Error path: provider failures ──────────────────────────────


class TestErrorPath:
    @pytest.mark.asyncio
    async def test_search_web_provider_exception(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch(
            "llmwikify.apps.research.web_search.WebSearch"
        ) as MockSearch:
            instance = MagicMock()
            instance.search = AsyncMock(
                side_effect=RuntimeError("all providers failed"),
            )
            MockSearch.return_value = instance

            r = await runtime.execute(
                "web_search", "search_web",
                {"query": "x"}, ctx,
            )

        assert r.status == "error"
        assert "all providers failed" in r.error


# ─── Input schema validation ────────────────────────────────────


class TestInputSchema:
    def test_search_web_schema_requires_query(self) -> None:
        schema = web_search_skill.actions["search_web"].input_schema
        assert "query" in schema["required"]

    def test_search_youtube_schema_requires_query(self) -> None:
        schema = web_search_skill.actions["search_youtube"].input_schema
        assert "query" in schema["required"]

    def test_search_news_schema_requires_query(self) -> None:
        schema = web_search_skill.actions["search_news"].input_schema
        assert "query" in schema["required"]

    def test_num_results_has_bounds(self) -> None:
        for action_name in ("search_web", "search_youtube", "search_news"):
            schema = web_search_skill.actions[action_name].input_schema
            num_results = schema["properties"]["num_results"]
            assert num_results["minimum"] == 1
            assert num_results["maximum"] == 50
            assert num_results["default"] == 5