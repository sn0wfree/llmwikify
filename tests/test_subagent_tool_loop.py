"""Unit tests for subagent tool loop (v0.41).

Covers the ReAct loop in ``LlmClientDriver.complete()`` when the
request declares ``actor_tools``. Each test uses a fake LLM client
that returns scripted ``chat_with_tools`` responses, then asserts
on the final ``messages`` list and return value.

Target: 10 tests covering fast-path (no tools), single tool call,
multi-iteration loop, max-iter termination, unknown tool, bad JSON
args, handler exception, path traversal in Read/Grep/Glob.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llmwikify.apps.chat.skills.workflows.subagent_runner import SubagentRequest
from llmwikify.apps.chat.skills.workflows.subagent_worker import (
    _TOOL_HANDLERS,
    _TOOL_SPECS,
    LlmClientDriver,
    _build_subagent_tools,
    _dispatch_tool_call,
    _extract_tool_calls,
    _normalize_chat_result,
)

# ─── Fake client + request helpers ──────────────────────────────


class FakeClient:
    """Scripted chat_with_tools / chat responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.chat_with_tools_calls: list[dict[str, Any]] = []
        self.chat_calls: list[dict[str, Any]] = []

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.chat_with_tools_calls.append({"messages": list(messages), "tools": tools})
        if not self.responses:
            return {"content": "[exhausted]", "tool_calls": None, "usage": {"total_tokens": 0}}
        return self.responses.pop(0)

    def chat(self, messages: list[dict[str, Any]]) -> str:
        self.chat_calls.append({"messages": list(messages)})
        return "[fallback]"


def _make_request(
    actor_tools: tuple[str, ...] = (),
    worktree_path: str | None = None,
    actor_model: str = "test-model",
) -> SubagentRequest:
    """Minimal SubagentRequest for tool loop tests."""
    from llmwikify.foundation.llm.spec import LLMSpec

    return SubagentRequest(
        actor_name="test_actor",
        actor_prompt_source="inline:test",
        actor_prompt_text="you are a test actor",
        actor_model=actor_model,
        actor_tools=actor_tools,
        actor_permission_mode="default",
        inputs={"query": "x"},
        budget={},
        session_id="s_test",
        worktree_path=worktree_path,
        llm=LLMSpec(
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
            context_window=8192,
            timeout=30.0,
            reasoning_split=False,
            auth_scheme="bearer",
            budget_on_exceed="warn",
            extra_headers={},
            source="test",
        ),
    )


def _tc(name: str, args: dict | str, call_id: str = "c1") -> dict[str, Any]:
    """Helper to construct a tool_call dict (as chat_with_tools returns)."""
    return {
        "id": call_id,
        "name": name,
        "args": json.dumps(args) if isinstance(args, dict) else args,
    }


# ─── Tool spec/handler inventory ────────────────────────────────


class TestToolInventory:
    def test_known_tools_have_specs_and_handlers(self) -> None:
        for name in ("WebSearch", "WebFetch", "Read", "Grep", "Glob"):
            assert name in _TOOL_SPECS, f"{name} missing from _TOOL_SPECS"
            assert name in _TOOL_HANDLERS, f"{name} missing from _TOOL_HANDLERS"

    def test_specs_have_function_definitions(self) -> None:
        for name, spec in _TOOL_SPECS.items():
            assert spec["type"] == "function"
            fn = spec["function"]
            assert fn["name"] == name
            assert "description" in fn
            params = fn["parameters"]
            assert params["type"] == "object"
            assert "properties" in params
            assert "required" in params


# ─── Build tools ─────────────────────────────────────────────────


