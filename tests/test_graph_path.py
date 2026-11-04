"""Tests for ``RelationEngine.get_path`` direction handling and error path.

Two defects were confirmed by inspection and reproduced:

* only ``NetworkXNoPath`` was caught, so an endpoint missing from the
  graph raised ``NodeNotFound`` out of a function documented to return
  ``None``;
* the graph is a ``MultiDiGraph``, so ``path(C, A)`` returned ``None``
  for a path that exists when traversed in reverse.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def graph_wiki(tmp_path: Path):
    """Wiki with Alpha → Beta → Gamma as stored relations."""
    from llmwikify.kernel import Wiki

    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    wiki = Wiki(tmp_path)
    for name in ("Alpha", "Beta", "Gamma"):
        wiki.write_page(f"concepts/{name}", f"# {name}\n\ncontent\n")

    engine = wiki.get_relation_engine()
    engine.add_relations(
        [
            {"source": "concepts/Alpha", "target": "concepts/Beta", "relation": "uses"},
            {"source": "concepts/Beta", "target": "concepts/Gamma", "relation": "uses"},
        ]
    )
    yield wiki, engine
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_forward_path_unchanged(graph_wiki):
    """The default direction still follows edge orientation."""
    _, engine = graph_wiki

    result = engine.get_path("concepts/Alpha", "concepts/Gamma")

    assert result is not None
    assert result["path"] == [
        "concepts/Alpha",
        "concepts/Beta",
        "concepts/Gamma",
    ]


def test_reverse_path_returns_none_by_default(graph_wiki):
    """Undirected traversal is opt-in; the default stays directed."""
    _, engine = graph_wiki

    assert engine.get_path("concepts/Gamma", "concepts/Alpha") is None


def test_reverse_path_found_with_direction_both(graph_wiki):
    _, engine = graph_wiki

    result = engine.get_path(
        "concepts/Gamma", "concepts/Alpha", direction="both"
    )

    assert result is not None
    assert result["path"] == [
        "concepts/Gamma",
        "concepts/Beta",
        "concepts/Alpha",
    ]


def test_both_direction_reports_real_edge_orientation(graph_wiki):
    """Edges must show how they are stored, not the traversal order."""
    _, engine = graph_wiki

    result = engine.get_path(
        "concepts/Gamma", "concepts/Alpha", direction="both"
    )

    assert result is not None
    edges = {(e["source"], e["target"]) for e in result["edges"]}
    assert ("concepts/Alpha", "concepts/Beta") in edges
    assert ("concepts/Beta", "concepts/Gamma") in edges


def test_missing_endpoint_returns_none(graph_wiki):
    """An endpoint absent from the graph is 'no path', not a crash."""
    _, engine = graph_wiki

    assert engine.get_path("concepts/DoesNotExist", "concepts/Beta") is None
    assert engine.get_path("concepts/Alpha", "concepts/DoesNotExist") is None


def test_max_length_still_applies(graph_wiki):
    _, engine = graph_wiki

    assert engine.get_path("concepts/Alpha", "concepts/Gamma", max_length=1) is None
    assert engine.get_path("concepts/Alpha", "concepts/Gamma", max_length=5) is not None


def test_invalid_direction_rejected(graph_wiki):
    _, engine = graph_wiki

    with pytest.raises(ValueError, match="direction"):
        engine.get_path("concepts/Alpha", "concepts/Beta", direction="sideways")


def test_cli_path_accepts_direction_flag(graph_wiki):
    """The CLI flag reaches the engine."""
    from llmwikify.interfaces.cli.commands.graph_query import run_graph_query

    wiki, _ = graph_wiki

    class _Args:
        subcommand = "path"
        args = ["concepts/Gamma", "concepts/Alpha"]
        direction = "both"

    assert run_graph_query(wiki, _Args()) == 0

    class _ArgsDirected:
        subcommand = "path"
        args = ["concepts/Gamma", "concepts/Alpha"]
        direction = "out"

    assert run_graph_query(wiki, _ArgsDirected()) == 0
