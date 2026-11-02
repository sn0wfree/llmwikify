"""Unit tests for ``interfaces/cli/commands/knowledge_gaps.py``."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.knowledge_gaps import (
    KnowledgeGapsCommand,
    run_knowledge_gaps,
)


class FakeWiki:
    def __init__(self, result: dict):
        self._result = result
        self.lint_kwargs: dict[str, Any] | None = None

    def lint(self, **kwargs: Any) -> dict:
        self.lint_kwargs = kwargs
        return self._result


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"json": False}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


EMPTY_RESULT = {
    "total_pages": 5,
    "issue_count": 2,
    "investigations": {},
}

FULL_RESULT = {
    "total_pages": 42,
    "issue_count": 7,
    "investigations": {
        "outdated_pages": [
            {"page": "old-page", "latest_year_mentioned": 2020},
            {"page": "stale", "latest_year_mentioned": None},
        ],
        "knowledge_gaps": [
            {"observation": "no coverage of X"},
            {"observation": "missing Y"},
            {"observation": "thin Z"},
        ],
        "redundancy_alerts": [
            {"observation": "A duplicates B"},
            {"observation": "C duplicates D"},
        ],
        "contradictions": [
            {"observation": "says 10"},
            {"type": "numeric", "observation": "says 20"},
        ],
    },
}


# ── json mode ───────────────────────────────────────────────────────


def test_json_output(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(FULL_RESULT)
    assert run_knowledge_gaps(wiki, _args(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pages"] == 42
    assert wiki.lint_kwargs == {"generate_investigations": True}


def test_always_requests_investigations() -> None:
    wiki = FakeWiki(EMPTY_RESULT)
    run_knowledge_gaps(wiki, _args(json=True))
    assert wiki.lint_kwargs == {"generate_investigations": True}


# ── text: all empty ─────────────────────────────────────────────────


def test_text_all_clear(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(EMPTY_RESULT)
    assert run_knowledge_gaps(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "Knowledge Gap Analysis" in out
    assert "Total pages: 5" in out
    assert "Total issues: 2" in out
    assert "No outdated pages detected" in out
    assert "No knowledge gaps detected" in out
    assert "No redundancy detected" in out
    assert "Contradictions" not in out


# ── text: full content ──────────────────────────────────────────────


def test_text_full(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(FULL_RESULT)
    assert run_knowledge_gaps(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "Total pages: 42" in out
    assert "Total issues: 7" in out
    # outdated — .get(key, default) returns None when key exists with None
    assert "Potentially Outdated Pages (2)" in out
    assert "old-page (latest: 2020)" in out
    assert "stale (latest: None)" in out
    # gaps
    assert "Knowledge Gaps (3)" in out
    assert "no coverage of X" in out
    # redundancy
    assert "Redundancy Alerts (2)" in out
    assert "A duplicates B" in out
    # contradictions — observation preferred, falls back to type
    assert "Contradictions (2)" in out
    assert "says 10" in out
    assert "says 20" in out


def test_text_contradiction_falls_back_to_type(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 1,
        "issue_count": 0,
        "investigations": {
            "contradictions": [{"type": "date", "observation": None}],
        },
    }
    # observation=None is falsy → falls back to type
    result["investigations"]["contradictions"] = [{"type": "date"}]
    wiki = FakeWiki(result)
    run_knowledge_gaps(wiki, _args())
    assert "date" in capsys.readouterr().out


def test_text_contradiction_with_observation_and_no_type(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 1,
        "issue_count": 0,
        "investigations": {"contradictions": [{"observation": "only obs"}]},
    }
    wiki = FakeWiki(result)
    run_knowledge_gaps(wiki, _args())
    assert "only obs" in capsys.readouterr().out


# ── defaults when attrs missing ─────────────────────────────────────


def test_default_attrs(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(EMPTY_RESULT)
    run_knowledge_gaps(wiki, argparse.Namespace())
    assert "Knowledge Gap Analysis" in capsys.readouterr().out


# ── KnowledgeGapsCommand ────────────────────────────────────────────


def test_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    KnowledgeGapsCommand().setup_parser(sub)
    ns = parser.parse_args(["knowledge-gaps", "--json", "-s"])
    assert ns.json is True
    assert ns.include_suggestions is True


def test_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    KnowledgeGapsCommand().setup_parser(sub)
    ns = parser.parse_args(["knowledge-gaps"])
    assert ns.json is False
    assert ns.include_suggestions is False


def test_command_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(EMPTY_RESULT)
    cmd = KnowledgeGapsCommand()
    assert cmd.run(_args(json=True), wiki, {}) == 0
    assert json.loads(capsys.readouterr().out)["total_pages"] == 5


def test_name_help() -> None:
    cmd = KnowledgeGapsCommand()
    assert cmd.name == "knowledge-gaps"
    assert "gaps" in cmd.help.lower()
