"""Phase 10-E (2026-06-20) tests for SubagentManager.

Borrowed from nanobot v0.2.1 ``agent/subagent.py``.

Cases:
  1. SubagentSpec dataclass defaults
  2. SubagentResult dataclass defaults
  3. SubagentManager.max_concurrent property
  4. Successful run returns ok status with final_content
  5. Run respects timeout_seconds (returns status='timeout')
  6. Child runner is constructed with NoOpHook + memory_manager=None
     (no recursive consolidation)
  7. Concurrent run() calls beyond max_concurrent serialize via
     semaphore (counts overlap, never exceeds cap)
  8. Child receives a system message with the goal injected at index 0
     (parent prompt builder is bypassed for the system slot)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.spec import ChatRunResult
from llmwikify.apps.chat.agent.subagent_manager import (
    SubagentManager,
    SubagentResult,
    SubagentSpec,
)


@dataclass
class _FakeRunResult:
    final_content: str = "child final"
    messages: list = None
    tools_used: list = None
    usage: dict = None
    stop_reason: str = "completed"
    error: str | None = None
    compacted_count: int = 0
    total_compacted_chars_saved: int = 0
    state_trace: list = None


class _StubParentRunner:
    """Minimal parent runner stand-in: implements the
    :meth:`AgentRunner.execution_context` contract (Phase 16+).

    Pre-Phase-16+ the stub also exposed ``_chat_service`` /
    ``_tool_executor`` / ``_prompt_builder`` / ``_config`` as
    private attributes that the manager read directly; that 4-field
    ``hasattr`` gate has been removed in favour of the public ABC
    method. We keep ``_chat_service`` etc. only because the new
    ``ChatRunnerV2.__init__`` still references them when
    constructing a child from a fresh ctx.
    """

    def __init__(self) -> None:
        from llmwikify.apps.chat.agent.execution_context import (
            AgentExecutionContext,
        )
        self._chat_service = MagicMock()
        self._tool_executor = MagicMock()
        self._prompt_builder = MagicMock()
        self._config = {}
        self._ctx = AgentExecutionContext(
            chat_service=self._chat_service,
            tool_executor=self._tool_executor,
            prompt_builder=self._prompt_builder,
            config=self._config,
        )

    def execution_context(self):
        return self._ctx


def _make_manager(max_concurrent: int = 2) -> SubagentManager:
    return SubagentManager(_StubParentRunner(), max_concurrent=max_concurrent)


def test_subagent_spec_minimal_fields() -> None:
    spec = SubagentSpec(
        goal="dig deeper",
        initial_messages=[{"role": "user", "content": "go"}],
        tool_registry=None,
        parent_session_id="s1",
    )
    assert spec.goal == "dig deeper"
    assert spec.max_iterations == 5
    assert spec.timeout_seconds == 120.0
    assert spec.inherit_wiki_id is None


def test_subagent_result_defaults() -> None:
    r = SubagentResult(status="ok")
    assert r.final_content is None
    assert r.tools_used == []
    assert r.usage == {}
    assert r.error is None
    assert r.state_trace == []
    assert r.stop_reason == "completed"


def test_manager_max_concurrent_property() -> None:
    mgr = _make_manager(max_concurrent=3)
    assert mgr.max_concurrent == 3


@pytest.mark.asyncio
async def test_run_success_returns_ok(monkeypatch) -> None:
    mgr = _make_manager()

    async def _fake_run_to_completion(self, spec) -> Any:
        return _FakeRunResult(
            final_content="42",
            messages=[],
            tools_used=["search"],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            stop_reason="completed",
            state_trace=[{"state": "REASON"}],
        )

    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _fake_run_to_completion,
    )
    spec = SubagentSpec(
        goal="what is the answer?",
        initial_messages=[{"role": "user", "content": "tell me"}],
        tool_registry=None,
        parent_session_id="parent-s1",
    )
    result = await mgr.run(spec)
    assert result.status == "ok"
    assert result.final_content == "42"
    assert result.tools_used == ["search"]
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert result.state_trace == [{"state": "REASON"}]
    assert result.error is None


@pytest.mark.asyncio
async def test_run_timeout_returns_timeout_status(monkeypatch) -> None:
    mgr = _make_manager()

    async def _slow_run_to_completion(self, spec) -> Any:
        await asyncio.sleep(10)
        return _FakeRunResult()

    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _slow_run_to_completion,
    )
    spec = SubagentSpec(
        goal="slow query",
        initial_messages=[{"role": "user", "content": "slow"}],
        tool_registry=None,
        parent_session_id="parent-s1",
        timeout_seconds=0.05,
    )
    result = await mgr.run(spec)
    assert result.status == "timeout"
    assert "timeout" in (result.error or "").lower()
    assert result.stop_reason == "timeout"


@pytest.mark.asyncio
async def test_child_runner_uses_noop_hook_no_memory_manager(monkeypatch) -> None:
    """The child must not bubble SSE events to the parent and must
    not trigger memory consolidation. Phase 16+: the manager passes a
    fresh :class:`AgentExecutionContext` to the child; we capture
    that ctx and verify ``hook``/``memory_manager``."""
    mgr = _make_manager()
    captured: dict[str, Any] = {}

    real_init = (
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.__init__"
    )
    from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
    orig_init = ChatRunnerV2.__init__

    def _capturing_init(self, *args, **kwargs):
        captured.update(kwargs)
        captured["args"] = args
        return orig_init(self, *args, **kwargs)

    async def _fake_run_to_completion(self, spec) -> Any:
        return _FakeRunResult()

    monkeypatch.setattr(real_init, _capturing_init)
    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _fake_run_to_completion,
    )
    spec = SubagentSpec(
        goal="x",
        initial_messages=[{"role": "user", "content": "y"}],
        tool_registry=None,
        parent_session_id="p1",
    )
    await mgr.run(spec)
    # Phase 16+: manager constructs a fresh ctx; verify its
    # hook/memory_manager overrides.
    from llmwikify.foundation.callback import NoOpHook
    assert "ctx" in captured
    child_ctx = captured["ctx"]
    assert isinstance(child_ctx.hook, NoOpHook)
    assert child_ctx.memory_manager is None


@pytest.mark.asyncio
async def test_concurrent_runs_respect_semaphore(monkeypatch) -> None:
    """With max_concurrent=1, two runs must serialize. We track
    ``in_flight`` and assert it never exceeds 1."""
    mgr = _make_manager(max_concurrent=1)
    in_flight = {"count": 0, "max": 0}

    async def _track_run_to_completion(self, spec) -> Any:
        in_flight["count"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["count"])
        await asyncio.sleep(0.02)
        in_flight["count"] -= 1
        return _FakeRunResult()

    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _track_run_to_completion,
    )

    def _make_spec(label: str) -> SubagentSpec:
        return SubagentSpec(
            goal=label,
            initial_messages=[{"role": "user", "content": label}],
            tool_registry=None,
            parent_session_id="p1",
        )

    await asyncio.gather(
        mgr.run(_make_spec("a")),
        mgr.run(_make_spec("b")),
        mgr.run(_make_spec("c")),
    )
    assert in_flight["max"] == 1


def test_build_child_spec_injects_goal_system_message() -> None:
    """The child's first message must be a system message containing
    the goal text. This is the contract that lets the parent skip
    the prompt builder for goal injection."""
    mgr = _make_manager()
    spec = SubagentSpec(
        goal="investigate quantum entanglement basics",
        initial_messages=[{"role": "user", "content": "begin"}],
        tool_registry=None,
        parent_session_id="p1",
    )
    child_spec = mgr._build_child_spec(spec)
    assert child_spec.messages[0]["role"] == "system"
    assert "quantum entanglement basics" in child_spec.messages[0]["content"]
    assert child_spec.messages[1] == {"role": "user", "content": "begin"}
    # Child session id is namespaced under parent for traceability
    assert child_spec.session_id == "subagent::p1"
    assert child_spec.goal_active_predicate is None
    assert child_spec.microcompact is True


@pytest.mark.asyncio
async def test_runner_exception_returns_error_status(monkeypatch) -> None:
    """If run_to_completion raises (not asyncio.TimeoutError), the
    manager must capture the error in SubagentResult and never re-
    raise to the caller."""
    mgr = _make_manager()

    async def _crash(self, spec) -> Any:
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _crash,
    )
    spec = SubagentSpec(
        goal="x",
        initial_messages=[{"role": "user", "content": "x"}],
        tool_registry=None,
        parent_session_id="p1",
    )
    result = await mgr.run(spec)
    assert result.status == "error"
    assert "simulated crash" in (result.error or "")
    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_run_propagates_runner_error_field(monkeypatch) -> None:
    """If run_to_completion returns a result with .error set (not
    raised), the manager flips status to 'error' but keeps the
    payload intact for diagnostics."""
    mgr = _make_manager()

    async def _err_result(self, spec) -> Any:
        return _FakeRunResult(
            final_content="partial",
            error="LLM rate-limited",
            stop_reason="error",
        )

    monkeypatch.setattr(
        "llmwikify.apps.chat.agent.runner_v2.ChatRunnerV2.run_to_completion",
        _err_result,
    )
    spec = SubagentSpec(
        goal="x",
        initial_messages=[{"role": "user", "content": "x"}],
        tool_registry=None,
        parent_session_id="p1",
    )
    result = await mgr.run(spec)
    assert result.status == "error"
    assert result.error == "LLM rate-limited"
    assert result.final_content == "partial"
