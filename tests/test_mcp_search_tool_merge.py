"""Search-tool merge acceptance (docs/designs/search-tool-merge.md §8).

Covers the compatibility matrix, the new ``wiki_ids`` scope semantics,
the global ``limit`` cap, backend passthrough, and the deprecated
``wiki_search_cross`` marker.
"""

import asyncio
import json

import pytest

from llmwikify.interfaces.mcp.adapter import MCPAdapter
from llmwikify.interfaces.server.core import WikiServer
from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def _call(mcp, name, args):
    return asyncio.run(mcp.call_tool(name, args))


def _payload(result):
    content = getattr(result, "content", None)
    first = content[0] if content else result
    return json.loads(getattr(first, "text", None) or str(first))


@pytest.fixture
def three_wikis(tmp_path):
    """Three local wikis; 'a' and 'b' share content, 'c' has its own."""
    roots = {}
    for name in ("a", "b", "c"):
        root = tmp_path / name
        wiki = Wiki(root)
        wiki.init()
        for i in range(5):
            wiki.write_page(f"common-{i}", f"# Common {i}\n\nshared topic content {i}\n")
        wiki.close()
        roots[name] = root
    registry = WikiRegistry({})
    for name in ("a", "b", "c"):
        registry.register_wiki(name, name, roots[name], is_default=(name == "a"))
    return registry


@pytest.fixture
def multi_mcp(three_wikis):
    server = WikiServer(three_wikis, enable_mcp=True, enable_rest=False, enable_webui=False)
    return server.mcp._mcp


# ── surface ──────────────────────────────────────────────────────


def test_single_wiki_surface_unchanged(tmp_path):
    """V1: single-wiki keeps 20 tools and the original wiki_search schema."""
    wiki = Wiki(tmp_path / "one")
    wiki.init()
    mcp = MCPAdapter(wiki)._mcp
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 20
    search = next(t for t in tools if t.name == "wiki_search")
    props = set((search.parameters or {}).get("properties", {}))
    assert props == {"query", "limit", "backend"}


def test_multi_wiki_keeps_both_tools_and_marks_deprecated(multi_mcp):
    """V2/V3: 26 tools, wiki_search_cross survives with a deprecated marker."""
    tools = asyncio.run(multi_mcp.list_tools())
    assert len(tools) == 26
    cross = next(t for t in tools if t.name == "wiki_search_cross")
    assert cross.annotations is not None
    assert getattr(cross.annotations, "deprecated", None) is True
    assert "deprecated" in (getattr(cross, "tags", None) or set())
    assert "Deprecated" in (cross.description or "")


# ── compatibility matrix ─────────────────────────────────────────


def test_legacy_call_shapes_still_work(multi_mcp):
    """V4: every pre-merge call shape keeps its scope."""
    # wiki_search(q) -> every wiki
    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "limit": 20}))
    assert isinstance(p, list)
    assert {r["wiki_id"] for r in p} == {"a", "b", "c"}

    # positional third argument is still wiki_id
    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "limit": 20, "wiki_id": "a"}))
    assert {r["wiki_id"] for r in p} == {"a"}

    # deprecated tool keeps its payload shape
    p = _payload(_call(multi_mcp, "wiki_search_cross", {"query": "shared", "limit": 20}))
    assert set(p) == {"results", "total_results", "searched_wikis"}
    assert {r["wiki_id"] for r in p["results"]} == {"a", "b", "c"}

    # ... and its wiki_ids filter
    p = _payload(
        _call(multi_mcp, "wiki_search_cross", {"query": "shared", "limit": 20, "wiki_ids": "a,b"})
    )
    assert {r["wiki_id"] for r in p["results"]} == {"a", "b"}
    assert set(p["searched_wikis"]) == {"a", "b"}


# ── new wiki_ids semantics ──────────────────────────────────────


def test_wiki_ids_scope_semantics(multi_mcp):
    """V5-V7: wiki_ids selects the scope; the deprecated wiki_id wins."""
    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "wiki_ids": "a,b", "limit": 20}))
    assert {r["wiki_id"] for r in p} == {"a", "b"}

    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "wiki_ids": "*", "limit": 20}))
    assert {r["wiki_id"] for r in p} == {"a", "b", "c"}

    p = _payload(
        _call(
            multi_mcp,
            "wiki_search",
            {"query": "shared", "wiki_id": "a", "wiki_ids": "b", "limit": 20},
        )
    )
    assert {r["wiki_id"] for r in p} == {"a"}

    # every requested id unknown -> explicit error, not an empty result
    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "wiki_ids": "nosuch"}))
    assert "error" in p


def test_limit_is_a_global_cap(multi_mcp):
    """V8: limit bounds the merged result set, not each wiki."""
    p = _payload(_call(multi_mcp, "wiki_search", {"query": "shared", "limit": 4}))
    assert len(p) <= 4
    p = _payload(_call(multi_mcp, "wiki_search_cross", {"query": "shared", "limit": 4}))
    assert len(p["results"]) <= 4


def test_backend_is_forwarded(multi_mcp, three_wikis):
    """V9: the backend reaches Wiki.search."""
    seen: list[str] = []
    wiki_a = three_wikis.get_wiki("a")
    original = wiki_a.search

    def spy(query, limit=10, backend="fts5"):
        seen.append(backend)
        return original(query, limit, backend=backend)

    wiki_a.search = spy  # type: ignore[method-assign]
    try:
        _call(multi_mcp, "wiki_search", {"query": "shared", "wiki_ids": "a", "backend": "qmd"})
    finally:
        wiki_a.search = original  # type: ignore[method-assign]
    assert seen == ["qmd"]


def test_rest_cross_forwards_backend(three_wikis):
    """V13: the REST route now actually uses the backend it accepts."""
    from fastapi.testclient import TestClient

    server = WikiServer(
        three_wikis,
        enable_mcp=False,
        enable_rest=True,
        enable_webui=False,
        local_mode=True,
    )
    seen: list[str] = []
    original = three_wikis.cross_wiki_search

    def spy(query, wiki_ids=None, limit=10, backend="fts5"):
        seen.append(backend)
        return original(query, wiki_ids, limit, backend=backend)

    three_wikis.cross_wiki_search = spy  # type: ignore[method-assign]
    try:
        resp = TestClient(server.app).get(
            "/api/search/cross", params={"q": "shared", "backend": "qmd"}
        )
        assert resp.status_code == 200
    finally:
        three_wikis.cross_wiki_search = original  # type: ignore[method-assign]
    assert seen == ["qmd"]


# ── skill layer ──────────────────────────────────────────────────


def test_skill_layer_exposes_wiki_ids(three_wikis):
    """V12: the skill action mirrors the MCP surface."""
    from llmwikify.apps.chat.skills import wiki_query_skill as W
    from llmwikify.apps.chat.skills.base import SkillContext

    skill = W.wiki_query_skill
    ctx = SkillContext(
        wiki=None, db=None, config={"wiki_registry": three_wikis}, session_id="s"
    )

    res = asyncio.run(
        skill.actions["wiki_search"].handler({"query": "shared", "wiki_ids": "a,b"}, ctx)
    )
    assert res.status == "ok"
    assert {r["wiki_id"] for r in res.data["result"]} == {"a", "b"}

    res = asyncio.run(skill.actions["wiki_search_cross"].handler({"query": "shared"}, ctx))
    assert set(res.data) == {"results", "total_results", "searched_wikis"}

    assert "Deprecated" in skill.actions["wiki_search_cross"].description
    props = skill.actions["wiki_search"].input_schema["properties"]
    assert {"wiki_ids", "backend", "wiki_id"} <= set(props)
