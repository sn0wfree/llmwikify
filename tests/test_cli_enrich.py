"""Boundary tests for the ``llmwikify enrich`` command.

The command chains ingest → LLM page write → enrichment. The LLM step is
stubbed here; what matters is the wiring and the dry-run path.
"""

from __future__ import annotations

import argparse
import json

from llmwikify.interfaces.cli.commands.enrich import run_enrich


def _args(**overrides) -> argparse.Namespace:
    base = {
        "file": "doc.md",
        "dry_run": False,
        "no_propose": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class _FakeWiki:
    """Wiki stub: ingest succeeds, LLM returns two write operations."""

    def __init__(self, root="."):
        self.root = root
        self.written: list[str] = []
        self.relations_written = False

    def ingest_source(self, source):
        return {
            "title": "Doc Title",
            "source_type": "markdown",
            "source_name": "doc.md",
            "saved_to_raw": True,
            "content_length": 120,
        }

    def _llm_process_source(self, result):
        return {
            "operations": [
                {"action": "write_page", "page_name": "concepts/Foo", "content": "# Foo"},
            ],
            "relations": [{"from": "a", "to": "b"}],
        }

    def execute_operations(self, operations):
        for op in operations:
            self.written.append(op.get("page_name", ""))
        return {
            "status": "completed",
            "operations_executed": len(operations),
            "results": [
                {"action": "write_page", "status": "done", "page": op.get("page_name", "")}
                for op in operations
            ],
        }

    def write_relations(self, relations, source_file=None):
        self.relations_written = True
        return {"count": len(relations)}

    def search(self, query, limit=10):
        return []

    def read_page(self, name, page_type=None):
        return {"error": "not found", "content": ""}

    def write_page(self, name, content, page_type=None):
        self.written.append(name)


def test_dry_run_writes_nothing(capsys):
    wiki = _FakeWiki()
    assert run_enrich(wiki, _args(dry_run=True)) == 0
    assert wiki.written == []
    assert "DRY RUN" in capsys.readouterr().err


def test_ingest_error_returns_1(capsys):
    class _Bad(_FakeWiki):
        def ingest_source(self, source):
            return {"error": "cannot read file"}

    assert run_enrich(_Bad(), _args()) == 1
    assert "cannot read file" in capsys.readouterr().out


def test_llm_not_configured_returns_1(capsys):
    class _NoLLM(_FakeWiki):
        def _llm_process_source(self, result):
            raise ValueError("LLM is not enabled")

    assert run_enrich(_NoLLM(), _args()) == 1
    assert "LLM not configured" in capsys.readouterr().out


def test_llm_failure_returns_1(capsys):
    class _Down(_FakeWiki):
        def _llm_process_source(self, result):
            raise ConnectionError("boom")

    assert run_enrich(_Down(), _args()) == 1
    assert "LLM processing failed" in capsys.readouterr().out


def test_pages_are_written_and_enriched(capsys):
    wiki = _FakeWiki()
    assert run_enrich(wiki, _args()) == 0
    assert "concepts/Foo" in wiki.written
    assert wiki.relations_written is True
    err = capsys.readouterr().err
    assert "Pages written: 1" in err
    assert "Enriched:" in err


def test_json_output(capsys):
    wiki = _FakeWiki()
    assert run_enrich(wiki, _args(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operations_executed"] == 1
    assert "enrich" in payload
    assert "links_added" in payload["enrich"]


def test_missing_file_argument_returns_1(capsys):
    wiki = _FakeWiki()
    assert run_enrich(wiki, _args(file=None)) == 1
    assert "no source file" in capsys.readouterr().out
