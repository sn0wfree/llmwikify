"""Unit tests for ChatOrchestrator._extract_research_run_id (v0.41).

Covers the helper that scans ctx._tool_calls for an autoresearch run
invocation and returns its run_id, used to bind the run to the assistant
message at save time so the ResearchRunCard can be reconstructed on
page reload.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.context_manager import AgentContext
from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator


def _ctx_with_tool_calls(tool_calls: dict[str, Any]) -> AgentContext:
    ctx = AgentContext()
    ctx._tool_calls = tool_calls
    return ctx


def test_returns_none_when_no_tool_calls() -> None:
    ctx = AgentContext()  # empty _tool_calls
    assert ChatOrchestrator._extract_research_run_id(ctx) is None


def test_returns_none_when_no_autoresearch_invocation() -> None:
    ctx = _ctx_with_tool_calls({
        "tc1": {"name": "wiki_query", "result": {"status": "ok", "data": {"answer": "x"}}},
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) is None


def test_extracts_run_id_from_skill_result_envelope() -> None:
    """The autoresearch skill returns SkillResult.ok({data: {run_id: ...}})."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "name": "autoresearch_compound_run",
            "result": {
                "status": "ok",
                "data": {
                    "run_id": "wf_2026-06-16T02-39-40_20517bd2",
                    "status": "running",
                },
            },
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) == "wf_2026-06-16T02-39-40_20517bd2"


def test_extracts_run_id_from_unwrapped_data() -> None:
    """If status != 'ok', result IS the data dict directly."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "name": "autoresearch_compound_run",
            "result": {"run_id": "wf_unwrapped_abc", "status": "running"},
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) == "wf_unwrapped_abc"


def test_uses_tool_key_when_name_missing() -> None:
    """Some tool call shapes use 'tool' instead of 'name'."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "tool": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": "wf_tool_key"}},
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) == "wf_tool_key"


def test_skips_non_dict_entries() -> None:
    """Robust against malformed tool_calls entries."""
    ctx = _ctx_with_tool_calls({
        "tc1": "not a dict",
        "tc2": None,
        "tc3": {"name": "autoresearch_compound_run", "result": "not a dict"},
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) is None


def test_skips_autoresearch_without_run_word() -> None:
    """The regex-style guard: must contain both 'autoresearch_compound'
    AND 'run' (e.g. autoresearch_compound_status should NOT match)."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "name": "autoresearch_compound_status",
            "result": {"status": "ok", "data": {"run_id": "wf_should_not_match"}},
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) is None


def test_returns_first_match_among_multiple() -> None:
    """If multiple autoresearch runs somehow exist, take the first one
    (defensive: a single assistant message shouldn't have more than one)."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "name": "wiki_query",
            "result": {"status": "ok", "data": {"answer": "x"}},
        },
        "tc2": {
            "name": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": "wf_first"}},
        },
        "tc3": {
            "name": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": "wf_second"}},
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) == "wf_first"


def test_skips_empty_string_run_id() -> None:
    """Empty run_id is not a valid run, skip it."""
    ctx = _ctx_with_tool_calls({
        "tc1": {
            "name": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": ""}},
        },
    })
    assert ChatOrchestrator._extract_research_run_id(ctx) is None