class TestBuildTools:
    def test_empty_actor_tools(self) -> None:
        req = _make_request(actor_tools=())
        defs, handlers = _build_subagent_tools(req.actor_tools, req)
        assert defs == []
        assert handlers == {}

    def test_known_tools_built(self) -> None:
        req = _make_request(actor_tools=("WebSearch", "WebFetch", "Read"))
        defs, handlers = _build_subagent_tools(req.actor_tools, req)
        assert len(defs) == 3
        assert sorted(handlers.keys()) == ["Read", "WebFetch", "WebSearch"]
        # Specs preserve input order; verify by name set
        spec_names = {d["function"]["name"] for d in defs}
        assert spec_names == {"Read", "WebFetch", "WebSearch"}
        # Each handler name maps to a tool spec of the same name
        for name in handlers:
            assert any(d["function"]["name"] == name for d in defs)

    def test_unknown_tools_silently_skipped(self) -> None:
        req = _make_request(actor_tools=("WebSearch", "UnknownTool", "Read"))
        defs, handlers = _build_subagent_tools(req.actor_tools, req)
        assert sorted(d["function"]["name"] for d in defs) == ["Read", "WebSearch"]
        assert sorted(handlers.keys()) == ["Read", "WebSearch"]


# ─── Dispatch ───────────────────────────────────────────────────


class TestDispatch:
    def test_unknown_tool_returns_error(self) -> None:
        tc = _tc("GhostTool", {})
        result = _dispatch_tool_call(tc, {})
        assert "error" in result
        assert "GhostTool" in result["error"]

    def test_bad_json_args_returns_error(self) -> None:
        tc = _tc("WebSearch", "{not valid json")
        handlers = {"WebSearch": lambda **kw: {"ok": True}}
        result = _dispatch_tool_call(tc, handlers)
        assert "error" in result
        assert "invalid tool args JSON" in result["error"]

    def test_handler_exception_caught(self) -> None:
        def boom(**kw):
            raise RuntimeError("boom!")

        tc = _tc("X", {})
        result = _dispatch_tool_call(tc, {"X": boom})
        assert "error" in result
        assert "boom!" in result["error"]

    def test_non_dict_result_wrapped(self) -> None:
        def string_handler(**kw):
            return "just a string"

        tc = _tc("X", {})
        result = _dispatch_tool_call(tc, {"X": string_handler})
        assert result == {"value": "just a string"}

    def test_handler_called_with_kwargs(self) -> None:
        captured = {}
        def capture(**kw):
            captured.update(kw)
            return {"ok": True}

        tc = _tc("X", {"foo": "bar", "n": 42})
        result = _dispatch_tool_call(tc, {"X": capture})
        assert captured == {"foo": "bar", "n": 42}
        assert result == {"ok": True}


# ─── Helpers ────────────────────────────────────────────────────


class TestNormalizeChatResult:
    def test_dict_with_content(self) -> None:
        text, tokens = _normalize_chat_result({"content": "hi", "usage": {"total_tokens": 10}})
        assert text == "hi"
        assert tokens == 10

    def test_dict_without_usage(self) -> None:
        text, tokens = _normalize_chat_result({"content": "hi"})
        assert text == "hi"
        assert tokens == 0

    def test_string_passthrough(self) -> None:
        text, tokens = _normalize_chat_result("raw")
        assert text == "raw"
        assert tokens == 0

    def test_extract_tool_calls_none(self) -> None:
        assert _extract_tool_calls({"content": "x"}) == []

    def test_extract_tool_calls_list(self) -> None:
        tcs = [{"id": "a", "name": "X", "args": "{}"}]
        assert _extract_tool_calls({"tool_calls": tcs}) == tcs


# ─── Tool loop: LlmClientDriver.complete() ──────────────────────


class _LoopDriver(LlmClientDriver):
    """LlmClientDriver with stubbed _build_client."""

    def __init__(self, fake_client: FakeClient) -> None:
        # Skip the parent __init__ — we override _build_client.
        self._fake = fake_client

    def _build_client(self, request, model: str):
        return self._fake


def _run_loop(
    driver: LlmClientDriver,
    request: SubagentRequest,
    messages: list[dict[str, Any]],
) -> tuple[str, int]:
    """Run driver.complete with a request ctx set."""
    from llmwikify.apps.chat.skills.workflows.subagent_worker import _request_ctx

    token = _request_ctx.set(request)
    try:
        return driver.complete(messages, request.actor_model)
    finally:
        _request_ctx.reset(token)


