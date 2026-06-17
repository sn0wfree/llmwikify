"""AgentHook base + CompositeHook (fan-out with error isolation).

Mirrors the lifecycle shape of nanobot's AgentHook (v0.2.1) but kept
dependency-free (no loguru). The 13 hook points cover the full agent
loop: iteration start, streaming, tool execution, confirmation, error,
finalize. CompositeHook fans out each event to every registered hook
with per-hook try/except, so a single failing hook cannot break the loop.

Synchronous hook methods are accepted (legacy callers from apps/agent/
hooks.py); the runner awaits them only when they are coroutine functions.
This avoids forcing every consumer to migrate to async in one step.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from llmwikify.foundation.callback.context import AgentHookContext

logger = logging.getLogger(__name__)


class AgentHook:
    name: str = "base"

    def wants_streaming(self) -> bool:
        return False

    def before_iteration(self, ctx: AgentHookContext) -> None:
        pass

    def on_stream(self, ctx: AgentHookContext, delta: str) -> None:
        pass

    def on_stream_end(self, ctx: AgentHookContext, *, resuming: bool) -> None:
        pass

    def emit_reasoning(self, ctx: AgentHookContext, content: str) -> None:
        pass

    def emit_reasoning_end(self, ctx: AgentHookContext) -> None:
        pass

    def before_execute_tools(self, ctx: AgentHookContext) -> None:
        pass

    def after_tool_executed(
        self, ctx: AgentHookContext, tool_call: Any, result: Any,
    ) -> None:
        pass

    def on_tool_error(
        self, ctx: AgentHookContext, tool_call: Any, error: BaseException,
    ) -> None:
        pass

    def on_confirmation(self, ctx: AgentHookContext, tool_call: Any) -> None:
        pass

    def after_iteration(self, ctx: AgentHookContext) -> None:
        pass

    def finalize_content(self, ctx: AgentHookContext, content: str | None) -> str | None:
        return content

    def on_error(self, ctx: AgentHookContext, error: BaseException) -> None:
        pass


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class NoOpHook(AgentHook):
    name = "noop"


class CompositeHook(AgentHook):
    name = "composite"

    def __init__(self, hooks: list[AgentHook] | None = None) -> None:
        self._hooks: list[AgentHook] = list(hooks) if hooks else []

    def add(self, hook: AgentHook) -> None:
        self._hooks.append(hook)

    def remove(self, name: str) -> None:
        self._hooks = [h for h in self._hooks if h.name != name]

    def clear(self) -> None:
        self._hooks.clear()

    def __len__(self) -> int:
        return len(self._hooks)

    async def _fire(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        for hook in self._hooks:
            try:
                method = getattr(hook, method_name)
                await _maybe_await(method(*args, **kwargs))
            except Exception:
                logger.warning(
                    "Hook %s.%s failed", hook.name, method_name, exc_info=True,
                )

    async def _fire_pipeline(
        self, method_name: str, ctx: AgentHookContext, content: str | None,
    ) -> str | None:
        current = content
        for hook in self._hooks:
            try:
                method = getattr(hook, method_name)
                result = await _maybe_await(method(ctx, current))
                if result is not None:
                    current = result
            except Exception:
                logger.exception(
                    "Hook %s.%s raised in pipeline", hook.name, method_name,
                )
                raise
        return current

    def wants_streaming(self) -> bool:
        return any(h.wants_streaming() for h in self._hooks)

    async def before_iteration(self, ctx: AgentHookContext) -> None:
        await self._fire("before_iteration", ctx)

    async def on_stream(self, ctx: AgentHookContext, delta: str) -> None:
        await self._fire("on_stream", ctx, delta)

    async def on_stream_end(self, ctx: AgentHookContext, *, resuming: bool) -> None:
        await self._fire("on_stream_end", ctx, resuming=resuming)

    async def emit_reasoning(self, ctx: AgentHookContext, content: str) -> None:
        await self._fire("emit_reasoning", ctx, content)

    async def emit_reasoning_end(self, ctx: AgentHookContext) -> None:
        await self._fire("emit_reasoning_end", ctx)

    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        await self._fire("before_execute_tools", ctx)

    async def after_tool_executed(
        self, ctx: AgentHookContext, tool_call: Any, result: Any,
    ) -> None:
        await self._fire("after_tool_executed", ctx, tool_call, result)

    async def on_tool_error(
        self, ctx: AgentHookContext, tool_call: Any, error: BaseException,
    ) -> None:
        await self._fire("on_tool_error", ctx, tool_call, error)

    async def on_confirmation(self, ctx: AgentHookContext, tool_call: Any) -> None:
        await self._fire("on_confirmation", ctx, tool_call)

    async def after_iteration(self, ctx: AgentHookContext) -> None:
        await self._fire("after_iteration", ctx)

    async def finalize_content(
        self, ctx: AgentHookContext, content: str | None,
    ) -> str | None:
        return await self._fire_pipeline("finalize_content", ctx, content)

    async def on_error(self, ctx: AgentHookContext, error: BaseException) -> None:
        await self._fire("on_error", ctx, error)
