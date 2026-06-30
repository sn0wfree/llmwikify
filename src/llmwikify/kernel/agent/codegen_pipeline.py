"""Codegen pipeline — 高层 codegen 策略.

- CodegenReasoner(Pipeline): LLMCallStep(sync) + ExtractCodeStep → ReasonResponse
- CodeActor(StepHandler): ValidateAndExecuteStep + BuildFeedbackStep → ActResult
- generate_factor_code(): 便利函数，一步完成 codegen
- generate_factor_code_sync(): 同步版本（run_101_alphas.py 等使用）

历史: 从 apps/chat/agent/unified/pipelines/codegen.py 搬迁。
"""
from __future__ import annotations

import asyncio
from typing import Any

from ._core_types import Pipeline, StepHandler, StepResult
from .spec import (
    ActResult,
    CodegenSpec,
    ReasonResponse,
    UnifiedResult,
)
from .steps import (
    BuildFeedbackStep,
    CodeExecResult,
    ExtractCodeStep,
    LLMCallStep,
    ValidateAndExecuteStep,
)


class CodegenReasoner(Pipeline):
    """Codegen REASON: LLMCallStep(sync) + ExtractCodeStep → ReasonResponse。

    流程: messages → LLM raw text → extract code → ReasonResponse

    构造时依赖: llm_client（可选，不传则自动构建）
    """

    def __init__(self, llm_client: Any = None) -> None:
        if llm_client is None:
            from llmwikify.foundation.llm.client import build_llm_client
            llm_client = build_llm_client()
        super().__init__(LLMCallStep(llm_client), ExtractCodeStep())

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        # 首轮：从 spec 构建初始 messages（system + user prompt）
        messages = input if input else []
        if not messages and ctx is not None and hasattr(ctx, "messages"):
            messages = ctx.messages
        if not messages and hasattr(spec, "factor_name") and spec.factor_name:
            user_prompt = f"""Factor: {spec.factor_name}
Formula (pseudo-code): {spec.formula_brief}

Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series` that computes
this factor. Use QuantNodes operators (rank, ts_argmax, rolling_std, etc.) which are
in the namespace, and use polars expressions otherwise.

Output ONLY the code block (use FUNCTION FORM for QuantNodes operators)."""
            messages = [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            if ctx is not None and hasattr(ctx, "messages"):
                ctx.messages = messages

        # Pipeline: messages → LLM text → code
        pipeline_result = await super().handle(messages, spec, ctx)
        if not pipeline_result.success:
            return StepResult.ok(ReasonResponse(
                error=pipeline_result.error,
                is_valid=False,
            ))

        # 追加 assistant 消息到历史（供下轮 feedback 用）
        if pipeline_result.output and ctx is not None and hasattr(ctx, "messages"):
            ctx.messages.append({"role": "assistant", "content": pipeline_result.output})

        return StepResult.ok(ReasonResponse(
            code=pipeline_result.output,
            is_valid=pipeline_result.output is not None,
        ))


class CodeActor(StepHandler):
    """Codegen ACT: ValidateAndExecuteStep + BuildFeedbackStep。

    流程: ReasonResponse.code → validate + execute → ActResult
    失败时: 构建 OBSERVE_FEEDBACK_TEMPLATE → messages_to_inject
    """

    def __init__(self) -> None:
        self._executor = ValidateAndExecuteStep()
        self._feedback = BuildFeedbackStep()

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        response = input  # ReasonResponse

        # 没有代码 → extract_failed
        if response.code is None:
            feedback_result = await self._feedback.handle(
                CodeExecResult(success=False, error="no code", error_kind="extract_failed"),
                spec, ctx,
            )
            return StepResult.ok(ActResult(
                success=False,
                error="no code",
                error_kind="extract_failed",
                messages_to_inject=[feedback_result.output] if feedback_result.output else [],
            ))

        # 验证 + 执行
        exec_result = await self._executor.handle(response.code, spec, ctx)
        code_result = exec_result.output  # CodeExecResult

        if not exec_result.success:
            # Pipeline 内部 step 失败（语法/安全检查）
            feedback_result = await self._feedback.handle(
                CodeExecResult(
                    success=False,
                    code=response.code,
                    error=exec_result.error,
                    error_kind="pipeline_error",
                ),
                spec, ctx,
            )
            return StepResult.ok(ActResult(
                success=False,
                error=exec_result.error,
                error_kind="pipeline_error",
                code=response.code,
                messages_to_inject=[feedback_result.output] if feedback_result.output else [],
            ))

        # 执行成功
        if code_result.success:
            return StepResult.ok(ActResult(
                success=True,
                output=code_result.series,
                code=code_result.code,
            ))

        # 执行失败 → 构建 feedback
        feedback_result = await self._feedback.handle(code_result, spec, ctx)
        return StepResult.ok(ActResult(
            success=False,
            error=code_result.error,
            error_kind=code_result.error_kind,
            code=code_result.code,
            messages_to_inject=[feedback_result.output] if feedback_result.output else [],
        ))


# ─── 便利函数 ──────────────────────────────────────────────


async def generate_factor_code(
    factor_name: str,
    formula_brief: str,
    df: Any,
    *,
    llm_client: Any = None,
    system_prompt: str = "",
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
    max_iterations: int = 0,
    hook: Any = None,
) -> UnifiedResult:
    """一步完成 codegen：构建 spec + loop → run_to_completion。

    替代旧 ``react_engine.compile_to_code_react`` + ``llm_code.generate_factor_code``。

    Args:
        factor_name: 因子名（如 "alpha-001"）
        formula_brief: 自然语言公式描述
        df: polars DataFrame（长格式）
        llm_client: LLM 客户端（None 则自动构建）
        system_prompt: 系统提示词（空则用 SYSTEM_PROMPT_CODE）
        max_repair_rounds: 最大修复轮数（默认 3）
        temperature: LLM 温度
        max_iterations: Loop 最大迭代数（0 = max_repair_rounds + 1）
        hook: UnifiedHook 子类（可选，用于 progress_callback 等）

    Returns:
        UnifiedResult（含 .code, .factor_series, .error, .to_dict()）
    """
    from llmwikify.kernel.codegen import SYSTEM_PROMPT_CODE

    from .loop import UnifiedAgentLoop

    if not system_prompt:
        system_prompt = SYSTEM_PROMPT_CODE
    if max_iterations <= 0:
        max_iterations = max_repair_rounds + 1

    spec = CodegenSpec(
        messages=[],
        df=df,
        factor_name=factor_name,
        formula_brief=formula_brief,
        max_repair_rounds=max_repair_rounds,
        system_prompt=system_prompt,
        temperature=temperature,
        max_iterations=max_iterations,
    )

    reasoner = CodegenReasoner(llm_client)
    actor = CodeActor()

    from .steps.checks import CheckSuccessStep
    loop = UnifiedAgentLoop(
        reasoner=reasoner,
        actor=actor,
        deciders={"after_act": CheckSuccessStep()},
        hook=hook,
    )

    return await loop.run_to_completion(spec)


def generate_factor_code_sync(
    factor_name: str,
    formula_brief: str,
    df: Any,
    **kwargs: Any,
) -> UnifiedResult:
    """同步版 generate_factor_code（内部 asyncio.run）。

    用于 run_101_alphas.py 等同步脚本。
    """
    return asyncio.run(generate_factor_code(factor_name, formula_brief, df, **kwargs))
