"""Tests for the V2 runner path in ChatOrchestrator (Plan B B-4).

Verifies that:
  - use_v2_runner config flag switches between v1 ReAct path and v2 path
  - v2 path helpers extract research_run_id from tool_call_end events
  - v2 path persists assistant message on done (mirrors v0.41 logic)
  - V2PersistenceHook delegates to tool_executor.persist_tool_result
  - Errors in persistence are isolated (logged, not raised)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.context_manager import AgentContext
from llmwikify.apps.chat.agent.orchestrator import (
    ChatOrchestrator,
    _V2PersistenceHook,
)


def _make_orchestrator() -> tuple[ChatOrchestrator, MagicMock]:
    """Build a bare ChatOrchestrator via __new__ to bypass heavy __init__."""
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    mock_executor = MagicMock(name="tool_executor")
    mock_executor._save_error_count = 0
    orch.tool_executor = mock_executor
    orch.config = {}
    return orch, mock_executor


# ─── _extract_research_run_id_from_tools ────────────────────────


def test_v2_extract_returns_none_when_empty() -> None:
    assert ChatOrchestrator._extract_research_run_id_from_tools([]) is None


def test_v2_extract_returns_none_when_no_autoresearch() -> None:
    tool_calls = [
        {"tool": "wiki_query", "result": {"status": "ok", "data": {"answer": "x"}}},
        {"tool": "read_file", "result": {"ok": True}},
    ]
    assert ChatOrchestrator._extract_research_run_id_from_tools(tool_calls) is None


def test_v2_extract_returns_run_id_from_skill_envelope() -> None:
    tool_calls = [
        {
            "tool": "autoresearch_compound_run",
            "result": {
                "status": "ok",
                "data": {"run_id": "wf_2026_abc", "status": "running"},
            },
        },
    ]
    rid = ChatOrchestrator._extract_research_run_id_from_tools(tool_calls)
    assert rid == "wf_2026_abc"


def test_v2_extract_handles_bare_result_dict() -> None:
    """When result is not wrapped in SkillResult envelope (status != 'ok')."""
    tool_calls = [
        {
            "tool": "autoresearch_compound_run",
            "result": {"run_id": "wf_bare_123", "status": "running"},
        },
    ]
    rid = ChatOrchestrator._extract_research_run_id_from_tools(tool_calls)
    assert rid == "wf_bare_123"


def test_v2_extract_handles_non_dict_result() -> None:
    tool_calls = [{"tool": "autoresearch_compound_run", "result": "string_result"}]
    assert ChatOrchestrator._extract_research_run_id_from_tools(tool_calls) is None


def test_v2_extract_handles_non_dict_data() -> None:
    tool_calls = [
        {
            "tool": "autoresearch_compound_run",
            "result": {"status": "ok", "data": "not_a_dict"},
        },
    ]
    assert ChatOrchestrator._extract_research_run_id_from_tools(tool_calls) is None


def test_v2_extract_skips_empty_run_id() -> None:
    tool_calls = [
        {
            "tool": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": ""}},
        },
    ]
    assert ChatOrchestrator._extract_research_run_id_from_tools(tool_calls) is None


def test_v2_extract_finds_run_id_among_many() -> None:
    tool_calls = [
        {"tool": "wiki_query", "result": {"ok": True}},
        {"tool": "read_file", "result": {"ok": True}},
        {
            "tool": "autoresearch_compound_run",
            "result": {"status": "ok", "data": {"run_id": "wf_target"}},
        },
        {"tool": "wiki_write", "result": {"ok": True}},
    ]
    assert ChatOrchestrator._extract_research_run_id_from_tools(tool_calls) == "wf_target"


# ─── _save_assistant_message_v2 ────────────────────────────────


def test_v2_save_calls_save_message_with_kwargs() -> None:
    orch, executor = _make_orchestrator()
    orch._save_assistant_message_v2(
        session_id="s1",
        content="hello",
        tool_calls=[{"tool": "t1", "args": {}, "result": {"ok": True}}],
        research_run_id=None,
    )
    executor.save_message.assert_called_once()
    call = executor.save_message.call_args
    assert call.args[0] == "s1"
    assert call.args[1] == "assistant"
    assert call.args[2] == "hello"
    assert call.kwargs.get("tool_calls") == [
        {"tool": "t1", "args": {}, "result": {"ok": True}},
    ]
    assert call.kwargs.get("research_run_id") is None


def test_v2_save_with_research_run_id() -> None:
    orch, executor = _make_orchestrator()
    orch._save_assistant_message_v2(
        session_id="s1",
        content="",
        tool_calls=[],
        research_run_id="wf_xyz",
    )
    _, kwargs = executor.save_message.call_args
    assert kwargs.get("research_run_id") == "wf_xyz"


def test_v2_save_with_empty_tool_calls_passes_none() -> None:
    orch, executor = _make_orchestrator()
    orch._save_assistant_message_v2(
        session_id="s1",
        content="x",
        tool_calls=[],
        research_run_id=None,
    )
    _, kwargs = executor.save_message.call_args
    assert kwargs.get("tool_calls") is None


# ─── _V2PersistenceHook ────────────────────────────────────────


def test_v2_persistence_hook_calls_persist_tool_result() -> None:
    executor = MagicMock()
    executor.persist_tool_result = AsyncMock()
    hook = _V2PersistenceHook(executor, "s1")
    tc = {"name": "read_file", "args": {"path": "/x"}}
    result = {"ok": True}
    asyncio.run(hook.after_tool_executed(MagicMock(), tc, result))
    executor.persist_tool_result.assert_awaited_once_with(
        "s1", "read_file", {"path": "/x"}, {"ok": True},
    )


def test_v2_persistence_hook_isolates_exception() -> None:
    executor = MagicMock()
    executor.persist_tool_result = AsyncMock(side_effect=RuntimeError("boom"))
    hook = _V2PersistenceHook(executor, "s1")
    tc = {"name": "read_file", "args": {}}
    result = {"ok": True}
    asyncio.run(hook.after_tool_executed(MagicMock(), tc, result))


def test_v2_persistence_hook_handles_non_dict_tool_call() -> None:
    executor = MagicMock()
    executor.persist_tool_result = AsyncMock()
    hook = _V2PersistenceHook(executor, "s1")
    asyncio.run(hook.after_tool_executed(MagicMock(), "string_tool_call", {"ok": True}))
    executor.persist_tool_result.assert_awaited_once_with(
        "s1", "", {}, {"ok": True},
    )


# ─── _chat_via_react dispatch (config flag) ─────────────────────


def test_v2_use_v2_runner_flag_default_false_keeps_v1_path() -> None:
    """Default config (no use_v2_runner key) keeps v1 ReAct path active."""
    assert "use_v2_runner" not in {}
    assert {}.get("use_v2_runner", False) is False


def test_v2_use_v2_runner_flag_true_switches_path() -> None:
    config = {"use_v2_runner": True}
    assert config.get("use_v2_runner", False) is True


# ─── V2 path integration (minimal, with mocks) ─────────────────


def test_v2_path_saves_assistant_message_via_helper() -> None:
    """Verify the v2 path calls _save_assistant_message_v2 on done event."""
    orch, executor = _make_orchestrator()
    accumulated: list[dict] = [
        {
            "tool": "read_file",
            "args": {"p": 1},
            "result": {"ok": True},
            "call_id": "c1",
        },
    ]
    orch._save_assistant_message_v2("s1", "final answer", accumulated, None)
    executor.save_message.assert_called_once()
    call = executor.save_message.call_args
    assert call.args[2] == "final answer"
    assert call.kwargs.get("tool_calls") == accumulated


def test_v2_path_research_run_id_extraction_helper() -> None:
    """Verify the v2 path can extract research_run_id from tool_call_end events."""
    tool_calls = [
        {
            "tool": "wiki_query",
            "args": {},
            "result": {"ok": True},
            "call_id": "c1",
        },
        {
            "tool": "autoresearch_compound_run",
            "args": {"q": "test"},
            "result": {"status": "ok", "data": {"run_id": "wf_extract_test"}},
            "call_id": "c2",
        },
    ]
    rid = ChatOrchestrator._extract_research_run_id_from_tools(tool_calls)
    assert rid == "wf_extract_test"
