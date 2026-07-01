"""Backward-compat shim: AgentExecutionContext 已迁 kernel.agent.execution_context.

历史: AgentExecutionContext 从 apps/chat/agent/execution_context.py 搬到
kernel/agent/execution_context.py (G+Y commit 6), 因为它是 agent 框架
通用概念, 不应依赖 apps/ 层。

本 shim 保留为 backward-compat re-export:
    from llmwikify.apps.chat.agent.execution_context import AgentExecutionContext

新代码应直接:
    from llmwikify.kernel.agent import AgentExecutionContext
"""
from llmwikify.kernel.agent.execution_context import AgentExecutionContext

__all__ = ["AgentExecutionContext"]
