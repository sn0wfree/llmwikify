"""Tests for unified/steps/ — 15 个预置 Steps 逐个测试。"""
from __future__ import annotations

import pytest

from llmwikify.apps.chat.agent.unified.core import StepResult
from llmwikify.apps.chat.agent.unified.spec import ActResult, ReasonResponse
from llmwikify.apps.chat.agent.unified.steps import (
    BuildFeedbackStep,
    CheckEmptyStep,
    CheckFieldStep,
    CheckSuccessStep,
    CheckToolCallsStep,
    CodeExecResult,
    ExtractCodeStep,
    ExtractJSONStep,
    MapStep,
    TruncateStep,
    ValidateSyntaxStep,
    WrapStep,
)

# ── ExtractCodeStep ───────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_code_step_with_fence():
    step = ExtractCodeStep()
    text = '```python\ndef compute_factor(df):\n    return pl.col("close")\n```'
    result = await step.handle(text, None, None)
    assert result.success is True
    assert "def compute_factor" in result.output


@pytest.mark.asyncio
async def test_extract_code_step_no_fence():
    step = ExtractCodeStep()
    result = await step.handle("no code here", None, None)
    assert result.success is False
    assert "no ```python```" in result.error


@pytest.mark.asyncio
async def test_extract_code_step_fallback_def():
    step = ExtractCodeStep()
    text = 'def compute_factor(df):\n    return pl.col("close")'
    result = await step.handle(text, None, None)
    assert result.success is True
    assert result.output.startswith("def compute_factor")


# ── ValidateSyntaxStep ────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_syntax_step_ok():
    step = ValidateSyntaxStep()
    result = await step.handle("x = 1\n", None, None)
    assert result.success is True
    assert result.output == "x = 1\n"


@pytest.mark.asyncio
async def test_validate_syntax_step_fail():
    step = ValidateSyntaxStep()
    result = await step.handle("def foo(\n", None, None)
    assert result.success is False
    assert "SyntaxError" in result.error


# ── CheckFieldStep ────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_field_step_match():
    step = CheckFieldStep(field="success", equals=True, stop_reason="success")
    result = await step.handle(ActResult(success=True), None, None)
    assert result.success is True
    assert result.output == (True, "success")


@pytest.mark.asyncio
async def test_check_field_step_no_match():
    step = CheckFieldStep(field="success", equals=True)
    result = await step.handle(ActResult(success=False), None, None)
    assert result.success is True
    assert result.output == (False, "")


# ── CheckEmptyStep ────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_empty_step_empty():
    step = CheckEmptyStep(field="tool_calls", stop_reason="no_tool_calls")
    result = await step.handle(ReasonResponse(tool_calls=[]), None, None)
    assert result.output == (True, "no_tool_calls")


@pytest.mark.asyncio
async def test_check_empty_step_nonempty():
    step = CheckEmptyStep(field="tool_calls")
    rr = ReasonResponse(tool_calls=[{"name": "test"}])
    result = await step.handle(rr, None, None)
    assert result.output == (False, "")


# ── CheckToolCallsStep ────────────────────────────────────


@pytest.mark.asyncio
async def test_check_tool_calls_step_empty():
    step = CheckToolCallsStep()
    result = await step.handle(ReasonResponse(tool_calls=[]), None, None)
    assert result.output == (True, "no_tool_calls")


@pytest.mark.asyncio
async def test_check_tool_calls_step_nonempty():
    step = CheckToolCallsStep()
    result = await step.handle(ReasonResponse(tool_calls=[{"name": "x"}]), None, None)
    assert result.output == (False, "")


# ── CheckSuccessStep ──────────────────────────────────────


@pytest.mark.asyncio
async def test_check_success_step_true():
    step = CheckSuccessStep()
    result = await step.handle(ActResult(success=True), None, None)
    assert result.output == (True, "success")


@pytest.mark.asyncio
async def test_check_success_step_false():
    step = CheckSuccessStep()
    result = await step.handle(ActResult(success=False), None, None)
    assert result.output == (False, "")


# ── MapStep ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_map_step():
    step = MapStep(lambda x: x * 3)
    result = await step.handle(7, None, None)
    assert result.success is True
    assert result.output == 21


@pytest.mark.asyncio
async def test_map_step_error():
    step = MapStep(lambda x: 1 / 0)
    result = await step.handle(7, None, None)
    assert result.success is False
    assert "division by zero" in result.error


# ── WrapStep ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrap_step():
    step = WrapStep(ReasonResponse, code=lambda x: x, raw_content=lambda x: "prefix")
    result = await step.handle("test_code", None, None)
    assert result.success is True
    assert isinstance(result.output, ReasonResponse)
    assert result.output.code == "test_code"
    assert result.output.raw_content == "prefix"


# ── TruncateStep ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_truncate_step_short():
    step = TruncateStep(max_len=100)
    result = await step.handle("short text", None, None)
    assert result.output == "short text"


@pytest.mark.asyncio
async def test_truncate_step_long():
    step = TruncateStep(max_len=10)
    result = await step.handle("a" * 100, None, None)
    assert len(result.output) < 100
    assert "truncated" in result.output


# ── BuildFeedbackStep ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_feedback_step_success():
    step = BuildFeedbackStep()
    result = await step.handle(CodeExecResult(success=True), None, None)
    assert result.success is True
    assert result.output is None


@pytest.mark.asyncio
async def test_build_feedback_step_failure():
    step = BuildFeedbackStep()
    cr = CodeExecResult(success=False, code="bad code", error="SyntaxError", error_kind="syntax_error")
    result = await step.handle(cr, None, None)
    assert result.success is True
    assert isinstance(result.output, dict)
    assert result.output["role"] == "user"
    assert "SyntaxError" in result.output["content"]
    assert "bad code" in result.output["content"]
