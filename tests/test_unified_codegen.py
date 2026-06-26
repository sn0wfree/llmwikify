"""Tests for unified/pipelines/codegen.py — CodegenReasoner + CodeActor。"""
from __future__ import annotations

import pytest

from llmwikify.apps.chat.agent.unified.core import StepResult
from llmwikify.apps.chat.agent.unified.pipelines.codegen import CodeActor, CodegenReasoner
from llmwikify.apps.chat.agent.unified.spec import ActResult, CodegenSpec, ReasonResponse


# ── Mock LLM ──────────────────────────────────────────────


class _ScriptedLLM:
    """LLM that returns pre-scripted responses."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[tuple] = []

    def chat(self, *, messages, temperature=0.3, **kwargs):
        self.calls.append((messages, kwargs))
        if not self._responses:
            raise AssertionError("LLM called more times than scripted")
        return self._responses.pop(0)


# ── CodegenReasoner ───────────────────────────────────────


@pytest.mark.asyncio
async def test_codegen_reasoner_extracts_code():
    llm = _ScriptedLLM(
        '```python\ndef compute_factor(df):\n    return pl.col("close")\n```'
    )
    reasoner = CodegenReasoner(llm_client=llm)
    spec = CodegenSpec(messages=[{"role": "user", "content": "test"}])
    result = await reasoner.handle(spec.messages, spec, None)
    assert result.success is True
    response = result.output
    assert isinstance(response, ReasonResponse)
    assert response.code is not None
    assert "def compute_factor" in response.code
    assert response.is_valid is True


@pytest.mark.asyncio
async def test_codegen_reasoner_no_code():
    llm = _ScriptedLLM("no code here at all")
    reasoner = CodegenReasoner(llm_client=llm)
    spec = CodegenSpec(messages=[{"role": "user", "content": "test"}])
    result = await reasoner.handle(spec.messages, spec, None)
    assert result.success is True  # StepResult itself succeeds
    response = result.output
    assert response.is_valid is False
    assert response.error is not None


# ── CodeActor ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_code_actor_no_code():
    actor = CodeActor()
    response = ReasonResponse(code=None)
    result = await actor.handle(response, None, None)
    assert result.success is True
    act = result.output
    assert isinstance(act, ActResult)
    assert act.success is False
    assert act.error_kind == "extract_failed"
    assert len(act.messages_to_inject) == 1
    assert act.messages_to_inject[0]["role"] == "user"


@pytest.mark.asyncio
async def test_code_actor_syntax_error():
    actor = CodeActor()
    response = ReasonResponse(code="def foo(\n")
    spec = CodegenSpec(messages=[], df=None)
    result = await actor.handle(response, spec, None)
    assert result.success is True
    act = result.output
    assert act.success is False
    assert "SyntaxError" in (act.error or "") or "pipeline_error" in (act.error_kind or "")
    assert len(act.messages_to_inject) == 1


@pytest.mark.asyncio
async def test_code_actor_success():
    """Test with a valid compute_factor that returns a Series."""
    import polars as pl

    code = '''
def compute_factor(df):
    return df.select(pl.col("close")).to_series()
'''
    actor = CodeActor()
    response = ReasonResponse(code=code)

    # Create a small test DataFrame
    df = pl.DataFrame({
        "date": [20240101, 20240102, 20240103],
        "code": ["A", "A", "A"],
        "close": [10.0, 11.0, 12.0],
        "open": [9.0, 10.0, 11.0],
        "high": [11.0, 12.0, 13.0],
        "low": [9.0, 10.0, 11.0],
        "volume": [1000.0, 1100.0, 1200.0],
        "returns": [0.0, 0.1, 0.09],
        "vwap": [10.0, 11.0, 12.0],
    })
    spec = CodegenSpec(messages=[], df=df)
    result = await actor.handle(response, spec, None)
    assert result.success is True
    act = result.output
    assert act.success is True
    assert act.output is not None  # pl.Series
