"""Tests for foundation/callback: AgentHook, CompositeHook, integrations.

Mirrors the 10-case matrix from docs/poc/phase-a-steps.md §2.6 plus
two extras covering async and streaming-or behaviour.
"""
from __future__ import annotations

from typing import Any

import pytest

from llmwikify.foundation.callback import (
    AgentHook,
    AgentHookContext,
    CompositeHook,
    NoOpHook,
)
from llmwikify.foundation.callback.integrations import (
    AutoIngestHook,
    DreamSyncHook,
    WikiHook,
)


class _RecorderHook(AgentHook):
    def __init__(self, name: str = "rec", fail_on: str | None = None) -> None:
        super().__init__()
        self.name = name
        self.calls: list[tuple[str, ...]] = []
        self.fail_on = fail_on

    def before_iteration(self, ctx: AgentHookContext) -> None:
        self.calls.append(("before_iteration",))
        if self.fail_on == "before_iteration":
            raise RuntimeError("boom")

    def on_stream(self, ctx: AgentHookContext, delta: str) -> None:
        self.calls.append(("on_stream", delta))

    def after_iteration(self, ctx: AgentHookContext) -> None:
        self.calls.append(("after_iteration",))

    def finalize_content(self, ctx: AgentHookContext, content: str | None) -> str | None:
        self.calls.append(("finalize_content", content or ""))
        return (content or "") + "!"


class _AsyncHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def before_iteration(self, ctx: AgentHookContext) -> None:
        self.calls.append("async_before_iteration")


def _make_tool_call(name: str = "wiki_write_page") -> Any:
    tc = type("TC", (), {})()
    tc.name = name
    tc.id = "tc_1"
    return tc


def _make_result(success: bool = True) -> Any:
    r = type("R", (), {})()
    r.success = success
    return r


async def test_noop_hook_via_composite() -> None:
    hook = NoOpHook()
    composite = CompositeHook([hook])
    ctx = AgentHookContext()
    await composite.before_iteration(ctx)
    await composite.on_stream(ctx, "delta")
    await composite.after_iteration(ctx)
    assert await composite.finalize_content(ctx, "x") == "x"
    assert composite.wants_streaming() is False


async def test_composite_fan_out_invokes_every_hook() -> None:
    a = _RecorderHook("a")
    b = _RecorderHook("b")
    composite = CompositeHook([a, b])
    await composite.before_iteration(AgentHookContext())
    assert [c[0] for c in a.calls] == ["before_iteration"]
    assert [c[0] for c in b.calls] == ["before_iteration"]


async def test_single_hook_failure_does_not_break_fanout() -> None:
    bad = _RecorderHook("bad", fail_on="before_iteration")
    good = _RecorderHook("good")
    composite = CompositeHook([bad, good])
    await composite.before_iteration(AgentHookContext())
    assert good.calls == [("before_iteration",)]


async def test_fan_out_order_is_fifo() -> None:
    seen: list[str] = []
    hooks = [_RecorderHook(f"h{i}") for i in range(5)]
    for h in hooks:
        original = h.before_iteration

        def make_record(hook_name: str, original_fn: Any) -> Any:
            def wrapper(ctx: AgentHookContext) -> None:
                seen.append(hook_name)
                original_fn(ctx)
            return wrapper

        h.before_iteration = make_record(h.name, original)
    composite = CompositeHook(hooks)
    await composite.before_iteration(AgentHookContext())
    assert seen == ["h0", "h1", "h2", "h3", "h4"]


