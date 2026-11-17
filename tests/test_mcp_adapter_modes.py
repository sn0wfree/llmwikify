"""Unit tests for the MCP adapter's two registration modes.

Locks in the single-wiki (20 tools) vs multi-wiki (26 tools) surfaces,
the same-name replacement path, and that ``wiki_switch`` really flips
the registry default.
"""

import asyncio
import warnings

from llmwikify.interfaces.mcp.adapter import MCPAdapter
from llmwikify.interfaces.server.core import WikiServer
from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def _names(adapter) -> set[str]:
    return {t.name for t in asyncio.run(adapter._mcp.list_tools())}


def _make_registry(tmp_path, ids=("a", "b")) -> WikiRegistry:
    registry = WikiRegistry({})
    for i in ids:
        registry.register_wiki(i, i.upper(), tmp_path / i, is_default=(i == ids[0]))
    return registry


def _call(adapter, name, args):
    return asyncio.run(adapter._mcp.call_tool(name, args))


# ── tool surface ─────────────────────────────────────────────────


def test_single_wiki_adapter_registers_20_tools(tmp_path):
    wiki = Wiki(tmp_path / "one")
    wiki.init()
    assert len(_names(MCPAdapter(wiki))) == 20


def test_registry_adapter_registers_26_tools(tmp_path):
    adapter = MCPAdapter(_make_registry(tmp_path))
    names = _names(adapter)
    assert len(names) == 26
    # the six registry-only tools are present
    assert {
        "wiki_list",
        "wiki_switch",
        "wiki_register",
        "wiki_unregister",
        "wiki_search_cross",
        "wiki_scan",
    } <= names


def test_registry_adapter_replaces_the_two_same_named_tools(tmp_path):
    """wiki_status / wiki_search become the wiki_id-aware variants."""
    adapter = MCPAdapter(_make_registry(tmp_path))
    tools = {t.name: t for t in asyncio.run(adapter._mcp.list_tools())}
    search_props = set((tools["wiki_search"].parameters or {}).get("properties", {}))
    assert {"wiki_id", "wiki_ids", "backend"} <= search_props


def test_registry_adapter_marks_cross_as_deprecated(tmp_path):
    adapter = MCPAdapter(_make_registry(tmp_path))
    cross = next(
        t for t in asyncio.run(adapter._mcp.list_tools()) if t.name == "wiki_search_cross"
    )
    assert getattr(cross.annotations, "deprecated", None) is True
    assert "deprecated" in (getattr(cross, "tags", None) or set())


def test_registration_emits_no_deprecation_warning(tmp_path):
    """The same-name swap must not hit the deprecated FastMCP.remove_tool."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        MCPAdapter(_make_registry(tmp_path))
    bad = [w for w in caught if "remove_tool" in str(w.message)]
    assert bad == [], [str(w.message) for w in bad]


# ── WikiServer decides the surface from how it was built ─────────


def test_wiki_server_from_wiki_stays_at_20(tmp_path):
    wiki = Wiki(tmp_path / "one")
    wiki.init()
    server = WikiServer(wiki, enable_mcp=True, enable_rest=False, enable_webui=False)
    assert len(_names(server.mcp)) == 20


def test_wiki_server_from_registry_exposes_26(tmp_path):
    server = WikiServer(
        _make_registry(tmp_path),
        enable_mcp=True,
        enable_rest=False,
        enable_webui=False,
    )
    assert len(_names(server.mcp)) == 26


def test_wiki_server_single_wiki_is_not_marked_multi(tmp_path):
    """An auto-built registry (one wiki) must not flip to the 26-tool mode."""
    wiki = Wiki(tmp_path / "one")
    wiki.init()
    server = WikiServer(wiki, enable_mcp=False, enable_rest=False, enable_webui=False)
    assert server._multi_wiki is False


def test_wiki_server_explicit_registry_is_marked_multi(tmp_path):
    server = WikiServer(
        _make_registry(tmp_path), enable_mcp=False, enable_rest=False, enable_webui=False
    )
    assert server._multi_wiki is True


# ── wiki_switch actually switches ────────────────────────────────


def test_wiki_switch_sets_the_registry_default(tmp_path):
    adapter = MCPAdapter(_make_registry(tmp_path))
    registry = adapter.registry
    assert registry.get_default_wiki_id() == "a"

    payload = _call(adapter, "wiki_switch", {"wiki_id": "b"})
    text = payload.content[0].text if payload.content else str(payload)
    assert '"default_wiki_id": "b"' in text
    assert registry.get_default_wiki_id() == "b"


def test_wiki_switch_unknown_id_does_not_move_the_default(tmp_path):
    adapter = MCPAdapter(_make_registry(tmp_path))
    registry = adapter.registry
    payload = _call(adapter, "wiki_switch", {"wiki_id": "nosuch"})
    text = payload.content[0].text if payload.content else str(payload)
    assert "Wiki not found" in text
    assert registry.get_default_wiki_id() == "a"


def test_core_tools_follow_the_switched_default(tmp_path):
    """After wiki_switch the dynamically-resolved tools read the new wiki."""
    registry = _make_registry(tmp_path)
    adapter = MCPAdapter(registry)

    # Give each wiki a distinct page through the real Wiki objects.
    for wid in ("a", "b"):
        wiki = registry.get_wiki(wid)
        wiki.write_page("marker", f"# marker from {wid}\n")

    before = _call(adapter, "wiki_read_page", {"page_name": "marker"})
    assert "marker from a" in before.content[0].text

    _call(adapter, "wiki_switch", {"wiki_id": "b"})
    after = _call(adapter, "wiki_read_page", {"page_name": "marker"})
    assert "marker from b" in after.content[0].text
