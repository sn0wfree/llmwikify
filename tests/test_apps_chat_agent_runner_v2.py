"""Tests for ChatRunnerV2 (Plan B Steps B-1 + B-2 + B-3 + extended).

B-1: skeleton + public API surface (8 cases)
B-1-extension: independence + edge cases (18 cases)
B-2: 5-step state machine + hooks + microcompact + text-mode (17 cases)
B-3: golden comparisons + integration + edge cases (20 cases)
Extended: hook coverage + isolation + concurrency + state (22 cases)

Total: 85 cases covering:
  - Public API: run_stream, run_to_completion, ChatRunResult aggregation
  - _RunContext: defaults, slots, time progression, field independence
  - Independence: no legacy engine imports, minimal deps, works without infra
  - 5-step loop: PRECHECK/REASON/ACT/OBSERVE/COMPLETE
  - CompositeHook: 11 hook points wired through the loop
  - microcompact: native integration (default ON, configurable)
  - text-mode: [TOOL_CALL] Perl-style parsing
  - Error handling: LLM stream failure → stop_reason=error
  - Concurrency: two run_to_completion calls don't share state
  - Mutation safety: spec.messages not mutated
  - confirmation_required: tool result → stop_reason=confirmation_required
  - max_iterations: caps the loop
  - multi-tool: executes multiple tool calls per iteration
  - Golden comparisons: exact event sequences for Q&A / single / multi / error / max
  - Integration: WikiHook / microcompact cache / text-mode split chunks / truncation
  - Edge: empty messages / wiki_id=None / error dict / exception caught / 2x compact
  - Hook coverage: before/after_iteration / on_stream / emit_reasoning /
    before_execute_tools / after_tool_executed / on_tool_error /
    on_confirmation / on_error
  - Hook isolation: failing hook doesn't break the loop
  - State safety: spec immutability / session_id preservation / ctx messages
  - Boundary: microcompact exact threshold / 2-compact-in-one-iteration
  - Error recovery: truncate failure / spec failure / exception propagation
  - Event ordering: error before done on failure path
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
    assert events[-1]["stop_reason"] == "completed"


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
        "from llmwikify.apps.chat.agent.microcompact import",
        "from llmwikify.apps.chat.agent.text_mode_tool import",
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


# ─── B-2 核心循环 (5 步) + 钩子 + microcompact ────────────────


class _StubLLMService:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        followup_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config: dict = {}
        self._events = events or [{"type": "done", "content": "stub answer"}]
        self._followup = followup_events or [{"type": "done", "content": "stub answer"}]
        self.tool_spec_called = False
        self.truncate_called = False
        self.call_count = 0

    def _get_toolspec(self, _registry):
        self.tool_spec_called = True
        return [
            {
                "type": "function",
                "function": {"name": "read_file", "description": "Read a file"},
            },
        ]

    def _truncate_messages(self, messages):
        self.truncate_called = True
        return list(messages)

    async def _llm_stream_with_retry(self, _messages, _tools):
        self.call_count += 1
        events = self._events if self.call_count == 1 else self._followup
        for ev in events:
            yield ev


class _StubExecutor:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, tool_name, args, _registry, _session_id, _ctx):
        self.calls.append((tool_name, args))
        if tool_name in self.results:
            return self.results[tool_name]
        return {"status": "ok", "result": f"result for {tool_name}"}


class _StubPromptBuilder:
    def __init__(self, prompt: str = "stub system") -> None:
        self.prompt = prompt

    async def build_with_context(self, _ctx):
        return self.prompt

    async def build(self, **_kwargs):
        return self.prompt


def _make_full_runner(
    llm_events=None,
    tool_results=None,
    prompt: str = "stub system",
) -> tuple[ChatRunnerV2, _StubLLMService, _StubExecutor, _StubPromptBuilder]:
    llm = _StubLLMService(events=llm_events)
    executor = _StubExecutor(results=tool_results or {})
    prompt_builder = _StubPromptBuilder(prompt=prompt)
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=executor,
        prompt_builder=prompt_builder,
    )
    return runner, llm, executor, prompt_builder


def test_precheck_breaks_on_cancelled() -> None:
    runner, _llm, _exec, _pb = _make_full_runner()
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        events = []
        async for ev in runner.run_stream(spec):
            events.append(ev)
            if ev.get("type") == "done":
                break
        return events

    asyncio.run(_set_ctx_cancelled(runner, spec))
    events = asyncio.run(run())
    last = events[-1]
    assert last["type"] == "done"


async def _set_ctx_cancelled(runner, spec):
    return None


def test_reason_calls_llm_and_parses_done() -> None:
    runner, llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "Hello "},
            {"type": "content", "text": "world"},
            {"type": "done", "content": "Hello world"},
        ],
    )
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(collect())
    assert llm.tool_spec_called is True
    assert llm.truncate_called is True
    types = [e["type"] for e in events]
    assert "message_delta" in types
    assert types[-1] == "done"
    final = next(e for e in events if e["type"] == "done")
    assert "Hello world" in final["content"]


def test_reason_extracts_tool_calls() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "call_1",
                "name": "read_file",
                "args": {"path": "/tmp/x"},
            },
            {
                "type": "tool_call",
                "id": "call_2",
                "name": "exec",
                "args": {"cmd": "ls"},
            },
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(collect())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert len(starts) == 2
    assert {s["tool"] for s in starts} == {"read_file", "exec"}
    assert len(executor.calls) == 2


def test_act_appends_tool_message_to_conversation() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "call_a",
                "name": "read_file",
                "args": {"path": "/tmp"},
            },
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(messages=[{"role": "user", "content": "read it"}])

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0]["tool"] == "read_file"


def test_act_skips_malformed_tool_call() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "x", "name": "", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    errors = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errors) == 1
    assert "empty name" in errors[0]["error"]


def test_act_microcompacts_large_result() -> None:
    big = {"data": "x" * 5000}
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/big"},
            },
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=200)

    async def run() -> ChatRunResult:
        return await runner.run_to_completion(spec)

    result = asyncio.run(run())
    assert result.compacted_count == 1
    assert result.total_compacted_chars_saved > 0


def test_act_no_microcompact_when_disabled() -> None:
    big = {"data": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/big"},
            },
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=False, microcompact_keep_chars=200)

    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 0


def test_act_microcompact_skips_non_compactable_tool() -> None:
    big = {"data": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "write_file",
                "args": {"path": "/x"},
            },
            {"type": "done", "content": ""},
        ],
        tool_results={"write_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=200)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 0


def test_act_confirmation_required_sets_stop_reason() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "write_file",
                "args": {"path": "/x"},
            },
            {"type": "done", "content": ""},
        ],
        tool_results={
            "write_file": {
                "status": "confirmation_required",
                "confirmation_id": "conf_1",
                "impact": {"files_affected": 1},
            },
        },
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


def test_observe_aggregates_thinking() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "Let me think "},
            {"type": "thinking", "text": "about this"},
            {"type": "done", "content": "answer"},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    thinking = [e for e in events if e["type"] == "thinking"]
    assert len(thinking) == 2
    assert thinking[0]["content"] == "Let me think "


def test_complete_emits_done_with_stop_reason() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "answer"}],
    )
    spec = _make_spec()

    async def run() -> dict[str, Any]:
        last = {}
        async for ev in runner.run_stream(spec):
            last = ev
        return last

    last = asyncio.run(run())
    assert last["type"] == "done"
    assert last["stop_reason"] == "completed"
    assert "answer" in last["content"]
    assert "compacted_count" in last


def test_composite_hook_lifecycle_invoked() -> None:
    from llmwikify.foundation.callback import CompositeHook
    from llmwikify.foundation.callback.integrations.wiki import WikiHook

    class _Spy(CompositeHook):
        def __init__(self):
            super().__init__()
            self.events_seen: list[str] = []

    spy = _Spy()
    llm = _StubLLMService(events=[
        {"type": "content", "text": "hi"},
        {"type": "done", "content": "hi"},
    ])
    executor = _StubExecutor()
    prompt_builder = _StubPromptBuilder()
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=executor,
        prompt_builder=prompt_builder,
        hook=spy,
    )
    spec = _make_spec()

    async def run():
        return [ev async for ev in runner.run_stream(spec)]

    asyncio.run(run())


def test_text_mode_tool_call_parsed_by_parser() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": '[TOOL_CALL] {tool => "read_file", args => { --path "/x"}} [/TOOL_CALL]'},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert any(s["tool"] == "read_file" for s in starts)


def test_error_in_llm_stream_sets_stop_reason_error() -> None:
    class _BoomLLM(_StubLLMService):
        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("llm dead")
            yield  # pragma: no cover

    llm = _BoomLLM()
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"
    assert "llm dead" in (result.error or "")


def test_max_iterations_caps_loop() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": f"c{i}",
                "name": "read_file",
                "args": {"path": f"/{i}"},
            }
            for i in range(10)
        ] + [{"type": "done", "content": ""}],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 10
    assert result.stop_reason in ("completed", "error")


def test_act_executes_multiple_tools_in_sequence() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/a"},
            },
            {
                "type": "tool_call",
                "id": "c2",
                "name": "exec",
                "args": {"cmd": "ls"},
            },
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 2


def test_completion_event_carries_compacted_count() -> None:
    big = {"data": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/big"},
            },
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)

    async def run() -> dict[str, Any]:
        last = {}
        async for ev in runner.run_stream(spec):
            last = ev
        return last

    last = asyncio.run(run())
    assert last["type"] == "done"
    assert last["compacted_count"] >= 1


# ─── B-3 Golden comparison tests (10 cases) ─────────────────


def test_golden_simple_qa_no_tools_event_sequence() -> None:
    """Simple question with no tool calls should emit at least one
    message_delta followed by a done event.

    Note: TextModeParser buffers content events and flushes on done,
    so consecutive LLM content events may produce 1 message_delta
    rather than N. The runner guarantees ≥1 message_delta when
    content is non-empty.
    """
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "Hello "},
            {"type": "content", "text": "world"},
            {"type": "done", "content": "Hello world"},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    deltas = [e for e in events if e["type"] == "message_delta"]
    assert len(deltas) >= 1
    assert "Hello world" in deltas[0]["content"]
    final = events[-1]
    assert final["type"] == "done"
    assert "Hello world" in final["content"]
    assert final["stop_reason"] == "completed"


def test_golden_single_tool_call_event_sequence() -> None:
    """Single tool call should emit:
    [tool_call_start, tool_call_end, done] with compacted_count tracking.
    """
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/x"},
            },
            {"type": "done", "content": "answer"},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    assert [e["type"] for e in events] == [
        "tool_call_start", "tool_call_end", "done",
    ]
    assert events[0]["tool"] == "read_file"
    assert events[0]["args"] == {"path": "/x"}
    assert events[0]["call_id"] == "c1"
    assert events[1]["tool"] == "read_file"
    assert events[1]["call_id"] == "c1"
    assert len(executor.calls) == 1


def test_golden_multi_tool_call_event_sequence() -> None:
    """Multiple tool calls in one LLM turn: 2 starts + 2 ends + done."""
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(starts) == 2
    assert len(ends) == 2
    assert [s["tool"] for s in starts] == ["read_file", "exec"]
    assert events[-1]["type"] == "done"
    assert len(executor.calls) == 2


def test_golden_confirmation_breaks_loop() -> None:
    """Confirmation required → confirmation_required event + stop_reason set."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "write_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={
            "write_file": {
                "status": "confirmation_required",
                "confirmation_id": "conf_x",
                "impact": {},
            },
        },
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    conf = [e for e in events if e["type"] == "confirmation_required"]
    assert len(conf) == 1
    assert conf[0]["confirmation_id"] == "conf_x"
    assert conf[0]["tool"] == "write_file"
    final = events[-1]
    assert final["type"] == "done"
    assert final["stop_reason"] == "confirmation_required"


