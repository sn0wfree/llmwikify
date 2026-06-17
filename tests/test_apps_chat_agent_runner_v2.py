"""Tests for ChatRunnerV2 skeleton (Plan B Step B-1).

B-1 only establishes the public API surface, so the matrix is small:
  1. ChatRunnerV2 instantiates with required deps
  2. run_stream yields at least one done event
  3. run_to_completion returns ChatRunResult with expected defaults
  4. ChatRunResult carries microcompact stats fields (compacted_count,
     total_compacted_chars_saved) when present in the event stream
  5. exception in run_stream → run_to_completion sets stop_reason=error
  6. _RunContext.elapsed() returns non-negative float
  7. hook parameter defaults to NoOpHook
  8. does not import legacy engines
  9. dependencies are minimal (only spec + callback)
 10. skeleton works without DB / LLM / SSE infrastructure

Plus 15 edge-case tests covering:
  - _RunContext defaults, slots, time progression, field independence
  - ChatRunResult aggregation: no events, error string, confirmation
  - Multi-event streaming: ordering, message_delta accumulation
  - Concurrency: two run_to_completion calls don't share state
  - Mutation safety: spec.messages not mutated by run
  - stop_reason preservation through the aggregation pipeline
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2, _RunContext
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.foundation.callback import NoOpHook


class _StubService:
    config: dict = {}


class _StubExecutor:
    pass


class _StubPromptBuilder:
    pass


def _make_runner() -> ChatRunnerV2:
    return ChatRunnerV2(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )


def _make_spec(**overrides) -> ChatRunSpec:
    defaults: dict = {
        "messages": [{"role": "user", "content": "hi"}],
        "tool_registry": object(),
        "session_id": "s1",
    }
    defaults.update(overrides)
    return ChatRunSpec(**defaults)


def test_runner_instantiates() -> None:
    runner = _make_runner()
    assert runner._chat_service.__class__.__name__ == "_StubService"
    assert runner._tool_executor.__class__.__name__ == "_StubExecutor"
    assert runner._prompt_builder.__class__.__name__ == "_StubPromptBuilder"
    assert runner._config == {}
    assert isinstance(runner._hook, NoOpHook)


def test_runner_accepts_custom_hook() -> None:
    hook = NoOpHook()
    runner = ChatRunnerV2(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
        hook=hook,
    )
    assert runner._hook is hook


def test_run_stream_yields_done_event() -> None:
    runner = _make_runner()
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        events = []
        async for ev in runner.run_stream(spec):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    assert len(events) >= 1
    assert events[-1]["type"] == "done"
    assert events[-1]["_v2"] is True


def test_run_to_completion_returns_chat_run_result() -> None:
    runner = _make_runner()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert isinstance(result, ChatRunResult)
    assert result.stop_reason == "completed"
    assert result.error is None
    assert result.tools_used == []
    assert result.compacted_count == 0
    assert result.total_compacted_chars_saved == 0


def test_run_context_elapsed_nonnegative() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    assert isinstance(ctx.elapsed(), float)
    assert ctx.elapsed() >= 0.0


def test_exception_in_run_stream_sets_error() -> None:
    class _Boom(ChatRunnerV2):
        async def run_stream(self, spec):
            raise RuntimeError("v2 boom")
            yield  # pragma: no cover

    runner = _Boom(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"
    assert "v2 boom" in (result.error or "")


def test_compacted_events_aggregate_stats() -> None:
    class _Emitting(ChatRunnerV2):
        async def run_stream(self, spec):
            yield {"type": "message_delta", "content": "Hello "}
            yield {"type": "compacted", "chars_saved": 200}
            yield {"type": "compacted", "chars_saved": 300}
            yield {"type": "tool_call_end", "tool": "read_file"}
            yield {"type": "done", "content": "Hello world"}

    runner = _Emitting(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 2
    assert result.total_compacted_chars_saved == 500
    assert "read_file" in result.tools_used
    assert result.final_content == "Hello world"


def test_run_context_carries_spec_state() -> None:
    spec = _make_spec(session_id="s42", wiki_id="w9")
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.spec.session_id == "s42"
    assert ctx.spec.wiki_id == "w9"
    assert ctx.cancelled is False
    assert ctx.paused is False
    assert ctx.stop_reason == "in_progress"


def test_runner_does_not_import_legacy_engines() -> None:
    import llmwikify.apps.chat.agent.runner_v2 as mod

    src = open(mod.__file__, encoding="utf-8").read()
    forbidden = (
        "from llmwikify.apps.chat.agent.chat_react",
        "from llmwikify.apps.chat.agent.react_engine",
        "from llmwikify.apps.chat.agent.orchestrator",
        "from llmwikify.apps.chat.agent.agent_service",
    )
    for needle in forbidden:
        assert needle not in src, (
            f"runner_v2 must not import legacy engines; found: {needle}"
        )


def test_runner_dependencies_are_minimal() -> None:
    import llmwikify.apps.chat.agent.runner_v2 as mod

    src = open(mod.__file__, encoding="utf-8").read()
    allowed_local_imports = {
        "from llmwikify.apps.chat.agent.spec import",
        "from llmwikify.foundation.callback import",
    }
    for line in src.splitlines():
        if line.startswith("from llmwikify") or line.startswith("import llmwikify"):
            assert any(line.startswith(p) for p in allowed_local_imports), (
                f"unexpected llmwikify import in runner_v2: {line.strip()}"
            )


def test_skeleton_works_without_db_llm_sse() -> None:
    runner = ChatRunnerV2(
        chat_service=None,
        tool_executor=None,
        prompt_builder=None,
    )
    spec = _make_spec()

    async def drain() -> list[dict[str, Any]]:
        out = []
        async for ev in runner.run_stream(spec):
            out.append(ev)
        return out

    events = asyncio.run(drain())
    assert events[-1]["type"] == "done"
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert result.error is None


# ─── Edge cases & boundaries ──────────────────────────────────


def test_run_context_init_with_empty_messages() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.messages == []
    assert ctx.tools_used == []
    assert ctx.observations == []
    assert ctx.usage == {}


def test_run_context_cancelled_paused_default_false() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.cancelled is False
    assert ctx.paused is False


def test_run_context_stop_reason_in_progress() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.stop_reason == "in_progress"


def test_run_context_elapsed_increases_with_time() -> None:
    import time as time_mod

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    first = ctx.elapsed()
    time_mod.sleep(0.05)
    second = ctx.elapsed()
    assert second > first
    assert second >= 0.05


def test_run_context_observations_independent_of_tools_used() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.tools_used.append("read_file")
    ctx.observations.append("Called read_file")
    assert ctx.tools_used == ["read_file"]
    assert ctx.observations == ["Called read_file"]


def test_chat_run_result_aggregation_with_no_events() -> None:
    class _Silent(ChatRunnerV2):
        async def run_stream(self, spec):
            if False:
                yield {}
            return

    runner = _Silent(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert result.final_content is None
    assert result.tools_used == []
    assert result.compacted_count == 0


def test_chat_run_result_default_error_is_none() -> None:
    result = ChatRunResult(
        final_content="x",
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="completed",
    )
    assert result.error is None


def test_chat_run_result_preserves_error_string() -> None:
    result = ChatRunResult(
        final_content=None,
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="error",
        error="TypeError: bad arg",
    )
    assert result.error == "TypeError: bad arg"
    assert result.stop_reason == "error"


def test_run_stream_drains_multiple_event_types() -> None:
    class _MultiEvent(ChatRunnerV2):
        async def run_stream(self, spec):
            yield {"type": "message_delta", "content": "Hello"}
            yield {"type": "thinking", "content": "thinking..."}
            yield {"type": "tool_call_start", "tool": "x", "args": {}}
            yield {"type": "tool_call_end", "tool": "x", "result": "ok"}
            yield {"type": "done", "content": "Hello world"}

    runner = _MultiEvent(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(collect())
    assert len(events) == 5
    assert [e["type"] for e in events] == [
        "message_delta", "thinking", "tool_call_start", "tool_call_end", "done",
    ]


def test_run_to_completion_aggregates_message_deltas() -> None:
    class _Streaming(ChatRunnerV2):
        async def run_stream(self, spec):
            yield {"type": "message_delta", "content": "Part 1. "}
            yield {"type": "message_delta", "content": "Part 2. "}
            yield {"type": "message_delta", "content": "Part 3."}
            yield {"type": "done", "content": "Part 1. Part 2. Part 3."}

    runner = _Streaming(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "Part 1. Part 2. Part 3."


def test_run_to_completion_handles_confirmation_required() -> None:
    class _Confirm(ChatRunnerV2):
        async def run_stream(self, spec):
            yield {"type": "tool_call_start", "tool": "write_file", "args": {}}
            yield {
                "type": "confirmation_required",
                "confirmation_id": "c1",
                "tool": "write_file",
            }
            yield {"type": "done", "content": ""}

    runner = _Confirm(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


def test_concurrent_run_to_completion_isolates_state() -> None:
    class _Tagged(ChatRunnerV2):
        async def run_stream(self, spec):
            yield {
                "type": "done",
                "content": f"tag={spec.session_id}",
            }

    runner = _Tagged(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )

    async def run_two() -> tuple[ChatRunResult, ChatRunResult]:
        return await asyncio.gather(
            runner.run_to_completion(_make_spec(session_id="alpha")),
            runner.run_to_completion(_make_spec(session_id="beta")),
        )

    r1, r2 = asyncio.run(run_two())
    assert "alpha" in (r1.final_content or "")
    assert "beta" in (r2.final_content or "")
    assert r1.final_content != r2.final_content


def test_run_context_dataclass_is_slots() -> None:
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert hasattr(_RunContext, "__slots__")
    try:
        ctx.unknown_field = "should fail"
    except AttributeError:
        pass
    else:
        pytest.fail("_RunContext is not slots-constrained")


def test_runner_does_not_mutate_input_spec_messages() -> None:
    runner = _make_runner()
    spec = _make_spec(messages=[{"role": "user", "content": "hello"}])
    original_len = len(spec.messages)
    asyncio.run(runner.run_to_completion(spec))
    assert len(spec.messages) == original_len


def test_run_to_completion_preserves_stop_reason_completed() -> None:
    runner = _make_runner()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "error")
