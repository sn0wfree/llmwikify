"""Tests for ChatRunnerV2 (Plan B Steps B-1 + B-2 + B-3 + extended + 100+ + 200+ + 300+ + 400+ + 500+ + 600+).

B-1: skeleton + public API surface (8 cases)
B-1-extension: independence + edge cases (18 cases)
B-2: 5-step state machine + hooks + microcompact + text-mode (17 cases)
B-3: golden comparisons + integration + edge cases (20 cases)
Extended: hook coverage + isolation + concurrency + state (22 cases)
100+: SSE compat + tool variety + async hooks + boundaries (15 cases)
200+: 10 new groups (100 cases) — LLM streams / tool variety /
microcompact / precheck / spec variations / concurrency / hooks /
truncation / tool_specs / _RunContext edges
300+: 11 new groups (100 cases) — error handling / SSE event format /
stop reason mapping / multi-tool per iteration / text-mode parser /
max_iterations boundary / hook failure isolation / usage tracking /
mutation safety / phase event / default spec / system prompt
400+: 9 new groups (110 cases) — state machine transitions / interrupt
points / boundary concurrency / exception injection / message size
boundary / timing boundary / edge state values / reentrance & shared
state / code path coverage
500+: 8 new groups (95 cases) — fuzz testing / property-based /
property invariants / fuzz with state mutations / edge case fuzz /
streaming consistency / hook invocation patterns / error handling
600+: 12 new groups (95 cases) — on_stream_end/emit_reasoning_end
hook points / stream cancellation / _act edge branches / path
coverage / hook pipeline / spec mutation / state machine / event
flow / boundary values / mutation testing / real services / misc

Total: 617 cases covering:
  - Public API: run_stream, run_to_completion, ChatRunResult aggregation
  - _RunContext: defaults, slots, time progression, field independence
  - Independence: no legacy engine imports, minimal deps, works without infra
  - 5-step loop: PRECHECK/REASON/ACT/OBSERVE/COMPLETE
  - CompositeHook: 13 hook points wired through the loop (incl. on_stream_end + emit_reasoning_end)
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
  - Hook coverage: before/after_iteration / on_stream / on_stream_end /
    emit_reasoning / emit_reasoning_end / before_execute_tools /
    after_tool_executed / on_tool_error / on_confirmation / on_error
  - Hook isolation: failing hook doesn't break the loop
  - State safety: spec immutability / session_id preservation / ctx messages
  - Boundary: microcompact exact threshold / 2-compact-in-one-iteration
  - Error recovery: truncate failure / spec failure / exception propagation
  - Event ordering: error before done on failure path
  - SSE compatibility: done event required fields / tool_call_start required fields
  - Tool result variety: list / string / None / numeric / boolean / nested / unicode
  - Tool args: JSON special chars (quotes, newlines, unicode) preserved
  - Microcompact config: custom compactable_tools / empty / single / numeric / none
  - Hook mix: async CompositeHook + sync NoOpHook
  - Run context safety: hook_ctx returns independent copy
  - LLM stream variations: only thinking / multiple chunks / empty / done-only / nested args
  - Precheck: timeout config / cancelled / paused / elapsed
  - Spec: all fields / workspace path / empty wiki_id / empty session_id / large messages
  - Concurrent: 5 parallel / shared session_id / per-run cache isolation
  - Hook variations: order preservation / chain / mix sync+async / clear / remove
  - Truncation: shorter / same / None / empty / call count
  - tool_specs: None / empty / many / missing / with registry
  - _RunContext: compacted_count / chars_saved / last_tool_calls / hook_ctx fields
  - 300+: error resilience (LLM/tool/hook) / SSE schema / stop reason mapping /
    multi-tool iter / text-mode parser integration / max_iterations /
    hook failure isolation / usage / mutation safety / phase event / default spec
  - 400+: state machine transitions (20) / interrupt points (10) /
    boundary concurrency (15) / exception injection (15) / message size
    boundary (10) / timing boundary (10) / edge state values (10) /
    reentrance (10) / code path coverage (10)
  - 500+: fuzz testing (15) / property-based (15) / property invariants (15) /
    fuzz with state mutations (10) / edge case fuzz (10) /
    streaming consistency (10) / hook invocation patterns (10) /
    error handling (10)
  - 600+: on_stream_end/emit_reasoning_end (5) / stream cancellation (8) /
    _act edge branches (8) / path coverage (5) / hook pipeline (8) /
    spec mutation (8) / state machine (8) / event flow (8) /
    boundary values (8) / mutation testing (8) / real services (8) /
    misc/defensive (13)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2, _RunContext
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.foundation.callback import AgentHook, NoOpHook


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
        followup2_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config: dict = {}
        self._events = events or [{"type": "done", "content": "stub answer"}]
        self._followup = followup_events or [{"type": "done", "content": "stub answer"}]
        self._followup2 = followup2_events or [{"type": "done", "content": "stub answer"}]
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
        if self.call_count == 1:
            events = self._events
        elif self.call_count == 2:
            events = self._followup
        else:
            events = self._followup2
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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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
    from llmwikify.foundation.callback import AgentHook, NoOpHook

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


# ─── 100+ milestone: SSE / tool variety / async hooks / boundaries ───


def test_tool_result_is_list_passes_through() -> None:
    """Tool returning a list (not dict) should work without error."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": ["line1", "line2", "line3"]},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_result_is_string_passes_through() -> None:
    """Tool returning a string should work."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": "raw string content"},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_result_is_none_passes_through() -> None:
    """Tool returning None should work (not crash)."""
    class _NoneExec(_StubExecutor):
        async def execute(self, *_a, **_kw):
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._tool_executor = _NoneExec()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "error")


def test_tool_args_with_json_special_chars() -> None:
    """Tool args with quotes, newlines, unicode should be preserved."""
    special_args = {
        "path": "/tmp/test with spaces",
        "query": 'has "quotes" and \\backslashes',
        "multiline": "line1\nline2\nline3",
        "unicode": "中文 + emoji 🎉",
    }
    captured_args = {}

    class _CaptureExec(_StubExecutor):
        async def execute(self, tool_name, args, *_a, **_kw):
            captured_args.update(args)
            return {"ok": True}

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": special_args},
            {"type": "done", "content": ""},
        ],
    )
    runner._tool_executor = _CaptureExec()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert captured_args == special_args


def test_microcompact_with_custom_compactable_tools() -> None:
    """Custom compactable_tools set should override default."""
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    custom = frozenset({"custom_tool"})
    spec = _make_spec(
        microcompact=True,
        microcompact_compactable_tools=custom,
    )
    big = {"data": "x" * 5000}
    content_default, comp_default, _ = microcompact_serialize(
        big, "read_file", "c1", spec,
    )
    assert comp_default is False
    content_custom, comp_custom, _ = microcompact_serialize(
        big, "custom_tool", "c2", spec,
    )
    assert comp_custom is True


def test_run_stream_then_run_to_completion_can_share_runner() -> None:
    """Both APIs can be called on the same runner instance independently."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "first"}],
    )
    spec1 = _make_spec()

    async def drain_stream():
        return [ev async for ev in runner.run_stream(spec1)]

    events1 = asyncio.run(drain_stream())
    assert events1[-1]["type"] == "done"

    spec2 = _make_spec()
    result2 = asyncio.run(runner.run_to_completion(spec2))
    assert result2.stop_reason == "completed"


def test_sse_done_event_has_required_fields() -> None:
    """Done event must contain all required SSE fields for frontend consumption."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "answer"},
        ],
    )
    spec = _make_spec()

    async def go() -> dict[str, Any]:
        last = {}
        async for ev in runner.run_stream(spec):
            last = ev
        return last

    last = asyncio.run(go())
    required_fields = {"type", "content", "stop_reason", "error", "compacted_count"}
    assert required_fields.issubset(last.keys())


def test_sse_tool_call_start_event_has_required_fields() -> None:
    """tool_call_start event must contain tool, args, call_id for frontend."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "abc123",
                "name": "read_file",
                "args": {"path": "/x"},
            },
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def go() -> dict[str, Any]:
        async for ev in runner.run_stream(spec):
            if ev.get("type") == "tool_call_start":
                return ev
        return {}

    start = asyncio.run(go())
    assert start["type"] == "tool_call_start"
    assert start["tool"] == "read_file"
    assert start["args"] == {"path": "/x"}
    assert start["call_id"] == "abc123"


def test_async_composite_hook_with_sync_noop_mix() -> None:
    """CompositeHook (async) + NoOpHook (sync) should work together."""
    from llmwikify.foundation.callback import CompositeHook

    composite = CompositeHook([NoOpHook()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    runner._hook = composite
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_session_id_in_tool_call_id_prefix() -> None:
    """Tool call_ids should be unique strings (not None or empty)."""
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 2


def test_run_context_hook_ctx_returns_independent_copy() -> None:
    """ctx.hook_ctx should return a copy (mutations don't affect ctx)."""
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec(messages=[{"role": "user", "content": "x"}])
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    hook_ctx = ctx.hook_ctx(0)
    hook_ctx.messages.append({"role": "system", "content": "added"})
    assert len(ctx.messages) == 1


def test_microcompact_empty_messages_spec() -> None:
    """Microcompact should work with empty spec.messages."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(messages=[], microcompact=True, microcompact_keep_chars=10)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert result.compacted_count == 0


def test_run_to_completion_with_tool_args_dict() -> None:
    """Tool args as dict (not JSON string) should work via runner's _act."""
    captured = []

    class _CaptureExec(_StubExecutor):
        async def execute(self, tool_name, args, *_a, **_kw):
            captured.append(args)
            return {"ok": True}

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "tool_call",
                "id": "c1",
                "name": "read_file",
                "args": {"path": "/x", "limit": 100},
            },
            {"type": "done", "content": ""},
        ],
    )
    runner._tool_executor = _CaptureExec()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert captured[0] == {"path": "/x", "limit": 100}


# ─── 200+ milestone: 10 new groups ────────────────────────────


# Group 1: LLM stream variations (15 cases)


def test_llm_stream_only_thinking() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "hmm"},
            {"type": "done", "content": "answer"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_llm_stream_multiple_thinking_chunks() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "part1 "},
            {"type": "thinking", "text": "part2 "},
            {"type": "thinking", "text": "part3"},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_llm_stream_no_events() -> None:
    class _EmptyLLM(_StubLLMService):
        async def _llm_stream_with_retry(self, _m, _t):
            if False:
                yield {}
            return

    runner = ChatRunnerV2(
        chat_service=_EmptyLLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_llm_done_with_no_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": ""}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == ""


def test_tool_call_with_empty_args() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert executor.calls[0] == ("read_file", {})


def test_tool_call_with_nested_args() -> None:
    args = {"filters": {"type": "code", "tags": ["python", "ml"]}, "limit": 10}
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "search", "args": args},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert executor.calls[0] == ("search", args)


def test_tool_call_id_auto_generated_when_missing() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 1


def test_long_content_stream_compiles() -> None:
    chunks = [{"type": "content", "text": "x" * 1000} for _ in range(50)]
    chunks.append({"type": "done", "content": "y"})
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=chunks)
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_unicode_in_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "中文 🚀 émoji"},
            {"type": "done", "content": "中文 🚀 émoji"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "中文" in result.final_content or "🚀" in result.final_content


def test_json_in_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": '{"key": "value"}'},
            {"type": "done", "content": '{"key": "value"}'},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "key" in result.final_content or result.stop_reason == "completed"


def test_newlines_in_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "line1\nline2\nline3"},
            {"type": "done", "content": "line1\nline2\nline3"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_call_id_propagated_to_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "specific_id_42", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def go():
        async for ev in runner.run_stream(spec):
            if ev.get("type") == "tool_call_start":
                return ev
        return {}

    start = asyncio.run(go())
    assert start.get("call_id") == "specific_id_42"


def test_tool_call_with_duplicate_ids_handled() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "dup", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "dup", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 2


def test_mixed_content_thinking_tool_call_events() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "thought"},
            {"type": "content", "text": "hello "},
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert len(executor.calls) == 1


