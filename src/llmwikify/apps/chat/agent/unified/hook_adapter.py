"""Hook 适配器 — AgentHook 13 点 → UnifiedHook 完整映射。

- UnifiedHook: 统一 hook 接口（16 个方法）
- AgentHookAdapter: 将 AgentHook 13 点桥接到 UnifiedHook

用法::

    from llmwikify.apps.chat.agent.unified.hook_adapter import AgentHookAdapter

    hook = AgentHookAdapter(agent_hook_instance)
    loop = UnifiedAgentLoop(reasoner=..., actor=..., deciders=..., hook=hook)
"""
from __future__ import annotations

from typing import Any

from llmwikify.apps.chat.agent.unified.core import UnifiedContext, UnifiedHook


class AgentHookAdapter(UnifiedHook):
    """AgentHook 13 点 → UnifiedHook 完整映射。

    将 AgentHook（foundation/callback/composite.py）的 13 个 hook 方法
    映射到 UnifiedHook 的 16 个方法。缺失的映射用 pass 占位。
    """

    def __init__(self, hook: Any) -> None:
        from llmwikify.foundation.callback.composite import NoOpHook
        self._hook = hook or NoOpHook()

    def wants_streaming(self) -> bool:
        return self._hook.wants_streaming()

    def before_iteration(self, ctx: UnifiedContext) -> None:
        self._hook.before_iteration(self._to_hook_ctx(ctx))

    def on_reason_start(self, ctx: UnifiedContext) -> None:
        pass  # AgentHook 没有直接对应

    def on_reason_end(self, ctx: UnifiedContext, response: Any) -> None:
        self._hook.on_stream_end(self._to_hook_ctx(ctx), resuming=False)

    def on_stream(self, ctx: UnifiedContext, delta: str) -> None:
        self._hook.on_stream(self._to_hook_ctx(ctx), delta)

    def emit_reasoning(self, ctx: UnifiedContext, content: str) -> None:
        self._hook.emit_reasoning(self._to_hook_ctx(ctx), content)

    def emit_reasoning_end(self, ctx: UnifiedContext) -> None:
        self._hook.emit_reasoning_end(self._to_hook_ctx(ctx))

    def on_act_start(self, ctx: UnifiedContext) -> None:
        self._hook.before_execute_tools(self._to_hook_ctx(ctx))

    def on_act_end(self, ctx: UnifiedContext, result: Any) -> None:
        pass  # after_tool_executed 由 ToolActor 内部调用

    def after_tool_executed(self, ctx: UnifiedContext, tool_call: Any, result: Any) -> None:
        self._hook.after_tool_executed(self._to_hook_ctx(ctx), tool_call, result)

    def on_tool_error(self, ctx: UnifiedContext, tool_call: Any, error: BaseException) -> None:
        self._hook.on_tool_error(self._to_hook_ctx(ctx), tool_call, error)

    def on_confirmation(self, ctx: UnifiedContext, tool_call: Any) -> None:
        self._hook.on_confirmation(self._to_hook_ctx(ctx), tool_call)

    def on_observe(self, ctx: UnifiedContext) -> None:
        pass  # AgentHook 没有直接对应

    def on_error(self, ctx: UnifiedContext, error: BaseException) -> None:
        self._hook.on_error(self._to_hook_ctx(ctx), error)

    def finalize(self, ctx: UnifiedContext, content: str | None) -> str | None:
        return self._hook.finalize_content(self._to_hook_ctx(ctx), content)

    def after_iteration(self, ctx: UnifiedContext) -> None:
        self._hook.after_iteration(self._to_hook_ctx(ctx))

    def _to_hook_ctx(self, ctx: UnifiedContext) -> Any:
        """UnifiedContext → AgentHookContext 映射（17 字段）。"""
        from llmwikify.foundation.callback.context import AgentHookContext

        return AgentHookContext(
            iteration=ctx.iteration,
            messages=ctx.messages,
            response=None,
            usage={},
            tool_calls=[],
            tool_results=[],
            tool_events=[],
            streamed_content=False,
            streamed_reasoning=False,
            final_content=ctx.final_content,
            stop_reason=ctx.stop_reason,
            error=ctx.error,
            observations=[],
            cancelled=False,
            paused=False,
            compacted_count=ctx.compacted_count,
            chars_saved=0,
        )