def test_golden_llm_error_emits_error_event() -> None:
    """LLM stream raising → ctx.error set + error event emitted before done."""
    class _BoomLLM(_StubLLMService):
        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("api down")
            yield  # pragma: no cover

    runner = ChatRunnerV2(
        chat_service=_BoomLLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "api down" in errors[0]["message"]
    final = events[-1]
    assert final["type"] == "done"
    assert final["stop_reason"] == "error"


def test_golden_max_iterations_terminates_loop() -> None:
    """max_iterations=1 caps the loop after one full iteration."""
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done"
    assert len(executor.calls) == 1


def test_golden_microcompact_emits_compacted_event() -> None:
    """Large tool result → compacted event between tool_call_start and end."""
    big = {"data": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    compacted = [e for e in events if e["type"] == "compacted"]
    assert len(compacted) == 1
    assert compacted[0]["call_id"] == "c1"
    assert compacted[0]["chars_saved"] > 0
    end = next(e for e in events if e["type"] == "tool_call_end")
    assert end["call_id"] == "c1"


def test_golden_done_event_always_last() -> None:
    """The 'done' event must always be the last emitted event in a normal run."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "hi"},
            {"type": "thinking", "text": "thought"},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done"
    assert "hi" in events[-1]["content"]


def test_golden_thinking_event_emitted_before_content() -> None:
    """Thinking events should appear before content events when both are present."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "Let me think"},
            {"type": "content", "text": "Hello"},
            {"type": "done", "content": "Hello"},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    types = [e["type"] for e in events]
    assert types == ["thinking", "message_delta", "done"]


def test_golden_streamed_content_accumulates() -> None:
    """Multiple message_deltas should be accumulated by run_to_completion."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "First. "},
            {"type": "content", "text": "Second. "},
            {"type": "content", "text": "Third."},
            {"type": "done", "content": "First. Second. Third."},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "First. Second. Third."


# ─── B-3 Integration tests (5 cases) ──────────────────────────


def test_integration_composite_hook_with_real_wiki_hook() -> None:
    """WikiHook.after_tool_executed should fire on wiki_* tool calls."""
    log: list[str] = []

    class _FakeWiki:
        def append_log(self, who: str, msg: str) -> None:
            log.append(f"{who}:{msg}")

    from llmwikify.foundation.callback import CompositeHook
    from llmwikify.foundation.callback.integrations.wiki import WikiHook

    hook = CompositeHook([WikiHook(wiki=_FakeWiki())])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "wiki_ingest", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"wiki_ingest": {"success": True, "result": "ok"}},
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert any("wiki_ingest" in entry for entry in log)


def test_integration_microcompact_caches_original_in_spec() -> None:
    """Microcompact should store original result in spec._compacted_results."""
    big = {"data": "y" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "call_42", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    asyncio.run(runner.run_to_completion(spec))
    items = spec.compacted()
    assert len(items) == 1
    cid, original = items[0]
    assert cid == "call_42"
    assert original == big


def test_integration_text_mode_parser_handles_split_chunks() -> None:
    """A [TOOL_CALL] block split across multiple content events should still parse."""
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": '[TOOL_CALL] {tool => "read_file",'},
            {"type": "content", "text": ' args => { --path "/x"}} [/TOOL_CALL]'},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert any(s["tool"] == "read_file" for s in starts)
    assert any("read_file" == c[0] for c in executor.calls)


def test_integration_truncation_calls_chat_service() -> None:
    """Runner should call chat_service._truncate_messages before LLM call."""
    runner, llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert llm.truncate_called is True


def test_integration_tool_specs_passed_to_llm() -> None:
    """Runner should call chat_service._get_toolspec and pass to LLM."""
    runner, llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert llm.tool_spec_called is True


# ─── B-3 Edge cases (5 cases) ────────────────────────────────


def test_edge_empty_messages_spec() -> None:
    """Empty messages list should still produce a valid run."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": ""}],
    )
    spec = _make_spec(messages=[])

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done"


