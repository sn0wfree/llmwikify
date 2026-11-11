"""代码提取 / 语法检查 Steps（纯文本，无因子执行）。

- ExtractCodeStep: 从 LLM 响应提取 Python 代码
- ValidateSyntaxStep: Python 语法检查

历史: 从 apps/chat/agent/unified/steps/code.py 搬迁。
因子执行路径（ExecuteCode / ValidateSafety / CodeSandbox）已随
本项目不再做因子编译而删除（2026-11-10）。
"""

from __future__ import annotations

from typing import Any

from llmwikify.kernel.agent._core_types import StepHandler, StepResult


class ExtractCodeStep(StepHandler):
    """从 LLM 响应提取 Python 代码。

    输入: text (str)
    输出: code (str) — 失败时返回 fail
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.codegen import extract_python

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
        from llmwikify.kernel.codegen import validate_syntax

        code = input
        ok, err = validate_syntax(code)
        if not ok:
            return StepResult.fail(f"SyntaxError: {err}")
        return StepResult.ok(code)