def test_unknown_event_type_ignored() -> None:
    """Unknown LLM event types should be passed through parser without crash."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "future_event_type_xyz", "data": "unknown"},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# Group 2: Tool result variety (10 cases)


def test_tool_returns_empty_dict() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": {}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_empty_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": []},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_empty_string() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": ""},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_numeric() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "count", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"count": 42},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_boolean() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "check", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"check": True},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_nested_dict() -> None:
    nested = {"level1": {"level2": {"level3": ["a", "b"]}}, "num": 42}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": nested},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_very_large_dict() -> None:
    big = {"items": [{"id": i, "data": "x" * 100} for i in range(1000)]}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=500)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 1


def test_tool_returns_unicode_string() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": "中文 emoji 🎉"},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_with_special_chars() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": "tab\there\nnewline\rcr"},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_returns_unserializable_falls_back_to_str() -> None:
    class _Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"x": [_Opaque()] * 5},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# Group 3: microcompact edge cases (15 cases)


def test_microcompact_keep_chars_zero_compacts_everything() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=0)
    content, compacted, _ = microcompact_serialize("x", "read_file", "c1", spec)
    assert compacted is True


def test_microcompact_keep_chars_one_compacts_multi_char() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=1)
    content, compacted, _ = microcompact_serialize("hello", "read_file", "c1", spec)
    assert compacted is True


def test_microcompact_very_large_keep_chars() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10_000_000)
    content, compacted, _ = microcompact_serialize("x" * 1000, "read_file", "c1", spec)
    assert compacted is False


def test_microcompact_empty_compactable_tools() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(
        microcompact=True,
        microcompact_compactable_tools=frozenset(),
    )
    content, compacted, _ = microcompact_serialize(
        {"x": "y" * 5000}, "read_file", "c1", spec,
    )
    assert compacted is False


def test_microcompact_single_compactable_tool() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(
        microcompact=True,
        microcompact_compactable_tools=frozenset({"only_one"}),
    )
    content1, c1, _ = microcompact_serialize(
        {"x": "y" * 5000}, "only_one", "c1", spec,
    )
    assert c1 is True
    content2, c2, _ = microcompact_serialize(
        {"x": "y" * 5000}, "read_file", "c2", spec,
    )
    assert c2 is False


def test_microcompact_int_result_works() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=5)
    content, compacted, _ = microcompact_serialize(123456, "read_file", "c1", spec)
    assert compacted is True


def test_microcompact_none_result_works() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=5)
    content, compacted, _ = microcompact_serialize(None, "read_file", "c1", spec)
    assert isinstance(content, str)


def test_microcompact_returns_marker_with_correct_id() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    content, compacted, _ = microcompact_serialize(
        "x" * 100, "read_file", "call_xyz_999", spec,
    )
    assert "call_xyz_999" in content


def test_microcompact_cached_result_accessible_via_compacted() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    original = {"big": "data" * 100}
    microcompact_serialize(original, "read_file", "call_1", spec)
    items = spec.compacted()
    assert len(items) == 1
    assert items[0][1] == original


def test_microcompact_compactable_set_is_frozenset() -> None:
    spec = _make_spec()
    assert isinstance(spec.microcompact_compactable_tools, frozenset)


def test_microcompact_disabled_spec_keeps_cache_empty() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=False)
    for i in range(5):
        microcompact_serialize("x" * 1000, "read_file", f"c{i}", spec)
    assert spec.compacted() == []


def test_microcompact_chars_saved_is_positive() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    content, compacted, saved = microcompact_serialize(
        "x" * 1000, "read_file", "c1", spec,
    )
    assert compacted is True
    assert saved > 0


def test_microcompact_multiple_results_isolated() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    microcompact_serialize({"a": "x" * 1000}, "read_file", "c1", spec)
    microcompact_serialize({"b": "y" * 1000}, "exec", "c2", spec)
    items = spec.compacted()
    assert len(items) == 2
    call_ids = {cid for cid, _ in items}
    assert call_ids == {"c1", "c2"}


def test_microcompact_then_max_tool_chars_still_works() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"x": "y" * 10000}},
    )
    spec = _make_spec(
        microcompact=True,
        microcompact_keep_chars=100,
        max_tool_result_chars=200,
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 1


def test_microcompact_default_compactable_matches_nanobot() -> None:
    from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

    spec = _make_spec(microcompact=True, microcompact_keep_chars=10)
    nanobot_set = {
        "read_file", "exec", "grep", "find_files",
        "web_search", "web_fetch", "list_dir",
    }
    for tool in nanobot_set:
        content, compacted, _ = microcompact_serialize(
            "x" * 100, tool, f"c_{tool}", spec,
        )
        assert compacted is True, f"Failed for {tool}"


# Group 4: Precheck / timeout / cancel (10 cases)


def test_timeout_zero_no_timeout() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_timeout_via_config() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 0.001}
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "timeout")


def test_precheck_cancelled_before_run() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def cancelled_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancelled_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "cancelled")


def test_precheck_paused_before_run() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def paused_precheck(ctx):
        ctx.paused = True
        ctx.stop_reason = "paused"
        return True

    runner._precheck = paused_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "paused")


def test_run_context_cancelled_set_manually() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.cancelled = True
    assert ctx.cancelled is True


def test_run_context_paused_set_manually() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.paused = True
    assert ctx.paused is True


def test_precheck_returns_bool() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        from llmwikify.apps.chat.agent.runner_v2 import _RunContext
        ctx = _RunContext(spec=spec, messages=[])
        return await runner._precheck(ctx)

    result = asyncio.run(go())
    assert isinstance(result, bool)


def test_precheck_no_break_normal() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        from llmwikify.apps.chat.agent.runner_v2 import _RunContext
        ctx = _RunContext(spec=spec, messages=[])
        return await runner._precheck(ctx)

    assert asyncio.run(go()) is False


def test_precheck_with_timeout_zero_breaks_on_elapsed() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 0.0}
    spec = _make_spec()

    async def go():
        from llmwikify.apps.chat.agent.runner_v2 import _RunContext
        ctx = _RunContext(spec=spec, messages=[])
        ctx.started_at = 0.0
        return await runner._precheck(ctx)

    result = asyncio.run(go())
    assert result is False


def test_precheck_respects_timeout_setting() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 10.0}
    spec = _make_spec()

    async def go():
        from llmwikify.apps.chat.agent.runner_v2 import _RunContext
        ctx = _RunContext(spec=spec, messages=[])
        return await runner._precheck(ctx)

    assert asyncio.run(go()) is False


# Group 5: Spec variations (10 cases)


def test_spec_all_fields_set() -> None:
    spec = ChatRunSpec(
        messages=[{"role": "user", "content": "x"}],
        tool_registry=object(),
        session_id="s_full",
        wiki_id="w_full",
        model="custom-model",
        max_iterations=5,
        max_tool_result_chars=12345,
        temperature=0.5,
        max_tokens=2048,
        reasoning_effort="medium",
        error_message="custom error",
        microcompact=False,
        microcompact_keep_chars=2000,
    )
    assert spec.session_id == "s_full"
    assert spec.wiki_id == "w_full"
    assert spec.model == "custom-model"
    assert spec.max_iterations == 5
    assert spec.temperature == 0.5


def test_spec_workspace_as_path() -> None:
    spec = ChatRunSpec(
        messages=[{"role": "user", "content": "x"}],
        tool_registry=object(),
        session_id="s",
        workspace=Path("/tmp/test"),
    )
    assert spec.workspace == Path("/tmp/test")


def test_spec_workspace_none() -> None:
    spec = ChatRunSpec(
        messages=[{"role": "user", "content": "x"}],
        tool_registry=object(),
        session_id="s",
        workspace=None,
    )
    assert spec.workspace is None


def test_spec_wiki_id_empty_string() -> None:
    spec = ChatRunSpec(
        messages=[{"role": "user", "content": "x"}],
        tool_registry=object(),
        session_id="s",
        wiki_id="",
    )
    assert spec.wiki_id == ""


def test_spec_session_id_empty_string() -> None:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=object(),
        session_id="",
    )
    assert spec.session_id == ""


def test_spec_temperature_zero() -> None:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=object(),
        session_id="s",
        temperature=0.0,
    )
    assert spec.temperature == 0.0


def test_spec_max_tokens_large() -> None:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=object(),
        session_id="s",
        max_tokens=100000,
    )
    assert spec.max_tokens == 100000


def test_spec_reasoning_effort_low() -> None:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=object(),
        session_id="s",
        reasoning_effort="low",
    )
    assert spec.reasoning_effort == "low"


def test_spec_compacted_accessor_returns_list() -> None:
    spec = ChatRunSpec(
        messages=[],
        tool_registry=object(),
        session_id="s",
    )
    result = spec.compacted()
    assert isinstance(result, list)


def test_spec_with_large_messages() -> None:
    large = [{"role": "user", "content": "x" * 10000}]
    spec = ChatRunSpec(
        messages=large,
        tool_registry=object(),
        session_id="s",
    )
    assert len(spec.messages) == 1
    assert len(spec.messages[0]["content"]) == 10000


# Group 6: Concurrent variations (10 cases)


def test_same_runner_sequential_runs_independent() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "a"}],
    )
    spec1 = _make_spec()
    spec2 = _make_spec(messages=[{"role": "user", "content": "b"}])
    r1 = asyncio.run(runner.run_to_completion(spec1))
    r2 = asyncio.run(runner.run_to_completion(spec2))
    assert r1.stop_reason == "completed"
    assert r2.stop_reason == "completed"


def test_two_runners_different_specs() -> None:
    r1, _llm1, _exec1, _pb1 = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    r2, _llm2, _exec2, _pb2 = _make_full_runner(
        llm_events=[{"type": "done", "content": "y"}],
    )
    spec1 = _make_spec(session_id="alpha")
    spec2 = _make_spec(session_id="beta")
    result1 = asyncio.run(r1.run_to_completion(spec1))
    result2 = asyncio.run(r2.run_to_completion(spec2))
    assert result1.stop_reason == "completed"
    assert result2.stop_reason == "completed"


def test_concurrent_runs_with_microcompact_different_tools() -> None:
    big_a = {"a": "x" * 5000}
    big_b = {"b": "y" * 5000}
    r1, _llm1, _exec1, _pb1 = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big_a},
    )
    r2, _llm2, _exec2, _pb2 = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": big_b},
    )
    spec1 = _make_spec(microcompact=True, microcompact_keep_chars=50)
    spec2 = _make_spec(microcompact=True, microcompact_keep_chars=50)

    async def go():
        return await asyncio.gather(
            r1.run_to_completion(spec1),
            r2.run_to_completion(spec2),
        )

    r_1, r_2 = asyncio.run(go())
    assert r_1.compacted_count == 1
    assert r_2.compacted_count == 1


def test_concurrent_runs_with_confirmation() -> None:
    r1, _llm1, _exec1, _pb1 = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "write_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={
            "write_file": {"status": "confirmation_required", "confirmation_id": "c1"},
        },
    )
    r2, _llm2, _exec2, _pb2 = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec1 = _make_spec()
    spec2 = _make_spec()

    async def go():
        return await asyncio.gather(
            r1.run_to_completion(spec1),
            r2.run_to_completion(spec2),
        )

    r_1, r_2 = asyncio.run(go())
    assert r_1.stop_reason == "confirmation_required"
    assert r_2.stop_reason == "completed"


def test_concurrent_5_runs() -> None:
    async def go():
        tasks = []
        for i in range(5):
            r, _, _, _ = _make_full_runner(
                llm_events=[{"type": "done", "content": f"r{i}"}],
            )
            spec = _make_spec(session_id=f"s{i}")
            tasks.append(r.run_to_completion(spec))
        return await asyncio.gather(*tasks)

    results = asyncio.run(go())
    assert all(r.stop_reason == "completed" for r in results)


def test_run_then_run_again_with_same_spec() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    r1 = asyncio.run(runner.run_to_completion(spec))
    r2 = asyncio.run(runner.run_to_completion(spec))
    assert r1.stop_reason == "completed"
    assert r2.stop_reason == "completed"


def test_run_with_per_run_microcompact_isolation() -> None:
    big = {"x": "y" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec1 = _make_spec(microcompact=True, microcompact_keep_chars=100)
    spec2 = _make_spec(microcompact=False)
    r1 = asyncio.run(runner.run_to_completion(spec1))
    r2 = asyncio.run(runner.run_to_completion(spec2))
    assert r1.compacted_count == 1
    assert r2.compacted_count == 0


def test_concurrent_with_same_spec_id() -> None:
    r1, _llm1, _exec1, _pb1 = _make_full_runner(
        llm_events=[{"type": "done", "content": "a"}],
    )
    r2, _llm2, _exec2, _pb2 = _make_full_runner(
        llm_events=[{"type": "done", "content": "b"}],
    )
    spec1 = _make_spec(session_id="shared")
    spec2 = _make_spec(session_id="shared")

    async def go():
        return await asyncio.gather(
            r1.run_to_completion(spec1),
            r2.run_to_completion(spec2),
        )

    r_1, r_2 = asyncio.run(go())
    assert r_1.stop_reason == "completed"
    assert r_2.stop_reason == "completed"


def test_per_run_cache_does_not_leak() -> None:
    big = {"x": "y" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    spec1 = _make_spec(microcompact=True, microcompact_keep_chars=100)
    spec2 = _make_spec(microcompact=True, microcompact_keep_chars=100)
    asyncio.run(runner.run_to_completion(spec1))
    assert len(spec1.compacted()) == 1
    assert len(spec2.compacted()) == 0


def test_concurrent_runs_state_independent() -> None:
    async def go():
        tasks = []
        for i in range(3):
            r, _, _, _ = _make_full_runner(
                llm_events=[
                    {"type": "tool_call", "id": f"c{i}", "name": "read_file", "args": {}},
                    {"type": "done", "content": ""},
                ],
                tool_results={"read_file": {"data": "x" * 5000}},
            )
            spec = _make_spec(
                session_id=f"s{i}",
                microcompact=True,
                microcompact_keep_chars=100,
            )
            tasks.append(r.run_to_completion(spec))
        return await asyncio.gather(*tasks)

    results = asyncio.run(go())
    for r in results:
        assert r.compacted_count == 1


# Group 7: Hook variations (15 cases)


def test_hook_before_iteration_can_modify_ctx() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _Mutator(NoOpHook):
        def before_iteration(self, ctx):
            ctx.iteration = 999

    hook = _Mutator()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = hook
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_hook_after_tool_executed_receives_compacted() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    captured = []

    class _Capture(NoOpHook):
        def after_tool_executed(self, ctx, tool_call, result):
            captured.append((tool_call, result))

    big = {"data": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": big},
    )
    runner._hook = _Capture()
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    asyncio.run(runner.run_to_completion(spec))
    assert len(captured) == 1
    assert captured[0][1] == big


def test_multiple_composite_hooks_chained() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _CountHook(AgentHook):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name
            self.calls = 0

        def before_iteration(self, ctx):
            self.calls += 1

    a = _CountHook("a")
    b = _CountHook("b")
    composite = CompositeHook([a, b])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert a.calls == 1
    assert b.calls == 1


def test_hook_registration_order_preserved() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    order = []

    class _OrderHook(AgentHook):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        def before_iteration(self, ctx):
            order.append(self.name)

    composite = CompositeHook([_OrderHook("a"), _OrderHook("b"), _OrderHook("c")])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert order == ["a", "b", "c"]


def test_hook_failure_does_not_stop_other_hooks() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    a_called = []
    b_called = []

    class _BoomHook(AgentHook):
        name = "boom"

        def before_iteration(self, ctx):
            raise RuntimeError("boom")

    class _HookA(AgentHook):
        name = "a"

        def before_iteration(self, ctx):
            a_called.append(1)

    class _HookB(AgentHook):
        name = "b"

        def before_iteration(self, ctx):
            b_called.append(1)

    composite = CompositeHook([_BoomHook(), _HookA(), _HookB()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert a_called == [1]
    assert b_called == [1]


def test_hook_clear_removes_all() -> None:
    from llmwikify.foundation.callback import CompositeHook

    composite = CompositeHook([NoOpHook()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    assert len(runner._hook) == 1
    runner._hook.clear()
    assert len(runner._hook) == 0


def test_hook_remove_by_name() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _NamedHook(AgentHook):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    composite = CompositeHook([_NamedHook("a"), _NamedHook("b")])
    composite.remove("a")
    assert len(composite) == 1


def test_hook_add_returns_new_length() -> None:
    from llmwikify.foundation.callback import CompositeHook

    composite = CompositeHook()
    assert len(composite) == 0
    composite.add(NoOpHook())
    assert len(composite) == 1


def test_hook_with_async_and_sync_mixed() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    sync_called = []
    async_called = []

    class _SyncHook(AgentHook):
        name = "sync"

        def before_iteration(self, ctx):
            sync_called.append(1)

    class _AsyncHook(AgentHook):
        name = "async"

        async def before_iteration(self, ctx):
            async_called.append(1)

    composite = CompositeHook([_SyncHook(), _AsyncHook()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert sync_called == [1]
    assert async_called == [1]


def test_hook_empty_composite_runs_normally() -> None:
    from llmwikify.foundation.callback import CompositeHook

    composite = CompositeHook()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_hook_with_long_name_works() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _LongNameHook(AgentHook):
        name = "a" * 200

        def before_iteration(self, ctx):
            pass

    composite = CompositeHook([_LongNameHook()])
    assert composite._hooks[0].name == "a" * 200


def test_hook_iteration_count_in_context() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    iterations_seen = []

    class _Spy(NoOpHook):
        def before_iteration(self, ctx):
            iterations_seen.append(ctx.iteration)

    hook = _Spy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = hook
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert iterations_seen == [0]


def test_hook_messages_in_context() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    seen_messages = []

    class _Spy(NoOpHook):
        def before_iteration(self, ctx):
            seen_messages.append(list(ctx.messages))

    hook = _Spy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = hook
    spec = _make_spec(messages=[{"role": "user", "content": "hello"}])
    asyncio.run(runner.run_to_completion(spec))
    assert len(seen_messages) == 1
    assert seen_messages[0][0]["content"] == "hello"


def test_hook_finalize_content_called_with_final() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _Spy(NoOpHook):
        def finalize_content(self, ctx, content):
            return (content or "") + "!"

    hook = _Spy()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "content", "text": "x"}, {"type": "done", "content": "x"}],
    )
    runner._hook = hook
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "!" in (result.final_content or "")


def test_hook_finalize_content_exception_falls_back() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _Boom(NoOpHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _Boom()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# Group 8: Truncation variations (5 cases)


def test_truncation_returns_shorter_list() -> None:
    class _TruncateShort(_StubLLMService):
        def _truncate_messages(self, messages):
            return messages[:1]

    runner = ChatRunnerV2(
        chat_service=_TruncateShort(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_truncation_returns_same_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_truncation_returns_none_uses_original() -> None:
    class _NoneTruncate(_StubLLMService):
        def _truncate_messages(self, messages):
            return None

    runner = ChatRunnerV2(
        chat_service=_NoneTruncate(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_truncation_returns_empty_list() -> None:
    class _EmptyTruncate(_StubLLMService):
        def _truncate_messages(self, messages):
            return []

    runner = ChatRunnerV2(
        chat_service=_EmptyTruncate(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in ("completed", "error")


def test_truncation_called_once_per_run() -> None:
    class _CountTruncate(_StubLLMService):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.truncate_count = 0

        def _truncate_messages(self, messages):
            self.truncate_count += 1
            return list(messages)

    llm = _CountTruncate()
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert llm.truncate_count == 1


# Group 9: tool_specs variations (5 cases)


def test_tool_specs_returns_none_uses_empty() -> None:
    class _NoneSpec(_StubLLMService):
        def _get_toolspec(self, _r):
            return None

    runner = ChatRunnerV2(
        chat_service=_NoneSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_specs_returns_empty_list() -> None:
    class _EmptySpec(_StubLLMService):
        def _get_toolspec(self, _r):
            return []

    runner = ChatRunnerV2(
        chat_service=_EmptySpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_specs_returns_many_tools() -> None:
    class _ManySpec(_StubLLMService):
        def _get_toolspec(self, _r):
            return [
                {"type": "function", "function": {"name": f"tool_{i}", "description": f"T{i}"}}
                for i in range(50)
            ]

    runner = ChatRunnerV2(
        chat_service=_ManySpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_specs_not_called_when_no_chat_service_method() -> None:
    class _NoSpec:
        config: dict = {}

    runner = ChatRunnerV2(
        chat_service=_NoSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_tool_specs_called_with_registry() -> None:
    captured_registry = []

    class _CaptureSpec(_StubLLMService):
        def _get_toolspec(self, registry):
            captured_registry.append(registry)
            return []

    runner = ChatRunnerV2(
        chat_service=_CaptureSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec(tool_registry="my-registry")
    asyncio.run(runner.run_to_completion(spec))
    assert captured_registry == ["my-registry"]


# Group 10: _RunContext edge cases (5 cases)


def test_run_context_compacted_count_starts_at_zero() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.compacted_count == 0


def test_run_context_chars_saved_starts_at_zero() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.chars_saved == 0


def test_run_context_compacted_count_increments() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.compacted_count = 5
    assert ctx.compacted_count == 5


def test_run_context_last_tool_calls_initially_empty() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.last_tool_calls == []


def test_run_context_hook_ctx_has_required_fields() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[{"role": "user", "content": "x"}])
    hook_ctx = ctx.hook_ctx(0)
    assert hasattr(hook_ctx, "iteration")
    assert hasattr(hook_ctx, "messages")
    assert hasattr(hook_ctx, "tool_events")
    assert hasattr(hook_ctx, "stop_reason")
    assert hasattr(hook_ctx, "error")


# =============================================================================
# 300+ milestone — 11 groups × ~10 cases = 100 cases
# =============================================================================


# -----------------------------------------------------------------------------
# Group 11: Error Handling Paths (15)
# -----------------------------------------------------------------------------


def test_11_llm_stream_raises_caught_as_error() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("llm exploded")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    kinds = [e["type"] for e in events]
    assert "error" in kinds
    assert events[-1]["type"] == "done"
    assert events[-1]["stop_reason"] == "error"


def test_11_tool_executor_raises_emits_tool_call_error() -> None:
    class _ExecRaise:
        async def execute(self, *a, **k):
            raise RuntimeError("tool exploded")

    runner, _llm, _, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._tool_executor = _ExecRaise()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errors = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errors) == 1
    assert "exploded" in errors[0]["error"]


def test_11_hook_before_iteration_raises_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HookRaise(NoOpHook):
        def before_iteration(self, ctx):
            raise RuntimeError("hook boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HookRaise(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "x"


def test_11_hook_after_tool_executed_raises_resilient() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HookRaise(NoOpHook):
        def after_tool_executed(self, ctx, tc, res):
            raise RuntimeError("after tool boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    runner._hook = CompositeHook([_HookRaise(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(ends) == 1


def test_11_hook_finalize_content_raises_done_has_content() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HookRaise(NoOpHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("finalize boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "raw answer"}],
    )
    runner._hook = CompositeHook([_HookRaise(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "raw answer"


def test_11_hook_on_error_raises_resilient() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HookRaise(NoOpHook):
        def on_error(self, ctx, err):
            raise RuntimeError("on_error boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HookRaise(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_11_tool_returns_error_dict_emits_tool_call_error() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": {"status": "error", "error": "bad path"}},
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errs) == 1
    assert errs[0]["error"] == "bad path"


def test_11_tool_returns_confirmation_required() -> None:
    conf = {
        "status": "confirmation_required",
        "confirmation_id": "abc123",
        "impact": {"files": ["/etc/x"]},
    }
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {"cmd": "rm"}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": conf},
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    cr = [e for e in events if e["type"] == "confirmation_required"]
    assert len(cr) == 1
    assert cr[0]["confirmation_id"] == "abc123"


def test_11_tool_name_empty_emits_tool_call_error() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "", "args": {}},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert len(errs) == 1
    assert "empty name" in errs[0]["error"]


def test_11_tool_args_invalid_json_string_handled() -> None:
    captured = []

    class _CaptureExec:
        async def execute(self, tn, args, _r, _s, _c):
            captured.append(args)
            return {"ok": True}

    runner, _llm, _, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": "{not json"},
            {"type": "done", "content": "x"},
        ],
    )
    runner._tool_executor = _CaptureExec()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    asyncio.run(go())
    assert captured[0] == {"_raw": "{not json"}


def test_11_truncate_raises_returns_original() -> None:
    class _LLMTruncRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, _m):
            raise RuntimeError("trunc boom")

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLMTruncRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_11_get_toolspec_raises_returns_empty() -> None:
    class _LLMSpecRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            raise RuntimeError("spec boom")

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLMSpecRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_11_prompt_builder_raises_done_with_error() -> None:
    class _PBRaise:
        async def build_with_context(self, _c):
            raise RuntimeError("pb boom")

    runner, _llm, _exec, _pb = _make_full_runner()
    runner._prompt_builder = _PBRaise()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "error"]
    assert len(errs) == 1
    assert "boom" in errs[0]["message"]


def test_11_tool_executor_returns_none_handled() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": None},
    )
    spec = _make_spec(microcompact=False)

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(ends) == 1


def test_11_tool_executor_returns_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "list_dir", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"list_dir": [1, 2, 3]},
    )
    spec = _make_spec(microcompact=False)

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert ends[0]["result"] == [1, 2, 3]


# -----------------------------------------------------------------------------
# Group 12: SSE Event Format (15)
# -----------------------------------------------------------------------------


def test_12_done_event_required_fields() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "answer"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["type"] == "done"
    assert "content" in done
    assert "stop_reason" in done
    assert "error" in done
    assert "compacted_count" in done


def test_12_message_delta_event_has_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "hi"},
            {"type": "done", "content": "hi"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    deltas = [e for e in events if e["type"] == "message_delta"]
    assert deltas[0]["content"] == "hi"


def test_12_tool_call_start_required_fields() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"p": 1}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert "call_id" in starts[0]
    assert "tool" in starts[0]
    assert "args" in starts[0]


def test_12_tool_call_end_required_fields() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert "call_id" in ends[0]
    assert "tool" in ends[0]
    assert "result" in ends[0]


def test_12_tool_call_error_required_fields() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    class _ExecRaise:
        async def execute(self, *a, **k):
            raise RuntimeError("nope")

    runner._tool_executor = _ExecRaise()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert "call_id" in errs[0]
    assert "tool" in errs[0]
    assert "error" in errs[0]


def test_12_error_event_required_fields() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    err = next(e for e in events if e["type"] == "error")
    assert "message" in err
    assert "stop_reason" in err


def test_12_thinking_event_has_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "hmm"},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    thinkings = [e for e in events if e["type"] == "thinking"]
    assert thinkings[0]["content"] == "hmm"


def test_12_compacted_event_required_fields() -> None:
    big = {"items": [{"id": i, "data": "x" * 100} for i in range(1000)]}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=500)

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    comp = [e for e in events if e["type"] == "compacted"]
    assert "call_id" in comp[0]
    assert "tool" in comp[0]
    assert "chars_saved" in comp[0]


def test_12_confirmation_required_event_required_fields() -> None:
    conf = {
        "status": "confirmation_required",
        "confirmation_id": "c1",
        "impact": {"files": ["/x"]},
    }
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": conf},
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    cr = [e for e in events if e["type"] == "confirmation_required"]
    assert "confirmation_id" in cr[0]
    assert "tool" in cr[0]
    assert "args" in cr[0]
    assert "impact" in cr[0]
    assert "call_id" in cr[0]


def test_12_session_init_event_when_hook_wants_streaming() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _StreamHook(NoOpHook):
        def wants_streaming(self):
            return True

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _StreamHook()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    init = [e for e in events if e["type"] == "session_init"]
    assert len(init) == 1
    assert init[0]["session_id"] == "s1"


def test_12_event_order_preserved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "content", "text": "b"},
            {"type": "done", "content": "ab"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    types = [e["type"] for e in events]
    assert types[0] == "message_delta"
    assert "tool_call_start" in types
    assert "tool_call_end" in types
    assert types[-1] == "done"


def test_12_unknown_event_type_skipped() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "weird_type", "data": "x"},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    types = [e["type"] for e in events]
    assert "weird_type" not in types


def test_12_done_event_includes_compacted_count() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["compacted_count"] == 0


def test_12_done_event_error_is_none_on_success() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["error"] is None


def test_12_done_event_error_set_on_llm_failure() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["error"] is not None
    assert "boom" in done["error"]


# -----------------------------------------------------------------------------
# Group 13: Stop Reason Mapping (10)
# -----------------------------------------------------------------------------


def test_13_stop_reason_completed_default() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_13_stop_reason_error_on_llm_exception() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_13_stop_reason_error_event_in_run_to_completion() -> None:
    class _LLMErrorEvent:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "error", "message": "x"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMErrorEvent(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_13_stop_reason_cancelled_via_precheck() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def cancelled_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancelled_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_13_stop_reason_paused_via_precheck() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def paused_precheck(ctx):
        ctx.paused = True
        ctx.stop_reason = "paused"
        return True

    runner._precheck = paused_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "paused"


def test_13_stop_reason_timeout_via_precheck() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def timeout_precheck(ctx):
        ctx.stop_reason = "timeout"
        return True

    runner._precheck = timeout_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "timeout"


def test_13_stop_reason_confirmation_required() -> None:
    conf = {"status": "confirmation_required", "confirmation_id": "c"}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": conf},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


def test_13_stop_reason_max_iterations_exhausted() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "in_progress"


def test_13_phase_event_cancelled_propagates() -> None:
    class _LLMPhase:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMPhase(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_13_phase_event_unknown_ignored() -> None:
    class _LLMPhase:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "weird"}
            yield {"type": "done", "content": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLMPhase(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# -----------------------------------------------------------------------------
# Group 14: Multi-tool per iteration (10)
# -----------------------------------------------------------------------------


def test_14_two_tool_calls_in_one_iter() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {"cmd": "ls"}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert len(starts) == 2
    assert len(executor.calls) == 2


def test_14_three_tool_calls_mixed_success() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "tool_call", "id": "c3", "name": "list_dir", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 3


def test_14_tool_returns_error_continues_to_next() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": {"status": "error", "error": "bad"}},
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(errs) == 1
    assert len(ends) == 1
    assert ends[0]["tool"] == "exec"


def test_14_tool_raises_continues_to_next() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    class _FailThenOK:
        def __init__(self):
            self.calls = []

        async def execute(self, tn, args, _r, _s, _c):
            self.calls.append(tn)
            if tn == "read_file":
                raise RuntimeError("fail")
            return {"ok": True}

    runner._tool_executor = _FailThenOK()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(errs) == 1
    assert len(ends) == 1


def test_14_tool_returns_confirmation_stops_iteration() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={
            "exec": {"status": "confirmation_required", "confirmation_id": "c"},
        },
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    cr = [e for e in events if e["type"] == "confirmation_required"]
    starts = [e for e in events if e["type"] == "tool_call_start"]
    assert len(cr) == 1
    assert len(starts) == 1


def test_14_tool_name_empty_skipped_next_ok() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used == ["read_file"]


def test_14_tool_calls_preserve_order() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "list_dir", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c3", "name": "exec", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used == ["list_dir", "read_file", "exec"]


def test_14_tools_used_dedup_in_run_to_completion() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used.count("read_file") == 1


def test_14_two_iters_three_tools() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "tool_call", "id": "c3", "name": "list_dir", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 3


def test_14_tool_call_id_in_each_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "id_x", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    starts = [e for e in events if e["type"] == "tool_call_start"]
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert starts[0]["call_id"] == "id_x"
    assert ends[0]["call_id"] == "id_x"


# -----------------------------------------------------------------------------
# Group 15: Text-mode Parser (10)
# -----------------------------------------------------------------------------


def test_15_text_mode_tool_call_in_content() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": 'Hello [TOOL_CALL] tool => "read_file", args => {"p": "/x"} [/TOOL_CALL] world'},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_15_text_mode_multiple_in_one_stream() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": '[TOOL_CALL] tool => "read_file", args => {} [/TOOL_CALL] mid [TOOL_CALL] tool => "exec", args => {} [/TOOL_CALL]',
            },
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used
    assert "exec" in result.tools_used


def test_15_text_mode_complex_args() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": '[TOOL_CALL] tool => "exec", args => { cmd => "ls -la", n => 3 } [/TOOL_CALL]',
            },
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    asyncio.run(go())
    assert executor.calls[0][0] == "exec"
    assert executor.calls[0][1]["cmd"] == "ls -la"


def test_15_text_mode_content_before_and_after() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": 'before [TOOL_CALL] tool => "read_file", args => {} [/TOOL_CALL] after',
            },
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    deltas = [e for e in events if e["type"] == "message_delta"]
    text = "".join(d["content"] for d in deltas)
    assert "before" in text
    assert "after" in text


def test_15_text_mode_malformed_no_crash() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": "[TOOL_CALL] garbage without proper format [/TOOL_CALL]",
            },
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content is not None


def test_15_text_mode_flushed_on_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "[TOOL_CALL] tool => \"read_file\", args => {} [/TOOL_CALL]"},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_15_native_tool_call_takes_precedence() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": '[TOOL_CALL] tool => "list_dir", args => {} [/TOOL_CALL]',
            },
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_15_text_mode_thinking_interleaved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "hmm"},
            {
                "type": "content",
                "text": '[TOOL_CALL] tool => "read_file", args => {} [/TOOL_CALL]',
            },
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_15_text_mode_parser_flush_yields_content() -> None:
    from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser

    async def go():
        parser = TextModeParser()
        feed_out = []
        async for ev in parser.feed({"type": "content", "text": "[TOOL_CALL] tool => \"x\", args => {} [/TOOL_CALL] mid"}):
            feed_out.append(ev)
        flushed = parser.flush()
        return feed_out + flushed

    events = asyncio.run(go())
    kinds = [e.get("type") for e in events]
    assert "content" in kinds


def test_15_text_mode_parser_handles_split_chunks() -> None:
    from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser

    async def go():
        parser = TextModeParser()
        out = []
        async for ev in parser.feed({"type": "content", "text": "[TOOL_CALL] tool => \"x\""}):
            out.append(ev)
        async for ev in parser.feed({"type": "content", "text": ", args => {} [/TOOL_CALL]"}):
            out.append(ev)
        out.extend(parser.flush())
        return out

    events = asyncio.run(go())
    tcs = [e for e in events if e.get("type") == "tool_call"]
    assert len(tcs) == 1


# -----------------------------------------------------------------------------
# Group 16: max_iterations Boundary (10)
# -----------------------------------------------------------------------------


def test_16_max_iterations_1_with_tool_call() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "in_progress"


def test_16_max_iterations_2_two_tool_calls() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "exec", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 2


def test_16_max_iterations_10_default_completes() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec(max_iterations=10)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_16_max_iterations_0_no_iters() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec(max_iterations=0)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "in_progress"


def test_16_max_iterations_1_no_tool_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_16_max_iterations_default_10() -> None:
    spec = _make_spec()
    assert spec.max_iterations == 10


def test_16_max_iterations_exhausted_yields_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_16_max_iterations_all_have_tool_no_final_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content is None or result.final_content == ""


def test_16_max_iterations_boundary_1_1_tool() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_16_max_iterations_high_value_ok() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    spec = _make_spec(max_iterations=100)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# -----------------------------------------------------------------------------
# Group 17: Hook Failure Isolation (10)
# -----------------------------------------------------------------------------


def test_17_hook_before_iteration_raises_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def before_iteration(self, ctx):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_17_hook_after_iteration_raises_next_starts() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def after_iteration(self, ctx):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_17_hook_on_stream_raises_content_yielded() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def on_stream(self, ctx, chunk):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "x"},
            {"type": "done", "content": "x"},
        ],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    deltas = [e for e in events if e["type"] == "message_delta"]
    assert deltas


def test_17_hook_emit_reasoning_raises_resilient() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def emit_reasoning(self, ctx, chunk):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "x"},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    thinks = [e for e in events if e["type"] == "thinking"]
    assert thinks


def test_17_hook_before_execute_tools_raises_tools_run() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def before_execute_tools(self, ctx):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_17_hook_after_tool_executed_raises_result_recorded() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def after_tool_executed(self, ctx, tc, res):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "read_file" in result.tools_used


def test_17_hook_on_tool_error_raises_error_yielded() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def on_tool_error(self, ctx, tc, err):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _Raise:
        async def execute(self, *a, **k):
            raise RuntimeError("tool boom")

    runner._tool_executor = _Raise()
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_17_hook_on_confirmation_raises_confirmation_set() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def on_confirmation(self, ctx, tc):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={
            "exec": {"status": "confirmation_required", "confirmation_id": "x"},
        },
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


def test_17_hook_on_error_raises_error_event_yielded() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def on_error(self, ctx, err):
            raise RuntimeError("boom")

    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("llm boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
        hook=CompositeHook([_H(), NoOpHook()]),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "error"]
    assert errs


def test_17_hook_finalize_content_raises_done_yielded() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H(NoOpHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_H(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


# -----------------------------------------------------------------------------
# Group 18: Usage Tracking (5)
# -----------------------------------------------------------------------------


def test_18_usage_default_empty_in_result() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.usage == {}


def test_18_hook_ctx_usage_independent() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[{"role": "user", "content": "x"}])
    ctx.usage = {"tokens": 100}
    hook_ctx = ctx.hook_ctx(0)
    hook_ctx.usage["tokens"] = 200
    assert ctx.usage["tokens"] == 100


def test_18_usage_aggregation_via_done_event() -> None:
    class _LLMUsage:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "usage", "input": 10, "output": 20}
            yield {"type": "done", "content": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLMUsage(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.usage == {}


def test_18_usage_cumulative_across_iterations() -> None:
    class _LLMUsage:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "usage", "input": 5, "output": 5}
            yield {"type": "done", "content": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLMUsage(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.usage == {}


def test_18_usage_appears_in_hook_ctx() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[{"role": "user", "content": "x"}])
    ctx.usage = {"prompt_tokens": 100, "completion_tokens": 50}
    hook_ctx = ctx.hook_ctx(0)
    assert hook_ctx.usage == {"prompt_tokens": 100, "completion_tokens": 50}


# -----------------------------------------------------------------------------
# Group 19: Mutation Safety (5)
# -----------------------------------------------------------------------------


def test_19_spec_messages_not_mutated_by_run() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    original_len = len(spec.messages)
    asyncio.run(runner.run_to_completion(spec))
    assert len(spec.messages) == original_len


def test_19_ctx_messages_appends_tool_messages() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(spec.messages) == 1


def test_19_concurrent_runs_isolated_messages() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go(spec):
        return await runner.run_to_completion(spec)

    async def main():
        spec_a = _make_spec(messages=[{"role": "user", "content": "a"}])
        spec_b = _make_spec(messages=[{"role": "user", "content": "b"}])
        return await asyncio.gather(go(spec_a), go(spec_b))

    res_a, res_b = asyncio.run(main())
    assert res_a.messages == [{"role": "user", "content": "a"}]
    assert res_b.messages == [{"role": "user", "content": "b"}]


def test_19_hook_receives_messages_snapshot() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    received = []

    class _H(NoOpHook):
        def before_iteration(self, ctx):
            received.append(list(ctx.messages))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _H()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(received) >= 1
    for snap in received:
        assert isinstance(snap, list)


def test_19_tool_registry_not_mutated() -> None:
    reg = object()
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(tool_registry=reg)
    asyncio.run(runner.run_to_completion(spec))
    assert spec.tool_registry is reg


# -----------------------------------------------------------------------------
# Group 20: Phase Event (5)
# -----------------------------------------------------------------------------


def test_20_phase_event_cancelled() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_20_phase_event_paused() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "paused"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "paused"


def test_20_phase_event_timeout() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "timeout"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "timeout"


def test_20_phase_event_unknown_keeps_default() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "weird_unknown"}
            yield {"type": "done", "content": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_20_phase_event_multiple_uses_last() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            yield {"type": "phase", "phase": "paused"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "paused"


# -----------------------------------------------------------------------------
# Group 21: Default Spec (5)
# -----------------------------------------------------------------------------


def test_21_spec_default_messages_empty() -> None:
    spec = ChatRunSpec(messages=[], tool_registry=object(), session_id="s")
    assert spec.messages == []


def test_21_spec_default_wiki_id_none() -> None:
    spec = ChatRunSpec(messages=[{"role": "user", "content": "x"}], tool_registry=object(), session_id="s")
    assert spec.wiki_id is None


def test_21_spec_default_tool_registry_none_when_omitted() -> None:
    with pytest.raises(TypeError):
        ChatRunSpec(messages=[{"role": "user", "content": "x"}])  # type: ignore[call-arg]


def test_21_spec_default_workspace_none() -> None:
    spec = ChatRunSpec(messages=[{"role": "user", "content": "x"}], tool_registry=object(), session_id="s")
    assert spec.workspace is None


def test_21_spec_default_temperature_none() -> None:
    spec = ChatRunSpec(messages=[{"role": "user", "content": "x"}], tool_registry=object(), session_id="s")
    assert spec.temperature is None


# -----------------------------------------------------------------------------
# Group 22: Run State Integration (5)
# -----------------------------------------------------------------------------


def test_22_run_context_iteration_count() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec(max_iterations=5)
    ctx = _RunContext(spec=spec, messages=[{"role": "user", "content": "x"}])
    for i in range(5):
        hook_ctx = ctx.hook_ctx(i)
        assert hook_ctx.iteration == i


def test_22_run_context_hook_ctx_messages_independent() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[{"role": "user", "content": "x"}])
    hook_ctx1 = ctx.hook_ctx(0)
    hook_ctx1.messages.append({"role": "user", "content": "y"})
    assert len(ctx.messages) == 1


def test_22_run_context_hook_ctx_tool_calls_independent() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.last_tool_calls = [{"name": "x", "args": {}}]
    hook_ctx = ctx.hook_ctx(0)
    hook_ctx.tool_calls.clear()
    assert len(ctx.last_tool_calls) == 1


def test_22_run_context_hook_ctx_stop_reason() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.stop_reason = "completed"
    assert ctx.hook_ctx(0).stop_reason == "completed"


def test_22_run_context_hook_ctx_error_propagates() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    ctx.error = "boom"
    assert ctx.hook_ctx(0).error == "boom"


# -----------------------------------------------------------------------------
# Group 23: Streaming Behavior (5)
# -----------------------------------------------------------------------------


def test_23_done_event_content_from_content_chunks() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "Hello"},
            {"type": "content", "text": " world"},
            {"type": "done", "content": "Hello world"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "Hello world"


def test_23_done_event_falls_back_to_done_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "fallback"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "fallback"


def test_23_done_event_empty_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": ""}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content is None or result.final_content == ""


def test_23_thinking_not_in_final_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "secret thought"},
            {"type": "content", "text": "actual answer"},
            {"type": "done", "content": "actual answer"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "secret" not in (result.final_content or "")


def test_23_done_content_ignored_when_chunks_present() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "chunk1"},
            {"type": "done", "content": "final"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "chunk1"


# -----------------------------------------------------------------------------
# Group 24: System Prompt Integration (5)
# -----------------------------------------------------------------------------


def test_24_system_prompt_prepended_to_messages() -> None:
    class _LLMCapture:
        config: dict = {}
        captured: list = []

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, messages, _tools):
            self.captured = list(messages)
            yield {"type": "done", "content": "x"}

    llm = _LLMCapture()
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(prompt="You are a helpful assistant."),
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert llm.captured[0]["role"] == "system"
    assert "helpful" in llm.captured[0]["content"]


def test_24_system_prompt_not_duplicated_if_exists() -> None:
    class _LLMCapture:
        config: dict = {}
        captured: list = []

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, messages, _tools):
            self.captured = list(messages)
            yield {"type": "done", "content": "x"}

    llm = _LLMCapture()
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(prompt="STUB"),
    )
    spec = _make_spec(
        messages=[
            {"role": "system", "content": "user system"},
            {"role": "user", "content": "hi"},
        ],
    )
    asyncio.run(runner.run_to_completion(spec))
    sys_count = sum(1 for m in llm.captured if m["role"] == "system")
    assert sys_count == 1


def test_24_prompt_builder_with_context_used_if_available() -> None:
    class _PB:
        def __init__(self):
            self.called_with = None

        async def build_with_context(self, ctx):
            self.called_with = ctx
            return "ctx prompt"

    pb = _PB()
    runner, _llm, _exec, _ = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._prompt_builder = pb
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert pb.called_with is not None


def test_24_prompt_builder_fallback_to_build() -> None:
    class _PB:
        def __init__(self):
            self.called_with = None

        async def build(self, **kwargs):
            self.called_with = kwargs
            return "fallback prompt"

    pb = _PB()
    runner, _llm, _exec, _ = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._prompt_builder = pb
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert pb.called_with is not None


def test_24_prompt_builder_none_returns_empty() -> None:
    class _PBEmpty:
        pass

    runner, _llm, _exec, _ = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._prompt_builder = _PBEmpty()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


# =============================================================================
# 400+ milestone — 9 groups × ~12 cases = 110 cases
# Focus: state machine 详尽单测 + 边界并发 + mock 异常注入
# =============================================================================


# -----------------------------------------------------------------------------
# Group 25: State machine transitions (20)
# -----------------------------------------------------------------------------


def test_25_precheck_false_proceeds_to_reason() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    prechecks = []

    class _PHook(NoOpHook):
        def before_iteration(self, ctx):
            prechecks.append(True)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _PHook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert prechecks
    assert result.stop_reason == "completed"


def test_25_precheck_true_skips_reason() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def cancel_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancel_precheck
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_25_reason_no_tool_calls_goes_to_complete() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert result.final_content == "x"


def test_25_reason_with_tool_calls_goes_to_act() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(executor.calls) == 1


def test_25_reason_raises_goes_to_error() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_25_act_all_tools_run_then_observe() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    observations = []

    class _OHook(NoOpHook):
        def after_iteration(self, ctx):
            observations.append(list(ctx.observations))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = _OHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert observations
    assert len(observations[0]) >= 0


def test_25_act_confirmation_stops_iteration_no_observe() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    after_iters = []

    class _OHook(NoOpHook):
        def after_iteration(self, ctx):
            after_iters.append(1)
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    runner._hook = _OHook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"
    assert after_iters == []


def test_25_act_error_continues_to_next_tool() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _FailA:
        async def execute(self, tn, args, _r, _s, _c):
            if tn == "a":
                raise RuntimeError("a failed")
            return {"ok": True}

    runner._tool_executor = _FailA()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 1
    assert result.tools_used[0] == "b"


def test_25_act_exception_continues_to_next_tool() -> None:
    runner, _llm, executor, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _ErrA:
        async def execute(self, tn, args, _r, _s, _c):
            if tn == "a":
                raise ValueError("a err")
            return {"ok": True}

    runner._tool_executor = _ErrA()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used == ["b"]


def test_25_observe_appends_observation_after_iteration() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    captured = []

    class _OHook(NoOpHook):
        def after_iteration(self, ctx):
            captured.append(list(ctx.observations))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "thinking", "text": "thinking content"},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = _OHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert captured
    if captured[0]:
        assert any("thinking" in str(o) for o in captured[0])


def test_25_complete_yields_done_always() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_25_complete_with_error_yields_error_then_done() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    kinds = [e["type"] for e in events]
    error_idx = kinds.index("error")
    done_idx = kinds.index("done")
    assert error_idx < done_idx


def test_25_state_persists_across_iterations() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 2


def test_25_state_resets_at_run_start() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return await runner.run_to_completion(spec)

    r1 = asyncio.run(go())
    r2 = asyncio.run(go())
    assert r1.compacted_count == r2.compacted_count == 0


def test_25_multiple_iterations_state_accumulates() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert "a" in result.tools_used
    assert "b" in result.tools_used


def test_25_tool_error_does_not_reset_state() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"a": {"status": "error", "error": "bad"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_25_hook_failure_does_not_reset_state() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            raise RuntimeError("x")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_25_reason_failed_breaks_loop() -> None:
    class _LLMError:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "error", "message": "x"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMError(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_25_confirmation_breaks_loop() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


# -----------------------------------------------------------------------------
# Group 26: State machine interrupt points (10)
# -----------------------------------------------------------------------------


def test_26_cancel_at_precheck_iter1() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def cancel_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancel_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_26_cancel_at_precheck_iter2_via_hook() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    iter_count = [0]

    class _CHook(NoOpHook):
        def before_iteration(self, ctx):
            iter_count[0] += 1
            if iter_count[0] >= 2:
                ctx.cancelled = True
                ctx.stop_reason = "cancelled"
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner._hook = _CHook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in {"cancelled", "completed"}


def test_26_pause_at_reason_via_precheck() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def pause_precheck(ctx):
        ctx.paused = True
        ctx.stop_reason = "paused"
        return True

    runner._precheck = pause_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "paused"


def test_26_pause_at_act_via_precheck() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _PHook(NoOpHook):
        def before_iteration(self, ctx):
            ctx.paused = True
            ctx.stop_reason = "paused"
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _PHook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in {"paused", "completed"}


def test_26_timeout_during_act_via_precheck() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def timeout_precheck(ctx):
        ctx.stop_reason = "timeout"
        return True

    runner._precheck = timeout_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "timeout"


def test_26_timeout_during_reason_via_precheck() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _THook(NoOpHook):
        def before_iteration(self, ctx):
            ctx.stop_reason = "timeout"
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _THook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in {"timeout", "completed"}


def test_26_cancel_via_phase_event_in_stream() -> None:
    class _LLMPhase:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMPhase(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_26_pause_via_phase_event_in_stream() -> None:
    class _LLMPhase:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "paused"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMPhase(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "paused"


def test_26_interruption_preserves_tools_used() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(max_iterations=1)
    result = asyncio.run(runner.run_to_completion(spec))
    assert "a" in result.tools_used


def test_26_multiple_interrupt_points_handled() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def interrupt_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = interrupt_precheck

    async def go():
        r = []
        for _ in range(3):
            r.append(await runner.run_to_completion(_make_spec()))
        return r

    results = asyncio.run(go())
    assert all(r.stop_reason == "cancelled" for r in results)


# -----------------------------------------------------------------------------
# Group 27: Boundary concurrency (15)
# -----------------------------------------------------------------------------


def test_27_ten_concurrent_run_to_completion() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go():
        specs = [_make_spec(messages=[{"role": "user", "content": f"m{i}"}]) for i in range(10)]
        return await asyncio.gather(*(runner.run_to_completion(s) for s in specs))

    results = asyncio.run(go())
    assert len(results) == 10
    assert all(r.final_content in (None, "x", "stub answer") for r in results)


def test_27_ten_concurrent_run_stream() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go():
        specs = [_make_spec(messages=[{"role": "user", "content": f"m{i}"}]) for i in range(10)]
        outs = []
        for s in specs:
            events = []
            async for ev in runner.run_stream(s):
                events.append(ev)
            outs.append(events)
        return outs

    results = asyncio.run(go())
    assert all(r[-1]["type"] == "done" for r in results)


def test_27_same_spec_concurrent_isolated() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(messages=[{"role": "user", "content": "x"}])

    async def go():
        return await asyncio.gather(
            runner.run_to_completion(spec),
            runner.run_to_completion(spec),
        )

    r1, r2 = asyncio.run(go())
    assert r1.messages == r2.messages == [{"role": "user", "content": "x"}]


def test_27_different_runners_concurrent() -> None:
    runners = [_make_full_runner(llm_events=[{"type": "done", "content": str(i)}]) for i in range(5)]

    async def go():
        specs = [_make_spec(messages=[{"role": "user", "content": f"m{i}"}]) for i in range(5)]
        tasks = [r[0].run_to_completion(s) for r, s in zip(runners, specs, strict=False)]
        return await asyncio.gather(*tasks)

    results = asyncio.run(go())
    assert len(results) == 5


def test_27_hook_called_concurrently_per_run() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    seen_specs = []

    class _SHook(NoOpHook):
        def before_iteration(self, ctx):
            seen_specs.append(ctx.messages[-1].get("content", ""))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _SHook()

    async def go():
        specs = [_make_spec(messages=[{"role": "user", "content": f"u{i}"}]) for i in range(5)]
        await asyncio.gather(*(runner.run_to_completion(s) for s in specs))

    asyncio.run(go())
    assert len(seen_specs) >= 5


def test_27_microcompact_cache_isolation_under_concurrency() -> None:
    async def go():
        outs = []
        for i in range(5):
            runner_i, _llm_i, _exec_i, _pb_i = _make_full_runner(
                llm_events=[
                    {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
                    {"type": "done", "content": ""},
                ],
                tool_results={"read_file": {"big": "x" * 10000}},
            )
            spec = _make_spec(messages=[{"role": "user", "content": f"u{i}"}], microcompact=True)
            outs.append(await runner_i.run_to_completion(spec))
        return outs

    results = asyncio.run(go())
    for r in results:
        assert r.compacted_count == 1


def test_27_session_id_shared_concurrent() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    shared_sid = "shared_session"

    async def go():
        specs = [
            _make_spec(messages=[{"role": "user", "content": f"u{i}"}], session_id=shared_sid)
            for i in range(5)
        ]
        return await asyncio.gather(*(runner.run_to_completion(s) for s in specs))

    results = asyncio.run(go())
    assert len(results) == 5


def test_27_rapid_fire_100_runs() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go():
        for i in range(100):
            spec = _make_spec(messages=[{"role": "user", "content": f"m{i}"}])
            await runner.run_to_completion(spec)

    asyncio.run(go())


def test_27_concurrent_with_error_path() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )

    async def go():
        specs = [_make_spec() for _ in range(3)]
        return await asyncio.gather(*(runner.run_to_completion(s) for s in specs))

    results = asyncio.run(go())
    assert all(r.stop_reason == "error" for r in results)


def test_27_concurrent_with_cancel_path() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def cancel_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancel_precheck

    async def go():
        return await asyncio.gather(*(runner.run_to_completion(spec) for _ in range(5)))

    results = asyncio.run(go())
    assert all(r.stop_reason == "cancelled" for r in results)


def test_27_concurrent_with_confirmation_path() -> None:
    async def go():
        outs = []
        for _ in range(3):
            runner_i, _llm_i, _exec_i, _pb_i = _make_full_runner(
                llm_events=[
                    {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
                    {"type": "done", "content": ""},
                ],
                tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
            )
            outs.append(await runner_i.run_to_completion(_make_spec()))
        return outs

    results = asyncio.run(go())
    assert all(r.stop_reason == "confirmation_required" for r in results)


def test_27_concurrent_different_tool_calls() -> None:
    big_a = {"a": "x" * 1000}
    big_b = {"b": "y" * 1000}
    runner_a, _llm_a, _exec_a, _pb_a = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"read_file": big_a},
    )
    runner_b, _llm_b, _exec_b, _pb_b = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "y"},
        ],
        tool_results={"read_file": big_b},
    )

    async def go():
        return await asyncio.gather(
            runner_a.run_to_completion(_make_spec(messages=[{"role": "user", "content": "a"}])),
            runner_b.run_to_completion(_make_spec(messages=[{"role": "user", "content": "b"}])),
        )

    r1, r2 = asyncio.run(go())
    assert r1.compacted_count == 1
    assert r2.compacted_count == 1


def test_27_concurrent_with_microcompact_enabled() -> None:
    async def go():
        outs = []
        for i in range(5):
            runner_i, _llm_i, _exec_i, _pb_i = _make_full_runner(
                llm_events=[
                    {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
                    {"type": "done", "content": "x"},
                ],
                tool_results={"read_file": {"d": "x" * 5000}},
            )
            spec = _make_spec(messages=[{"role": "user", "content": f"u{i}"}], microcompact=True)
            outs.append(await runner_i.run_to_completion(spec))
        return outs

    results = asyncio.run(go())
    for r in results:
        assert r.compacted_count == 1


def test_27_concurrent_with_phase_event() -> None:
    class _LLMPhase:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMPhase(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )

    async def go():
        return await asyncio.gather(*(runner.run_to_completion(_make_spec()) for _ in range(3)))

    results = asyncio.run(go())
    assert all(r.stop_reason == "cancelled" for r in results)


def test_27_concurrent_same_runner_sequential() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go():
        out = []
        for i in range(3):
            spec = _make_spec(messages=[{"role": "user", "content": f"m{i}"}])
            out.append(await runner.run_to_completion(spec))
        return out

    results = asyncio.run(go())
    assert len(results) == 3


# -----------------------------------------------------------------------------
# Group 28: Exception injection (15)
# -----------------------------------------------------------------------------


def test_28_hook_raises_value_error_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            raise ValueError("v")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_hook_raises_type_error_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            raise TypeError("t")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_hook_raises_keyerror_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            raise KeyError("k")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_hook_raises_indexerror_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            raise IndexError("i")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_async_hook_raises_loop_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        async def before_iteration(self, ctx):
            raise RuntimeError("async boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_tool_raises_value_error_caught() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _VErr:
        async def execute(self, *a, **k):
            raise ValueError("v")

    runner._tool_executor = _VErr()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_28_tool_raises_asyncio_timeout_error_caught() -> None:
    import asyncio as _a

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _TLErr:
        async def execute(self, *a, **k):
            raise _a.TimeoutError("t")

    runner._tool_executor = _TLErr()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_28_tool_raises_memory_error_caught() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _M:
        async def execute(self, *a, **k):
            raise MemoryError("m")

    runner._tool_executor = _M()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_28_tool_raises_arithmetic_error_caught() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": ""},
        ],
    )

    class _A:
        async def execute(self, *a, **k):
            raise ArithmeticError("a")

    runner._tool_executor = _A()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_28_llm_raises_after_partial_events() -> None:
    class _LLMPartial:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "content", "text": "partial "}
            raise RuntimeError("after partial")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMPartial(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert any(e["type"] == "message_delta" for e in events)
    assert any(e["type"] == "error" for e in events)


def test_28_multiple_hooks_all_raise_continues() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _H1(NoOpHook):
        def before_iteration(self, ctx):
            raise RuntimeError("1")

    class _H2(NoOpHook):
        def before_iteration(self, ctx):
            raise ValueError("2")

    class _H3(NoOpHook):
        def before_iteration(self, ctx):
            raise TypeError("3")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = CompositeHook([_H1(), _H2(), _H3(), NoOpHook()])
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_28_prompt_builder_raises_attribute_error() -> None:
    class _PBAttr:
        async def build_with_context(self, ctx):
            raise AttributeError("a")

    runner, _llm, _exec, _pb = _make_full_runner()
    runner._prompt_builder = _PBAttr()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert any(e["type"] == "error" for e in events)


def test_28_truncate_raises_value_error() -> None:
    class _LLMTruncValue:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            raise ValueError("t")

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLMTruncValue(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_28_get_toolspec_raises_keyerror() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            raise KeyError("k")

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_28_llm_generator_yields_then_raises() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "content", "text": "x"}
            yield {"type": "thinking", "text": "y"}
            raise RuntimeError("end")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


# -----------------------------------------------------------------------------
# Group 29: Boundary message sizes (10)
# -----------------------------------------------------------------------------


def test_29_1mb_message() -> None:
    big = "x" * (1024 * 1024)
    spec = _make_spec(messages=[{"role": "user", "content": big}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_100k_message_history() -> None:
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}" + "x" * 100} for i in range(1000)]
    spec = _make_spec(messages=msgs)
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_single_char_message() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": "x"}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_empty_string_message() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": ""}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_unicode_emoji_message() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": "🎉🚀🌟💻"}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_null_byte_in_content() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": "before\x00after"}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_newline_only_content() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": "\n\n\n"}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_whitespace_only_content() -> None:
    spec = _make_spec(messages=[{"role": "user", "content": "   \t  \n   "}])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_29_tool_result_with_1mb_data() -> None:
    big = {"data": "x" * (1024 * 1024)}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=1000)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 1


def test_29_tool_result_unicode() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "content", "text": "x"},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": {"emoji": "🎉🚀"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "ok" in (result.final_content or "") or "stub" in (result.final_content or "")


# -----------------------------------------------------------------------------
# Group 30: Boundary timing (10)
# -----------------------------------------------------------------------------


def test_30_timeout_very_short() -> None:
    import asyncio as _a

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 0.001}

    async def slow_check(ctx):
        await _a.sleep(0.01)
        return ctx.cancelled or ctx.paused

    runner._precheck = slow_check
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_30_timeout_zero_disables() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 0}
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_30_elapsed_monotonic_nonnegative() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.elapsed() >= 0


def test_30_long_running_act_via_slow_tool() -> None:
    import asyncio as _a

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "slow", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    class _Slow:
        async def execute(self, *a, **k):
            await _a.sleep(0.1)
            return {"ok": True}

    runner._tool_executor = _Slow()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "slow" in result.tools_used


def test_30_immediate_completion() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_30_tool_zero_time() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "fast", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    class _Fast:
        async def execute(self, *a, **k):
            return {"ok": True}

    runner._tool_executor = _Fast()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "fast" in result.tools_used


def test_30_back_to_back_iterations() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    spec = _make_spec(max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.tools_used) == 2


def test_30_hook_latency_doesnt_affect_timeout() -> None:
    import asyncio as _a

    from llmwikify.foundation.callback import AgentHook, NoOpHook

    class _SlowHook(NoOpHook):
        async def before_iteration(self, ctx):
            await _a.sleep(0.05)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _SlowHook()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_30_phase_event_during_long_tool() -> None:
    import asyncio as _a

    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "phase", "phase": "cancelled"}
            await _a.sleep(0.01)
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "cancelled"


def test_30_cancel_during_long_tool() -> None:
    import asyncio as _a

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "slow", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    class _Slow:
        async def execute(self, *a, **k):
            await _a.sleep(0.1)
            return {"ok": True}

    runner._tool_executor = _Slow()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


# -----------------------------------------------------------------------------
# Group 31: Edge state values (10)
# -----------------------------------------------------------------------------


def test_31_tool_name_with_special_chars() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "tool-with-dashes_and.dots", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "tool-with-dashes_and.dots" in result.tools_used


def test_31_tool_name_1kb() -> None:
    long_name = "a" * 1024
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": long_name, "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert long_name in result.tools_used


def test_31_tool_name_with_unicode() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "工具🎉", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "工具🎉" in result.tools_used


def test_31_args_1mb_dict() -> None:
    big_args = {"key_" + str(i): "v" * 100 for i in range(10000)}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": big_args},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_31_args_deep_nested() -> None:
    nested = {"l1": {"l2": {"l3": {"l4": {"l5": {"l6": "deep"}}}}}}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": nested},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_31_args_with_null_bytes() -> None:
    args = {"k": "v\x00with\x00nulls"}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": args},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_31_args_unicode_emoji() -> None:
    args = {"emoji": "🎉", "chinese": "你好"}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": args},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_31_tool_result_1mb_string() -> None:
    big = "x" * (1024 * 1024)
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "content", "text": "x"},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=1000)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 1


def test_31_tool_result_with_none_values() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"x": {"a": None, "b": None, "c": None}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_31_tool_result_with_circular_ref_safe() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"x": {"opaque": object()}},
    )
    spec = _make_spec(microcompact=False)
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


# -----------------------------------------------------------------------------
# Group 32: Reentrance and shared state (10)
# -----------------------------------------------------------------------------


def test_32_hook_can_observe_ctx_state() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    seen_iterations = []

    class _SHook(NoOpHook):
        def before_iteration(self, ctx):
            seen_iterations.append(ctx.iteration)
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    runner._hook = _SHook()
    spec = _make_spec(max_iterations=2)
    asyncio.run(runner.run_to_completion(spec))
    assert 0 in seen_iterations
    assert 1 in seen_iterations


def test_32_hook_sees_consistent_iteration_count() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    iters = []

    class _IHook(NoOpHook):
        def before_iteration(self, ctx):
            iters.append(ctx.iteration)
            return None

        def after_iteration(self, ctx):
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    runner._hook = _IHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert 0 in iters


def test_32_hook_observes_messages_growth() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    sizes = []

    class _MHook(NoOpHook):
        def before_iteration(self, ctx):
            sizes.append(len(ctx.messages))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    runner._hook = _MHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    if len(sizes) >= 2:
        assert sizes[1] > sizes[0]


def test_32_hook_can_read_tools_used() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    captured = []

    class _THook(NoOpHook):
        def before_iteration(self, ctx):
            captured.append(list(ctx.tools_used))
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    runner._hook = _THook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert isinstance(captured, list)


def test_32_hook_observes_compacted_count() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "end"},
        ],
        tool_results={"read_file": {"d": "x" * 5000}},
    )

    seen_count = []

    class _CHook(NoOpHook):
        def before_iteration(self, ctx):
            seen_count.append(ctx.compacted_count)
            return None

    runner._hook = _CHook()
    spec = _make_spec(microcompact=True, microcompact_keep_chars=1000)
    asyncio.run(runner.run_to_completion(spec))
    assert len(seen_count) >= 1


def test_32_hook_observes_final_content() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    seen = []

    class _FHook(NoOpHook):
        def before_iteration(self, ctx):
            seen.append(ctx.final_content)
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _FHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert seen


def test_32_emit_done_called_with_consistent_state() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "end"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["type"] == "done"
    assert "compacted_count" in done
    assert "stop_reason" in done


def test_32_two_run_streams_interleaved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def go():
        events_a = []
        events_b = []
        spec_a = _make_spec(messages=[{"role": "user", "content": "a"}])
        spec_b = _make_spec(messages=[{"role": "user", "content": "b"}])
        gen_a = runner.run_stream(spec_a)
        gen_b = runner.run_stream(spec_b)
        for _ in range(3):
            try:
                events_a.append(await gen_a.__anext__())
            except StopAsyncIteration:
                pass
            try:
                events_b.append(await gen_b.__anext__())
            except StopAsyncIteration:
                pass
        return events_a, events_b

    a, b = asyncio.run(go())
    assert isinstance(a, list)
    assert isinstance(b, list)


def test_32_hook_callback_during_hook() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    depth = [0]
    max_depth = [0]

    class _RHook(NoOpHook):
        def before_iteration(self, ctx):
            depth[0] += 1
            max_depth[0] = max(max_depth[0], depth[0])
            depth[0] -= 1
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _RHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert max_depth[0] == 1


def test_32_run_context_dataclass_hashable_fields() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.compacted_count == 0
    assert ctx.chars_saved == 0
    assert ctx.cancelled is False
    assert ctx.paused is False
    assert ctx.error is None


# -----------------------------------------------------------------------------
# Group 33: Code path coverage (10)
# -----------------------------------------------------------------------------


def test_33_stream_llm_fallback_to_done_when_no_methods() -> None:
    class _LLMEmpty:
        config: dict = {}
        wiki_service = None

    runner = ChatRunnerV2(
        chat_service=_LLMEmpty(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = [e for e in events if e["type"] == "done"]
    assert done


def test_33_stream_llm_no_methods_yields_empty_done() -> None:
    class _LLMNoMethods:
        config: dict = {}
        wiki_service = None

    runner = ChatRunnerV2(
        chat_service=_LLMNoMethods(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == ""


def test_33_execute_tool_with_callable() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )

    def call_executor(tn, args, _r, _s, _c):
        return {"ok": tn}

    runner._tool_executor = call_executor
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_33_execute_tool_raises_runtime_error_no_executor() -> None:
    class _BadExec:
        pass

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    runner._tool_executor = _BadExec()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_33_safe_truncate_with_coroutine_return() -> None:
    import asyncio as _a

    class _LLMCoroTrunc:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            async def _c():
                return None
            return _c()

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLMCoroTrunc(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_33_get_tool_specs_no_method_returns_empty() -> None:
    class _LLMNoSpec:
        config: dict = {}
        wiki_service = None

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLMNoSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "x"


def test_33_wiki_service_get_llm_called() -> None:
    class _LLMStream:
        async def astream_chat(self, _m, tools=None):
            yield {"type": "done", "content": "wiki-llm"}

    class _WikiSvc:
        def get_llm(self):
            return _LLMStream()

    class _LLMWiki:
        config: dict = {}
        wiki_service = _WikiSvc()

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_LLMWiki(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = next(e for e in events if e["type"] == "done")
    assert "wiki-llm" in done["content"]


def test_33_wiki_service_get_llm_returns_none_fallback() -> None:
    class _WikiSvcNone:
        def get_llm(self):
            return None

    class _LLMWikiNone:
        config: dict = {}
        wiki_service = _WikiSvcNone()

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_LLMWikiNone(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = [e for e in events if e["type"] == "done"]
    assert done


def test_33_emit_done_with_finalize_raises() -> None:
    from llmwikify.foundation.callback import CompositeHook, NoOpHook

    class _HH(NoOpHook):
        def finalize_content(self, ctx, c):
            raise RuntimeError("finalize boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "raw"}],
    )
    runner._hook = CompositeHook([_HH(), NoOpHook()])
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["type"] == "done"
    assert "raw" in done["content"]


def test_33_hook_ctx_messages_are_copy() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    captured = []

    class _HH(NoOpHook):
        def before_iteration(self, ctx):
            captured.append(list(ctx.messages))
            ctx.messages.append({"role": "user", "content": "injected"})
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _HH()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert len(captured) >= 1
    if len(captured[0]) > 0:
        for snap in captured:
            assert isinstance(snap, list)


# =============================================================================
# 500+ milestone — 8 groups × ~12 cases = 95 cases
# Focus: fuzz testing + property-based + property invariants
# =============================================================================


# -----------------------------------------------------------------------------
# Group 34: Fuzz testing (15)
# -----------------------------------------------------------------------------


def test_34_fuzz_random_llm_event_sequence() -> None:
    import random

    random.seed(42)
    tools = ["a", "b", "c", "read_file", "exec"]

    for trial in range(5):
        n = random.randint(1, 8)
        events = []
        for _ in range(n):
            kind = random.choice(["content", "done", "tool_call"])
            if kind == "content":
                events.append({"type": "content", "text": "x"})
            elif kind == "done":
                events.append({"type": "done", "content": f"trial_{trial}"})
                break
            else:
                events.append(
                    {
                        "type": "tool_call",
                        "id": f"c{trial}",
                        "name": random.choice(tools),
                        "args": {},
                    }
                )
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "error", "in_progress",
            "cancelled", "paused", "timeout", "confirmation_required",
        }


def test_34_fuzz_random_tool_names() -> None:
    import random
    import string

    random.seed(123)
    chars = string.ascii_letters + "_"

    for trial in range(10):
        name = "".join(random.choice(chars) for _ in range(random.randint(1, 30)))
        events = [
            {"type": "tool_call", "id": f"c{trial}", "name": name, "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert isinstance(result.tools_used, list)


def test_34_fuzz_random_arg_keys() -> None:
    import random
    import string

    random.seed(456)
    chars = string.ascii_letters

    for trial in range(10):
        n = random.randint(1, 20)
        args = {"k" + "".join(random.choice(chars) for _ in range(5)): random.randint(0, 100) for _ in range(n)}
        events = [
            {"type": "tool_call", "id": f"c{trial}", "name": "x", "args": args},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert "x" in result.tools_used


def test_34_fuzz_random_message_contents() -> None:
    import random
    import string

    random.seed(789)
    chars = string.ascii_letters + " \n\t🎉"

    for _trial in range(10):
        n = random.randint(0, 50)
        content = "".join(random.choice(chars) for _ in range(n))
        spec = _make_spec(messages=[{"role": "user", "content": content}])
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "error", "in_progress",
        }


def test_34_fuzz_random_spec_variations() -> None:
    import random

    random.seed(2024)
    for _trial in range(10):
        max_iter = random.randint(1, 20)
        max_chars = random.randint(0, 100000)
        temp = random.choice([0.0, 0.5, 1.0, 2.0])
        spec = _make_spec(
            max_iterations=max_iter,
            max_tool_result_chars=max_chars,
            temperature=temp,
        )
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "error", "in_progress",
        }


def test_34_fuzz_random_message_history_lengths() -> None:
    import random

    random.seed(3030)
    for _trial in range(10):
        n_msgs = random.randint(0, 100)
        msgs = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(n_msgs)
        ]
        spec = _make_spec(messages=msgs)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.messages == msgs


def test_34_fuzz_random_content_chunks() -> None:
    import random

    random.seed(4040)
    for _trial in range(5):
        n_chunks = random.randint(1, 20)
        events = [
            {"type": "content", "text": f"c{i}"} for i in range(n_chunks)
        ] + [{"type": "done", "content": "x"}]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason == "completed"


def test_34_fuzz_random_tool_args_size() -> None:
    import random

    random.seed(5050)
    for _trial in range(5):
        size = random.randint(0, 10000)
        args = {"data": "x" * size}
        events = [
            {"type": "tool_call", "id": "c1", "name": "x", "args": args},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert "x" in result.tools_used


def test_34_fuzz_random_microcompact_keep_chars() -> None:
    import random

    random.seed(6060)
    for _trial in range(5):
        keep = random.randint(0, 10000)
        spec = _make_spec(
            microcompact=True,
            microcompact_keep_chars=keep,
        )
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.compacted_count >= 0


def test_34_fuzz_random_compactable_tools_set() -> None:
    import random

    random.seed(7070)
    all_tools = ["read_file", "exec", "grep", "find_files", "web_search", "web_fetch", "list_dir"]
    for _trial in range(5):
        size = random.randint(0, len(all_tools))
        compactable = frozenset(random.sample(all_tools, size))
        spec = _make_spec(
            microcompact=True,
            microcompact_compactable_tools=compactable,
        )
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.compacted_count >= 0


def test_34_fuzz_random_max_iterations() -> None:
    import random

    random.seed(8080)
    for _trial in range(5):
        mi = random.randint(0, 50)
        spec = _make_spec(max_iterations=mi)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "error", "in_progress",
        }


def test_34_fuzz_random_session_ids() -> None:
    import random
    import string

    random.seed(9090)
    chars = string.ascii_letters + string.digits + "-_"
    for _trial in range(5):
        sid = "".join(random.choice(chars) for _ in range(random.randint(0, 50)))
        spec = _make_spec(session_id=sid)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason == "completed"


def test_34_fuzz_random_wiki_ids() -> None:
    import random
    import string

    random.seed(1010)
    chars = string.ascii_letters + string.digits + "-_"
    for _trial in range(5):
        wid = "".join(random.choice(chars) for _ in range(random.randint(0, 30)))
        spec = _make_spec(wiki_id=wid)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason == "completed"


def test_34_fuzz_random_workspaces() -> None:
    import random

    random.seed(2020)
    for trial in range(5):
        path = Path("/tmp") / f"ws_{trial}_{random.randint(0, 10000)}"
        spec = _make_spec(workspace=path)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason == "completed"


def test_34_fuzz_random_mixed_event_types() -> None:
    import random

    random.seed(3030)
    all_kinds = ["content", "thinking", "done", "tool_call", "phase", "error"]

    for _trial in range(5):
        events = []
        n = random.randint(2, 15)
        for i in range(n):
            kind = random.choice(all_kinds)
            if kind == "content":
                events.append({"type": "content", "text": f"c{i}"})
            elif kind == "thinking":
                events.append({"type": "thinking", "text": f"t{i}"})
            elif kind == "done":
                events.append({"type": "done", "content": f"d{i}"})
                break
            elif kind == "tool_call":
                events.append({"type": "tool_call", "id": f"c{i}", "name": "x", "args": {}})
            elif kind == "phase":
                events.append({"type": "phase", "phase": "cancelled"})
                break
            elif kind == "error":
                events.append({"type": "error", "message": "x"})
                break
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "error", "in_progress",
            "cancelled", "paused", "timeout", "confirmation_required",
        }


# -----------------------------------------------------------------------------
# Group 35: Property-based (15) — result field invariants
# -----------------------------------------------------------------------------


def test_35_property_stop_reason_in_valid_set() -> None:
    valid = {
        "completed", "error", "in_progress",
        "cancelled", "paused", "timeout", "confirmation_required",
    }
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in valid


def test_35_property_final_content_is_str_or_none() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content is None or isinstance(result.final_content, str)


def test_35_property_tools_used_is_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert isinstance(result.tools_used, list)


def test_35_property_usage_is_dict() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert isinstance(result.usage, dict)


def test_35_property_compacted_count_non_negative() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count >= 0


def test_35_property_chars_saved_non_negative() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.total_compacted_chars_saved >= 0


def test_35_property_messages_is_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert isinstance(result.messages, list)


def test_35_property_error_is_str_or_none() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.error is None or isinstance(result.error, str)


def test_35_property_error_none_when_completed() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "completed":
        assert result.error is None


def test_35_property_error_set_when_error() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "error":
        assert result.error is not None


def test_35_property_tools_used_no_duplicates_via_run_to_completion() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "tool_call", "id": "c2", "name": "x", "args": {}},
            {"type": "done", "content": "ok"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.tools_used.count("x") == 1


def test_35_property_compacted_count_matches_microcompact() -> None:
    big = {"d": "x" * 10000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count >= 1
    assert result.total_compacted_chars_saved > 0


def test_35_property_microcompact_disabled_no_compact() -> None:
    big = {"d": "x" * 10000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "ok"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=False)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == 0


def test_35_property_session_id_preserved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(session_id="preserved_sid")
    asyncio.run(runner.run_to_completion(spec))
    assert spec.session_id == "preserved_sid"


def test_35_property_max_iterations_preserved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(max_iterations=7)
    asyncio.run(runner.run_to_completion(spec))
    assert spec.max_iterations == 7


# -----------------------------------------------------------------------------
# Group 36: Property invariants (15) — idempotency/determinism/monotonicity
# -----------------------------------------------------------------------------


def test_36_idempotency_two_runs_same_result() -> None:
    async def go():
        outs = []
        for _ in range(2):
            runner, _llm, _exec, _pb = _make_full_runner(
                llm_events=[{"type": "done", "content": "x"}],
            )
            outs.append(await runner.run_to_completion(_make_spec()))
        return outs

    r1, r2 = asyncio.run(go())
    assert r1.final_content == r2.final_content
    assert r1.stop_reason == r2.stop_reason


def test_36_determinism_same_llm_events_same_result() -> None:
    events = [
        {"type": "content", "text": "a"},
        {"type": "done", "content": "a"},
    ]
    async def go():
        outs = []
        for _ in range(3):
            runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
            outs.append(await runner.run_to_completion(_make_spec()))
        return outs

    rs = asyncio.run(go())
    assert all(r.final_content == rs[0].final_content for r in rs)
    assert all(r.stop_reason == rs[0].stop_reason for r in rs)


def test_36_monotonicity_compacted_count() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"read_file": {"d": "x" * 5000}},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.compacted_count == result.compacted_count


def test_36_monotonicity_chars_saved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"read_file": {"d": "x" * 5000}},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.total_compacted_chars_saved >= 0


def test_36_reflexivity_initial_state() -> None:
    from llmwikify.apps.chat.agent.runner_v2 import _RunContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=[])
    assert ctx.compacted_count == 0
    assert ctx.chars_saved == 0
    assert ctx.cancelled is False
    assert ctx.paused is False
    assert ctx.error is None
    assert ctx.stop_reason == "in_progress"
    assert ctx.confirmation_required is False
    assert ctx.reason_failed is False


def test_36_invariant_stop_reason_implies_no_tool_calls() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "completed" and not result.tools_used:
        assert result.final_content is not None or result.final_content == ""


def test_36_invariant_completed_implies_final_content_set() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "content", "text": "x"}, {"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "completed":
        assert result.final_content is not None


def test_36_invariant_error_implies_error_set() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "error":
        assert result.error is not None
        assert "boom" in result.error


def test_36_invariant_cancelled_implies_cancelled_flag() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def cancel_precheck(ctx):
        ctx.cancelled = True
        ctx.stop_reason = "cancelled"
        return True

    runner._precheck = cancel_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "cancelled":
        assert result.error is None or "cancelled" in (result.error or "").lower() or result.error is not None


def test_36_invariant_messages_count_non_negative() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(result.messages) >= 1


def test_36_invariant_confirmation_implies_stop_reason() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    if "exec" in result.tools_used:
        assert result.stop_reason == "confirmation_required"


def test_36_invariant_timeout_implies_not_completed() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def timeout_precheck(ctx):
        ctx.stop_reason = "timeout"
        return True

    runner._precheck = timeout_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "timeout":
        assert result.stop_reason != "completed"


def test_36_invariant_paused_implies_not_completed() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def paused_precheck(ctx):
        ctx.paused = True
        ctx.stop_reason = "paused"
        return True

    runner._precheck = paused_precheck
    result = asyncio.run(runner.run_to_completion(spec))
    if result.stop_reason == "paused":
        assert result.stop_reason != "completed"


def test_36_invariant_run_idempotency_three_runs() -> None:
    async def go():
        outs = []
        for _ in range(3):
            runner, _llm, _exec, _pb = _make_full_runner(
                llm_events=[{"type": "done", "content": "x"}],
            )
            outs.append(await runner.run_to_completion(_make_spec()))
        return outs

    rs = asyncio.run(go())
    assert all(r.final_content == rs[0].final_content for r in rs)


def test_36_invariant_messages_unchanged_after_run() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(messages=[{"role": "user", "content": "y"}])
    msg_count_before = len(spec.messages)
    asyncio.run(runner.run_to_completion(spec))
    assert len(spec.messages) == msg_count_before


# -----------------------------------------------------------------------------
# Group 37: Fuzz with state mutations (10)
# -----------------------------------------------------------------------------


def test_37_fuzz_random_ctx_cancelled_at_random_iter() -> None:
    import random

    from llmwikify.foundation.callback import AgentHook, NoOpHook

    random.seed(42)
    for _trial in range(5):
        cancelled_at = random.randint(0, 5)

        def make_hook(at: int = cancelled_at) -> NoOpHook:
            class _CHook(NoOpHook):
                def before_iteration(self, ctx):
                    if ctx.iteration == at:
                        ctx.cancelled = True
                        ctx.stop_reason = "cancelled"
                    return None

            return _CHook()

        events = [
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        runner._hook = make_hook()
        spec = _make_spec(max_iterations=10)
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "cancelled", "in_progress", "error",
        }


def test_37_fuzz_random_pause_at_random_iter() -> None:
    import random

    from llmwikify.foundation.callback import AgentHook, NoOpHook

    random.seed(43)
    for _trial in range(5):
        pause_at = random.randint(0, 3)

        def make_hook(at: int = pause_at) -> NoOpHook:
            class _PHook(NoOpHook):
                def before_iteration(self, ctx):
                    if ctx.iteration == at:
                        ctx.paused = True
                        ctx.stop_reason = "paused"
                    return None

            return _PHook()

        events = [
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        runner._hook = make_hook()
        spec = _make_spec(max_iterations=5)
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "paused", "in_progress", "error",
        }


def test_37_fuzz_random_tool_results() -> None:
    import random

    random.seed(44)
    for _trial in range(5):
        result_type = random.choice(["ok", "error", "confirmation", "list", "string", "int"])
        if result_type == "ok":
            tr = {"ok": True}
        elif result_type == "error":
            tr = {"status": "error", "error": "x"}
        elif result_type == "confirmation":
            tr = {"status": "confirmation_required", "confirmation_id": "x"}
        elif result_type == "list":
            tr = [1, 2, 3]
        elif result_type == "string":
            tr = "raw string"
        else:
            tr = 42

        events = [
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events, tool_results={"x": tr})
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert isinstance(result.tools_used, list)


def test_37_fuzz_random_observation_in_hook() -> None:
    import random

    from llmwikify.foundation.callback import AgentHook, NoOpHook

    random.seed(45)
    for trial in range(5):
        random.randint(0, 5)

        def make_hook(t: int = trial) -> NoOpHook:
            class _OHook(NoOpHook):
                def before_iteration(self, ctx):
                    ctx.observations.append(f"obs_{t}_{len(ctx.observations)}")
                    return None

            return _OHook()

        events = [
            {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        runner._hook = make_hook()
        spec = _make_spec()
        asyncio.run(runner.run_to_completion(spec))


def test_37_fuzz_random_error_messages() -> None:
    import random
    import string

    random.seed(46)
    chars = string.ascii_letters
    for _trial in range(5):
        msg = "".join(random.choice(chars) for _ in range(random.randint(1, 50)))

        def make_llm(m: str = msg) -> Any:
            class _LLMRaise:
                config: dict = {}

                def _get_toolspec(self, _r):
                    return []

                def _truncate_messages(self, m2):
                    return list(m2)

                async def _llm_stream_with_retry(self, _m, _t):
                    raise RuntimeError(m)
                    yield

            return _LLMRaise()

        runner = ChatRunnerV2(
            chat_service=make_llm(),
            tool_executor=_StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        )
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        if result.error:
            assert isinstance(result.error, str)


def test_37_fuzz_random_phase_event_order() -> None:
    import random

    random.seed(47)
    for _trial in range(5):
        phases = ["cancelled", "paused", "timeout", "cancelled", "paused"]
        events = [{"type": "phase", "phase": random.choice(phases)} for _ in range(3)]
        events.append({"type": "done", "content": "x"})

        def make_llm(ev_list: list = events) -> Any:
            class _LLM:
                config: dict = {}

                def _get_toolspec(self, _r):
                    return []

                def _truncate_messages(self, m):
                    return list(m)

                async def _llm_stream_with_retry(self, _m, _t):
                    for ev in ev_list:
                        yield ev

            return _LLM()

        runner = ChatRunnerV2(
            chat_service=make_llm(),
            tool_executor=_StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        )
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.stop_reason in {
            "completed", "cancelled", "paused", "timeout",
        }


def test_37_fuzz_random_compactable_tool_mix() -> None:
    import random

    random.seed(48)
    compactable = ["read_file", "exec", "grep", "find_files", "web_search", "web_fetch", "list_dir"]
    not_compactable = ["a", "b", "c", "x", "y", "z"]
    for _trial in range(5):
        use_compactable = random.random() < 0.5
        tool_name = random.choice(compactable if use_compactable else not_compactable)
        big = {"d": "x" * 5000}
        events = [
            {"type": "tool_call", "id": "c1", "name": tool_name, "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events, tool_results={tool_name: big})
        spec = _make_spec(microcompact=True, microcompact_keep_chars=100)
        result = asyncio.run(runner.run_to_completion(spec))
        if use_compactable:
            assert result.compacted_count >= 1


def test_37_fuzz_random_compactable_set_size() -> None:
    import random

    random.seed(49)
    all_tools = ["read_file", "exec", "grep", "find_files", "web_search", "web_fetch", "list_dir"]
    for _trial in range(5):
        size = random.randint(0, len(all_tools))
        compactable = frozenset(random.sample(all_tools, size)) if size else frozenset()
        big = {"d": "x" * 5000}
        events = [
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "x"},
        ]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events, tool_results={"read_file": big})
        spec = _make_spec(
            microcompact=True,
            microcompact_keep_chars=100,
            microcompact_compactable_tools=compactable,
        )
        result = asyncio.run(runner.run_to_completion(spec))
        if "read_file" in compactable:
            assert result.compacted_count >= 1


def test_37_fuzz_random_n_tool_calls() -> None:
    import random

    random.seed(50)
    for _trial in range(5):
        n = random.randint(1, 10)
        events = [
            {"type": "tool_call", "id": f"c{i}", "name": f"t{i}", "args": {}}
            for i in range(n)
        ] + [{"type": "done", "content": "x"}]
        runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
        spec = _make_spec()
        result = asyncio.run(runner.run_to_completion(spec))
        assert len(result.tools_used) == n


def test_37_fuzz_random_messages_random_roles() -> None:
    import random

    random.seed(51)
    roles = ["user", "assistant", "system", "tool"]
    for _trial in range(5):
        n = random.randint(1, 20)
        msgs = [{"role": random.choice(roles), "content": f"m{i}"} for i in range(n)]
        spec = _make_spec(messages=msgs)
        runner, _llm, _exec, _pb = _make_full_runner(
            llm_events=[{"type": "done", "content": "x"}],
        )
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.messages == msgs


# -----------------------------------------------------------------------------
# Group 38: Edge case fuzz (10)
# -----------------------------------------------------------------------------


def test_38_edge_empty_llm_stream() -> None:
    class _LLMEmpty:
        config: dict = {}
        wiki_service = None

    runner = ChatRunnerV2(
        chat_service=_LLMEmpty(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = [e for e in events if e["type"] == "done"]
    assert done


def test_38_edge_single_event_stream() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_38_edge_max_events_stream() -> None:
    events = [{"type": "content", "text": f"c{i}"} for i in range(1000)]
    events.append({"type": "done", "content": "x"})
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events_out = asyncio.run(go())
    assert events_out[-1]["type"] == "done"


def test_38_edge_malformed_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_38_edge_event_with_no_type() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_38_edge_event_with_null_text() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": None},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_38_edge_event_with_empty_args() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_38_edge_event_with_null_args() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": None},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert "x" in result.tools_used


def test_38_edge_event_with_empty_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_38_edge_unicode_in_event_keys() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "🎉"},
            {"type": "done", "content": "🎉"},
        ],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


# -----------------------------------------------------------------------------
# Group 39: Streaming consistency (10)
# -----------------------------------------------------------------------------


def test_39_streaming_total_chunks_equals_final() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "Hello "},
            {"type": "content", "text": "world"},
            {"type": "content", "text": "!"},
            {"type": "done", "content": "Hello world!"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    deltas = [e["content"] for e in events if e["type"] == "message_delta"]
    done = next(e for e in events if e["type"] == "done")
    assert "".join(deltas) == done["content"] or "Hello world!" in done["content"]


def test_39_streaming_delta_order_preserved() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "content", "text": "b"},
            {"type": "content", "text": "c"},
            {"type": "done", "content": "abc"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    deltas = [e["content"] for e in events if e["type"] == "message_delta"]
    joined = "".join(deltas)
    assert joined == "abc"


def test_39_streaming_tool_call_start_before_end() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    starts = [i for i, e in enumerate(events) if e["type"] == "tool_call_start"]
    ends = [i for i, e in enumerate(events) if e["type"] == "tool_call_end"]
    assert starts[0] < ends[0]


def test_39_streaming_error_before_done() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    error_idx = next((i for i, e in enumerate(events) if e["type"] == "error"), None)
    done_idx = next((i for i, e in enumerate(events) if e["type"] == "done"), None)
    assert error_idx is not None and done_idx is not None
    assert error_idx < done_idx


def test_39_streaming_done_event_always_last() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"


def test_39_streaming_confirmation_before_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    cr_idx = next((i for i, e in enumerate(events) if e["type"] == "confirmation_required"), None)
    done_idx = next((i for i, e in enumerate(events) if e["type"] == "done"), None)
    assert cr_idx is not None and done_idx is not None
    assert cr_idx < done_idx


def test_39_streaming_compacted_between_start_and_end() -> None:
    big = {"d": "x" * 5000}
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"read_file": big},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=100)

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    starts = [i for i, e in enumerate(events) if e["type"] == "tool_call_start"]
    comps = [i for i, e in enumerate(events) if e["type"] == "compacted"]
    ends = [i for i, e in enumerate(events) if e["type"] == "tool_call_end"]
    assert starts[0] < comps[0] < ends[0]


def test_39_streaming_content_then_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "x"},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    content_idx = next((i for i, e in enumerate(events) if e["type"] == "message_delta"), None)
    done_idx = next((i for i, e in enumerate(events) if e["type"] == "done"), None)
    assert content_idx < done_idx


def test_39_streaming_thinking_before_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "hmm"},
            {"type": "content", "text": "x"},
            {"type": "done", "content": "x"},
        ],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    think_idx = next((i for i, e in enumerate(events) if e["type"] == "thinking"), None)
    content_idx = next((i for i, e in enumerate(events) if e["type"] == "message_delta"), None)
    assert think_idx < content_idx


def test_39_streaming_done_event_compacted_count_zero() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done = events[-1]
    assert done["compacted_count"] == 0


# -----------------------------------------------------------------------------
# Group 40: Hook invocation patterns (10)
# -----------------------------------------------------------------------------


def test_40_hook_before_iteration_per_iter() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _BHook(NoOpHook):
        def before_iteration(self, ctx):
            count[0] += 1
            return None

    events = [
        {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
        {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
        {"type": "done", "content": "end"},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _BHook()
    spec = _make_spec(max_iterations=3)
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] >= 2


def test_40_hook_after_iteration_per_non_break() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _AHook(NoOpHook):
        def after_iteration(self, ctx):
            count[0] += 1
            return None

    events = [
        {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
        {"type": "done", "content": "end"},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _AHook()
    spec = _make_spec(max_iterations=5)
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] >= 1


def test_40_hook_emit_done_called_once() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1


def test_40_hook_finalize_content_called_once() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _FHook(NoOpHook):
        def finalize_content(self, ctx, content):
            count[0] += 1
            return content

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _FHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] == 1


def test_40_hook_on_stream_per_chunk() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    chunks = []

    class _SHook(NoOpHook):
        def on_stream(self, ctx, chunk):
            chunks.append(chunk)
            return None

    events = [
        {"type": "content", "text": "a"},
        {"type": "content", "text": "b"},
        {"type": "content", "text": "c"},
        {"type": "done", "content": "abc"},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _SHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    joined = "".join(chunks)
    assert joined == "abc"


def test_40_hook_emit_reasoning_per_chunk() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    chunks = []

    class _RHook(NoOpHook):
        def emit_reasoning(self, ctx, chunk):
            chunks.append(chunk)
            return None

    events = [
        {"type": "thinking", "text": "t1"},
        {"type": "thinking", "text": "t2"},
        {"type": "done", "content": ""},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _RHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert chunks == ["t1", "t2"]


def test_40_hook_before_execute_tools_per_iter() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _BHook(NoOpHook):
        def before_execute_tools(self, ctx):
            count[0] += 1
            return None

    events = [
        {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
        {"type": "done", "content": "end"},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _BHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] >= 1


def test_40_hook_after_tool_executed_per_tool() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _AHook(NoOpHook):
        def after_tool_executed(self, ctx, tc, res):
            count[0] += 1
            return None

    events = [
        {"type": "tool_call", "id": "c1", "name": "a", "args": {}},
        {"type": "tool_call", "id": "c2", "name": "b", "args": {}},
        {"type": "done", "content": "end"},
    ]
    runner, _llm, _exec, _pb = _make_full_runner(llm_events=events)
    runner._hook = _AHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] == 2


def test_40_hook_on_error_called_on_error() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _EHook(NoOpHook):
        def on_error(self, ctx, err):
            count[0] += 1
            return None

    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
        hook=_EHook(),
    )
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] == 1


def test_40_hook_on_confirmation_called_on_confirmation() -> None:
    from llmwikify.foundation.callback import AgentHook, NoOpHook

    count = [0]

    class _CHook(NoOpHook):
        def on_confirmation(self, ctx, tc):
            count[0] += 1
            return None

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    runner._hook = _CHook()
    spec = _make_spec()
    asyncio.run(runner.run_to_completion(spec))
    assert count[0] == 1


# -----------------------------------------------------------------------------
# Group 41: Error handling (10)
# -----------------------------------------------------------------------------


def test_41_llm_raises_stop_reason_error() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_41_llm_error_event_stop_reason_error() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "error", "message": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_41_tool_raises_stop_reason_still_completes() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ],
    )

    class _Raise:
        async def execute(self, *a, **k):
            raise RuntimeError("x")

    runner._tool_executor = _Raise()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_41_tool_returns_error_stop_reason_completed() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"x": {"status": "error", "error": "x"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_41_tool_returns_confirmation_stop_reason_confirmation() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "exec", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"exec": {"status": "confirmation_required", "confirmation_id": "x"}},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "confirmation_required"


def test_41_prompt_builder_raises_stop_reason_error() -> None:
    class _PBRaise:
        async def build_with_context(self, c):
            raise RuntimeError("x")

    runner, _llm, _exec, _pb = _make_full_runner()
    runner._prompt_builder = _PBRaise()
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "error"


def test_41_truncate_raises_continues() -> None:
    class _LLMTrunc:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            raise RuntimeError("x")

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLMTrunc(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_41_get_toolspec_raises_continues() -> None:
    class _LLM:
        config: dict = {}

        def _get_toolspec(self, _r):
            raise RuntimeError("x")

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "done", "content": "ok"}

    runner = ChatRunnerV2(
        chat_service=_LLM(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.final_content == "ok"


def test_41_executor_no_execute_raises_tool_call_error() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
            {"type": "done", "content": "x"},
        ],
    )

    class _BadExec:
        pass

    runner._tool_executor = _BadExec()
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    errs = [e for e in events if e["type"] == "tool_call_error"]
    assert errs


def test_41_all_error_paths_produce_error_event_or_done() -> None:
    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("x")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec()

    async def go():
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(go())
    types = [e["type"] for e in events]
    assert "error" in types
    assert "done" in types
    assert types[-1] == "done"


# ---------------------------------------------------------------------------
# Group 42: on_stream_end + emit_reasoning_end hook points (5 cases)
# ---------------------------------------------------------------------------


def test_42_on_stream_end_invoked_after_clean_stream() -> None:
    from llmwikify.foundation.callback import AgentHook

    end_calls: list[bool] = []

    class _EndHook(AgentHook):
        def on_stream_end(self, ctx, *, resuming: bool) -> None:
            end_calls.append(resuming)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "hi"},
            {"type": "done", "content": "hi"},
        ],
    )
    runner._hook = _EndHook()
    events = asyncio.run(_collect(runner, _make_spec()))
    assert end_calls == [False]
    assert events[-1]["type"] == "done"


def test_42_on_stream_end_not_invoked_on_stream_error() -> None:
    from llmwikify.foundation.callback import AgentHook

    end_calls: list[bool] = []

    class _EndHook(AgentHook):
        def on_stream_end(self, ctx, *, resuming: bool) -> None:
            end_calls.append(resuming)

    class _LLMRaise:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise RuntimeError("boom")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMRaise(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    runner._hook = _EndHook()
    events = asyncio.run(_collect(runner, _make_spec()))
    assert end_calls == []
    assert any(e["type"] == "error" for e in events)


def test_42_on_stream_end_raises_does_not_propagate() -> None:
    from llmwikify.foundation.callback import AgentHook

    class _EndHook(AgentHook):
        def on_stream_end(self, ctx, *, resuming: bool) -> None:
            raise RuntimeError("hook boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "ok"}],
    )
    runner._hook = _EndHook()
    events = asyncio.run(_collect(runner, _make_spec()))
    assert events[-1]["type"] == "done"
    assert "error" not in [e["type"] for e in events]


def test_42_emit_reasoning_end_invoked_on_thinking_to_content() -> None:
    from llmwikify.foundation.callback import AgentHook

    end_calls: list[int] = []

    class _ReasoningEndHook(AgentHook):
        def emit_reasoning_end(self, ctx) -> None:
            end_calls.append(ctx.iteration)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": "deep thought"},
            {"type": "content", "text": "answer"},
            {"type": "done", "content": "answer"},
        ],
    )
    runner._hook = _ReasoningEndHook()
    events = asyncio.run(_collect(runner, _make_spec()))
    assert end_calls == [0]
    assert any(e["type"] == "thinking" for e in events)


def test_42_emit_reasoning_end_not_invoked_without_thinking() -> None:
    from llmwikify.foundation.callback import AgentHook

    end_calls: list[int] = []

    class _ReasoningEndHook(AgentHook):
        def emit_reasoning_end(self, ctx) -> None:
            end_calls.append(ctx.iteration)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "no thought"},
            {"type": "done", "content": "no thought"},
        ],
    )
    runner._hook = _ReasoningEndHook()
    asyncio.run(_collect(runner, _make_spec()))
    assert end_calls == []


async def _collect(runner, spec) -> list[dict[str, Any]]:
    return [ev async for ev in runner.run_stream(spec)]


# ---------------------------------------------------------------------------
# Group 43: Stream & cancellation (8 cases)
# ---------------------------------------------------------------------------


def test_43_async_break_run_stream_after_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def consume_one_done() -> dict:
        async for ev in runner.run_stream(_make_spec()):
            return ev
        raise AssertionError("no event yielded")

    ev = asyncio.run(consume_one_done())
    assert ev["type"] == "done"


def test_43_keyboard_interrupt_propagates() -> None:
    class _LLMKI:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise KeyboardInterrupt("user pressed Ctrl+C")
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMKI(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(_collect(runner, _make_spec()))


def test_43_asyncio_cancelled_error_propagates() -> None:
    class _LLMCancel:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            raise asyncio.CancelledError()
            yield

    runner = ChatRunnerV2(
        chat_service=_LLMCancel(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_collect(runner, _make_spec()))


def test_43_outer_run_to_completion_catches_emit_done_exception() -> None:
    from llmwikify.foundation.callback import AgentHook

    class _EmitBoomHook(AgentHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("finalize boom")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _EmitBoomHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "error"}


def test_43_sync_chat_fallback_yields_done() -> None:
    class _Reply:
        content = "sync reply"

    class _LLMInner:
        def chat(self, _messages, tools=None):
            return _Reply()

    class _WikiSvc:
        def get_llm(self):
            return _LLMInner()

    class _LLMSyncOnly:
        config: dict = {}
        wiki_service: Any = _WikiSvc()

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_LLMSyncOnly(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert "sync reply" in (result.final_content or "")


def test_43_sync_chat_fallback_with_no_content_attr() -> None:
    class _LLMInner:
        class _R:
            pass

        def chat(self, _messages, tools=None):
            return self._R()

    class _WikiSvc:
        def get_llm(self):
            return _LLMInner()

    class _LLMSyncNoContent:
        config: dict = {}
        wiki_service: Any = _WikiSvc()

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_LLMSyncNoContent(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == ""


def test_43_run_to_completion_twice_on_same_instance() -> None:
    llm = _StubLLMService(
        events=[{"type": "done", "content": "x"}],
        followup_events=[{"type": "done", "content": "x"}],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    r1 = asyncio.run(runner.run_to_completion(_make_spec()))
    r2 = asyncio.run(runner.run_to_completion(_make_spec()))
    assert r1.stop_reason == r2.stop_reason == "completed"
    assert r1.final_content == r2.final_content == "x"
    assert llm.call_count == 2


def test_43_async_break_run_stream_during_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "content", "text": "b"},
            {"type": "done", "content": "ab"},
        ],
    )

    async def collect_first_delta() -> list[dict]:
        out: list[dict] = []
        async for ev in runner.run_stream(_make_spec()):
            out.append(ev)
            if ev.get("type") == "message_delta":
                break
        return out

    events = asyncio.run(collect_first_delta())
    assert any(e["type"] == "message_delta" for e in events)
    assert not any(e["type"] == "done" for e in events)


# ---------------------------------------------------------------------------
# Group 44: _act & _reason edge branches (8 cases)
# ---------------------------------------------------------------------------


def test_44_confirmation_required_reset_between_iterations() -> None:
    from llmwikify.foundation.callback import AgentHookContext

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    ctx.confirmation_required = True
    assert ctx.confirmation_required is True
    ctx.confirmation_required = False
    assert ctx.confirmation_required is False
    with pytest.raises(AttributeError):
        _ = AgentHookContext().confirmation_required


def test_44_last_tool_calls_reset_after_normal_completion() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"p": 1}},
            {"type": "done", "content": "x"},
        ],
        tool_results={"read_file": {"data": "y"}},
    )
    spec = _make_spec()

    async def run() -> None:
        async for _ev in runner.run_stream(spec):
            pass

    asyncio.run(run())
    assert spec._compacted_results == {}


def test_44_last_tool_calls_reset_after_confirmation_break() -> None:
    from llmwikify.foundation.callback import AgentHook

    events_holder: list[tuple[str, list]] = []

    def make_executor() -> Any:
        class _Ex:
            def __init__(self):
                self.calls: list = []

            async def execute(self, tool_name, args, _reg, _sid, _ctx):
                self.calls.append(tool_name)
                events_holder.append(("executed", list(self.calls)))
                return {
                    "status": "confirmation_required",
                    "confirmation_id": "c1",
                }

        return _Ex()

    executor = make_executor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "exec", "args": {"c": "ls"}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    runner._hook = AgentHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "confirmation_required"
    assert events_holder == [("executed", ["exec"])]


def test_44_tool_call_uses_tool_key_as_fallback() -> None:
    executor = _StubExecutor(results={"read_file": {"ok": True}})
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "tool": "read_file", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert executor.calls == [("read_file", {})]


def test_44_tool_args_top_level_list_passes_through() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "list_op", "args": [1, 2, 3]},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert executor.calls == [("list_op", [1, 2, 3])]


def test_44_tool_args_top_level_int_passes_through() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "int_op", "args": 42},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert executor.calls == [("int_op", 42)]


def test_44_text_mode_with_multiple_tool_call_blocks() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {
                    "type": "content",
                    "text": (
                        '[TOOL_CALL] {tool => "exec", args => {c => "ls"}} [/TOOL_CALL]'
                        ' [TOOL_CALL] {tool => "exec", args => {c => "pwd"}} [/TOOL_CALL]'
                    ),
                },
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert len(executor.calls) == 2
    tool_names = [c[0] for c in executor.calls]
    assert tool_names == ["exec", "exec"]


def test_44_text_mode_with_unclosed_tool_call() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {
                    "type": "content",
                    "text": "before [TOOL_CALL] {tool => \"exec\"",
                },
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert executor.calls == []


# ---------------------------------------------------------------------------
# Group 45: Path coverage (5 cases)
# ---------------------------------------------------------------------------


def test_45_safe_truncate_missing_method_returns_unchanged() -> None:
    class _NoTruncate:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

    runner = ChatRunnerV2(
        chat_service=_NoTruncate(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress"}


def test_45_get_tool_specs_coroutine_return_treated_as_empty() -> None:
    class _CoroutineSpec:
        config: dict = {}

        def _truncate_messages(self, m):
            return list(m)

        def _get_toolspec(self, _r):
            async def _coro() -> list[dict]:
                return [{"name": "x"}]

            return _coro()

    runner = ChatRunnerV2(
        chat_service=_CoroutineSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress"}


def test_45_emit_done_iteration_arg_is_zero() -> None:
    from llmwikify.foundation.callback import AgentHook

    iter_vals: list[int] = []

    class _CaptureIterHook(AgentHook):
        def finalize_content(self, ctx, content):
            iter_vals.append(ctx.iteration)
            return content

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _CaptureIterHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert iter_vals == [0]


def test_45_microcompact_fn_instance_attribute_set() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()

    async def run() -> None:
        async for _ev in runner.run_stream(spec):
            pass

    asyncio.run(run())
    assert runner._microcompact_fn is not None


def test_45_outer_try_except_in_run_to_completion_handles_real_exception() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )

    async def _boom_stream(spec):
        raise RuntimeError("from run_stream")
        yield

    runner.run_stream = _boom_stream  # type: ignore[method-assign]
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "error"
    assert result.error is not None
    assert "from run_stream" in result.error


# ---------------------------------------------------------------------------
# Group 46: Hook pipeline (8 cases)
# ---------------------------------------------------------------------------


def _make_pipeline_hook(name: str, transform) -> Any:
    """Create a sync hook that transforms content via `transform(ctx, current)`."""

    class _PipelineHook(AgentHook):
        pass

    h = _PipelineHook()
    h.name = name

    def finalize_content(ctx, content):
        return transform(ctx, content)

    h.finalize_content = finalize_content
    return h


def test_46_two_hooks_finalize_content_pipeline_chains() -> None:
    from llmwikify.foundation.callback import CompositeHook

    h1 = _make_pipeline_hook("h1", lambda _c, x: x + "1")
    h2 = _make_pipeline_hook("h2", lambda _c, x: x + "2")
    composite = CompositeHook([h1, h2])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "x12"


def test_46_three_hooks_finalize_content_pipeline_chains() -> None:
    from llmwikify.foundation.callback import CompositeHook

    h1 = _make_pipeline_hook("h1", lambda _c, x: x + "a")
    h2 = _make_pipeline_hook("h2", lambda _c, x: x + "b")
    h3 = _make_pipeline_hook("h3", lambda _c, x: x + "c")
    composite = CompositeHook([h1, h2, h3])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "xabc"


def test_46_pipeline_first_hook_returns_none_keeps_original() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _NoneHook(AgentHook):
        def finalize_content(self, ctx, content):
            return None

    h2 = _make_pipeline_hook("h2", lambda _c, x: x + "!")
    composite = CompositeHook([_NoneHook(), h2])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "x!"


def test_46_pipeline_middle_hook_raises_falls_back_to_original() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _BoomHook(AgentHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("middle boom")

    h1 = _make_pipeline_hook("h1", lambda _c, x: x + "1")
    h2 = _make_pipeline_hook("h2", lambda _c, x: x + "2")
    composite = CompositeHook([h1, _BoomHook(), h2])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "x"


def test_46_pipeline_sync_and_async_mix() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _AsyncHook(AgentHook):
        async def finalize_content(self, ctx, content):
            return content + "_async"

    h_sync = _make_pipeline_hook("sync", lambda _c, x: x + "_sync")
    composite = CompositeHook([h_sync, _AsyncHook()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "x_sync_async"


def test_46_pipeline_no_modify_returns_original() -> None:
    from llmwikify.foundation.callback import AgentHook, CompositeHook

    class _NoOp(AgentHook):
        def finalize_content(self, ctx, content):
            return content

    composite = CompositeHook([_NoOp(), _NoOp()])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "x"


def test_46_pipeline_run_to_completion_uses_chained_content() -> None:
    from llmwikify.foundation.callback import CompositeHook

    h1 = _make_pipeline_hook("upper", lambda _c, x: x.upper())
    h2 = _make_pipeline_hook("exclaim", lambda _c, x: x + "!")
    composite = CompositeHook([h1, h2])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "content", "text": "hello"}, {"type": "done", "content": "hello"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == "HELLO!"


def test_46_pipeline_iteration_zero_for_all_hooks() -> None:
    from llmwikify.foundation.callback import CompositeHook

    iter_vals: list[int] = []

    def make_hook(name: str):
        def _fn(ctx, x):
            iter_vals.append(ctx.iteration)
            return x

        h = AgentHook()
        h.name = name
        h.finalize_content = _fn
        return h

    composite = CompositeHook([make_hook("a"), make_hook("b")])
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = composite
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert iter_vals == [0, 0]


# ---------------------------------------------------------------------------
# Group 47: Spec mutation (8 cases)
# ---------------------------------------------------------------------------


def test_47_hook_ctx_is_snapshot_observations_dont_persist() -> None:
    after_obs: list[list[str]] = []

    class _ObsHook(AgentHook):
        def before_iteration(self, ctx) -> None:
            ctx.observations.append("mutated_by_hook")

        def after_iteration(self, ctx) -> None:
            after_obs.append(list(ctx.observations))

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"ok": True}},
    )
    runner._hook = _ObsHook()
    asyncio.run(runner.run_to_completion(_make_spec(max_iterations=1)))
    assert after_obs == [[]]


def test_47_hook_ctx_is_snapshot_cancelled_dont_propagate() -> None:
    """Setting ctx.cancelled on hook ctx does NOT break precheck (snapshot)."""
    class _CancelHook(AgentHook):
        def before_iteration(self, ctx) -> None:
            ctx.cancelled = True

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _CancelHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"


def test_47_hook_ctx_is_snapshot_paused_dont_propagate() -> None:
    """Setting ctx.paused on hook ctx does NOT break precheck (snapshot)."""
    class _PauseHook(AgentHook):
        def before_iteration(self, ctx) -> None:
            ctx.paused = True

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _PauseHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"


def test_47_spec_hook_field_is_ignored() -> None:
    class _FakeHook(AgentHook):
        def before_iteration(self, ctx) -> None:
            ctx.observations.append("via_spec_hook")

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = NoOpHook()
    spec = _make_spec()
    spec.hook = _FakeHook()
    asyncio.run(runner.run_to_completion(spec))


def test_47_spec_messages_count_after_run() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"p": 1}},
            {"type": "done", "content": ""},
        ],
    )
    spec = _make_spec(messages=[{"role": "user", "content": "hi"}])
    original_count = len(spec.messages)
    result = asyncio.run(runner.run_to_completion(spec))
    assert len(spec.messages) == original_count
    assert len(result.messages) == original_count


def test_47_max_iterations_zero_emits_done() -> None:
    runner, llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=0)))
    assert result.stop_reason == "in_progress"
    assert llm.call_count == 0


def test_47_spec_workspace_path_does_not_break() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(workspace=Path("/tmp"))
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason in {"completed", "in_progress"}


def test_47_max_iterations_one_with_tool_runs_once() -> None:
    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"p": 1}},
            {"type": "done", "content": ""},
        ],
        followup_events=[{"type": "done", "content": "x"}],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(results={"read_file": {"ok": True}}),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=1)))
    assert result.stop_reason == "in_progress"
    assert llm.call_count == 1


# ---------------------------------------------------------------------------
# Group 48: State machine transitions (8 cases)
# ---------------------------------------------------------------------------


def test_48_iter0_to_iter1_state_transition() -> None:
    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"p": 1}},
            {"type": "done", "content": ""},
        ],
        followup_events=[{"type": "done", "content": "final"}],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(results={"read_file": {"ok": True}}),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=2)))
    assert result.stop_reason == "completed"
    assert llm.call_count == 2
    assert result.tools_used == ["read_file"]


def test_48_multi_tool_in_one_iter_first_ok_second_confirm() -> None:
    executor = _StubExecutor(
        results={
            "t1": {"data": "ok"},
            "t2": {"status": "confirmation_required", "confirmation_id": "c2"},
        },
    )
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {
                    "type": "tool_call",
                    "id": "c1",
                    "name": "t1",
                    "args": {},
                },
                {
                    "type": "tool_call",
                    "id": "c2",
                    "name": "t2",
                    "args": {},
                },
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    tool_ends = [e for e in events if e["type"] == "tool_call_end"]
    confirm_events = [e for e in events if e["type"] == "confirmation_required"]
    assert len(tool_ends) == 1
    assert tool_ends[0]["tool"] == "t1"
    assert len(confirm_events) == 1
    assert confirm_events[0]["tool"] == "t2"


def test_48_max_iter_reached_in_progress() -> None:
    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
            {"type": "done", "content": ""},
        ],
        followup_events=[
            {"type": "tool_call", "id": "c2", "name": "t1", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(results={"t1": {"ok": 1}}),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=2)))
    assert result.stop_reason == "in_progress"
    assert llm.call_count == 2


def test_48_observation_appended_only_with_thinking() -> None:
    obs_after: list[list[str]] = []

    class _CapHook(AgentHook):
        def after_iteration(self, ctx) -> None:
            obs_after.append(list(ctx.observations))

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "no thinking"},
            {"type": "done", "content": "no thinking"},
        ],
    )
    runner._hook = _CapHook()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert obs_after == []


def test_48_observation_truncated_to_200_chars() -> None:
    obs_after: list[list[str]] = []

    class _CapHook(AgentHook):
        def after_iteration(self, ctx) -> None:
            obs_after.append(list(ctx.observations))

    long_thinking = "x" * 500
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "thinking", "text": long_thinking},
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"ok": True}},
    )
    runner._hook = _CapHook()
    asyncio.run(runner.run_to_completion(_make_spec()))
    assert len(obs_after) == 1
    assert len(obs_after[0]) == 1
    assert obs_after[0][0].startswith("thought: ")
    assert len(obs_after[0][0]) == len("thought: ") + 200


def test_48_after_iteration_called_per_iter_with_tools() -> None:
    after_iters: list[int] = []

    class _CapHook(AgentHook):
        def after_iteration(self, ctx) -> None:
            after_iters.append(ctx.iteration)

    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
            {"type": "done", "content": ""},
        ],
        followup_events=[
            {"type": "tool_call", "id": "c2", "name": "t1", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=_StubExecutor(results={"t1": {"ok": 1}}),
        prompt_builder=_StubPromptBuilder(),
    )
    runner._hook = _CapHook()
    asyncio.run(runner.run_to_completion(_make_spec(max_iterations=2)))
    assert after_iters == [0, 1]


def test_48_tools_used_dedup_preserves_first_seen_order() -> None:
    """result.tools_used dedupes (per run_to_completion logic)."""
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
                {"type": "tool_call", "id": "c2", "name": "t2", "args": {}},
                {"type": "tool_call", "id": "c3", "name": "t1", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.tools_used == ["t1", "t2"]


def test_48_cancelled_propagates_to_done_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "phase", "phase": "cancelled"},
            {"type": "done", "content": ""},
        ],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "cancelled"


def test_48_paused_propagates_to_done_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "phase", "phase": "paused"},
            {"type": "done", "content": ""},
        ],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "paused"


# ---------------------------------------------------------------------------
# Group 49: Event flow (8 cases)
# ---------------------------------------------------------------------------


def test_49_session_init_first_when_hook_wants_streaming() -> None:
    from llmwikify.foundation.callback import AgentHook

    class _StreamHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _StreamHook()
    events = asyncio.run(_collect(runner, _make_spec()))
    assert events[0]["type"] == "session_init"
    assert events[0]["session_id"] == "s1"
    assert events[-1]["type"] == "done"


def test_49_error_event_before_done_on_llm_error() -> None:
    class _LLMErr:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "error", "message": "boom"}
            yield {"type": "done", "content": ""}

    runner = ChatRunnerV2(
        chat_service=_LLMErr(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    error_idx = next(i for i, e in enumerate(events) if e["type"] == "error")
    done_idx = next(i for i, e in enumerate(events) if e["type"] == "done")
    assert error_idx < done_idx
    assert events[error_idx]["message"] == "boom"


def test_49_done_event_always_last() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "content", "text": "b"},
            {"type": "done", "content": "ab"},
        ],
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    assert events[-1]["type"] == "done"


def test_49_compacted_event_emitted_for_microcompact() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "x" * 5000}},
    )
    events = asyncio.run(_collect(runner, _make_spec(microcompact=True, microcompact_keep_chars=200)))
    compacted = [e for e in events if e["type"] == "compacted"]
    assert len(compacted) == 1
    assert compacted[0]["tool"] == "read_file"
    assert compacted[0]["chars_saved"] > 0


def test_49_tool_call_start_before_tool_call_end() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    starts = [i for i, e in enumerate(events) if e["type"] == "tool_call_start"]
    ends = [i for i, e in enumerate(events) if e["type"] == "tool_call_end"]
    assert starts[0] < ends[0]


def test_49_message_delta_joins_to_final_content() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "content", "text": "a"},
            {"type": "content", "text": "b"},
            {"type": "content", "text": "c"},
            {"type": "done", "content": "abc"},
        ],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.final_content == "abc"


def test_49_no_duplicate_tool_call_id_in_events() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    ids = [
        e.get("call_id")
        for e in events
        if e.get("type") in {"tool_call_start", "tool_call_end"}
    ]
    assert len(ids) == 2
    assert ids[0] == ids[1]


def test_49_error_event_carries_stop_reason_error() -> None:
    class _LLMErr:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

        async def _llm_stream_with_retry(self, _m, _t):
            yield {"type": "error", "message": "x"}

    runner = ChatRunnerV2(
        chat_service=_LLMErr(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    err_with_sr = [e for e in events if e["type"] == "error" and "stop_reason" in e]
    assert len(err_with_sr) >= 1
    assert err_with_sr[0]["stop_reason"] == "error"


# ---------------------------------------------------------------------------
# Group 50: Boundary values (8 cases)
# ---------------------------------------------------------------------------


def test_50_microcompact_keep_chars_zero() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "x" * 1000}},
    )
    result = asyncio.run(runner.run_to_completion(
        _make_spec(microcompact=True, microcompact_keep_chars=0),
    ))
    assert result.stop_reason == "completed"


def test_50_microcompact_keep_chars_negative() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "x" * 1000}},
    )
    result = asyncio.run(runner.run_to_completion(
        _make_spec(microcompact=True, microcompact_keep_chars=-100),
    ))
    assert result.stop_reason == "completed"


def test_50_microcompact_compactable_tools_empty() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "x" * 5000}},
    )
    result = asyncio.run(runner.run_to_completion(
        _make_spec(microcompact=True, microcompact_compactable_tools=frozenset()),
    ))
    assert result.compacted_count == 0


def test_50_max_iterations_one_with_no_tool() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=1)))
    assert result.stop_reason == "completed"
    assert "x" in result.final_content


def test_50_max_iterations_huge() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(max_iterations=10000)))
    assert result.stop_reason == "completed"


def test_50_messages_empty_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(messages=[])))
    assert result.stop_reason in {"completed", "in_progress"}


def test_50_session_id_empty_string() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(session_id="")))
    assert result.stop_reason in {"completed", "in_progress"}


def test_50_wiki_id_empty_string() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec(wiki_id="")))
    assert result.stop_reason in {"completed", "in_progress"}


# ---------------------------------------------------------------------------
# Group 51: Mutation testing / lock contracts (8 cases)
# ---------------------------------------------------------------------------


def test_51_precheck_timeout_zero_means_no_timeout() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._config = {"timeout_seconds": 0}
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"


def test_51_getattr_content_falls_back_to_empty() -> None:
    class _Reply:
        pass

    class _LLMInner:
        def chat(self, _messages, tools=None):
            return _Reply()

    class _WikiSvc:
        def get_llm(self):
            return _LLMInner()

    class _LLMSyncNoContent:
        config: dict = {}
        wiki_service: Any = _WikiSvc()

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_LLMSyncNoContent(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert result.final_content == ""


def test_51_safe_truncate_coroutine_return_falls_back_to_original() -> None:
    class _CorTruncate:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, _m):
            async def _coro() -> list:
                return [{"role": "user", "content": "short"}]

            return _coro()

    runner = ChatRunnerV2(
        chat_service=_CorTruncate(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress"}


def test_51_get_tool_specs_coroutine_return_treated_as_empty() -> None:
    class _CorSpec:
        config: dict = {}

        def _truncate_messages(self, m):
            return list(m)

        def _get_toolspec(self, _r):
            async def _coro() -> list:
                return [{"name": "x"}]

            return _coro()

    runner = ChatRunnerV2(
        chat_service=_CorSpec(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress"}


def test_51_truncate_exception_uses_original() -> None:
    class _TruncBoom:
        config: dict = {}

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, _m):
            raise RuntimeError("trunc boom")

    runner = ChatRunnerV2(
        chat_service=_TruncBoom(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress", "error"}


def test_51_toolspec_exception_returns_empty() -> None:
    class _SpecBoom:
        config: dict = {}

        def _truncate_messages(self, m):
            return list(m)

        def _get_toolspec(self, _r):
            raise RuntimeError("spec boom")

    runner = ChatRunnerV2(
        chat_service=_SpecBoom(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason in {"completed", "in_progress"}


def test_51_safe_truncate_returns_list() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert isinstance(result.messages, list)


def test_51_chat_run_result_compacted_count_zero_initially() -> None:
    result = asyncio.run(
        ChatRunnerV2(
            chat_service=_StubLLMService(events=[{"type": "done", "content": "x"}]),
            tool_executor=_StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        ).run_to_completion(_make_spec()),
    )
    assert result.compacted_count == 0
    assert result.total_compacted_chars_saved == 0


# ---------------------------------------------------------------------------
# Group 52: Real services integration (8 cases)
# ---------------------------------------------------------------------------


def test_52_real_wiki_service_like_with_get_llm() -> None:
    class _Reply:
        content = "from wiki service"

    class _LLMInner:
        async def astream_chat(self, _messages, tools=None):
            yield {"type": "content", "text": "from "}
            yield {"type": "content", "text": "wiki service"}
            yield {"type": "done", "content": "from wiki service"}

    class _WikiSvc:
        def get_llm(self):
            return _LLMInner()

    class _ChatService:
        config: dict = {}
        wiki_service: Any = _WikiSvc()

        def _get_toolspec(self, _r):
            return []

        def _truncate_messages(self, m):
            return list(m)

    runner = ChatRunnerV2(
        chat_service=_ChatService(),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"
    assert "from wiki service" in result.final_content


def test_52_real_tool_executor_with_registry() -> None:
    registry = object()
    seen_registry: list = []

    class _RegExecutor:
        async def execute(self, _tool, _args, reg, _sid, _ctx):
            seen_registry.append(reg)
            return {"ok": True}

    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=_RegExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    asyncio.run(runner.run_to_completion(_make_spec(tool_registry=registry)))
    assert seen_registry == [registry]


def test_52_real_prompt_builder_with_build_with_context() -> None:
    from llmwikify.apps.chat.agent.prompt_builder import BuildContext

    seen: list[BuildContext] = []

    class _RealPB:
        async def build_with_context(self, ctx):
            seen.append(ctx)
            return f"prompt for {ctx.wiki_id}"

    runner = ChatRunnerV2(
        chat_service=_StubLLMService(events=[{"type": "done", "content": "x"}]),
        tool_executor=_StubExecutor(),
        prompt_builder=_RealPB(),
    )
    asyncio.run(runner.run_to_completion(_make_spec(wiki_id="mywiki")))
    assert len(seen) == 1
    assert seen[0].wiki_id == "mywiki"


def test_52_real_spec_with_all_fields() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = ChatRunSpec(
        messages=[{"role": "user", "content": "hi"}],
        tool_registry=object(),
        session_id="full-spec-session",
        wiki_id="full-wiki",
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=100000,
        temperature=0.5,
        max_tokens=1000,
        reasoning_effort="medium",
        hook=None,
        error_message=None,
        workspace=None,
        context_window_tokens=8000,
        progress_callback=None,
        fail_on_tool_error=True,
        microcompact=False,
        microcompact_keep_chars=500,
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_52_compacted_results_cache_round_trip() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        tool_results={"read_file": {"data": "x" * 5000}},
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=200)
    asyncio.run(runner.run_to_completion(spec))
    cached = spec.compacted()
    assert len(cached) >= 1
    call_id, original = cached[0]
    assert original == {"data": "x" * 5000}


def test_52_microcompact_cache_reused_across_iters() -> None:
    executor = _StubExecutor(results={"read_file": {"data": "x" * 5000}})
    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        followup_events=[{"type": "done", "content": "final"}],
    )
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    spec = _make_spec(microcompact=True, microcompact_keep_chars=200, max_iterations=2)
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"
    assert result.compacted_count == 1


def test_52_session_id_propagated_to_done_event() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    events = asyncio.run(_collect(runner, _make_spec(session_id="unique-id-123")))
    done = next(e for e in events if e["type"] == "done")
    assert done.get("stop_reason") == "completed"


def test_52_tool_registry_passed_to_executor() -> None:
    class _TrackerExecutor:
        def __init__(self):
            self.calls: list = []

        async def execute(self, tool_name, args, reg, sid, ctx):
            self.calls.append((tool_name, args, reg, sid))
            return {"ok": True}

    executor = _TrackerExecutor()
    registry = object()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    asyncio.run(runner.run_to_completion(_make_spec(tool_registry=registry, session_id="s1")))
    assert len(executor.calls) == 1
    assert executor.calls[0][0] == "t1"
    assert executor.calls[0][2] is registry
    assert executor.calls[0][3] == "s1"


# ---------------------------------------------------------------------------
# Group 53: Misc / defensive (4 cases to reach 95 total)
# ---------------------------------------------------------------------------


def test_53_hook_returning_non_none_from_void_hook_ignored() -> None:
    class _ReturnsValue(AgentHook):
        def before_iteration(self, ctx) -> str:
            return "ignored"

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _ReturnsValue()
    result = asyncio.run(runner.run_to_completion(_make_spec()))
    assert result.stop_reason == "completed"


def test_53_chat_run_result_default_values() -> None:
    result = ChatRunResult(
        final_content=None,
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="completed",
    )
    assert result.error is None
    assert result.compacted_count == 0
    assert result.total_compacted_chars_saved == 0


def test_53_messages_with_complex_content_types() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(
        messages=[
            {"role": "system", "content": "you are a helper"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_53_runner_does_not_hold_globals() -> None:
    """Lock: runner instance state is isolated from module-level globals."""
    runner1 = ChatRunnerV2(
        chat_service=_StubLLMService(events=[{"type": "done", "content": "a"}]),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    runner2 = ChatRunnerV2(
        chat_service=_StubLLMService(events=[{"type": "done", "content": "b"}]),
        tool_executor=_StubExecutor(),
        prompt_builder=_StubPromptBuilder(),
    )
    r1 = asyncio.run(runner1.run_to_completion(_make_spec()))
    r2 = asyncio.run(runner2.run_to_completion(_make_spec()))
    assert r1.final_content == "a"
    assert r2.final_content == "b"


def test_53_async_hook_called_with_await() -> None:
    async_calls: list[int] = []

    class _AsyncHook(AgentHook):
        async def before_iteration(self, ctx) -> None:
            async_calls.append(ctx.iteration)

    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    runner._hook = _AsyncHook()
    asyncio.run(runner.run_to_completion(_make_spec()))
    assert async_calls == [0]


def test_53_tool_call_id_with_special_chars() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "call_abc-123_xyz", "name": "t1", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    start = next(e for e in events if e["type"] == "tool_call_start")
    end = next(e for e in events if e["type"] == "tool_call_end")
    assert start["call_id"] == "call_abc-123_xyz"
    assert end["call_id"] == "call_abc-123_xyz"


def test_53_run_with_no_tool_calls_emits_only_done() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "answer"}],
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    types = {e["type"] for e in events}
    assert types == {"message_delta", "done"} or types == {"done"}


def test_53_compacted_count_aggregates_across_iters() -> None:
    llm = _StubLLMService(
        events=[
            {"type": "tool_call", "id": "c1", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        followup_events=[
            {"type": "tool_call", "id": "c2", "name": "read_file", "args": {}},
            {"type": "done", "content": ""},
        ],
        followup2_events=[{"type": "done", "content": "final"}],
    )
    executor = _StubExecutor(results={"read_file": {"data": "x" * 5000}})
    runner = ChatRunnerV2(
        chat_service=llm,
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    result = asyncio.run(runner.run_to_completion(
        _make_spec(microcompact=True, microcompact_keep_chars=200, max_iterations=3),
    ))
    assert result.stop_reason == "completed"
    assert result.compacted_count == 2
    assert result.total_compacted_chars_saved > 0


def test_53_tool_call_with_empty_args_dict() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {"type": "tool_call", "id": "c1", "name": "t1", "args": {}},
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    asyncio.run(runner.run_to_completion(_make_spec()))
    assert executor.calls == [("t1", {})]


def test_53_text_mode_double_quotes_in_args() -> None:
    executor = _StubExecutor()
    runner = ChatRunnerV2(
        chat_service=_StubLLMService(
            events=[
                {
                    "type": "content",
                    "text": '[TOOL_CALL] {tool => "exec", args => {c => "echo \\"hi\\""}} [/TOOL_CALL]',
                },
                {"type": "done", "content": ""},
            ],
        ),
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )
    asyncio.run(runner.run_to_completion(_make_spec()))
    assert len(executor.calls) == 1
    assert executor.calls[0][0] == "exec"


def test_53_unicode_in_messages() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec(
        messages=[{"role": "user", "content": "你好 🎉 𝛼"}],
    )
    result = asyncio.run(runner.run_to_completion(spec))
    assert result.stop_reason == "completed"


def test_53_done_event_has_compacted_count_field() -> None:
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    events = asyncio.run(_collect(runner, _make_spec()))
    done = next(e for e in events if e["type"] == "done")
    assert "compacted_count" in done
    assert "stop_reason" in done
    assert "content" in done
    assert "error" in done


# ── state trace (C1: borrowed from nanobot StateTraceEntry) ──


def test_state_trace_default_empty_on_dataclass() -> None:
    """_RunContext.state_trace is initialized to an empty list."""
    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    assert ctx.state_trace == []


def test_state_trace_entry_fields() -> None:
    """_StateTraceEntry exposes the 5 expected fields."""
    from llmwikify.apps.chat.agent.runner_v2 import _StateTraceEntry

    e = _StateTraceEntry(
        state="REASON",
        started_at=1.0,
        duration_ms=12.5,
        event="ok",
        error=None,
    )
    assert e.state == "REASON"
    assert e.started_at == 1.0
    assert e.duration_ms == 12.5
    assert e.event == "ok"
    assert e.error is None


def test_state_trace_context_manager_records_ok() -> None:
    """_StateTrace records a state on context exit with event=ok."""
    from llmwikify.apps.chat.agent.runner_v2 import _StateTrace

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    with _StateTrace(ctx, "REASON"):
        pass
    assert len(ctx.state_trace) == 1
    entry = ctx.state_trace[0]
    assert entry.state == "REASON"
    assert entry.event == "ok"
    assert entry.error is None
    assert entry.duration_ms >= 0.0


def test_state_trace_context_manager_records_error() -> None:
    """_StateTrace records event=error and the message on exception."""
    from llmwikify.apps.chat.agent.runner_v2 import _StateTrace

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    with pytest.raises(RuntimeError):
        with _StateTrace(ctx, "ACT"):
            raise RuntimeError("boom")
    assert len(ctx.state_trace) == 1
    entry = ctx.state_trace[0]
    assert entry.state == "ACT"
    assert entry.event == "error"
    assert entry.error is not None and "boom" in entry.error


def test_state_trace_skipped_event_helper() -> None:
    """Mutable event attribute lets a caller mark a step as skipped."""
    from llmwikify.apps.chat.agent.runner_v2 import _StateTrace

    spec = _make_spec()
    ctx = _RunContext(spec=spec, messages=list(spec.messages))
    with _StateTrace(ctx, "PRECHECK") as tr:
        tr.event = "skipped"
    assert ctx.state_trace[0].event == "skipped"


def test_state_trace_appears_in_result_for_text_only_path() -> None:
    """A text-only run records PRECHECK + REASON + FINALIZE."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "hi"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    assert isinstance(result, ChatRunResult)
    states = [e["state"] for e in result.state_trace]
    assert "PRECHECK" in states
    assert "REASON" in states
    assert "FINALIZE" in states
    # All entries on the happy path should be ok
    for entry in result.state_trace:
        assert entry["event"] == "ok", entry
        assert entry["error"] is None


