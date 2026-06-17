"""Tests for ChatRunner + microcompact (Phase A Facade).

Covers the 20-case matrix from docs/poc/phase-a-steps.md §3.7:
  1-5  microcompact pure-function tests
  6-15 ChatRunSpec / ChatRunResult dataclass tests
 16-20 ChatRunner facade + bridge integration tests
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.microcompact import (
    build_microcompact_fn,
    microcompact_serialize,
)
from llmwikify.apps.chat.agent.runner import ChatRunner
from llmwikify.apps.chat.agent.spec import (
    DEFAULT_COMPACTABLE_TOOLS,
    ChatRunResult,
    ChatRunSpec,
)


def _make_spec(**overrides) -> ChatRunSpec:
    defaults: dict = {
        "messages": [{"role": "user", "content": "hi"}],
        "tool_registry": object(),
        "session_id": "s1",
    }
    defaults.update(overrides)
    return ChatRunSpec(**defaults)


def test_microcompact_default_off_when_disabled() -> None:
    spec = _make_spec(microcompact=False)
    big = {"data": "x" * 5000}
    content, compacted, saved = microcompact_serialize(big, "read_file", "c1", spec)
    assert compacted is False
    assert saved == 0
    assert "data" in content and "xxx" in content
    assert spec.compacted() == []


def test_microcompact_keeps_small_results() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=1000)
    small = {"data": "tiny"}
    content, compacted, _saved = microcompact_serialize(small, "read_file", "c1", spec)
    assert compacted is False
    assert "tiny" in content
    assert spec.compacted() == []


def test_microcompact_replaces_oversized_result() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=200)
    big = {"lines": ["line"] * 1000}
    content, compacted, saved = microcompact_serialize(big, "read_file", "c1", spec)
    assert compacted is True
    assert saved > 0
    assert "[Tool result compacted]" in content
    assert "Tool: read_file" in content
    assert "Original: " in content
    assert spec.compacted() == [("c1", big)]


def test_microcompact_skips_non_compactable_tool() -> None:
    spec = _make_spec(microcompact=True)
    big = {"data": "x" * 5000}
    content, compacted, _saved = microcompact_serialize(big, "write_file", "c1", spec)
    assert compacted is False
    assert spec.compacted() == []


def test_microcompact_marker_contains_metadata() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    big = {"payload": "y" * 2000}
    content, compacted, _saved = microcompact_serialize(big, "exec", "call_xyz", spec)
    assert compacted is True
    assert "Tool: exec" in content
    assert "Original: " in content and "chars" in content
    assert "Kept: 100 chars" in content
    assert "tool_call_id: call_xyz" in content
    assert "yyyy" in content


def test_microcompact_build_fn_updates_counter() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=50)
    counter: dict[str, int] = {}
    fn = build_microcompact_fn(spec, counter=counter)

    fn({"a": "x" * 500}, "read_file", "c1")
    fn({"b": "y" * 500}, "read_file", "c2")
    fn("small", "read_file", "c3")

    assert counter["count"] == 2
    assert counter["chars_saved"] > 0


def test_default_compactable_tools_set_matches_nanobot() -> None:
    expected = {
        "read_file", "exec", "grep", "find_files",
        "web_search", "web_fetch", "list_dir",
    }
    assert DEFAULT_COMPACTABLE_TOOLS == frozenset(expected)


def test_chat_run_spec_defaults() -> None:
    spec = _make_spec()
    assert spec.microcompact is True
    assert spec.microcompact_keep_chars == 1000
    assert spec.microcompact_compactable_tools == DEFAULT_COMPACTABLE_TOOLS
    assert spec.max_iterations == 10
    assert spec.max_tool_result_chars == 50000
    assert spec._compacted_results == {}


def test_chat_run_spec_accepts_overrides() -> None:
    spec = _make_spec(
        microcompact=False,
        microcompact_keep_chars=200,
        max_iterations=5,
        workspace=Path("/tmp"),
    )
    assert spec.microcompact is False
    assert spec.microcompact_keep_chars == 200
    assert spec.max_iterations == 5
    assert spec.workspace == Path("/tmp")


def test_chat_run_result_defaults() -> None:
    result = ChatRunResult(
        final_content="hello",
        messages=[],
        tools_used=["read_file"],
        usage={"prompt_tokens": 10},
        stop_reason="completed",
    )
    assert result.error is None
    assert result.compacted_count == 0
    assert result.total_compacted_chars_saved == 0


def test_chat_run_result_carries_compact_stats() -> None:
    result = ChatRunResult(
        final_content=None,
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="error",
        error="boom",
        compacted_count=3,
        total_compacted_chars_saved=12345,
    )
    assert result.compacted_count == 3
    assert result.total_compacted_chars_saved == 12345
    assert result.error == "boom"


def test_chat_runner_build_bridge_wires_microcompact() -> None:
    class FakeChatService:
        config: dict = {}

    runner = ChatRunner(FakeChatService())
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    bridge = runner.build_bridge(spec)
    assert bridge._microcompact_fn is not None
    big = {"data": "z" * 500}
    content, compacted, _saved = bridge._microcompact_fn(big, "read_file", "c1")
    assert compacted is True
    assert "[Tool result compacted]" in content


def test_chat_runner_bridge_without_microcompact_fn_is_none() -> None:
    class FakeChatService:
        config: dict = {}

    ChatRunner(FakeChatService())
    from llmwikify.apps.chat.agent.chat_react import ChatReActBridge
    bridge2 = ChatReActBridge(chat_service=FakeChatService())
    assert bridge2._microcompact_fn is None


def test_chat_react_bridge_default_microcompact_fn_is_none() -> None:
    from llmwikify.apps.chat.agent.chat_react import ChatReActBridge

    class FakeService:
        config: dict = {}

    bridge = ChatReActBridge(chat_service=FakeService())
    assert bridge._microcompact_fn is None


def test_chat_react_bridge_accepts_microcompact_fn() -> None:
    from llmwikify.apps.chat.agent.chat_react import ChatReActBridge

    def sentinel(*_a, **_k):
        return ("MARKER", True, 100)

    bridge = ChatReActBridge(chat_service=type("S", (), {"config": {}})(), microcompact_fn=sentinel)
    assert bridge._microcompact_fn is sentinel


def test_run_to_completion_returns_error_on_exception() -> None:
    class BrokenChatService:
        config: dict = {}

    async def fake_run(self, spec):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    import llmwikify.apps.chat.agent.runner as runner_mod
    original = runner_mod.ChatRunner.run
    runner_mod.ChatRunner.run = fake_run
    try:
        import asyncio
        spec = _make_spec()
        result = asyncio.run(ChatRunner(BrokenChatService()).run_to_completion(spec))
        assert result.stop_reason == "error"
        assert "boom" in (result.error or "")
    finally:
        runner_mod.ChatRunner.run = original


def test_compacted_accessor_returns_copy() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=50)
    big = {"a": "b" * 500}
    microcompact_serialize(big, "read_file", "c1", spec)
    items = spec.compacted()
    items.clear()
    assert spec.compacted() == [("c1", big)]


def test_chat_run_spec_path_field_accepts_none() -> None:
    spec = _make_spec(workspace=None)
    assert spec.workspace is None
    spec2 = _make_spec(workspace=Path("/tmp/x"))
    assert spec2.workspace == Path("/tmp/x")


def test_microcompact_serialize_handles_non_dict_result() -> None:
    spec = _make_spec(microcompact=True, microcompact_keep_chars=50)
    result_str = "x" * 2000
    content, compacted, saved = microcompact_serialize(
        result_str, "read_file", "c1", spec,
    )
    assert compacted is True
    assert "xxxx" in content
    assert saved > 0


def test_microcompact_serialize_handles_unserializable() -> None:
    class Opaque:
        def __repr__(self) -> str:
            return "<opaque payload>"

    spec = _make_spec(microcompact=True, microcompact_keep_chars=50)
    big = [Opaque()] * 200
    content, compacted, _saved = microcompact_serialize(big, "exec", "c1", spec)
    assert compacted is True
    assert "[Tool result compacted]" in content
    assert "opaque" in content
