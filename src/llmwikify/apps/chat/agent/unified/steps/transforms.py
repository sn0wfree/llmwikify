"""数据转换 Steps。

- MapStep: 转换 output
- WrapStep: 包装 output 到指定类型
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from llmwikify.apps.chat.agent.unified.core import StepHandler, StepResult


class MapStep(StepHandler):
    """转换 output。

    输入: Any
    输出: fn(input)

    用法::

        MapStep(lambda r: ActResult(success=r.success, output=r.series))
    """

    def __init__(self, fn: Callable[[Any], Any]) -> None:
        self._fn = fn

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        try:
            output = self._fn(input)
            return StepResult.ok(output)
        except Exception as exc:
            return StepResult.fail(f"MapStep failed: {exc}")


class WrapStep(StepHandler):
    """包装 output 到指定类型。

    输入: Any
    输出: cls(**field_fns(input))

    用法::

        WrapStep(ReasonResponse, code=lambda x: x, raw_content=lambda x: x)
    """

    def __init__(self, cls: type, **field_fns: Any) -> None:
        self._cls = cls
        self._field_fns = field_fns

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        try:
            fields: dict[str, Any] = {}
            for key, fn in self._field_fns.items():
                if callable(fn):
                    fields[key] = fn(input)
                else:
                    fields[key] = fn
            return StepResult.ok(self._cls(**fields))
        except Exception as exc:
            return StepResult.fail(f"WrapStep failed: {exc}")
