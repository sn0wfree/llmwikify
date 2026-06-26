"""Unified Agent Loop — 统一状态机框架。

将 Chat Agent、Codegen Agent、Research Agent 三套独立的 ReAct 循环
合并为一个 UnifiedAgentLoop，支持策略自由组合。

核心抽象：
- StepHandler: 无状态、单次调用的步骤接口
- StreamingHandler: 有状态、流式的 handler 接口
- Pipeline: Steps 串行组合
- UnifiedAgentLoop: 统一编排循环

用法::

    from llmwikify.apps.chat.agent.unified import (
        StepHandler, StreamingHandler, StepResult, Pipeline,
        BaseSpec, ChatSpec, CodegenSpec,
        ReasonResponse, ActResult, UnifiedResult,
        UnifiedHook, UnifiedContext,
    )
"""

from llmwikify.apps.chat.agent.unified.core import (
    Pipeline,
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedContext,
    UnifiedHook,
)
from llmwikify.apps.chat.agent.unified.spec import (
    ActResult,
    BaseSpec,
    ChatSpec,
    CodegenSpec,
    ReasonResponse,
    UnifiedResult,
)

__all__ = [
    "StepHandler",
    "StreamingHandler",
    "StepResult",
    "Pipeline",
    "UnifiedHook",
    "UnifiedContext",
    "BaseSpec",
    "ChatSpec",
    "CodegenSpec",
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
]
