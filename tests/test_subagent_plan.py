"""Differential guard for the subagent tool loop on the shared runtime.

The subagent worker carried its own ReAct-style tool loop; it now runs
on the shared ``AgentRuntime`` with :class:`SubagentPlan`.

The plan is an adapter — it calls the same client and the same
dispatcher the old loop did. These tests pin the boundary: that the
worker really goes through the shared runtime, and that the plan
keeps the old loop's contract (the iteration cap, the plain-chat
fallback, the fatal-error propagation, the message bookkeeping).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from llmwikify.apps.chat.skills.workflows import subagent_plan as plan_mod
from llmwikify.apps.chat.skills.workflows.subagent_plan import SubagentPlan
from llmwikify.apps.chat.skills.workflows.subagent_worker import (
    LlmClientDriver,
)
from llmwikify.kernel.agent.runtime import AgentRuntime, RuntimeContext, run_sync


class _FakeClient:
    """A client that answers with a scripted sequence of tool calls."""

    def __init__(self, responses: list[Any], fail_with: Exception | None = None):
        self._responses = list(responses)
        self._fail_with = fail_with
        self.calls: list[dict[str, Any]] = []
        self.plain_calls = 0

    def chat_with_tools(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if self._fail_with is not None:
            raise self._fail_with
        return self._responses.pop(0)

    def chat(self, messages=None):
        self.plain_calls += 1
        return {"content": "fallback answer", "tokens": 7}


def _plan(client: Any, messages: list[dict[str, Any]] | None = None) -> SubagentPlan:
    return SubagentPlan(
        client,
        messages if messages is not None else [],
        [{"name": "WebSearch"}],
        {},
        max_iterations=plan_mod.MAX_TOOL_ITER,
        extract_content_and_tokens=lambda r: (r.get("content", ""), r.get("tokens", 0)),
        extract_tool_calls=lambda r: r.get("tool_calls", []),
        normalize_chat_result=lambda r: (r.get("content", ""), r.get("tokens", 0)),
        dispatch_tool_call=lambda tc, handlers: {"ok": True},
    )


def _drive(plan: SubagentPlan) -> None:
    async def _run() -> None:
        async for _event in AgentRuntime().run_stream(RuntimeContext(), plan):
            pass

    run_sync(_run())


def test_the_worker_drives_the_shared_runtime() -> None:
    """``_complete_with_tools`` must use the shared runtime."""
    src = inspect.getsource(LlmClientDriver._complete_with_tools)
    assert "RUNTIME.run_stream" in src
    assert "SubagentPlan(" in src


def test_the_worker_no_longer_has_its_own_loop() -> None:
    """The old inline ``for _ in range(_MAX_TOOL_ITER)`` loop is gone."""
    src = inspect.getsource(LlmClientDriver._complete_with_tools)
    assert "for _ in range(_MAX_TOOL_ITER)" not in src


def test_the_plan_keeps_the_iteration_cap() -> None:
    """The cap is the same value the old loop used."""
    assert plan_mod.MAX_TOOL_ITER == 5


def test_no_tool_calls_ends_the_loop_after_one_round() -> None:
    """Without tool calls the loop stops after one round."""
    client = _FakeClient([{"content": "answer", "tokens": 3, "tool_calls": []}])
    plan = _plan(client)
    _drive(plan)
    assert plan.content == "answer"
    assert plan.total_tokens == 3
    assert len(client.calls) == 1


def test_tool_calls_are_executed_and_fed_back() -> None:
    """A tool call runs and its result goes back into the messages."""
    messages: list[dict[str, Any]] = []
    client = _FakeClient(
        [
            {
                "content": "step 1",
                "tokens": 1,
                "tool_calls": [{"id": "c1", "name": "WebSearch", "args": "{}"}],
            },
            {"content": "final", "tokens": 2, "tool_calls": []},
        ]
    )
    plan = _plan(client, messages)
    _drive(plan)
    assert plan.content == "final"
    assert plan.total_tokens == 3
    # The assistant message and the tool result are appended only when
    # the model asked for tools — the second round asked for none, so the
    # loop stopped there.
    roles = [m["role"] for m in messages]
    assert roles == ["assistant", "tool"]
    assert messages[1]["tool_call_id"] == "c1"


def test_the_iteration_cap_is_enforced() -> None:
    """The model keeps asking for tools — the cap stops the loop."""
    messages: list[dict[str, Any]] = []
    responses = [
        {
            "content": f"step {i}",
            "tokens": 1,
            "tool_calls": [{"id": f"c{i}", "name": "WebSearch", "args": "{}"}],
        }
        for i in range(plan_mod.MAX_TOOL_ITER + 3)
    ]
    client = _FakeClient(responses)
    plan = _plan(client, messages)
    _drive(plan)
    assert len(client.calls) == plan_mod.MAX_TOOL_ITER
    assert plan.content == f"step {plan_mod.MAX_TOOL_ITER - 1}"


def test_a_non_fatal_error_falls_back_to_plain_chat() -> None:
    """A tool-not-supported error recovers with a plain chat call."""
    client = _FakeClient([], fail_with=RuntimeError("tools unsupported"))
    plan = _plan(client)
    _drive(plan)
    assert client.plain_calls == 1
    assert plan.content == "fallback answer"
    assert plan.total_tokens == 7


def test_a_fatal_status_is_propagated() -> None:
    """Auth / rate-limit errors must not be swallowed."""
    from llmwikify.foundation.llm.streamable import LLMRequestError

    err = LLMRequestError(429, "https://api.invalid/v1", "")
    client = _FakeClient([], fail_with=err)
    plan = _plan(client)
    with pytest.raises(LLMRequestError):
        _drive(plan)
    assert client.plain_calls == 0
