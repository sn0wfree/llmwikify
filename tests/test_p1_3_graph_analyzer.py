"""Tests for P1.3: Graph analyzer features."""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from llmwikify.kernel.graph.analyzer import GraphAnalyzer
from llmwikify.kernel.wiki.wiki import Wiki


@pytest.fixture
def graph_wiki():
    """Create a wiki with some relations for graph testing."""
    tmp = Path(tempfile.mkdtemp())

    wiki = Wiki(tmp)
    wiki.init(agent="generic")

    # Create some concept pages
    concepts_dir = tmp / "wiki" / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    (concepts_dir / "Artificial Intelligence.md").write_text("""
---
title: Artificial Intelligence
type: concept
---

# Artificial Intelligence

## Summary
AI is a broad field.

## Sources
- [Source: Test](raw/test.md)

[[concepts/Machine Learning]]
[[concepts/Deep Learning]]
""")

    (concepts_dir / "Machine Learning.md").write_text("""
---
title: Machine Learning
type: concept
---

# Machine Learning

## Summary
ML is a subset of AI.

## Sources
- [Source: Test](raw/test.md)

[[concepts/Artificial Intelligence]]
[[concepts/Deep Learning]]
""")

    (concepts_dir / "Deep Learning.md").write_text("""
---
title: Deep Learning
type: concept
---

# Deep Learning

## Summary
DL uses neural networks.

## Sources
- [Source: Test](raw/test.md)

[[concepts/Machine Learning]]
[[concepts/Neural Networks]]
""")

    yield wiki, tmp

    shutil.rmtree(tmp)


class TestGraphAnalyzerCache:
    """Analyze result cache: hit, force, and fingerprint invalidation."""

    def test_second_call_is_cached(self, graph_wiki):
        wiki, _ = graph_wiki
        a1 = GraphAnalyzer(wiki).analyze()
        a2 = GraphAnalyzer(wiki).analyze()
        assert a1.get("cached") is False
        assert a2.get("cached") is True
        assert a2.get("status") == a1.get("status")

    def test_force_recomputes(self, graph_wiki):
        wiki, _ = graph_wiki
        GraphAnalyzer(wiki).analyze()
        forced = GraphAnalyzer(wiki).analyze(force=True)
        assert forced.get("cached") is False

    def test_data_change_invalidates(self, graph_wiki):
        wiki, _ = graph_wiki
        GraphAnalyzer(wiki).analyze()
        wiki.index.conn.execute(
            "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
            ("concepts/Artificial Intelligence", "concepts/Deep Learning"),
        )
        wiki.index.conn.commit()
        after = GraphAnalyzer(wiki).analyze()
        assert after.get("cached") is False

    def test_viz_cache_hit_and_invalidate(self, graph_wiki):
        from llmwikify.kernel.graph.visualizer import build_visualization_data

        wiki, _ = graph_wiki
        v1 = build_visualization_data(wiki.index, wiki)
        v2 = build_visualization_data(wiki.index, wiki)
        assert v1.get("cached") is False
        assert v2.get("cached") is True
        wiki.index.conn.execute(
            "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
            ("concepts/Machine Learning", "concepts/Neural Networks"),
        )
        wiki.index.conn.commit()
        v3 = build_visualization_data(wiki.index, wiki)
        assert v3.get("cached") is False


class TestGraphAnalyzer:
    """Test graph analyzer functionality."""

    def test_analyze_returns_dict(self, graph_wiki):
        """Test that analyze returns a dict."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)
        result = analyzer.analyze()

        assert isinstance(result, dict)
        assert "status" in result
        # May be "empty" if no relations yet, but structure should exist

    def test_analyze_missing_dependency_branch(self, graph_wiki, monkeypatch):
        """Regression (slim image, 2026-10-14): when networkx ([graph]
        extra) is absent, analyze() must return a clear
        ``missing_dependency`` status instead of a misleading
        "no pages" / "empty" message."""
        wiki, _tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # sys.modules[key] = None makes `import networkx` raise ImportError
        monkeypatch.setitem(sys.modules, "networkx", None)
        result = analyzer.analyze()

        assert result["status"] == "missing_dependency"
        assert result["missing"] == ["networkx"]
        assert "llmwikify[graph]" in result["fix"]
        assert "[graph] extra" in result["message"]

    def test_suggest_pages_for_concepts(self, graph_wiki):
        """Test suggestion of pages for high-degree concepts."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Test with empty graph data
        import networkx as nx

        empty_g = nx.MultiDiGraph()
        suggestions = analyzer._suggest_pages_for_concepts(empty_g)
        assert isinstance(suggestions, list)
        assert len(suggestions) == 0

    def test_suggest_orphan_pages(self, graph_wiki):
        """Test orphan page suggestions."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        suggestions = analyzer._suggest_orphan_pages()
        assert isinstance(suggestions, list)

    def test_suggest_link_improvements(self, graph_wiki):
        """Test link improvement suggestions."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Test with empty graph
        import networkx as nx

        empty_g = nx.MultiDiGraph()
        suggestions = analyzer._suggest_link_improvements(empty_g)
        assert isinstance(suggestions, list)

    def test_generate_suggestions(self, graph_wiki):
        """Test full suggestion generation."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Test with empty graph
        import networkx as nx

        empty_g = nx.MultiDiGraph()
        suggestions = analyzer._generate_suggestions(empty_g, {})
        assert isinstance(suggestions, list)

    def test_page_exists_check(self, graph_wiki):
        """Test page existence checking."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Should find existing pages
        assert analyzer._page_exists("concepts/Artificial Intelligence")

        # Should not find non-existent pages
        assert not analyzer._page_exists("nonexistent/page")

    def test_label_community(self, graph_wiki):
        """Test community labeling."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Test with concepts prefix
        label = analyzer._label_community(
            [
                "concepts/AI",
                "concepts/ML",
                "concepts/DL",
            ]
        )
        assert "Concept" in label or "AI" in label

        # Test with mixed prefixes
        label = analyzer._label_community(
            [
                "concepts/AI",
                "entities/Company",
                "concepts/ML",
            ]
        )
        assert label  # Should return something

    def test_find_bridge_nodes(self, graph_wiki):
        """Test bridge node detection."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        # Test with empty graph
        import networkx as nx

        empty_g = nx.MultiDiGraph()
        bridges = analyzer._find_bridge_nodes(empty_g, {})
        assert isinstance(bridges, list)

    def test_get_suggested_pages_report(self, graph_wiki):
        """Test report generation."""
        wiki, tmp = graph_wiki
        analyzer = GraphAnalyzer(wiki)

        report = analyzer.get_suggested_pages_report()
        assert isinstance(report, str)
        # Even if empty, should return a message
        assert len(report) > 0


class TestWikiGraphAnalyze:
    """Test Wiki.graph_analyze method."""

    def test_graph_analyze_returns_dict(self, graph_wiki):
        """Test that graph_analyze returns a dict."""
        wiki, tmp = graph_wiki
        result = wiki.graph_analyze()

        assert isinstance(result, dict)
        assert "status" in result

    def test_graph_suggested_pages_report(self, graph_wiki):
        """Test suggested pages report."""
        wiki, tmp = graph_wiki
        report = wiki.graph_suggested_pages_report()

        assert isinstance(report, str)
        assert len(report) > 0


class TestCLICommandExists:
    """Test that graph-analyze CLI command exists."""

    def test_graph_analyze_command_exists(self):
        """Test that graph_analyze method exists on CLI."""
        from llmwikify.interfaces.cli.commands import WikiCLI

        cli = WikiCLI.__new__(WikiCLI)
        assert hasattr(cli, "graph_analyze")
