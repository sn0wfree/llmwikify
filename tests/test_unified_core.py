"""Tests for unified/core.py — StepResult, Pipeline, UnifiedContext, UnifiedHook."""
from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.agent.unified.core import (
    Pipeline,
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedContext,
    UnifiedHook,
    _maybe_await,
)
from llmwikify.apps.chat.agent.unified.spec import BaseSpec


# ── StepResult ────────────────────────────────────────────


def test_step_result_ok_defaults():
    r = StepResult.ok()
    assert r.success is True
    assert r.output is None
    assert r.events == []
    assert r.error is None


def test_step_result_ok_with_output():
    r = StepResult.ok("hello", [{"type": "delta"}])
    assert r.success is True
    assert r.output == "hello"
    assert r.events == [{"type": "delta"}]


def test_step_result_fail():
    r = StepResult.fail("bad input")
    assert r.success is False
    assert r.error == "bad input"
    assert r.output is None


def test_step_result_fail_with_events():
    r = StepResult.fail("err", [{"type": "error"}])
    assert r.events == [{"type": "error"}]


# ── Pipeline ──────────────────────────────────────────────


class _DoubleStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.ok(input * 2)


class _AddTenStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.ok(input + 10)


class _FailStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.fail("intentional fail")


class _EmitEventStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.ok(input, events=[{"type": "custom", "value": input}])


@pytest.mark.asyncio
async def test_pipeline_pass_through():
    pipeline = Pipeline(_DoubleStep(), _AddTenStep())
    result = await pipeline.handle(5, None, None)
    assert result.success is True
    assert result.output == 20  # (5*2) + 10


@pytest.mark.asyncio
async def test_pipeline_fail_fast():
    pipeline = Pipeline(_DoubleStep(), _FailStep(), _AddTenStep())
    result = await pipeline.handle(5, None, None)
    assert result.success is False
    assert result.error == "intentional fail"


@pytest.mark.asyncio
async def test_pipeline_events_accumulate():
    pipeline = Pipeline(_EmitEventStep(), _EmitEventStep())
    result = await pipeline.handle(3, None, None)
    assert result.success is True
    assert len(result.events) == 2
    # First step gets input=3, emits event with value=3, output=3
    # Second step gets input=3, emits event with value=3, output=3
    assert result.events[0]["value"] == 3
    assert result.events[1]["value"] == 3


# ── UnifiedContext ────────────────────────────────────────


def test_unified_context_init():
    spec = BaseSpec(messages=[{"role": "user", "content": "hi"}])
    ctx = UnifiedContext(spec=spec)
    assert ctx.messages == [{"role": "user", "content": "hi"}]
    assert ctx.iteration == 0
    assert ctx.start_time > 0


def test_unified_context_elapsed():
    spec = BaseSpec(messages=[])
    ctx = UnifiedContext(spec=spec)
    assert ctx.elapsed_sec >= 0


def test_unified_context_tools_none():
    spec = BaseSpec(messages=[])
    ctx = UnifiedContext(spec=spec)
    assert ctx.tools is None


# ── UnifiedHook ───────────────────────────────────────────


def test_unified_hook_defaults():
    hook = UnifiedHook()
    assert hook.wants_streaming() is False
    assert hook.before_iteration(UnifiedContext(spec=BaseSpec(messages=[]))) is None
    assert hook.finalize(UnifiedContext(spec=BaseSpec(messages=[])), "content") == "content"


# ── _maybe_await ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_await_sync():
    result = await _maybe_await(lambda x: x * 2, 5)
    assert result == 10


@pytest.mark.asyncio
async def test_maybe_await_async():
    async def double(x):
        return x * 2
    result = await _maybe_await(double, 5)
    assert result == 10
