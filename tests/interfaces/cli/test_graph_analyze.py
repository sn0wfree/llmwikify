"""Unit tests for ``interfaces/cli/commands/graph_analyze.py``."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.graph_analyze import (
    GraphAnalyzeCommand,
    run_graph_analyze,
)


class FakeWiki:
    def __init__(self, result: dict | None = None, report: str = "REPORT"):
        self._result = result if result is not None else {}
        self._report = report
        self.analyze_calls = 0
        self.report_calls = 0

    def graph_analyze(self) -> dict:
        self.analyze_calls += 1
        return self._result

    def graph_suggested_pages_report(self) -> str:
        self.report_calls += 1
        return self._report


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"json": False, "report": False}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


FULL_RESULT = {
    "status": "ok",
    "stats": {"nodes": 10, "edges": 20, "density": 0.4, "is_connected": True},
    "centrality": {
        "pagerank": [
            {"node": "a", "score": 0.9},
            {"node": "b", "score": 0.5},
            {"node": "c", "score": 0.3},
            {"node": "d", "score": 0.2},
            {"node": "e", "score": 0.1},
            {"node": "f", "score": 0.05},
        ],
        "hubs": [{"node": "h1", "out_degree": 8}, {"node": "h2", "out_degree": 5}],
        "authorities": [{"node": "a1", "in_degree": 9}, {"node": "a2", "in_degree": 4}],
    },
    "communities": {
        "num_communities": 2,
        "communities": {
            "0": {"label": "cluster-0", "size": 5},
            "1": {"label": "cluster-1", "size": 3},
        },
        "bridges": [{"node": "b", "observation": "connects A and B"}],
    },
    "suggestions": [
        {"priority": "high", "observation": "missing topic", "suggestion": "write page"},
        {"priority": "medium", "observation": "thin page", "suggestion": "expand"},
        {"priority": "low", "observation": "stale", "suggestion": "refresh"},
        {"priority": "info", "observation": "misc", "suggestion": "note"},
    ],
}


# ── json mode ───────────────────────────────────────────────────────


def test_json_output(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(FULL_RESULT)
    assert run_graph_analyze(wiki, _args(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert wiki.analyze_calls == 1
    assert wiki.report_calls == 0


# ── report mode ─────────────────────────────────────────────────────


def test_report_mode(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(report="DETAILED REPORT")
    assert run_graph_analyze(wiki, _args(report=True)) == 0
    out = capsys.readouterr().out
    assert "DETAILED REPORT" in out
    assert wiki.report_calls == 1
    assert wiki.analyze_calls == 0  # report short-circuits analyze


# ── empty graph ─────────────────────────────────────────────────────


def test_empty_graph(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "empty", "message": "No graph data available"})
    assert run_graph_analyze(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "No graph data available" in out
    assert "Knowledge Graph Analysis" not in out


def test_empty_graph_default_message(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "empty"})
    assert run_graph_analyze(wiki, _args()) == 0
    assert "No graph data available" in capsys.readouterr().out


# ── full text output ────────────────────────────────────────────────


def test_full_text_output(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(FULL_RESULT)
    assert run_graph_analyze(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "Knowledge Graph Analysis" in out
    assert "Nodes: 10" in out
    assert "Edges: 20" in out
    assert "Density: 0.4" in out
    assert "Connected: Yes" in out
    # pagerank top 5 only (6 items → 5 printed)
    assert "Core Concepts (PageRank)" in out
    assert "• a (score: 0.9)" in out
    assert "• e (score: 0.1)" in out
    assert "• f" not in out
    # hubs / authorities
    assert "Hub Nodes" in out
    assert "• h1 (out-degree: 8)" in out
    assert "Authority Nodes" in out
    assert "• a1 (in-degree: 9)" in out
    # communities + bridges
    assert "Communities (2)" in out
    assert "cluster-0: 5 nodes" in out
    assert "Bridge Nodes" in out
    assert "connects A and B" in out
    # suggestions: 4 items, all printed (limit 10)
    assert "Suggested Pages (4)" in out
    assert "🔴 [HIGH] missing topic" in out
    assert "write page" in out
    assert "🟡 [MEDIUM]" in out
    assert "🟢 [LOW]" in out
    assert "• [INFO]" in out  # unknown priority → bullet


def test_disconnected_graph(capsys: pytest.CaptureFixture) -> None:
    result = dict(FULL_RESULT)
    result["stats"] = {"nodes": 3, "edges": 1, "density": 0.1, "is_connected": False}
    wiki = FakeWiki(result)
    run_graph_analyze(wiki, _args())
    assert "Connected: No" in capsys.readouterr().out


def test_no_suggestions(capsys: pytest.CaptureFixture) -> None:
    result = dict(FULL_RESULT)
    result["suggestions"] = []
    wiki = FakeWiki(result)
    run_graph_analyze(wiki, _args())
    out = capsys.readouterr().out
    assert "No suggestions at this time" in out


def test_missing_stats_keys(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "ok"})
    assert run_graph_analyze(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "Nodes: 0" in out
    assert "Edges: 0" in out
    assert "Connected: No" in out
    assert "No suggestions" in out


def test_no_centrality_sections(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "ok", "stats": {"nodes": 1}})
    run_graph_analyze(wiki, _args())
    out = capsys.readouterr().out
    assert "PageRank" not in out
    assert "Hub Nodes" not in out
    assert "Authority Nodes" not in out
    assert "Communities" not in out


def test_many_suggestions_truncated(capsys: pytest.CaptureFixture) -> None:
    result = dict(FULL_RESULT)
    result["suggestions"] = [
        {"priority": "high", "observation": f"o{i}", "suggestion": f"s{i}"} for i in range(15)
    ]
    wiki = FakeWiki(result)
    run_graph_analyze(wiki, _args())
    out = capsys.readouterr().out
    assert "Suggested Pages (15)" in out
    assert "o9" in out
    assert "o10" not in out


# ── defaults when attrs missing ─────────────────────────────────────


def test_defaults_when_attrs_missing(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "ok", "stats": {"nodes": 1}})
    run_graph_analyze(wiki, argparse.Namespace())
    assert "Knowledge Graph Analysis" in capsys.readouterr().out


# ── GraphAnalyzeCommand ─────────────────────────────────────────────


def test_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    GraphAnalyzeCommand().setup_parser(sub)
    ns = parser.parse_args(["graph-analyze", "--json", "--report"])
    assert ns.json is True
    assert ns.report is True


def test_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    GraphAnalyzeCommand().setup_parser(sub)
    ns = parser.parse_args(["graph-analyze"])
    assert ns.json is False
    assert ns.report is False


def test_command_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(FULL_RESULT)
    cmd = GraphAnalyzeCommand()
    assert cmd.run(_args(json=True), wiki, {}) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_name_help() -> None:
    cmd = GraphAnalyzeCommand()
    assert cmd.name == "graph-analyze"
    assert "PageRank" in cmd.help