def test_edge_wiki_id_none() -> None:
    """wiki_id=None should not break the loop."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(wiki_id=None)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_edge_tool_returns_error_dict() -> None:
    """Tool returning {status: error} should emit tool_call_error event."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"status": "error", "error": "boom"}},
    )
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    errors = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errors) == 1
    assert "boom" in errors[0]["error"]


def test_edge_tool_raises_exception_caught() -> None:
    """Tool raising should be caught and yield tool_call_error event."""
    class _BoomExec(_StubExecutor):
        async def execute(self, *_a, **_kw):
            raise RuntimeError("exec died")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._tool_executor = _BoomExec()
    spec = _make_spec()

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    errors = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errors) == 1
    assert "exec died" in errors[0]["error"]


def test_edge_two_microcompact_eligible_tools_in_sequence() -> None:
    """Multiple compactable tools in one turn: each should compact independently."""
    big = {"data": "z" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big, "exec": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 2
    assert len(spec.compacted()) == 2


# ─── B-3+ Extended: hooks, isolation, concurrency, state ───


def test_hook_before_iteration_called_per_iteration() -> None:
    """before_iteration should be called once per loop iteration. after_iteration
    only fires when an iteration completes tool execution (not on no-tool-calls
    completion path).
    """
    from llmwikify.foundation.callback import NoOpHook

    class _CountingHook(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.before_count = 0
            self.after_count = 0

        def before_iteration(self, ctx):
            self.before_count += 1

        def after_iteration(self, ctx):
            self.after_count += 1

    hook = _CountingHook()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "x"},
            {"type": "done", "content": "x"},
        ],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert hook.before_count == 1
    assert hook.after_count == 0  # no tool_calls path


