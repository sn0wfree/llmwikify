"""Unit tests for Phase 12: wiki_query_skill (28-action aggregator).

Covers:

  - WikiQuerySkill metadata (name, 28 actions, manifest)
  - Core wiki actions: search, read_page, write_page, status, lint
  - Multi-wiki actions: wiki_list, wiki_search
  - Error handling: no wiki, no registry, missing required args

Target: 20+ tests, no I/O, mock wiki.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills import SkillContext, SkillResult
from llmwikify.apps.chat.skills.wiki_query_skill import (
    WikiQuerySkill,
    wiki_query_skill,
)

# ─── Mock wiki ────────────────────────────────────────────────────


class MockWiki:
    def init(self, overwrite: bool = False) -> dict:
        return {"status": "ok", "initialized": True}

    def ingest_source(self, source: str) -> dict:
        return {"status": "ok", "source": source}

    def write_page(self, page_name: str, content: str) -> str:
        return f"Written: {page_name}"

    def read_page(self, page_name: str) -> str:
        return f"Content of {page_name}"

    def search(self, query: str, limit: int = 10, backend: str = "fts5") -> list[str]:
        return [f"result_{i}" for i in range(min(3, limit))]

    def lint(self, mode: str = "check", limit: int = 10, force: bool = False, generate_investigations: bool = False) -> dict:
        return {"hints": {}, "issue_count": 0, "total_pages": 5}

    def status(self) -> dict:
        return {"pages": 5, "status": "ok"}

    def append_log(self, operation: str, details: str) -> str:
        return f"Logged: {operation}"

    def recommend(self) -> dict:
        return {"missing": [], "orphans": []}

    def build_index(self) -> dict:
        return {"status": "ok"}

    def read_schema(self) -> str:
        return "# Wiki Schema"

    def update_schema(self, content: str) -> str:
        return "Updated"

    def synthesize_query(self, **kwargs: object) -> dict:
        return {"status": "ok", "page": kwargs.get("page_name", "auto")}

    def sink_status(self) -> dict:
        return {"sinks": []}

    def suggest_synthesis(self, source_name: str | None = None) -> dict:
        return {"suggestions": []}

    def graph_analyze(self) -> dict:
        return {"pagerank": {}, "communities": []}

    def get_inbound_links(self, page_name: str, include_context: bool = False) -> list[str]:
        return ["inbound_page"]

    def get_outbound_links(self, page_name: str, include_context: bool = False) -> list[str]:
        return ["outbound_page"]

    class index:
        pass


@pytest.fixture
def ctx_with_wiki() -> SkillContext:
    return SkillContext(wiki=MockWiki())


@pytest.fixture
def ctx_empty() -> SkillContext:
    return SkillContext()


# ─── Metadata ─────────────────────────────────────────────────────


class TestWikiQuerySkillMetadata:
    def test_name(self) -> None:
        assert wiki_query_skill.name == "wiki_query"

    def test_28_actions(self) -> None:
        assert len(wiki_query_skill.actions) == 28

    def test_action_names_sorted(self) -> None:
        names = sorted(wiki_query_skill.actions.keys())
        assert names == sorted([
            "init", "ingest", "write_page", "read_page", "search",
            "lint", "analyze_source", "references", "status", "log",
            "recommend", "build_index", "read_schema", "update_schema",
            "synthesize", "sink_status", "suggest_synthesis",
            "knowledge_gaps", "graph_analyze", "graph",
            "wiki_list", "wiki_switch", "wiki_register", "wiki_unregister",
            "wiki_status", "wiki_search", "wiki_search_cross", "wiki_scan",
        ])

    def test_manifest_action_count(self) -> None:
        m = wiki_query_skill.manifest()
        assert m.action_count == 28


# ─── Core wiki actions ───────────────────────────────────────────


class TestCoreWikiActions:
    @pytest.mark.asyncio
    async def test_search(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["search"]
        r = await action.handler({"query": "test", "limit": 5}, ctx_with_wiki)
        assert r.status == "ok"
        assert len(r.data["result"]) == 3

    @pytest.mark.asyncio
    async def test_search_missing_query(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["search"]
        r = await action.handler({}, ctx_with_wiki)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_read_page(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["read_page"]
        r = await action.handler({"page_name": "test"}, ctx_with_wiki)
        assert r.status == "ok"
        assert "Content of test" in r.data["result"]

    @pytest.mark.asyncio
    async def test_write_page(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["write_page"]
        r = await action.handler({"page_name": "p", "content": "c"}, ctx_with_wiki)
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_status(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["status"]
        r = await action.handler({}, ctx_with_wiki)
        assert r.status == "ok"
        assert r.data["result"]["pages"] == 5

    @pytest.mark.asyncio
    async def test_lint(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["lint"]
        r = await action.handler({}, ctx_with_wiki)
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_init(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["init"]
        r = await action.handler({}, ctx_with_wiki)
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_references(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["references"]
        r = await action.handler({"page_name": "p"}, ctx_with_wiki)
        assert r.status == "ok"
        assert "inbound" in r.data

    @pytest.mark.asyncio
    async def test_log(self, ctx_with_wiki: SkillContext) -> None:
        action = wiki_query_skill.actions["log"]
        r = await action.handler({"operation": "edit", "details": "changed p"}, ctx_with_wiki)
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_no_wiki(self, ctx_empty: SkillContext) -> None:
        action = wiki_query_skill.actions["search"]
        r = await action.handler({"query": "test"}, ctx_empty)
        assert r.status == "error"


# ─── Multi-wiki actions ──────────────────────────────────────────


class MockWikiRegistry:
    def list_wikis(self) -> list:
        return []

    def get_default_wiki_id(self) -> str | None:
        return None


class TestMultiWikiActions:
    @pytest.mark.asyncio
    async def test_wiki_list_no_registry(self, ctx_empty: SkillContext) -> None:
        action = wiki_query_skill.actions["wiki_list"]
        r = await action.handler({}, ctx_empty)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_wiki_list(self, ctx_with_wiki: SkillContext) -> None:
        ctx_with_wiki.config["wiki_registry"] = MockWikiRegistry()
        action = wiki_query_skill.actions["wiki_list"]
        r = await action.handler({}, ctx_with_wiki)
        assert r.status == "ok"
        assert r.data["wikis"] == []

    @pytest.mark.asyncio
    async def test_wiki_switch_no_registry(self, ctx_empty: SkillContext) -> None:
        action = wiki_query_skill.actions["wiki_switch"]
        r = await action.handler({"wiki_id": "x"}, ctx_empty)
        assert r.status == "error"
