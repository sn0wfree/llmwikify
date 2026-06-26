"""Unified Agent Loop — 统一状态机。

UnifiedAgentLoop 编排 StepHandler 和 StreamingHandler 两种 handler，
实现统一的 ReAct 循环：

    PRECHECK → [REASON → DECIDE① → ACT → DECIDE② → OBSERVE → DECIDE③] → FINALIZE

用法::

    from llmwikify.apps.chat.agent.unified.loop import UnifiedAgentLoop

    loop = UnifiedAgentLoop(
        reasoner=CodegenReasoner(llm_client),
        actor=CodeActor(),
        deciders={"after_act": CheckSuccessStep()},
    )
    async for event in loop.run_stream(spec):
        ...
    result = await loop.run_to_completion(spec)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from llmwikify.apps.chat.agent.unified.core import (
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedContext,
    UnifiedHook,
    _maybe_await,
)
from llmwikify.apps.chat.agent.unified.spec import BaseSpec, UnifiedResult

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

        try:
            for iteration in range(spec.max_iterations):
                ctx.iteration = iteration

                # ── PRECHECK ──
                if self._precheck and self._precheck(ctx):
                    yield {"type": "phase", "phase": ctx.stop_reason or "timeout"}
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
        ctx_ref = None
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

        # 从 last_act_result 提取 code / factor_series
        # run_stream 内部的 ctx 已被 GC，但 last_act_result 在 break 前已赋值
        # 需要重新获取 — 通过检查 spec 的 _last_ctx 属性（run_stream 设置）
        if hasattr(spec, "_last_ctx"):
            last_act = getattr(spec._last_ctx, "last_act_result", None)
            if last_act is not None:
                if hasattr(last_act, "code") and last_act.code:
                    result.code = last_act.code
                if hasattr(last_act, "output") and last_act.output is not None:
                    result.factor_series = last_act.output

        return result

    def execution_context(self) -> Any:
        """返回执行上下文（SubagentManager 用）。"""
        from llmwikify.apps.chat.agent.execution_context import AgentExecutionContext

        return AgentExecutionContext(
            chat_service=getattr(self._reasoner, "_chat_service", None),
            tool_executor=getattr(self._actor, "_executor", None),
            prompt_builder=getattr(self._reasoner, "_prompt_builder", None),
            config={},
        )
