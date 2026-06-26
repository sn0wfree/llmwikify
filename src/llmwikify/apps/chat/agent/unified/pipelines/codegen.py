"""Codegen 策略 — 用预置 Steps 组合。

- CodegenReasoner(Pipeline): LLMCallStep(sync) + ExtractCodeStep → ReasonResponse
- CodeActor(StepHandler): ValidateAndExecuteStep + BuildFeedbackStep → ActResult

用法::

    from llmwikify.apps.chat.agent.unified.pipelines.codegen import (
        CodegenReasoner, CodeActor,
    )

    reasoner = CodegenReasoner(llm_client)
    actor = CodeActor()
"""
from __future__ import annotations

from typing import Any

from llmwikify.apps.chat.agent.unified.core import Pipeline, StepHandler, StepResult
from llmwikify.apps.chat.agent.unified.spec import ActResult, ReasonResponse
from llmwikify.apps.chat.agent.unified.steps import (
    BuildFeedbackStep,
    CodeExecResult,
    LLMCallStep,
    ExtractCodeStep,
    ValidateAndExecuteStep,
)


class CodegenReasoner(Pipeline):
    """Codegen REASON: LLMCallStep(sync) + ExtractCodeStep → ReasonResponse。

    流程: messages → LLM raw text → extract code → ReasonResponse

    构造时依赖: llm_client（可选，不传则自动构建）
    """

    def __init__(self, llm_client: Any = None) -> None:
        if llm_client is None:
            from llmwikify.reproduction.codegen.llm_code import build_llm_client
            llm_client = build_llm_client()
        super().__init__(LLMCallStep(llm_client), ExtractCodeStep())

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        # Pipeline: messages → LLM text → code
        pipeline_result = await super().handle(input, spec, ctx)
        if not pipeline_result.success:
            return StepResult.ok(ReasonResponse(
                error=pipeline_result.error,
                is_valid=False,
            ))
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
