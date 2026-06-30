"""AgentExecutionContext — 共享执行上下文 dataclass.

历史: 从 apps/chat/agent/execution_context.py 搬到 kernel/agent/ (G+Y commit 6)。
因为它是 agent 框架通用概念, 不应依赖 apps/ 层。

4 个 collaborators 任何 agent loop 都需要:
- chat_service: LLM-connectivity adapter
- tool_executor: Tool dispatcher (None for tool-less agents)
- prompt_builder: System-prompt / message-shape builder
- config: Free-form feature flags
- memory_manager: Optional memory layer
- hook: Optional lifecycle hook
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentExecutionContext:
    """Bundle of collaborators shared across an agent loop boundary.

    Attributes:
        chat_service: LLM-connectivity adapter (or no-op stub for
            tool-only agents).
        tool_executor: Tool dispatcher. ``None`` for agents that do
            not use tools.
        prompt_builder: System-prompt / message-shape builder.
        config: Free-form feature flags (max iterations, microcompact,
            etc.). ``None`` falls back to ``merge_six_step_config()``
            in ``ChatRunnerV2``.
        memory_manager: Optional memory layer for the loop. ``None``
            disables per-run memory consolidation.
        hook: Optional :class:`AgentHook` for cross-cutting lifecycle
            events. ``None`` is equivalent to ``NoOpHook()``.
    """

    chat_service: Any
    tool_executor: Any
    prompt_builder: Any
    config: dict[str, Any] | None = None
    memory_manager: Any = None
    hook: Any = field(default=None)


__all__ = ["AgentExecutionContext"]
