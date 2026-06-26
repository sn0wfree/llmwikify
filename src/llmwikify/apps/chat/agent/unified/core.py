"""Unified Agent Loop — 核心抽象。

定义两种 handler 类型和共享基础设施：

- StepResult: 统一的步骤输出
- StepHandler: 无状态、单次调用的步骤接口
- StreamingHandler: 有状态、流式的 handler 接口
- Pipeline: Steps 串行组合
- UnifiedHook: 统一 hook 接口
- UnifiedContext: Loop 内部状态
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any


# ─── StepResult — 统一的步骤输出 ─────────────────────────


@dataclass
class StepResult:
    """StepHandler / StreamingHandler 的统一输出。

    - output: 该步骤的产出（类型由具体 step 决定）
    - events: 透传给调用方的 SSE events
    - success: 步骤是否成功
    - error: 失败原因（success=False 时）
    """

    output: Any = None
    events: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @staticmethod
    def ok(output: Any = None, events: list[dict[str, Any]] | None = None) -> StepResult:
        return StepResult(output=output, events=events or [])

    @staticmethod
    def fail(error: str, events: list[dict[str, Any]] | None = None) -> StepResult:
        return StepResult(success=False, error=error, events=events or [])


# ─── StepHandler — 无状态步骤接口 ───────────────────────


class StepHandler(ABC):
    """无状态、单次调用的步骤。

    适用于：LLM 调用、代码提取、语法检查、字段检查、数据转换等。
    不适用于：流式解析、有状态循环、双输出（用 StreamingHandler）。

    用法::

        step = ExtractCodeStep()
        result = await step.handle(llm_text, spec, ctx)
        # result.output = code str
    """

    @abstractmethod
    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        ...


# ─── StreamingHandler — 有状态流式接口 ──────────────────


class StreamingHandler(ABC):
    """有状态、流式的 handler。

    适用于：Chat Reasoner（TextModeParser 状态机）、Tool Actor（microcompact 双输出）。
    与 StepHandler 的区别：有生命周期，内部管理状态，yield 多次。

    用法::

        handler = ChatReasoner(chat_service)
        async for event in handler.stream(messages, spec, ctx):
            if isinstance(event, StepResult):
                response = event.output  # 最终结果
            else:
                yield event  # 透传给 SSE
    """

    @abstractmethod
    def stream(
        self, input: Any, spec: Any, ctx: Any,
    ) -> AsyncIterator[dict[str, Any] | StepResult]:
        """yield SSE events，最后一个 yield StepResult(output=结果)。"""
        ...
        yield StepResult()  # pragma: no cover  # type: ignore[misc]


# ─── Pipeline — Steps 串行组合 ──────────────────────────


class Pipeline(StepHandler):
    """步骤流水线 — 串行执行多个 StepHandler。

    上一个 step 的 output 作为下一个 step 的 input。
    任一 step 失败 → 整体失败（fail-fast）。
    events 累积。

    用法::

        pipeline = Pipeline(LLMCallStep(client), ExtractCodeStep())
        result = await pipeline.handle(messages, spec, ctx)
    """

    def __init__(self, *steps: StepHandler) -> None:
        self._steps = steps

    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        current = input
        all_events: list[dict[str, Any]] = []
        for step in self._steps:
            result = await step.handle(current, spec, ctx)
            all_events.extend(result.events)
            if not result.success:
                return StepResult.fail(result.error, all_events)
            current = result.output
        return StepResult.ok(current, all_events)

    def __repr__(self) -> str:
        names = " → ".join(type(s).__name__ for s in self._steps)
        return f"Pipeline({names})"


# ─── UnifiedHook — 统一 Hook 接口 ──────────────────────


class UnifiedHook:
    """统一 hook 接口 — 所有 mode 共用。

    比 AgentHook 13 点更通用，适用于 Chat/Codegen/Research。
    AgentHook 通过 AgentHookAdapter 桥接到此接口。
    """

    def wants_streaming(self) -> bool:
        return False

    def before_iteration(self, ctx: UnifiedContext) -> None:
        pass

    def on_reason_start(self, ctx: UnifiedContext) -> None:
        pass

    def on_reason_end(self, ctx: UnifiedContext, response: Any) -> None:
        pass

    def on_stream(self, ctx: UnifiedContext, delta: str) -> None:
        pass

    def emit_reasoning(self, ctx: UnifiedContext, content: str) -> None:
        pass

    def emit_reasoning_end(self, ctx: UnifiedContext) -> None:
        pass

    def on_act_start(self, ctx: UnifiedContext) -> None:
        pass

    def on_act_end(self, ctx: UnifiedContext, result: Any) -> None:
        pass

    def after_tool_executed(self, ctx: UnifiedContext, tool_call: Any, result: Any) -> None:
        pass

    def on_tool_error(self, ctx: UnifiedContext, tool_call: Any, error: BaseException) -> None:
        pass

    def on_confirmation(self, ctx: UnifiedContext, tool_call: Any) -> None:
        pass

    def on_observe(self, ctx: UnifiedContext) -> None:
        pass

    def on_error(self, ctx: UnifiedContext, error: BaseException) -> None:
        pass

    def finalize(self, ctx: UnifiedContext, content: str | None) -> str | None:
        return content

    def after_iteration(self, ctx: UnifiedContext) -> None:
        pass


# ─── UnifiedContext — Loop 内部状态 ─────────────────────


@dataclass
class UnifiedContext:
    """Loop 内部状态 — 不暴露给策略（策略通过 spec 和 StepResult 交互）。"""

    spec: Any  # BaseSpec
    messages: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    start_time: float = 0.0
    stop_reason: str = ""
    error: str | None = None
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    compacted_count: int = 0
    total_compacted_chars_saved: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    last_output: Any = None
    last_act_result: Any = None

    def __post_init__(self) -> None:
        # 延迟导入避免循环依赖
        from llmwikify.apps.chat.agent.unified.spec import BaseSpec

        if isinstance(self.spec, BaseSpec):
            self.messages = list(self.spec.messages)
        self.start_time = time.monotonic()

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def tools(self) -> list[dict[str, Any]] | None:
        """从 spec 获取 tool specs（Chat 用）。"""
        if hasattr(self.spec, "tool_registry") and self.spec.tool_registry:
            reg = self.spec.tool_registry
            if hasattr(reg, "get_tool_specs"):
                return reg.get_tool_specs()
            if hasattr(reg, "list_tools"):
                return list(reg.list_tools())
        return None


# ─── 辅助函数 ───────────────────────────────────────────


async def _maybe_await(fn_or_coro: Any, *args: Any, **kwargs: Any) -> Any:
    """调用 sync 或 async callable，统一 await。"""
    if callable(fn_or_coro):
        result = fn_or_coro(*args, **kwargs)
    else:
        result = fn_or_coro
    if hasattr(result, "__await__"):
        return await result
    return result
