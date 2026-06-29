"""LLM 调用相关 Steps。

- LLMCallStep: LLM 同步调用
- ExtractJSONStep: 从 LLM 响应提取 JSON
"""
from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.agent.unified.core import StepHandler, StepResult

logger = logging.getLogger(__name__)


class LLMCallStep(StepHandler):
    """LLM 同步调用。

    输入: messages (list[dict])
    输出: raw response text (str)

    构造时依赖: llm_client（StreamableLLMClient 或兼容对象）
    运行时依赖: 从 spec 取 temperature
    """

    def __init__(self, llm_client: Any, max_retries: int = 3) -> None:
        self._llm = llm_client
        self._max_retries = max_retries

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        messages = input
        temperature = getattr(spec, "temperature", 0.3)

        last_error: str | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._llm.chat(messages=messages, temperature=temperature)
                return StepResult.ok(response)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("LLM call attempt %d failed: %s", attempt + 1, last_error)

        return StepResult.fail(f"LLM call failed after {self._max_retries} attempts: {last_error}")


class ExtractJSONStep(StepHandler):
    """从 LLM 响应提取 JSON。

    输入: text (str)
    输出: dict | None
    """

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        from llmwikify.kernel.quant.codegen import extract_json_from_response

        text = input
        data = extract_json_from_response(text)
        if data is None:
            return StepResult.fail("no JSON found in response")
        return StepResult.ok(data)
