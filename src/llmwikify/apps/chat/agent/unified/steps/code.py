"""代码执行相关 Steps。

- ExtractCodeStep: 从 LLM 响应提取 Python 代码
- ValidateSyntaxStep: Python 语法检查
- ValidateSafetyStep: CodeSandbox 安全检查
- ExecuteCodeStep: 执行 compute_factor 代码
- ValidateAndExecuteStep: 完整验证+执行流水线
- CodeExecResult: 代码执行结果
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from llmwikify.apps.chat.agent.unified.core import Pipeline, StepHandler, StepResult

logger = logging.getLogger(__name__)


@dataclass
class CodeExecResult:
    """代码执行结果 — CodeActor 和 CodegenReasoner 共用。"""

    success: bool
    code: str = ""
    series: Any = None  # pl.Series
    error: str | None = None
    error_kind: str = "none"


class ExtractCodeStep(StepHandler):
    """从 LLM 响应提取 Python 代码。

    输入: text (str)
    输出: code (str) — 失败时返回 fail
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.quant.codegen import extract_python

        text = input
        code = extract_python(text)
        if code is None:
            return StepResult.fail("no ```python``` fence found")
        return StepResult.ok(code)


class ValidateSyntaxStep(StepHandler):
    """Python 语法检查。

    输入: code (str)
    输出: code (str) — 通过时原样返回
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.quant.codegen import validate_syntax

        code = input
        ok, err = validate_syntax(code)
        if not ok:
            return StepResult.fail(f"SyntaxError: {err}")
        return StepResult.ok(code)


class ValidateSafetyStep(StepHandler):
    """CodeSandbox 安全检查。

    输入: code (str)
    输出: code (str) — 通过时原样返回
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.quant.codegen import validate_safety

        code = input
        ok, err = validate_safety(code)
        if not ok:
            return StepResult.fail(f"SafetyError: {err}")
        return StepResult.ok(code)


class ExecuteCodeStep(StepHandler):
    """执行 compute_factor 代码。

    输入: code (str)
    输出: CodeExecResult

    从 spec 取 df (CodegenSpec.df)。
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.quant.codegen import execute_code

        code = input
        df = getattr(spec, "df", None)

        try:
            series = execute_code(code, df)
        except Exception as exc:
            import traceback
            return StepResult.ok(CodeExecResult(
                success=False,
                code=code,
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                error_kind="execute_error",
            ))

        import polars as pl
        if not isinstance(series, pl.Series):
            return StepResult.ok(CodeExecResult(
                success=False,
                code=code,
                error=f"expected pl.Series, got {type(series).__name__}",
                error_kind="output_invalid",
            ))

        return StepResult.ok(CodeExecResult(
            success=True,
            code=code,
            series=series,
        ))


class ValidateAndExecuteStep(Pipeline):
    """代码验证+执行流水线。

    输入: code (str)
    输出: CodeExecResult

    流程: ValidateSyntaxStep → ValidateSafetyStep → ExecuteCodeStep
    """

    def __init__(self) -> None:
        super().__init__(
            ValidateSyntaxStep(),
            ValidateSafetyStep(),
            ExecuteCodeStep(),
        )
