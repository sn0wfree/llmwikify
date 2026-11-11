"""反馈相关 Steps.

- TruncateStep: 截断文本

历史: 从 apps/chat/agent/unified/steps/feedback.py 搬迁。
BuildFeedbackStep（因子执行 OBSERVE 反馈）已随因子编译路径删除。
"""

from __future__ import annotations

from typing import Any

from llmwikify.kernel.agent._core_types import StepHandler, StepResult


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
