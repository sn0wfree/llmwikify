"""反馈相关 Steps.

- BuildFeedbackStep: 构建错误 feedback 消息
- TruncateStep: 截断文本

历史: 从 apps/chat/agent/unified/steps/feedback.py 搬迁。
"""
from __future__ import annotations

from typing import Any

from llmwikify.kernel.agent._core_types import StepHandler, StepResult


class BuildFeedbackStep(StepHandler):
    """构建错误 feedback 消息。

    输入: CodeExecResult
    输出: message dict ({"role": "user", "content": ...}) 或 None（成功时）
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.agent.steps.code import CodeExecResult
        from llmwikify.kernel.quant.codegen import OBSERVE_FEEDBACK_TEMPLATE

        result = input
        if not isinstance(result, CodeExecResult):
            return StepResult.ok(None)
        if result.success:
            return StepResult.ok(None)

        truncated = (result.error or "")[:600]
        context = ""
        if result.code:
            context = f"Your last code was:\n```python\n{result.code[:500]}\n```"
        content = OBSERVE_FEEDBACK_TEMPLATE.format(
            stage=result.error_kind,
            error=truncated,
            context=context,
        )
        return StepResult.ok({"role": "user", "content": content})


class TruncateStep(StepHandler):
    """截断文本。

    输入: text (str)
    输出: text[:max_len] (str)
    """

    def __init__(self, max_len: int = 600) -> None:
        self._max_len = max_len

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        text = input
        if isinstance(text, str) and len(text) > self._max_len:
            return StepResult.ok(text[: self._max_len] + "...[truncated]")
        return StepResult.ok(text)