class TestToolLoop:
    def test_fast_path_no_actor_tools(self) -> None:
        """When actor_tools is empty, the loop is skipped (uses chat())."""
        fake = FakeClient([{"content": "done", "usage": {"total_tokens": 5}}])
        # Patch .chat to return a string directly
        fake.chat = lambda messages: "fast-path-result"
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=())
        messages = [{"role": "user", "content": "hi"}]
        text, tokens = _run_loop(driver, request, messages)
        assert text == "fast-path-result"
        # chat_with_tools NOT called
        assert fake.chat_with_tools_calls == []

    def test_single_tool_call(self) -> None:
        """LLM makes one tool call, then returns content."""
        fake = FakeClient([
            {
                "content": "",
                "tool_calls": [_tc("WebSearch", {"query": "x"})],
                "usage": {"total_tokens": 10},
            },
            {"content": "final answer", "tool_calls": None, "usage": {"total_tokens": 5}},
        ])
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=("WebSearch",))
        messages = [{"role": "user", "content": "hi"}]

        # Patch _TOOL_HANDLERS["WebSearch"] directly (module-level dict
        # holds the reference; patching the function object would not
        # affect the binding).
        from unittest.mock import patch
        stub = lambda **kw: {"results": [{"title": "t", "url": "u", "snippet": "s"}]}
        with patch.dict(
            "llmwikify.apps.chat.skills.workflows.subagent_worker._TOOL_HANDLERS",
            {"WebSearch": stub},
        ):
            text, tokens = _run_loop(driver, request, messages)

        assert text == "final answer"
        assert tokens == 15  # 10 + 5
        # Two iterations (tool call, then no tool call)
        assert len(fake.chat_with_tools_calls) == 2
        # Second call's messages include the tool result
        second_call_messages = fake.chat_with_tools_calls[1]["messages"]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "c1"
        result = json.loads(tool_msgs[0]["content"])
        assert result["results"][0]["title"] == "t"

    def test_multiple_iterations(self) -> None:
        """Three tool calls across three iterations, then done."""
        fake = FakeClient([
            {"content": "", "tool_calls": [_tc("WebSearch", {"query": "q1"}, "c1")], "usage": {"total_tokens": 1}},
            {"content": "", "tool_calls": [_tc("WebSearch", {"query": "q2"}, "c2")], "usage": {"total_tokens": 1}},
            {"content": "", "tool_calls": [_tc("WebSearch", {"query": "q3"}, "c3")], "usage": {"total_tokens": 1}},
            {"content": "all done", "tool_calls": None, "usage": {"total_tokens": 1}},
        ])
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=("WebSearch",))
        messages = [{"role": "user", "content": "hi"}]

        from unittest.mock import patch
        with patch.dict(
            "llmwikify.apps.chat.skills.workflows.subagent_worker._TOOL_HANDLERS",
            {"WebSearch": lambda **kw: {"results": []}},
        ):
            text, tokens = _run_loop(driver, request, messages)

        assert text == "all done"
        assert len(fake.chat_with_tools_calls) == 4  # 3 tool + 1 done

    def test_max_iter_termination(self) -> None:
        """If LLM keeps returning tool_calls, loop exits after MAX_TOOL_ITER."""
        # Provide MAX_TOOL_ITER + 1 tool responses, then check the loop stops.
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _MAX_TOOL_ITER

        responses = [
            {"content": "", "tool_calls": [_tc("WebSearch", {"query": f"q{i}"}, f"c{i}")],
             "usage": {"total_tokens": 1}}
            for i in range(_MAX_TOOL_ITER + 2)
        ]
        fake = FakeClient(responses)
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=("WebSearch",))
        messages = [{"role": "user", "content": "hi"}]

        from unittest.mock import patch
        with patch.dict(
            "llmwikify.apps.chat.skills.workflows.subagent_worker._TOOL_HANDLERS",
            {"WebSearch": lambda **kw: {"results": []}},
        ):
            text, tokens = _run_loop(driver, request, messages)

        # Loop bounded by _MAX_TOOL_ITER
        assert len(fake.chat_with_tools_calls) == _MAX_TOOL_ITER

    def test_unknown_tool_in_dispatch_returns_error(self) -> None:
        """If the LLM returns a tool we don't have, dispatch returns error."""
        fake = FakeClient([
            {
                "content": "",
                "tool_calls": [_tc("MysteryTool", {}, "c1")],
                "usage": {"total_tokens": 1},
            },
            {"content": "done", "tool_calls": None, "usage": {"total_tokens": 1}},
        ])
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=("WebSearch",))
        messages = [{"role": "user", "content": "hi"}]
        text, tokens = _run_loop(driver, request, messages)
        assert text == "done"
        # Second call should include the error message
        second = fake.chat_with_tools_calls[1]["messages"]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        err = json.loads(tool_msgs[0]["content"])
        assert "unknown tool" in err["error"]
        assert "MysteryTool" in err["error"]

    def test_handler_exception_doesnt_crash_loop(self) -> None:
        """If a handler raises, the error is fed back and the loop continues."""
        fake = FakeClient([
            {
                "content": "",
                "tool_calls": [_tc("WebSearch", {"query": "x"}, "c1")],
                "usage": {"total_tokens": 1},
            },
            {"content": "recovered", "tool_calls": None, "usage": {"total_tokens": 1}},
        ])
        driver = _LoopDriver(fake)
        request = _make_request(actor_tools=("WebSearch",))
        messages = [{"role": "user", "content": "hi"}]

        from unittest.mock import patch
        def boom(**kw):
            raise RuntimeError("handler exploded")
        with patch.dict(
            "llmwikify.apps.chat.skills.workflows.subagent_worker._TOOL_HANDLERS",
            {"WebSearch": boom},
        ):
            text, tokens = _run_loop(driver, request, messages)

        assert text == "recovered"


