"""条件判断 Steps — Decider 基础组件.

- CheckFieldStep: 通用字段检查
- CheckEmptyStep: 空检查
- CheckToolCallsStep: tool_calls 空检查（Chat Decider）
- CheckSuccessStep: success 检查（Codegen Decider）

历史: 从 apps/chat/agent/unified/steps/checks.py 搬迁。
"""
from __future__ import annotations

from typing import Any

from llmwikify.kernel.agent._core_types import StepHandler, StepResult
from llmwikify.kernel.agent.spec import ActResult, ReasonResponse


class CheckFieldStep(StepHandler):
    """通用字段检查 — Decider 基础组件。

    输入: Any（检查其 field 属性）
    输出: (bool, str) — (should_stop, reason)

    用法::

        CheckFieldStep(field="success", equals=True)
        # input.success == True → (True, "success")
    """

    def __init__(
        self,
        field: str,
        equals: Any = True,
        stop_reason: str = "",
    ) -> None:
        self._field = field
        self._equals = equals
        self._reason = stop_reason or field

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        value = getattr(input, self._field, None)
        if value == self._equals:
            return StepResult.ok((True, self._reason))
        return StepResult.ok((False, ""))


class CheckEmptyStep(StepHandler):
    """检查列表/字段是否为空。

    输入: Any（检查其 field 属性）
    输出: (bool, str) — (should_stop, reason)
    """

    def __init__(self, field: str, stop_reason: str = "") -> None:
        self._field = field
        self._reason = stop_reason or f"empty_{field}"

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        value = getattr(input, self._field, None)
        if not value:
            return StepResult.ok((True, self._reason))
        return StepResult.ok((False, ""))


class CheckToolCallsStep(StepHandler):
    """Decider: REASON 后检查 tool_calls。

    输入: ReasonResponse
    输出: (bool, str) — (should_stop, reason)
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        if not isinstance(input, ReasonResponse):
            return StepResult.ok((False, ""))
        if not input.tool_calls:
            return StepResult.ok((True, "no_tool_calls"))
        return StepResult.ok((False, ""))


class CheckSuccessStep(StepHandler):
    """Decider: ACT 后检查 success。

    输入: ActResult
    输出: (bool, str) — (should_stop, reason)
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        if not isinstance(input, ActResult):
            return StepResult.ok((False, ""))
        if input.success:
            return StepResult.ok((True, "success"))
        return StepResult.ok((False, ""))
