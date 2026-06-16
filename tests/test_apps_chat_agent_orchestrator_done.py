"""Integration tests for the v0.41 done handler changes.

Verifies that:
  - When ctx._tool_calls contains an autoresearch_compound_run entry,
    the done handler passes research_run_id to tool_executor.save_message.
  - When the LLM produces no natural-language reply AND a run was
    triggered, the persisted content gets a fixed stub string.
  - When no autoresearch was triggered, research_run_id is None.
  - When autoresearch triggered AND LLM did produce a reply, the
    original final_answer is preserved (no stub).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.context_manager import AgentContext
from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator


def _make_orchestrator_with_mock_executor() -> tuple[ChatOrchestrator, MagicMock]:
    """Build a bare ChatOrchestrator via __new__ to bypass heavy __init__."""
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    mock_executor = MagicMock(name="tool_executor")
    # The done handler reads _save_error_count; must be a real int.
    mock_executor._save_error_count = 0
    orch.tool_executor = mock_executor
    return orch, mock_executor


def _ctx(tool_calls: dict[str, Any] | None = None) -> AgentContext:
    ctx = AgentContext()
    if tool_calls:
        ctx._tool_calls = tool_calls
    return ctx


def _done_event(final_answer: str = "") -> dict[str, Any]:
    return {
        "type": "phase",
        "phase": "done",
        "final_state": {"final_answer": final_answer, "llm_content": ""},
    }


def _last_save_kwargs(executor: MagicMock) -> tuple[str, dict]:
    """Extract (content, kwargs) from the last save_message call.

    save_message signature:
        save_message(session_id, role, content, tool_calls=None, ...,
                     research_run_id=None)
    The first three are positional; the rest are kwargs.
    """
    call = executor.save_message.call_args
    positional = call.args  # (session_id, role, content)
    content = positional[2] if len(positional) >= 3 else ""
    return content, dict(call.kwargs)


class TestDoneHandlerResearchRunId:
    def test_binds_research_run_id_when_autoresearch_triggered(self) -> None:
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {
                "name": "autoresearch_compound_run",
                "result": {
                    "status": "ok",
                    "data": {
                        "run_id": "wf_2026-06-16_xyz",
                        "status": "running",
                    },
                },
            },
        })
        orch._translate_react_event(_done_event(), ctx, "sess1")
        executor.save_message.assert_called_once()
        _, kwargs = _last_save_kwargs(executor)
        assert kwargs.get("research_run_id") == "wf_2026-06-16_xyz", (
            f"expected research_run_id bound, got: {kwargs}"
        )

    def test_research_run_id_none_when_no_autoresearch(self) -> None:
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {"name": "wiki_query", "result": {"status": "ok", "data": {}}},
        })
        orch._translate_react_event(_done_event("hello"), ctx, "sess1")
        _, kwargs = _last_save_kwargs(executor)
        assert kwargs.get("research_run_id") is None

    def test_empty_content_gets_stub_when_research_triggered(self) -> None:
        """When LLM produced no reply but /study triggered a run, write
        a stub string so reload shows text alongside the card."""
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {
                "name": "autoresearch_compound_run",
                "result": {"status": "ok", "data": {"run_id": "wf_abc"}},
            },
        })
        orch._translate_react_event(_done_event(""), ctx, "sess1")
        content, kwargs = _last_save_kwargs(executor)
        assert "研究已启动" in content, f"expected stub, got: {content!r}"
        assert kwargs.get("research_run_id") == "wf_abc"

    def test_existing_reply_preserved_when_research_triggered(self) -> None:
        """When LLM did reply, the natural-language text wins. No stub."""
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {
                "name": "autoresearch_compound_run",
                "result": {"status": "ok", "data": {"run_id": "wf_abc"}},
            },
        })
        orch._translate_react_event(
            _done_event("我已完成研究并整理了提案。"), ctx, "sess1",
        )
        content, kwargs = _last_save_kwargs(executor)
        assert "我已完成研究" in content
        assert "研究已启动" not in content
        assert kwargs.get("research_run_id") == "wf_abc"

    def test_no_stub_when_no_research_triggered(self) -> None:
        """Without autoresearch, an empty final_answer stays empty (no stub)."""
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({})  # no tool calls at all
        orch._translate_react_event(_done_event(""), ctx, "sess1")
        content, kwargs = _last_save_kwargs(executor)
        assert content == ""
        assert kwargs.get("research_run_id") is None

    def test_whitespace_only_content_treated_as_empty(self) -> None:
        """Whitespace-only final_answer should also get the stub."""
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {
                "name": "autoresearch_compound_run",
                "result": {"status": "ok", "data": {"run_id": "wf_xyz"}},
            },
        })
        orch._translate_react_event(_done_event("\n\n\n"), ctx, "sess1")
        content, _ = _last_save_kwargs(executor)
        assert "研究已启动" in content

    def test_done_event_with_error_prefix_returns_error_event(self) -> None:
        """Error path: '[error] ...' final → ChatEvent.error, no save_message."""
        orch, executor = _make_orchestrator_with_mock_executor()
        ctx = _ctx({
            "tc1": {
                "name": "autoresearch_compound_run",
                "result": {"status": "ok", "data": {"run_id": "wf_xyz"}},
            },
        })
        result = orch._translate_react_event(
            _done_event("[error] stream failed"), ctx, "sess1",
        )
        assert result["type"] == "error"
        executor.save_message.assert_not_called()