# ─── File tool path traversal guard ─────────────────────────────


class TestFileToolSafety:
    """Read/Grep/Glob must refuse paths outside worktree."""

    def _setup_worktree(self, tmp_path: Path) -> Path:
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "in_repo.txt").write_text("inside")
        return wt

    def test_read_outside_worktree_rejected(self, tmp_path: Path) -> None:
        wt = self._setup_worktree(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")

        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_read
        result = _handle_read("../outside.txt", worktree_path=str(wt))
        assert "error" in result
        assert "outside worktree" in result["error"]

    def test_read_absolute_path_rejected(self, tmp_path: Path) -> None:
        wt = self._setup_worktree(tmp_path)
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_read
        result = _handle_read("/etc/passwd", worktree_path=str(wt))
        assert "error" in result
        assert "outside worktree" in result["error"]

    def test_read_inside_worktree_succeeds(self, tmp_path: Path) -> None:
        wt = self._setup_worktree(tmp_path)
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_read
        result = _handle_read("in_repo.txt", worktree_path=str(wt))
        assert "content" in result
        assert "inside" in result["content"]
        assert result["truncated"] is False

    def test_read_no_worktree_returns_error(self) -> None:
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_read
        result = _handle_read("anything.txt", worktree_path=None)
        assert "error" in result
        assert "no worktree_path" in result["error"]

    def test_glob_outside_worktree_rejected(self, tmp_path: Path) -> None:
        wt = self._setup_worktree(tmp_path)
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_glob
        result = _handle_glob("../*.txt", worktree_path=str(wt))
        assert "error" in result
        assert "outside worktree" in result["error"]

    def test_glob_inside_worktree_succeeds(self, tmp_path: Path) -> None:
        wt = self._setup_worktree(tmp_path)
        (wt / "sub").mkdir()
        (wt / "sub" / "x.py").write_text("x")
        from llmwikify.apps.chat.skills.workflows.subagent_worker import _handle_glob
        result = _handle_glob("**/*.py", worktree_path=str(wt))
        assert "files" in result
        assert any("x.py" in f for f in result["files"])