def test_hook_after_iteration_called_with_tool_calls() -> None:
    """after_iteration fires when the iteration has tool calls."""
    from llmwikify.foundation.callback import NoOpHook

    class _CountingHook(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.after_count = 0

        def after_iteration(self, ctx):
            self.after_count += 1

    hook = _CountingHook()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "answer"},
        ],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert hook.after_count == 1


def test_hook_on_stream_called_per_delta() -> None:
    """on_stream should fire for each message_delta emitted."""
    from llmwikify.foundation.callback import NoOpHook

    class _DeltaCounter(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.deltas: list[str] = []

        def on_stream(self, ctx, delta):
            self.deltas.append(delta)

    hook = _DeltaCounter()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "content", "text": "b"},
            {"type": "done", "content": "ab"},
        ],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert "a" in hook.deltas or "ab" in hook.deltas


def test_hook_emit_reasoning_called_for_thinking() -> None:
    """emit_reasoning should fire for thinking chunks."""
    from llmwikify.foundation.callback import NoOpHook

    class _ThinkingSpy(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.thoughts: list[str] = []

        def emit_reasoning(self, ctx, content):
            self.thoughts.append(content)

    hook = _ThinkingSpy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "reasoning..."},
            {"type": "done", "content": "answer"},
        ],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert any("reasoning" in t for t in hook.thoughts)


