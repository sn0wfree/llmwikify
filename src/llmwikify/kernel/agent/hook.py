"""UnifiedHook — 通用 hook 接口.

所有 mode 共用。比 AgentHook 13 点更通用，适用于 Chat/Codegen/Research。
AgentHook 通过 AgentHookAdapter 桥接到此接口。

历史: 从 apps/chat/agent/unified/core.py 搬迁。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import UnifiedContext


class UnifiedHook:
    """统一 hook 接口 — 所有 mode 共用。

    16 个事件点（默认全部 no-op）：
    - wants_streaming / before_iteration / after_iteration
    - on_reason_start / on_reason_end / on_stream
    - emit_reasoning / emit_reasoning_end
    - on_act_start / on_act_end
    - after_tool_executed / on_tool_error / on_confirmation
    - on_observe / on_error
    - finalize
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
