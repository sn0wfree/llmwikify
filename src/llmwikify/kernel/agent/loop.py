"""Unified Agent Loop — 统一状态机.

UnifiedAgentLoop 编排 StepHandler 和 StreamingHandler 两种 handler,
实现统一的 ReAct 循环:

    PRECHECK → [REASON → DECIDE① → ACT → DECIDE② → OBSERVE → DECIDE③] → FINALIZE

历史: 从 apps/chat/agent/unified/loop.py 搬迁。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from ._core_types import (
    StepHandler,
    StepResult,
    StreamingHandler,
    _maybe_await,
)
from .context import UnifiedContext
from .hook import UnifiedHook
from .spec import BaseSpec, UnifiedResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class UnifiedAgentLoop:
    """统一状态机。

    编排 StepHandler 和 StreamingHandler 两种 handler。
    REASON 和 ACT 可以是任一类型，DECIDE 只用 StepHandler。
    """

    def __init__(
        self,
        reasoner: StepHandler | StreamingHandler,
        actor: StepHandler | StreamingHandler,
        deciders: dict[str, StepHandler] | None = None,
        hook: UnifiedHook | None = None,
        precheck: Callable[[UnifiedContext], bool] | None = None,
        finalize: Callable[[UnifiedContext], str | None] | None = None,
    ) -> None:
        self._reasoner = reasoner
        self._actor = actor
        self._deciders = deciders or {}
        self._hook = hook or UnifiedHook()
        self._precheck = precheck
        self._finalize = finalize

    async def run_stream(self, spec: BaseSpec) -> AsyncIterator[dict[str, Any]]:
        ctx = UnifiedContext(spec=spec)
        spec._last_ctx = ctx  # 让 run_to_completion 能访问 ctx

        # ── SESSION_INIT（Chat 流式模式）──
        if self._hook.wants_streaming():
            session_id = getattr(spec, "session_id", "")
            yield {"type": "session_init", "session_id": session_id}

        try:
            for iteration in range(spec.max_iterations):
                ctx.iteration = iteration

                # ── PRECHECK（含 cancel/pause 检查）──
                if self._precheck and self._precheck(ctx):
                    yield {"type": "phase", "phase": ctx.stop_reason or "timeout"}
                    break

                # 额外检查 cancelled/paused（ChatSpec 字段）
                if getattr(spec, "cancelled", False):
                    ctx.stop_reason = "cancelled"
                    yield {"type": "phase", "phase": "cancelled"}
                    break
                if getattr(spec, "paused", False):
                    ctx.stop_reason = "paused"
                    yield {"type": "phase", "phase": "paused"}
                    break

                await _maybe_await(self._hook.before_iteration, ctx)

                # ── REASON ──
                await _maybe_await(self._hook.on_reason_start, ctx)
                response = None

                if isinstance(self._reasoner, StreamingHandler):
                    async for event in self._reasoner.stream(ctx.messages, spec, ctx):
                        if isinstance(event, StepResult):
                            if not event.success:
                                ctx.error = event.error
                                ctx.stop_reason = "error"
                                yield {"type": "error", "message": event.error}
                                break
                            response = event.output
                        else:
                            yield event  # 透传流式 events
                    if ctx.error:
                        break
                else:
                    result = await self._reasoner.handle(ctx.messages, spec, ctx)
                    for ev in result.events:
                        yield ev
                    if not result.success:
                        ctx.error = result.error
                        ctx.stop_reason = "error"
                        yield {"type": "error", "message": result.error}
                        break
                    response = result.output

                if response is None:
                    ctx.error = "Reasoner returned no response"
                    ctx.stop_reason = "error"
                    yield {"type": "error", "message": ctx.error}
                    break

                await _maybe_await(self._hook.on_reason_end, ctx, response)

                # ── DECIDE after REASON ──
                if "after_reason" in self._deciders:
                    decide_result = await self._deciders["after_reason"].handle(response, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                # ── assistant tool_calls 注入（Chat 多轮必需）──
                tool_calls = getattr(response, "tool_calls", None)
                if tool_calls:
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": getattr(response, "raw_content", "") or "",
                        "tool_calls": [
                            {
                                "id": tc.get("id", f"call_{iteration}_{i}"),
                                "type": "function",
                                "function": {
                                    "name": tc.get("name", ""),
                                    "arguments": tc.get("arguments", "{}"),
                                },
                            }
                            for i, tc in enumerate(tool_calls)
                        ],
                    }
                    ctx.messages.append(assistant_msg)

                # ── ACT ──
                await _maybe_await(self._hook.on_act_start, ctx)
                result = None

                if isinstance(self._actor, StreamingHandler):
                    async for event in self._actor.stream(response, spec, ctx):
                        if isinstance(event, StepResult):
                            if not event.success:
                                ctx.error = event.error
                                ctx.stop_reason = "error"
                                yield {"type": "error", "message": event.error}
                                break
                            result = event.output
                        else:
                            yield event  # 透传流式 events
                    if ctx.error:
                        break
                else:
                    act_result = await self._actor.handle(response, spec, ctx)
                    for ev in act_result.events:
                        yield ev
                    if not act_result.success:
                        ctx.error = act_result.error
                        ctx.stop_reason = "error"
                        yield {"type": "error", "message": act_result.error}
                        break
                    result = act_result.output

                if result is None:
                    ctx.error = "Actor returned no result"
                    ctx.stop_reason = "error"
                    yield {"type": "error", "message": ctx.error}
                    break

                ctx.last_act_result = result
                await _maybe_await(self._hook.on_act_end, ctx, result)

                # ── tools_used 累积 ──
                tool_name = getattr(result, "tool_name", "")
                if tool_name:
                    ctx.tools_used.append(tool_name)

                if result.needs_confirmation:
                    ctx.stop_reason = "confirmation_required"
                    yield {"type": "confirmation_required"}
                    break

                # ── DECIDE after ACT ──
                if "after_act" in self._deciders:
                    decide_result = await self._deciders["after_act"].handle(result, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                # ── OBSERVE ──
                for msg in result.messages_to_inject:
                    ctx.messages.append(msg)
                ctx.steps.append({"iteration": iteration, "result": result})
                await _maybe_await(self._hook.on_observe, ctx)

                # ── DECIDE after OBSERVE ──
                if "after_observe" in self._deciders:
                    decide_result = await self._deciders["after_observe"].handle(result, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                # ── memory consolidation（Chat 用）──
                memory_mgr = getattr(spec, "memory_manager", None)
                if memory_mgr and hasattr(memory_mgr, "consolidate_session"):
                    try:
                        await _maybe_await(memory_mgr.consolidate_session)
                    except Exception as exc:
                        logger.warning("Memory consolidation failed: %s", exc)

                await _maybe_await(self._hook.after_iteration, ctx)

        except Exception as exc:
            ctx.error = str(exc)
            ctx.stop_reason = "error"
            logger.exception("UnifiedAgentLoop error")
            await _maybe_await(self._hook.on_error, ctx, exc)
            yield {"type": "error", "message": str(exc)}

        # ── FINALIZE ──
        final_content = ctx.final_content
        if self._finalize:
            final_content = self._finalize(ctx)
        final_content = self._hook.finalize(ctx, final_content)

        yield {
            "type": "done",
            "content": final_content or "",
            "stop_reason": ctx.stop_reason or "completed",
            "error": ctx.error,
            "iterations": ctx.iteration + 1,
            "elapsed_sec": ctx.elapsed_sec,
        }

    async def run_to_completion(self, spec: BaseSpec) -> UnifiedResult:
        """drain run_stream，构建 UnifiedResult。"""
        result = UnifiedResult()
        async for event in self.run_stream(spec):
            kind = event.get("type")
            if kind == "done":
                result.final_content = event.get("content")
                result.stop_reason = event.get("stop_reason", "completed")
                result.error = event.get("error")
                result.iterations = event.get("iterations", 0)
                result.elapsed_sec = event.get("elapsed_sec", 0)
            elif kind == "error":
                result.error = event.get("message")
                result.stop_reason = "error"

        # 从 ctx 提取累积数据
        if hasattr(spec, "_last_ctx"):
            ctx = spec._last_ctx
            # codegen: code / factor_series
            last_act = getattr(ctx, "last_act_result", None)
            if last_act is not None:
                if hasattr(last_act, "code") and last_act.code:
                    result.code = last_act.code
                if hasattr(last_act, "output") and last_act.output is not None:
                    result.factor_series = last_act.output
            # chat: messages / tools_used / compacted_count / usage
            result.messages = list(ctx.messages)
            result.tools_used = list(ctx.tools_used)
            result.compacted_count = ctx.compacted_count
            result.total_compacted_chars_saved = ctx.total_compacted_chars_saved
            result.usage = dict(ctx.usage)

        return result

    def execution_context(self) -> Any:
        """返回执行上下文（SubAgentManager 用）。"""
        from .execution_context import AgentExecutionContext

        return AgentExecutionContext(
            chat_service=getattr(self._reasoner, "_chat_service", None),
            tool_executor=getattr(self._actor, "_executor", None),
            prompt_builder=getattr(self._reasoner, "_prompt_builder", None),
            config={},
        )
