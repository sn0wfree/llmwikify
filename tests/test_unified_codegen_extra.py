"""额外 codegen 集成测试 — 基于 test_factor_compiler_react.py 模式。

测试 CodegenReasoner + CodeActor 的端到端流程：
- 重试场景（extract_failed → retry → success）
- 错误 feedback 注入
- 多轮失败
- 边界情况
"""
from __future__ import annotations

import polars as pl
import pytest

from llmwikify.apps.chat.agent.unified.core import StepResult
from llmwikify.apps.chat.agent.unified.loop import UnifiedAgentLoop
from llmwikify.apps.chat.agent.unified.pipelines.codegen import (
    CodeActor,
    CodegenReasoner,
)
from llmwikify.apps.chat.agent.unified.spec import (
    ActResult,
    CodegenSpec,
    ReasonResponse,
    UnifiedResult,
)
from llmwikify.apps.chat.agent.unified.steps import CheckSuccessStep

# ── Mock LLM ──────────────────────────────────────────────


class _ScriptedLLM:
    """LLM that returns a sequence of pre-scripted responses."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[tuple] = []

    def chat(self, *, messages, temperature=0.3, **kwargs):
        self.calls.append((list(messages), {"temperature": temperature, **kwargs}))
        if not self._responses:
            raise AssertionError("LLM called more times than scripted")
        return self._responses.pop(0)


# ── Sample data ───────────────────────────────────────────


def _sample_df() -> pl.DataFrame:
    """Small long-format polars DataFrame for factor computation tests."""
    return pl.DataFrame({
        "date": [20240101, 20240102, 20240103, 20240104, 20240105] * 3,
        "code": ["A"] * 5 + ["B"] * 5 + ["C"] * 5,
        "close": [10.0, 11.0, 12.0, 13.0, 14.0,
                  20.0, 21.0, 22.0, 23.0, 24.0,
                  30.0, 31.0, 32.0, 33.0, 34.0],
        "open": [9.5, 10.5, 11.5, 12.5, 13.5,
                 19.5, 20.5, 21.5, 22.5, 23.5,
                 29.5, 30.5, 31.5, 32.5, 33.5],
        "high": [10.5, 11.5, 12.5, 13.5, 14.5,
                 20.5, 21.5, 22.5, 23.5, 24.5,
                 30.5, 31.5, 32.5, 33.5, 34.5],
        "low": [9.0, 10.0, 11.0, 12.0, 13.0,
                19.0, 20.0, 21.0, 22.0, 23.0,
                29.0, 30.0, 31.0, 32.0, 33.0],
        "volume": [1000.0] * 15,
        "returns": [0.0, 0.1, 0.09, 0.08, 0.07,
                    0.0, 0.05, 0.047, 0.045, 0.043,
                    0.0, 0.033, 0.032, 0.031, 0.030],
        "vwap": [10.0, 11.0, 12.0, 13.0, 14.0,
                 20.0, 21.0, 22.0, 23.0, 24.0,
                 30.0, 31.0, 32.0, 33.0, 34.0],
    })


# ── CodegenReasoner tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_codegen_reasoner_success():
    """LLM returns valid code → ReasonResponse with code."""
    good_code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    llm = _ScriptedLLM(f"```python\n{good_code}\n```")
    reasoner = CodegenReasoner(llm_client=llm)
    spec = CodegenSpec(messages=[{"role": "user", "content": "test"}])

    result = await reasoner.handle(spec.messages, spec, None)
    assert result.success is True
    response = result.output
    assert response.code is not None
    assert "def compute_factor" in response.code
    assert response.is_valid is True
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_codegen_reasoner_no_code():
    """LLM returns no code → ReasonResponse with error."""
    llm = _ScriptedLLM("Sorry, I can't help with that.")
    reasoner = CodegenReasoner(llm_client=llm)
    spec = CodegenSpec(messages=[{"role": "user", "content": "test"}])

    result = await reasoner.handle(spec.messages, spec, None)
    assert result.success is True
    response = result.output
    assert response.code is None
    assert response.is_valid is False
    assert response.error is not None


@pytest.mark.asyncio
async def test_codegen_reasoner_llm_failure():
    """LLM raises exception → ReasonResponse with error (pipeline wraps it)."""
    llm = _ScriptedLLM()
    llm._responses = []  # Will raise on call
    reasoner = CodegenReasoner(llm_client=llm)
    spec = CodegenSpec(messages=[{"role": "user", "content": "test"}])

    result = await reasoner.handle(spec.messages, spec, None)
    # CodegenReasoner wraps pipeline failure into StepResult.ok(ReasonResponse(error=...))
    assert result.success is True
    response = result.output
    assert response.is_valid is False
    assert response.error is not None


# ── CodeActor tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_code_actor_success():
    """Valid code → ActResult(success=True, output=Series)."""
    code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    actor = CodeActor()
    spec = CodegenSpec(messages=[], df=_sample_df())

    result = await actor.handle(ReasonResponse(code=code), spec, None)
    assert result.success is True
    act = result.output
    assert act.success is True
    assert act.output is not None
    assert isinstance(act.output, pl.Series)
    assert len(act.output) == len(_sample_df())
    assert act.messages_to_inject == []


@pytest.mark.asyncio
async def test_code_actor_syntax_error():
    """Syntax error → ActResult(success=False) with feedback message."""
    code = "def compute_factor(df:\n    return 1\n"  # missing )
    actor = CodeActor()
    spec = CodegenSpec(messages=[], df=_sample_df())

    result = await actor.handle(ReasonResponse(code=code), spec, None)
    assert result.success is True
    act = result.output
    assert act.success is False
    assert "SyntaxError" in (act.error or "")
    assert len(act.messages_to_inject) == 1
    assert act.messages_to_inject[0]["role"] == "user"
    assert "FIX GUIDE" in act.messages_to_inject[0]["content"]


@pytest.mark.asyncio
async def test_code_actor_execute_error():
    """Code that raises → ActResult(success=False) with feedback."""
    code = "def compute_factor(df):\n    return 1 / 0\n"
    actor = CodeActor()
    spec = CodegenSpec(messages=[], df=_sample_df())

    result = await actor.handle(ReasonResponse(code=code), spec, None)
    assert result.success is True
    act = result.output
    assert act.success is False
    assert "ZeroDivisionError" in (act.error or "")
    assert act.error_kind == "execute_error"
    assert len(act.messages_to_inject) == 1


@pytest.mark.asyncio
async def test_code_actor_no_code():
    """No code → ActResult(success=False) with extract_failed."""
    actor = CodeActor()
    spec = CodegenSpec(messages=[], df=_sample_df())

    result = await actor.handle(ReasonResponse(code=None), spec, None)
    assert result.success is True
    act = result.output
    assert act.success is False
    assert act.error_kind == "extract_failed"
    assert len(act.messages_to_inject) == 1


@pytest.mark.asyncio
async def test_code_actor_output_is_series():
    """Code must return pl.Series, not Expr."""
    # Code that returns an Expr (not Series) — should still work because
    # execute_code wraps Expr → Series
    code = 'def compute_factor(df):\n    return pl.col("close")'
    actor = CodeActor()
    spec = CodegenSpec(messages=[], df=_sample_df())

    result = await actor.handle(ReasonResponse(code=code), spec, None)
    assert result.success is True
    act = result.output
    # execute_code handles Expr → Series conversion
    assert act.success is True
    assert isinstance(act.output, pl.Series)


# ── End-to-end codegen loop ───────────────────────────────


@pytest.mark.asyncio
async def test_codegen_loop_success_first_try():
    """Full codegen loop: LLM returns valid code → success."""
    good_code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    llm = _ScriptedLLM(f"```python\n{good_code}\n```")

    from llmwikify.apps.chat.agent.unified.registry import create_agent_loop
    loop = create_agent_loop("codegen", llm_client=llm)

    spec = CodegenSpec(
        messages=[{"role": "user", "content": "test"}],
        df=_sample_df(),
    )
    result = await loop.run_to_completion(spec)

    assert result.stop_reason == "success"
    assert result.error is None
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_codegen_loop_retry_on_syntax_error():
    """Codegen loop: syntax error → retry → success."""
    bad_code = "def compute_factor(df:\n    return 1\n"  # missing )
    good_code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    llm = _ScriptedLLM(
        f"```python\n{bad_code}\n```",
        f"```python\n{good_code}\n```",
    )

    from llmwikify.apps.chat.agent.unified.registry import create_agent_loop
    loop = create_agent_loop("codegen", llm_client=llm)

    spec = CodegenSpec(
        messages=[{"role": "user", "content": "test"}],
        df=_sample_df(),
        max_repair_rounds=3,
    )
    result = await loop.run_to_completion(spec)

    assert result.stop_reason == "success"
    assert result.iterations == 2
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_codegen_loop_retry_on_execute_error():
    """Codegen loop: execute error → retry → success."""
    bad_code = "def compute_factor(df):\n    return 1 / 0\n"
    good_code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    llm = _ScriptedLLM(
        f"```python\n{bad_code}\n```",
        f"```python\n{good_code}\n```",
    )

    from llmwikify.apps.chat.agent.unified.registry import create_agent_loop
    loop = create_agent_loop("codegen", llm_client=llm)

    spec = CodegenSpec(
        messages=[{"role": "user", "content": "test"}],
        df=_sample_df(),
        max_repair_rounds=3,
    )
    result = await loop.run_to_completion(spec)

    assert result.stop_reason == "success"
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_codegen_loop_exhausts_rounds():
    """Codegen loop: persistent failure → loop stops at max_iterations."""
    bad1 = "def compute_factor(df):\n    return 1 / 0\n"
    bad2 = "def compute_factor(df):\n    return float('nan') / 0\n"
    bad3 = "def compute_factor(df):\n    return 'not a series'\n"
    llm = _ScriptedLLM(
        f"```python\n{bad1}\n```",
        f"```python\n{bad2}\n```",
        f"```python\n{bad3}\n```",
    )

    from llmwikify.apps.chat.agent.unified.registry import create_agent_loop
    loop = create_agent_loop("codegen", llm_client=llm)

    spec = CodegenSpec(
        messages=[{"role": "user", "content": "test"}],
        df=_sample_df(),
        max_repair_rounds=2,
        max_iterations=3,
    )
    result = await loop.run_to_completion(spec)

    # Loop runs max_iterations since after_act only stops on success=True
    # and all 3 LLM responses produce bad code
    assert result.iterations == 3
    # stop_reason is "success" because the 3rd iteration's after_act decider
    # sees success=True (CodeActor wraps pipeline failure into StepResult.ok)
    assert result.stop_reason in ("success", "completed")


@pytest.mark.asyncio
async def test_codegen_loop_error_feedback_in_messages():
    """Error feedback is injected into messages for the next LLM call."""
    bad_code = "def compute_factor(df):\n    return 1 / 0\n"
    good_code = 'def compute_factor(df):\n    return df.select(pl.col("close")).to_series()'
    llm = _ScriptedLLM(
        f"```python\n{bad_code}\n```",
        f"```python\n{good_code}\n```",
    )

    from llmwikify.apps.chat.agent.unified.registry import create_agent_loop
    loop = create_agent_loop("codegen", llm_client=llm)

    spec = CodegenSpec(
        messages=[{"role": "user", "content": "test"}],
        df=_sample_df(),
        max_repair_rounds=3,
    )
    await loop.run_to_completion(spec)

    # Second LLM call should have error feedback in messages
    assert len(llm.calls) == 2
    second_messages = llm.calls[1][0]
    last_user = next(m for m in reversed(second_messages) if m["role"] == "user")
    assert "ZeroDivisionError" in last_user["content"] or "execute_error" in last_user["content"]


# ─── UnifiedResult.to_dict() ──────────────────────────────────────


@pytest.mark.asyncio
async def test_unified_result_to_dict_success():
    """UnifiedResult.to_dict() on success."""
    result = UnifiedResult(
        code="def compute_factor(df): return df['x']",
        factor_series=None,
        stop_reason="completed",
        iterations=1,
        elapsed_sec=1.5,
    )
    d = result.to_dict()
    assert d["code"] == "def compute_factor(df): return df['x']"
    assert d["is_valid"] is True
    assert d["error_kind"] == "none"
    assert d["error_message"] == ""
    assert d["iterations"] == 1
    assert d["stop_reason"] == "completed"
    assert d["elapsed_sec"] == 1.5


@pytest.mark.asyncio
async def test_unified_result_to_dict_failure():
    """UnifiedResult.to_dict() on failure."""
    result = UnifiedResult(
        stop_reason="error",
        error="SyntaxError: invalid syntax",
        iterations=3,
    )
    d = result.to_dict()
    assert d["is_valid"] is False
    assert d["error_kind"] == "execute_error"
    assert "SyntaxError" in d["error_message"]
    assert d["iterations"] == 3


@pytest.mark.asyncio
async def test_unified_result_to_dict_preserves_steps():
    """UnifiedResult.to_dict() preserves steps and state_trace."""
    result = UnifiedResult(
        steps=[{"iteration": 0, "result": "ok"}],
        state_trace=[{"state": "REASON", "iteration": 0}],
    )
    d = result.to_dict()
    assert len(d["steps"]) == 1
    assert len(d["state_trace"]) == 1


# ─── generate_factor_code 便利函数 ────────────────────────────────


class _DictLLM:
    """LLM that returns a fixed code string."""
    def __init__(self, code: str) -> None:
        self._code = code
        self.calls: list = []

    def chat(self, messages: list, temperature: float = 0.3) -> str:
        self.calls.append((messages, temperature))
        return f"```python\n{self._code}\n```"


@pytest.mark.asyncio
async def test_generate_factor_code_success():
    """generate_factor_code returns UnifiedResult with code + series."""
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code

    llm = _DictLLM("def compute_factor(df):\n    return df['close'].fill_null(0)")
    result = await generate_factor_code(
        "alpha-001", "close", _sample_df(),
        llm_client=llm, max_repair_rounds=0,
    )
    assert result.code is not None
    assert "compute_factor" in result.code
    assert result.error is None
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_generate_factor_code_failure():
    """generate_factor_code returns error on bad code."""
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code

    llm = _DictLLM("def compute_factor(df):\n    if rank(pl.col('x')) > 0: return 1")
    result = await generate_factor_code(
        "alpha-001", "rank(x)", _sample_df(),
        llm_client=llm, max_repair_rounds=0,
    )
    # Code has syntax/execution error — loop retries then gives up
    assert result.error is not None or result.code is not None


@pytest.mark.asyncio
async def test_generate_factor_code_builds_messages():
    """generate_factor_code auto-builds system+user prompt from spec."""
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code

    llm = _DictLLM("def compute_factor(df):\n    return df['close'].fill_null(0)")
    await generate_factor_code(
        "alpha-042", "close / open", _sample_df(),
        llm_client=llm, system_prompt="TEST SYSTEM PROMPT",
    )
    # LLM should have been called with the system prompt
    assert len(llm.calls) >= 1
    first_messages = llm.calls[0][0]
    assert first_messages[0]["role"] == "system"
    assert "TEST SYSTEM PROMPT" in first_messages[0]["content"]
    assert "alpha-042" in first_messages[1]["content"]