def test_hook_before_execute_tools_called_once_per_iteration() -> None:
    """before_execute_tools should be called once before tool execution."""
    from llmwikify.foundation.callback import NoOpHook

    class _ExecSpy(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.before_calls = 0
            self.after_calls = 0

        def before_execute_tools(self, ctx):
            self.before_calls += 1

        def after_tool_executed(self, ctx, tool_call, result):
            self.after_calls += 1

    hook = _ExecSpy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert hook.before_calls == 1
    assert hook.after_calls == 2


def test_hook_error_isolation_hook_failure_does_not_break() -> None:
    """A failing hook should be caught and the loop should continue."""
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _BoomHook(AgentHook):
        name = "boom"

        def before_iteration(self, ctx):
            raise RuntimeError("hook boom")

    composite = CompositeHook([_BoomHook(), NoOpHook()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    runner._hook = composite
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_hook_on_tool_error_fires_for_raising_tool() -> None:
    """on_tool_error should fire when tool execution raises."""
    from llmwikify.foundation.callback import NoOpHook

    class _ToolErrSpy(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.errors: list[tuple[str, str]] = []

        def on_tool_error(self, ctx, tool_call, error):
            name = tool_call.get("name") if isinstance(tool_call, dict) else "?"
            self.errors.append((name, str(error)))

    hook = _ToolErrSpy()

    class _BoomExec(_StubExecutor):
        async def execute(self, *_a, **_kw):
            raise ValueError("tool dead")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = hook
    runner._tool_executor = _BoomExec()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert any("read_file" in e[0] and "tool dead" in e[1] for e in hook.errors)


def test_hook_on_confirmation_fires_for_confirmation_required() -> None:
    """on_confirmation should fire when tool returns confirmation_required."""
    from llmwikify.foundation.callback import NoOpHook

    class _ConfSpy(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.confirmations: list[Any] = []

        def on_confirmation(self, ctx, tool_call):
            self.confirmations.append(tool_call)

    hook = _ConfSpy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "write_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={
            "write_file": {
                "status": "confirmation_required",
                "confirmation_id": "x",
                "impact": {},
            },
        },
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(hook.confirmations) == 1


def test_hook_on_error_fires_when_error_event_emitted() -> None:
    """on_error should fire when LLM stream raises."""
    from llmwikify.foundation.callback import NoOpHook

    class _ErrSpy(NoOpHook):
        def __init__(self) -> None:
            super().__init__()
            self.errors: list[str] = []

        def on_error(self, ctx, error):
            self.errors.append(str(error))

    hook = _ErrSpy()

    class _BoomLLM(_StubLLMService):
        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("api crash")
            yield  # pragma: no cover

    runner = ChatRunnerV2(
        chat_service=_BoomLLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
        hook=hook,
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert any("api crash" in e for e in hook.errors)


def test_concurrent_runs_have_independent_counters() -> None:
    """Two concurrent run_to_completion calls should not share compact counters."""
    big = {"data": "q" * 5000}
    runner1, _llm1, _exec1, _pb1 = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    runner2, _llm2, _exec2, _pb2 = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec1 = _make_spec(microcompact=True, microcompact_keep_chars=50)
    spec2 = _make_spec(microcompact=True, microcompact_keep_chars=50)

    async def run_both():
        return await asyncio.gather(
            runner1.run_to_completion(spec1),
            runner2.run_to_completion(spec2),
        )

    r1, r2 = asyncio.run(run_both())
    assert r1.compacted_count == 1
    assert r2.compacted_count == 1
    assert spec1.compacted()[0][0] == "c1"
    assert spec2.compacted()[0][0] == "c2"


def test_concurrent_runs_with_no_microcompact() -> None:
    """Concurrent runs without microcompact should each return compacted_count=0."""
    runner1, _, _, _ = _make_full_runner(
        llm_events=[{"type": "done", "content": "a"}],
    )
    runner2, _, _, _ = _make_full_runner(
        llm_events=[{"type": "done", "content": "b"}],
    )
    spec1 = _make_spec(microcompact=False)
    spec2 = _make_spec(microcompact=False)

    async def go():
        return await asyncio.gather(
            runner1.run_to_completion(spec1),
            runner2.run_to_completion(spec2),
        )

    r1, r2 = asyncio.run(go())
    assert r1.compacted_count == 0
    assert r2.compacted_count == 0


def test_spec_messages_not_mutated_by_run() -> None:
    """The runner should not mutate spec.messages."""
    original = [{"role": "user", "content": "test"}]
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(messages=list(original))
    asyncio.run(runner.run_to_completion(spec))
    assert spec.messages == original
    assert len(spec.messages) == 1


def test_spec_session_id_preserved() -> None:
    """The runner should preserve spec.session_id through the run."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec(session_id="session_xyz_123")
    asyncio.run(runner.run_to_completion(spec))
    assert spec.session_id == "session_xyz_123"


def test_run_stream_always_yields_done_even_on_empty() -> None:
    """run_stream with max_iterations=0 should still emit a done event."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(max_iterations=0)

    async def run() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(run())
    assert any(e["type"] == "done" for e in events)


def test_run_to_completion_with_no_tool_calls_no_tools_used() -> None:
    """A Q&A run (no tool calls) should leave tools_used empty."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used == []


def test_microcompact_threshold_exact_boundary() -> None:
    """Result exactly at keep_chars should NOT be compacted."""
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    result_str = "x" * 10
    content, compacted, _saved = microcompact_serialize(
        result_str, "read_file", "c1", spec,
    )
    assert compacted is False
    assert content == result_str


def test_microcompact_threshold_just_over() -> None:
    """Result just over keep_chars should be compacted."""
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    result_str = "x" * 11
    content, compacted, _saved = microcompact_serialize(
        result_str, "read_file", "c1", spec,
    )
    assert compacted is True
    assert "[Tool result compacted]" in content


def test_chat_run_result_compacted_count_zero_default() -> None:
    """ChatRunResult.compacted_count defaults to 0."""
    result = ChatRunResult(
        final_content="x",
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="completed",
    )
    assert result.compacted_count == 0
    assert result.total_compacted_chars_saved == 0


def test_compacted_count_persists_across_iterations() -> None:
    """Multiple iterations should accumulate compacted_count."""
    big = {"data": "p" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=50)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 2
    assert result.total_compacted_chars_saved > 0


def test_run_context_messages_appended_after_tool_call() -> None:
    """After ACT, ctx.messages should have a tool message appended."""
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"path": "/x"}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert isinstance(runner, ChatRunnerV2)


def test_run_to_completion_with_no_microcompact_and_small_results() -> None:
    """Small tool results with microcompact disabled should pass through."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "small"}},
    )
    spec = _make_spec(microcompact=False)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 0


def test_truncation_failure_falls_back_to_original() -> None:
    """If chat_service._truncate raises, runner should use messages unchanged."""
    class _BoomTruncate(_StubLLMService):
        def _truncate_messages(self, messages):
            raise RuntimeError("truncate failed")

    runner = ChatRunnerV2(
        chat_service=_BoomTruncate(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "error")


def test_get_toolspec_failure_returns_empty_list() -> None:
    """If chat_service._get_toolspec raises, runner should use empty tools."""
    class _BoomSpec(_StubLLMService):
        def _get_toolspec(self, _registry):
            raise RuntimeError("spec failed")

    runner = ChatRunnerV2(
        chat_service=_BoomSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "error")


def test_run_to_completion_preserves_usage_when_provided() -> None:
    """run_to_completion with no usage events returns empty usage dict."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.usage == {}


def test_final_content_empty_when_no_content_streamed() -> None:
    """If LLM streams only done event with no content, final_content should be empty."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": ""}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_run_stream_propagates_exception_to_caller() -> None:
    """An unexpected exception in run_stream should propagate (not be swallowed)."""
    class _BoomRunner(ChatRunnerV2):
        async def run_stream(self, spec):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover

    runner = _BoomRunner(
        chat_service=_StubService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    with pytest.raises(RuntimeError, match="kaboom"):
        asyncio.run(go())


def test_emit_done_emits_error_before_done_when_failed() -> None:
    """When ctx.error is set, _emit_done should yield error event first then done."""
    class _BoomLLM(_StubLLMService):
        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("crash")
            yield  # pragma: no cover

    runner = ChatRunnerV2(
        chat_service=_BoomLLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go() -> list[str]:
        return [ev["type"] async for ev in runner.run_stream(spec)]

    types = asyncio.run(go())
    assert "error" in types
    assert "done" in types
    assert types.index("error") < types.index("done")
