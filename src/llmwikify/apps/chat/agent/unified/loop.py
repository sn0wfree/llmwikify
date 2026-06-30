"""Backward-compat shim: UnifiedAgentLoop 已迁 kernel.agent.

历史: UnifiedAgentLoop 已从 apps/chat/agent/unified/loop.py 搬到
kernel/agent/loop.py (commit 1 of G+Y)。本文件保留为 backward-compat re-export,
让旧 import path 仍工作。

新代码应直接:
    from llmwikify.kernel.agent import UnifiedAgentLoop
"""
from llmwikify.kernel.agent.loop import UnifiedAgentLoop

__all__ = ["UnifiedAgentLoop"]
