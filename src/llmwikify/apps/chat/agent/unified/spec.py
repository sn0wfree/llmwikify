"""Backward-compat shim: 通用 Spec/Result 已迁 kernel.agent.

历史: BaseSpec / CodegenSpec / ReasonResponse / ActResult / UnifiedResult 已从
apps/chat/agent/unified/spec.py 搬到 kernel/agent/spec.py (commit 1 of G+Y)。

ChatSpec 保留在本文件 (chat-specific, 继承 BaseSpec)。

本文件保留为 backward-compat re-export, 让旧 import path 仍工作:
    from llmwikify.apps.chat.agent.unified.spec import ChatSpec, BaseSpec
    from llmwikify.apps.chat.agent.unified.spec import CodegenSpec, UnifiedResult

新代码应直接:
    from llmwikify.kernel.agent import (
        BaseSpec, CodegenSpec, ReasonResponse, ActResult, UnifiedResult,
    )
    from llmwikify.apps.chat.agent.unified.spec import ChatSpec
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.kernel.agent.spec import (
    ActResult,
    BaseSpec,
    CodegenSpec,
    ReasonResponse,
    UnifiedResult,
)


@dataclass
class ChatSpec(BaseSpec):
    """Chat mode 专用 Spec. 继承 kernel.agent.BaseSpec.

    Chat-specific 字段:
    - tool_registry / session_id / wiki_id / workspace
    - microcompact 配置
    - hook (AgentHook) / goal_active_predicate
    - model / max_tokens / reasoning_effort 等 LLM 配置
    - context_window_tokens / _compacted_results
    - memory_manager / cancelled / paused
    """

    tool_registry: Any = None
    session_id: str = ""
    wiki_id: str | None = None
    workspace: Path | None = None
    microcompact: bool = True
    microcompact_keep_chars: int = 1000
    microcompact_compactable_tools: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "read_file", "exec", "grep", "find_files", "web_search", "web_fetch", "list_dir",
        }),
    )
    hook: Any | None = None  # AgentHook
    goal_active_predicate: Callable[[], bool] | None = None

    # ── 对齐 ChatRunSpec 的缺失字段 ──
    model: str = ""
    max_tokens: int = 0
    reasoning_effort: str = ""
    max_tool_result_chars: int = 0
    fail_on_tool_error: bool = False
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    context_window_tokens: int = 0
    _compacted_results: dict[str, Any] = field(default_factory=dict)
    memory_manager: Any | None = None
    cancelled: bool = False
    paused: bool = False


__all__ = [
    "BaseSpec",
    "ChatSpec",
    "CodegenSpec",
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
]
