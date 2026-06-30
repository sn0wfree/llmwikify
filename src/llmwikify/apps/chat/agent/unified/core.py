"""Backward-compat shim: 通用框架已迁 kernel.agent.

历史: StepHandler / StepResult / StreamingHandler / Pipeline / UnifiedHook /
UnifiedContext / _maybe_await 已从 apps/chat/agent/unified/core.py 搬到
kernel/agent/ (commit 1 of G+Y)。本文件保留为 backward-compat re-export,
让旧 import path 仍工作。

新代码应直接:
    from llmwikify.kernel.agent import (
        StepHandler, StepResult, StreamingHandler, Pipeline,
        UnifiedHook, UnifiedContext, _maybe_await,
    )
"""
from llmwikify.kernel.agent._core_types import (
    Pipeline,
    StepHandler,
    StepResult,
    StreamingHandler,
    _maybe_await,
)
from llmwikify.kernel.agent.context import UnifiedContext
from llmwikify.kernel.agent.hook import UnifiedHook

__all__ = [
    "StepHandler",
    "StreamingHandler",
    "StepResult",
    "Pipeline",
    "UnifiedHook",
    "UnifiedContext",
    "_maybe_await",
]
