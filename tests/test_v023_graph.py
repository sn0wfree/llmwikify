"""Tests for v0.23.0 Graph export and community detection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core.graph_export import (
    _build_networkx,
    build_graph,
    compute_surprise_score,
    detect_communities,
    generate_report,
)
from llmwikify.core.index import WikiIndex


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    index = WikiIndex(db_path)
    index.initialize()
    return index


@pytest.fixture
def populated_index(temp_db):
    """Create an index with some pages and links."""
    temp_db.conn.execute(
        "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
        ("Attention", "attention.md", 100, 20, 2)
    )
    temp_db.conn.execute(
        "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
        ("Transformer", "transformer.md", 200, 40, 1)
    )
    temp_db.conn.execute(
        "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
        ("KVCache", "kv_cache.md", 150, 30, 0)
    )
    temp_db.conn.execute(
        "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
        ("Attention", "Transformer")
    )
    temp_db.conn.execute(
        "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
        ("Transformer", "KVCache")
    )
    temp_db.conn.commit()
    return temp_db


class TestBuildGraph:
    def test_build_from_empty(self, temp_db):
        graph = build_graph(temp_db)
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) == 0
        assert len(graph["edges"]) == 0

    def test_build_with_wikilinks(self, populated_index):
        graph = build_graph(populated_index, include_wikilinks=True, include_relations=False)
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2

    def test_build_with_relations(self, temp_db):
        # Add relations directly
        temp_db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, target TEXT, relation TEXT, confidence TEXT
            );
        """)
        temp_db.conn.execute(
            "INSERT INTO relations (source, target, relation, confidence) VALUES (?, ?, ?, ?)",
            ("A", "B", "uses", "EXTRACTED")
        )
        temp_db.conn.commit()

        graph = build_graph(temp_db, include_wikilinks=False, include_relations=True)
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1


class TestCommunityDetection:
    def test_empty_graph(self, temp_db):
        result = detect_communities(temp_db)
        assert result["warning"] is not None
        assert result["num_communities"] == 0

    def test_no_edges(self, temp_db):
        temp_db.conn.execute(
            "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
            ("A", "a.md", 100, 20, 0)
        )
        temp_db.conn.execute(
            "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
            ("B", "b.md", 100, 20, 0)
        )
        temp_db.conn.commit()

        # Pages without links don't appear in the graph (no edges)
        result = detect_communities(temp_db)
        # No wikilinks, no relations = empty graph
        assert result["num_communities"] == 0 or result.get("warning") is not None

    def test_detection_runs(self, populated_index):
        result = detect_communities(populated_index)
        assert result["num_communities"] >= 1
        assert result["total_nodes"] >= 1
        assert 0 <= result["modularity"] <= 1


class TestSurpriseScore:
    def test_extracted_low_score(self):
        graph = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "type": "uses", "confidence": "EXTRACTED"}],
        }
        G = _build_networkx(graph)
        score, reasons = compute_surprise_score(
            G, "A", "B",
            {"confidence": "EXTRACTED"},
            {0: ["A", "B"]}
        )
        assert score == 1  # Only base confidence
        assert len(reasons) == 0

    def test_ambiguous_high_score(self):
        graph = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "type": "uses", "confidence": "AMBIGUOUS"}],
        }
        G = _build_networkx(graph)
        score, reasons = compute_surprise_score(
            G, "A", "B",
            {"confidence": "AMBIGUOUS"},
            {0: ["A"], 1: ["B"]}
        )
        assert score >= 4  # AMBIGUOUS(3) + cross-community(1)

    def test_cross_type_bonus(self):
        graph = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "type": "uses", "confidence": "EXTRACTED"}],
        }
        G = _build_networkx(graph)
        score, reasons = compute_surprise_score(
            G, "A", "B",
            {"confidence": "EXTRACTED", "source_type_a": "paper", "source_type_b": "analysis"},
            {0: ["A"], 1: ["B"]}
        )
        assert score >= 4  # EXTRACTED(1) + cross-type(2) + cross-community(1)


class TestReport:
    def test_report_generated(self, populated_index):
        report = generate_report(populated_index, top_n=5)
        assert "# Unexpected Connections Report" in report
        assert "## Overview" in report

    def test_report_empty(self, temp_db):
        report = generate_report(temp_db, top_n=5)
        assert "No unexpected connections" in report or "Total nodes: 0" in report


class TestBuildNetworkX:
    def test_empty_graph(self):
        G = _build_networkx({"nodes": [], "edges": []})
        assert G.number_of_nodes() == 0

    def test_nodes_and_edges(self):
        graph = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "type": "uses"}],
        }
        G = _build_networkx(graph)
        assert G.number_of_nodes() == 2
        assert G.number_of_edges() == 1
