"""Unit tests for ``interfaces/cli/commands/lint.py``.

The command is a thin dispatcher over ``wiki.lint()`` plus three
formatters — all driven with a fake wiki so no real lint engine runs.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.lint import (
    LintCommand,
    _lint_brief,
    _lint_full,
    _lint_recommendations,
    run_lint,
)


class FakeWiki:
    def __init__(self, result: dict):
        self._result = result
        self.last_kwargs: dict[str, Any] | None = None

    def lint(self, **kwargs: Any) -> dict:
        self.last_kwargs = kwargs
        return self._result


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "format": "full",
        "mode": "check",
        "limit": 10,
        "force": False,
        "generate_investigations": False,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ── _lint_full ──────────────────────────────────────────────────────


def test_full_no_issues(capsys: pytest.CaptureFixture) -> None:
    result = {"total_pages": 5, "issue_count": 0, "issues": []}
    assert _lint_full(result) == 0
    out = capsys.readouterr().out
    assert "Total pages: 5" in out
    assert "All healthy!" in out


def test_full_with_issues(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 10,
        "issue_count": 3,
        "issues": [
            {"type": "orphan_page", "page": "a", "message": "no inbound"},
            {"type": "broken_link", "page": "b", "message": "missing target"},
            {"issue_type": "orphan_page", "page": "c", "message": "x"},
        ],
    }
    assert _lint_full(result) == 1
    out = capsys.readouterr().out
    assert "By type:" in out
    assert "orphan_page: 2" in out
    assert "broken_link: 1" in out
    assert "First 20 issues:" in out
    assert "[orphan_page] a" in out


def test_full_more_than_20_issues(capsys: pytest.CaptureFixture) -> None:
    issues = [{"type": "t", "page": f"p{i}", "message": "m"} for i in range(25)]
    result = {"total_pages": 25, "issue_count": 25, "issues": issues}
    assert _lint_full(result) == 1
    out = capsys.readouterr().out
    # only first 20 printed
    assert out.count("❌ [t]") == 20
    assert "p19" in out and "p20" not in out


def test_full_investigations(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 1,
        "issue_count": 0,
        "issues": [],
        "investigations": {
            "contradictions": [{"observation": "A says X, B says Y"}],
            "data_gaps": [{"observation": "no data for Z"}],
            "outdated_pages": [{"observation": "stale", "page": "old"}],
            "knowledge_gaps": [{"observation": "missing topic"}],
            "redundancy_alerts": [{"observation": "dup content"}],
        },
    }
    assert _lint_full(result) == 0
    out = capsys.readouterr().out
    assert "Investigations" in out
    assert "Contradictions (1)" in out
    assert "Data Gaps (1)" in out
    assert "Outdated Pages (1)" in out
    assert "Knowledge Gaps (1)" in out
    assert "Redundancy (1)" in out


def test_full_investigations_empty_sections(capsys: pytest.CaptureFixture) -> None:
    result = {"total_pages": 1, "issue_count": 0, "issues": [], "investigations": {}}
    assert _lint_full(result) == 0
    assert "Investigations" not in capsys.readouterr().out


def test_full_auto_fix(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 1,
        "issue_count": 0,
        "issues": [],
        "auto_fix": {
            "wikilinks_fixed": 3,
            "wikilinks_skipped": 1,
            "wikilinks_ambiguous": 2,
            "index_updated": True,
        },
    }
    assert _lint_full(result) == 0
    out = capsys.readouterr().out
    assert "Auto-Fix Results" in out
    assert "Wikilinks fixed: 3" in out
    assert "Wikilinks skipped: 1" in out
    assert "Ambiguous matches: 2" in out
    assert "Index updated: ✅" in out


def test_full_auto_fix_zero_values(capsys: pytest.CaptureFixture) -> None:
    result = {
        "total_pages": 1,
        "issue_count": 0,
        "issues": [],
        "auto_fix": {"wikilinks_fixed": 0, "index_updated": False},
    }
    assert _lint_full(result) == 0
    out = capsys.readouterr().out
    assert "Wikilinks fixed: 0" in out
    assert "skipped" not in out
    assert "Index updated" not in out


def test_full_issue_without_type_key(capsys: pytest.CaptureFixture) -> None:
    result = {"total_pages": 1, "issue_count": 1, "issues": [{"page": "x"}]}
    assert _lint_full(result) == 1
    assert "unknown" in capsys.readouterr().out


# ── _lint_brief ─────────────────────────────────────────────────────


def test_brief_no_hints(capsys: pytest.CaptureFixture) -> None:
    assert _lint_brief({}) == 0
    out = capsys.readouterr().out
    assert "Wiki looks healthy" in out
    assert "Summary: 0 suggestion(s)" in out


def test_brief_critical_and_informational(capsys: pytest.CaptureFixture) -> None:
    result = {
        "hints": {
            "critical": [{"message": "broken stuff"}],
            "informational": [{"message": "minor note"}],
        },
        "issues": [],
    }
    assert _lint_brief(result) == 0
    out = capsys.readouterr().out
    assert "[HIGH] broken stuff" in out
    assert "[MEDIUM] minor note" in out
    assert "Summary: 2 suggestion(s)" in out


def test_brief_orphan_and_broken_link_issues(capsys: pytest.CaptureFixture) -> None:
    result = {
        "issues": [
            {"type": "orphan_page", "page": "lonely"},
            {"type": "broken_link", "page": "src", "link": "dest"},
            {"type": "other", "page": "z"},
        ]
    }
    assert _lint_brief(result) == 0
    out = capsys.readouterr().out
    assert "Orphan page: [[lonely]]" in out
    assert "Broken link in src → [[dest]]" in out
    assert "Summary: 2 suggestion(s)" in out  # "other" type ignored


def test_brief_more_than_10_hints(capsys: pytest.CaptureFixture) -> None:
    result = {"hints": {"critical": [{"message": f"m{i}"} for i in range(15)]}}
    assert _lint_brief(result) == 0
    out = capsys.readouterr().out
    assert "Summary: 15 suggestion(s)" in out
    # only first 10 printed
    assert "[HIGH] m0" in out
    assert "[HIGH] m10" not in out


# ── _lint_recommendations ───────────────────────────────────────────


def test_recs_empty(capsys: pytest.CaptureFixture) -> None:
    assert _lint_recommendations({}) == 0
    out = capsys.readouterr().out
    assert "No missing pages" in out
    assert "No orphan pages" in out


def test_recs_missing_from_critical(capsys: pytest.CaptureFixture) -> None:
    result = {
        "hints": {
            "critical": [
                {"message": "Pages referenced but missing: alpha, beta"},
                {"message": "unrelated critical"},
            ]
        },
        "issues": [],
    }
    assert _lint_recommendations(result) == 0
    out = capsys.readouterr().out
    assert "Missing Pages (2)" in out
    assert "[[alpha]]" in out and "[[beta]]" in out


def test_recs_orphans(capsys: pytest.CaptureFixture) -> None:
    result = {"issues": [{"type": "orphan_page", "page": "solo"}]}
    assert _lint_recommendations(result) == 0
    out = capsys.readouterr().out
    assert "Orphan Pages (1)" in out
    assert "[[solo]]" in out


def test_recs_dedupes_missing(capsys: pytest.CaptureFixture) -> None:
    result = {
        "hints": {
            "critical": [{"message": "Pages referenced but missing: dup"}],
            "informational": [{"message": "missing page: dup, extra"}],
        },
        "issues": [],
    }
    assert _lint_recommendations(result) == 0
    out = capsys.readouterr().out
    assert "Missing Pages (2)" in out  # dup + extra, not dup twice
    assert out.count("[[dup]]") == 1


def test_recs_informational_missing_page(capsys: pytest.CaptureFixture) -> None:
    result = {"hints": {"informational": [{"message": "missing page: gamma"}]}}
    assert _lint_recommendations(result) == 0
    assert "[[gamma]]" in capsys.readouterr().out


def test_recs_more_than_10(capsys: pytest.CaptureFixture) -> None:
    names = ", ".join(f"p{i}" for i in range(15))
    result = {"hints": {"critical": [{"message": f"Pages referenced but missing: {names}"}]}}
    assert _lint_recommendations(result) == 0
    out = capsys.readouterr().out
    assert "Missing Pages (15)" in out
    assert "[[p9]]" in out
    assert "[[p10]]" not in out


# ── run_lint ────────────────────────────────────────────────────────


def test_run_lint_json(capsys: pytest.CaptureFixture) -> None:
    payload = {"total_pages": 3, "issue_count": 0, "issues": []}
    wiki = FakeWiki(payload)
    assert run_lint(wiki, _args(format="json")) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == payload


def test_run_lint_full(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"total_pages": 1, "issue_count": 0, "issues": []})
    assert run_lint(wiki, _args(format="full")) == 0
    assert "Wiki Health Check" in capsys.readouterr().out


def test_run_lint_brief(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({})
    assert run_lint(wiki, _args(format="brief")) == 0
    assert "Wiki Suggestions" in capsys.readouterr().out


def test_run_lint_recommendations(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({})
    assert run_lint(wiki, _args(format="recommendations")) == 0
    assert "Wiki Recommendations" in capsys.readouterr().out


def test_run_lint_forwards_kwargs() -> None:
    wiki = FakeWiki({"total_pages": 0, "issue_count": 0, "issues": []})
    run_lint(wiki, _args(mode="fix", limit=5, force=True, generate_investigations=True))
    assert wiki.last_kwargs == {
        "mode": "fix",
        "limit": 5,
        "force": True,
        "generate_investigations": True,
    }


def test_run_lint_defaults_when_attrs_missing() -> None:
    wiki = FakeWiki({"total_pages": 0, "issue_count": 0, "issues": []})
    # Namespace with only format — other attrs use getattr defaults
    run_lint(wiki, argparse.Namespace(format="json"))
    assert wiki.last_kwargs == {
        "mode": "check",
        "limit": 10,
        "force": False,
        "generate_investigations": False,
    }


def test_run_lint_issues_exit_code() -> None:
    wiki = FakeWiki({"total_pages": 1, "issue_count": 1, "issues": [{"type": "x"}]})
    assert run_lint(wiki, _args(format="full")) == 1


# ── LintCommand ─────────────────────────────────────────────────────


def test_lint_command_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    LintCommand().setup_parser(sub)
    ns = parser.parse_args(["lint", "-f", "brief", "--mode", "fix", "-l", "3", "--force", "-g"])
    assert ns.format == "brief"
    assert ns.mode == "fix"
    assert ns.limit == 3
    assert ns.force is True
    assert ns.generate_investigations is True


def test_lint_command_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    LintCommand().setup_parser(sub)
    ns = parser.parse_args(["lint"])
    assert ns.format == "full"
    assert ns.mode == "check"
    assert ns.limit == 10
    assert ns.force is False
    assert ns.generate_investigations is False


def test_lint_command_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"total_pages": 2, "issue_count": 0, "issues": []})
    cmd = LintCommand()
    assert cmd.run(_args(format="json"), wiki, {}) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pages"] == 2


def test_lint_command_name_help() -> None:
    cmd = LintCommand()
    assert cmd.name == "lint"
    assert cmd.help == "Health check"