async def test_hook_context_mutations_visible_across_hooks() -> None:
    class Writer(AgentHook):
        def __init__(self, name: str, key: str) -> None:
            super().__init__()
            self.name = name
            self.key = key

        def before_iteration(self, ctx: AgentHookContext) -> None:
            ctx.usage[self.key] = 42

    class Reader(AgentHook):
        def __init__(self, name: str, key: str, sink: dict[str, int]) -> None:
            super().__init__()
            self.name = name
            self.key = key
            self.sink = sink

        def before_iteration(self, ctx: AgentHookContext) -> None:
            self.sink[self.key] = ctx.usage.get(self.key, -1)

    sink: dict[str, int] = {}
    composite = CompositeHook([Writer("w", "tokens"), Reader("r", "tokens", sink)])
    await composite.before_iteration(AgentHookContext())
    assert sink == {"tokens": 42}


def test_integration_hooks_instantiate() -> None:
    wiki = type("W", (), {"append_log": lambda self, *a, **k: None})()
    dream = type("D", (), {"run_dream": lambda self: None})()

    WikiHook(wiki)
    DreamSyncHook(dream_editor=dream)
    DreamSyncHook(dream_editor=None)
    AutoIngestHook(wiki)


async def test_wiki_hook_logs_only_on_wiki_tools() -> None:
    log_calls: list[tuple[str, str]] = []

    class FakeWiki:
        def append_log(self, who: str, msg: str) -> None:
            log_calls.append((who, msg))

    wiki = FakeWiki()
    hook = WikiHook(wiki)
    composite = CompositeHook([hook])
    ctx = AgentHookContext()
    await composite.after_tool_executed(ctx, _make_tool_call("wiki_write_page"), _make_result(success=True))
    await composite.after_tool_executed(ctx, _make_tool_call("wiki_ingest"), _make_result(success=True))
    await composite.after_tool_executed(ctx, _make_tool_call("read_file"), _make_result(success=True))
    await composite.after_tool_executed(ctx, _make_tool_call("wiki_write_page"), _make_result(success=False))

    assert log_calls == [
        ("agent", "Tool wiki_write_page executed successfully"),
        ("agent", "Tool wiki_ingest executed successfully"),
    ]


async def test_dream_sync_flag() -> None:
    hook = DreamSyncHook(dream_editor=None)
    composite = CompositeHook([hook])
    ctx = AgentHookContext()
    await composite.after_tool_executed(ctx, _make_tool_call("wiki_synthesize"), _make_result(success=True))
    assert hook.pending_dream is True
    assert hook.check_and_run_dream() is False


def test_add_remove_clear_registry() -> None:
    composite = CompositeHook()
    a = _RecorderHook("a")
    b = _RecorderHook("b")
    composite.add(a)
    composite.add(b)
    assert len(composite) == 2
    composite.remove("a")
    assert len(composite) == 1
    assert composite._hooks == [b]
    composite.clear()
    assert len(composite) == 0


async def test_finalize_content_is_pipeline() -> None:
    a = _RecorderHook("a")
    b = _RecorderHook("b")
    composite = CompositeHook([a, b])
    result = await composite.finalize_content(AgentHookContext(), "hello")
    assert result == "hello!!"
    assert [c[0] for c in a.calls] == ["finalize_content"]
    assert [c[0] for c in b.calls] == ["finalize_content"]


async def test_finalize_content_propagates_exception() -> None:
    class Boom(AgentHook):
        name = "boom"

        def finalize_content(self, ctx: AgentHookContext, content: str | None) -> str | None:
            raise RuntimeError("pipeline must surface")

    composite = CompositeHook([Boom()])
    with pytest.raises(RuntimeError, match="pipeline must surface"):
        await composite.finalize_content(AgentHookContext(), "x")


async def test_async_hook_is_awaited() -> None:
    async_hook = _AsyncHook()
    composite = CompositeHook([async_hook])
    await composite.before_iteration(AgentHookContext())
    assert async_hook.calls == ["async_before_iteration"]


def test_wants_streaming_or_over_hooks() -> None:
    class Streamer(AgentHook):
        name = "streamer"

        def wants_streaming(self) -> bool:
            return True

    composite = CompositeHook([NoOpHook(), NoOpHook()])
    assert composite.wants_streaming() is False
    composite.add(Streamer())
    assert composite.wants_streaming() is True