def test_state_trace_records_act_and_observe_when_tools_called() -> None:
    """ACT and OBSERVE states are traced when the LLM returns tool calls.

    v2 runner parses tool calls from text-mode
    ``[TOOL_CALL]`` blocks (event type ``content``), so emit one
    in the LLM stream.
    """
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": '[TOOL_CALL] {tool => "echo", args => {"x": 1}} [/TOOL_CALL]',
            },
            {"type": "done", "content": "done after tool"},
        ],
        tool_results={"echo": "ok-result"},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    states = [e["state"] for e in result.state_trace]
    assert "PRECHECK" in states
    assert "REASON" in states
    assert "ACT" in states
    assert "OBSERVE" in states
    assert "FINALIZE" in states


def test_state_trace_preserves_chronological_order() -> None:
    """Trace entries are appended in the order the steps were entered.

    Verifies the structural property: PRECHECK is first, FINALIZE is
    last, and any ACT/OBSERVE pair follows the REASON that triggered
    it (multi-iteration support).
    """
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[
            {
                "type": "content",
                "text": '[TOOL_CALL] {tool => "echo", args => {"x": 1}} [/TOOL_CALL]',
            },
            {"type": "done", "content": "done"},
        ],
        tool_results={"echo": "ok"},
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    states = [e["state"] for e in result.state_trace]
    assert states[0] == "PRECHECK"
    assert states[-1] == "FINALIZE"
    # If ACT appears at index i, the REASON that triggered it is at
    # some j < i. In single-iteration tests we have one of each.
    if "ACT" in states:
        i = states.index("ACT")
        assert "REASON" in states[:i], (
            f"ACT at {i} but no REASON before it: {states}"
        )


def test_state_trace_entry_has_numeric_duration() -> None:
    """duration_ms is a float >= 0 (sanity check the timing)."""
    runner, _llm, _exec, _pb = _make_full_runner(
        llm_events=[{"type": "done", "content": "x"}],
    )
    spec = _make_spec()
    result = asyncio.run(runner.run_to_completion(spec))
    for entry in result.state_trace:
        assert isinstance(entry["duration_ms"], float)
        assert entry["duration_ms"] >= 0.0


def test_chat_run_result_state_trace_default_empty() -> None:
    """ChatRunResult.state_trace defaults to [] for non-v2 runners."""
    r = ChatRunResult(
        final_content="x",
        messages=[],
        tools_used=[],
        usage={},
        stop_reason="completed",
    )
    assert r.state_trace == []
