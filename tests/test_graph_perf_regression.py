"""Regression tests for session perf/fix work (2026-10-22).

Covers: build_graph dedup semantics, page-name set (posix),
graph_analyze force, visualization cache, UTF-8 IO.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel.graph.analyzer import GraphAnalyzer
from llmwikify.kernel.graph.export import build_graph
from llmwikify.kernel.graph.visualizer import build_visualization_data
from llmwikify.kernel.storage.backend import LocalFileBackend
from llmwikify.kernel.storage.index import WikiIndex
from llmwikify.kernel.wiki.wiki import Wiki


@pytest.fixture
def temp_index(tmp_path):
    index = WikiIndex(tmp_path / "t.db")
    index.initialize()
    return index


class TestBuildGraphDedup:
    def test_wikilink_direction_preserved(self, temp_index):
        temp_index.conn.executemany(
            "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
            [("A", "B"), ("B", "A"), ("A", "B")],
        )
        temp_index.conn.commit()
        g = build_graph(temp_index, include_wikilinks=True, include_relations=False)
        pairs = {(e["source"], e["target"]) for e in g["edges"]}
        assert pairs == {("A", "B"), ("B", "A")}
        ab = next(e for e in g["edges"] if e["source"] == "A")
        assert ab["weight"] == 2

    def test_relation_higher_confidence_wins(self, temp_index):
        temp_index.conn.executescript(
            """
            CREATE TABLE relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, target TEXT, relation TEXT, confidence TEXT
            );
            """
        )
        temp_index.conn.executemany(
            "INSERT INTO relations (source, target, relation, confidence) VALUES (?,?,?,?)",
            [
                ("A", "B", "uses", "AMBIGUOUS"),
                ("A", "B", "uses", "EXTRACTED"),
                ("A", "B", "uses", "INFERRED"),
            ],
        )
        temp_index.conn.commit()
        g = build_graph(temp_index, include_wikilinks=False, include_relations=True)
        assert len(g["edges"]) == 1
        assert g["edges"][0]["weight"] == 3
        assert g["edges"][0]["confidence"] == "EXTRACTED"

    def test_unique_edge_count_stable(self, temp_index):
        rows = []
        for i in range(100):
            rows.append((f"p{i % 20}", f"p{(i * 7) % 20}"))
        temp_index.conn.executemany(
            "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)", rows
        )
        temp_index.conn.commit()
        g = build_graph(temp_index)
        uniq = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
        assert len(g["edges"]) == len(uniq)


@pytest.fixture
def graph_wiki(tmp_path):
    wiki = Wiki(tmp_path)
    wiki.init(agent="generic")
    concepts = tmp_path / "wiki" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / "Alpha.md").write_text(
        "---\ntitle: Alpha\ntype: concept\n---\n\n# Alpha\n\n[[concepts/Beta]]\n",
        encoding="utf-8",
    )
    (concepts / "Beta.md").write_text(
        "---\ntitle: Beta\ntype: concept\n---\n\n# Beta\n\n[[concepts/Alpha]]\n",
        encoding="utf-8",
    )
    wiki.index.build_index() if hasattr(wiki.index, "build_index") else None
    yield wiki
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestPageNameSet:
    def test_posix_separators(self, graph_wiki):
        names = GraphAnalyzer(graph_wiki)._page_name_set()
        assert any(n.startswith("concepts/") for n in names)
        assert not any("\\" in n for n in names)
        assert "concepts/Alpha" in names


class TestAnalyzeForceAndVizCache:
    def test_force_flag_recomputes(self, graph_wiki):
        a = GraphAnalyzer(graph_wiki)
        first = a.analyze()
        second = a.analyze()
        forced = a.analyze(force=True)
        assert first.get("cached") is False
        assert second.get("cached") is True
        assert forced.get("cached") is False

    def test_viz_cache_and_invalidate(self, graph_wiki):
        v1 = build_visualization_data(graph_wiki.index, graph_wiki)
        v2 = build_visualization_data(graph_wiki.index, graph_wiki)
        assert v1.get("cached") is False
        assert v2.get("cached") is True
        # data change → fingerprint bump
        graph_wiki.index.conn.execute(
            "INSERT INTO page_links (source_page, target_page) VALUES (?, ?)",
            ("concepts/Alpha", "concepts/Gamma"),
        )
        graph_wiki.index.conn.commit()
        v3 = build_visualization_data(graph_wiki.index, graph_wiki)
        assert v3.get("cached") is False

    def test_wiki_graph_analyze_accepts_force(self, graph_wiki):
        r1 = graph_wiki.graph_analyze()
        r2 = graph_wiki.graph_analyze(force=True)
        assert "status" in r1
        assert r2.get("cached") is False


class TestUtf8IO:
    def test_backend_roundtrip_unicode(self, tmp_path):
        backend = LocalFileBackend(tmp_path)
        text = "中文↔符号 café 🚀"
        backend.put_wiki_md(text)
        assert backend.get_wiki_md() == text
