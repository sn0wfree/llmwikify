"""Tests for P1.3: Graph analyzer features."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from src.llmwikify.core.wiki import Wiki
from src.llmwikify.core.graph_analyzer import GraphAnalyzer


@pytest.fixture
def graph_wiki():
    """Create a wiki with some relations for graph testing."""
    tmp = Path(tempfile.mkdtemp())

    wiki = Wiki(tmp)
    wiki.init(agent='generic')

    # Create some concept pages
    concepts_dir = tmp / 'wiki' / 'concepts'
    concepts_dir.mkdir(parents=True, exist_ok=True)

    (concepts_dir / 'Artificial Intelligence.md').write_text("""
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

    (concepts_dir / 'Machine Learning.md').write_text("""
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

    (concepts_dir / 'Deep Learning.md').write_text("""
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
        label = analyzer._label_community([
            "concepts/AI",
            "concepts/ML",
            "concepts/DL",
        ])
        assert "Concept" in label or "AI" in label

        # Test with mixed prefixes
        label = analyzer._label_community([
            "concepts/AI",
            "entities/Company",
            "concepts/ML",
        ])
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
        from src.llmwikify.cli.commands import WikiCLI
        cli = WikiCLI.__new__(WikiCLI)
        assert hasattr(cli, 'graph_analyze')
