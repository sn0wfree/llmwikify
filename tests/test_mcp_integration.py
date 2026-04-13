"""Integration tests for MCP server tools using FastMCP."""

import asyncio
import json
import pytest
from pathlib import Path

from llmwikify.core import Wiki
from llmwikify.mcp import create_mcp_server


@pytest.fixture
def wiki(tmp_path):
    w = Wiki(tmp_path)
    w.init()
    yield w
    w.close()


@pytest.fixture
def mcp(wiki):
    return create_mcp_server(wiki)


class TestMCPIntegration:
    """End-to-end tests for MCP tool calls (sync wrappers for async FastMCP)."""

    def test_ingest_write_read_cycle(self, mcp, wiki):
        """Test ingest → write page → read page cycle."""
        async def _run():
            src = wiki.raw_dir / "test_article.md"
            src.write_text("# Gold Price Hits Record High\n\nGold prices surged to $3000/oz.")

            result = await mcp.call_tool("wiki_ingest", {"source": str(src)})
            text = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
            data = json.loads(text)
            assert "title" in data
            assert "content" in data
            assert data["source_name"] == "test_article.md"

            await mcp.call_tool("wiki_write_page", {
                "page_name": "entities/Test Entity",
                "content": "---\ntitle: Test Entity\ntype: entity\n---\n\n# Test Entity\n\nA test entity.\n\n[[Concept Page]]\n"
            })

            entity_path = wiki.wiki_dir / "entities" / "Test Entity.md"
            assert entity_path.exists()

            read_result = await mcp.call_tool("wiki_read_page", {"page_name": "entities/Test Entity"})
            read_text = read_result.content[0].text if hasattr(read_result.content[0], 'text') else str(read_result.content[0])
            assert "Test Entity" in read_text
            assert "[[Concept Page]]" in read_text

        asyncio.run(_run())

    def test_search_and_status(self, mcp, wiki):
        """Test search and status tools."""
        async def _run():
            await mcp.call_tool("wiki_write_page", {
                "page_name": "Gold Mining",
                "content": "# Gold Mining\n\nGold mining is the extraction of gold.\n"
            })

            status_result = await mcp.call_tool("wiki_status", {})
            text = status_result.content[0].text if hasattr(status_result.content[0], 'text') else str(status_result.content[0])
            data = json.loads(text)
            assert data["initialized"] is True
            assert "pages_by_type" in data
            assert "graph_stats" in data

        asyncio.run(_run())

    def test_lint_and_log(self, mcp, wiki):
        """Test lint and log tools."""
        async def _run():
            lint_result = await mcp.call_tool("wiki_lint", {})
            lint_text = lint_result.content[0].text if hasattr(lint_result.content[0], 'text') else str(lint_result.content[0])
            lint_data = json.loads(lint_text)
            assert "issue_count" in lint_data

            log_result = await mcp.call_tool("wiki_log", {"operation": "test", "details": "MCP integration test"})
            log_text = log_result.content[0].text if hasattr(log_result.content[0], 'text') else str(log_result.content[0])
            assert "Logged" in log_text

        asyncio.run(_run())

    def test_status_has_pages_by_type(self, mcp, wiki):
        """Test that status returns pages_by_type."""
        async def _run():
            status_result = await mcp.call_tool("wiki_status", {})
            text = status_result.content[0].text if hasattr(status_result.content[0], 'text') else str(status_result.content[0])
            data = json.loads(text)
            assert "pages_by_type" in data
            assert "root" in data["pages_by_type"]
            for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
                assert subdir in data["pages_by_type"]

        asyncio.run(_run())

    def test_status_has_graph_stats(self, mcp, wiki):
        """Test that status returns graph_stats."""
        async def _run():
            status_result = await mcp.call_tool("wiki_status", {})
            text = status_result.content[0].text if hasattr(status_result.content[0], 'text') else str(status_result.content[0])
            data = json.loads(text)
            assert "graph_stats" in data
            assert "total_relations" in data["graph_stats"]
            assert data["graph_stats"]["total_relations"] == 0

        asyncio.run(_run())


class TestRelationEngine:
    """Tests for dynamic relation types from wiki.md."""

    def test_default_relation_types(self, wiki):
        engine = wiki.get_relation_engine()
        types = engine.get_relation_types()
        assert "is_a" in types
        assert "supports" in types
        assert "contradicts" in types

    def test_add_valid_relation(self, wiki):
        engine = wiki.get_relation_engine()
        rel_id = engine.add_relation("Gold", "Precious Metal", "is_a", "EXTRACTED")
        assert rel_id is not None
        assert rel_id > 0

    def test_add_invalid_relation_raises(self, wiki):
        engine = wiki.get_relation_engine()
        with pytest.raises(ValueError):
            engine.add_relation("Gold", "Silver", "invalid_relation_type")


class TestWikiInitSubdirs:
    """Test that wiki init creates subdirectories and overview.md."""

    def test_creates_subdirs(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
            assert (wiki.wiki_dir / subdir).exists()
        wiki.close()

    def test_creates_overview(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        overview = wiki.wiki_dir / "overview.md"
        assert overview.exists()
        content = overview.read_text()
        assert "title: Overview" in content
        assert "type: overview" in content
        wiki.close()
