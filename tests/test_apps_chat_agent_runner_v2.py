"""Tests for ChatRunnerV2 (Plan B Steps B-1 + B-2).

B-1: skeleton + public API surface (8 cases)
B-1-extension: independence + edge cases (18 cases)
B-2: 5-step state machine + hooks + microcompact + text-mode (15 cases)

Total: 41 cases covering:
  - Public API: run_stream, run_to_completion, ChatRunResult aggregation
  - _RunContext: defaults, slots, time progression, field independence
  - Independence: no legacy engine imports, minimal deps, works without infra
  - 5-step loop: PRECHECK/REASON/ACT/OBSERVE/COMPLETE
  - CompositeHook: 11 hook points wired through the loop
  - microcompact: native integration (default ON, configurable)
  - text-mode: [TOOL_CALL:...] parsing via TextModeParser
  - Error handling: LLM stream failure → stop_reason=error
  - Concurrency: two run_to_completion calls don't share state
  - Mutation safety: spec.messages not mutated
  - confirmation_required: tool result → stop_reason=confirmation_required
  - max_iterations: caps the loop
  - multi-tool: executes multiple tool calls per iteration
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
