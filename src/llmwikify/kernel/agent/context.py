"""UnifiedContext — Loop 内部状态.

策略通过 spec 和 StepResult 交互, 不直接访问 ctx.

历史: 从 apps/chat/agent/unified/core.py 搬迁。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .spec import BaseSpec


@dataclass
class UnifiedContext:
    """Loop 内部状态 — 不暴露给策略。"""

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
        from .spec import BaseSpec

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
