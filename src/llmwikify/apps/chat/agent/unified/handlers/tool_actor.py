"""ToolActor — Chat ACT 阶段（StreamingHandler）。

工具调度 + confirmation + microcompact 双输出。

有状态：microcompact 在 spec._compacted_results 上产生副作用。
双输出：compacted content → messages，original result → SSE events。
流式：逐 tool yield TOOL_CALL_START / END / ERROR events。

用法::

    actor = ToolActor(tool_executor)
    async for event in actor.stream(response, spec, ctx):
        if isinstance(event, StepResult):
            result = event.output  # ActResult
        else:
            yield event  # 透传给 SSE
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from llmwikify.apps.chat.agent.unified.core import (
    StepResult,
    StreamingHandler,
    UnifiedContext,
    _maybe_await,
)
from llmwikify.apps.chat.agent.unified.spec import ActResult, BaseSpec, ReasonResponse

logger = logging.getLogger(__name__)


class ToolActor(StreamingHandler):
    """Chat ACT: 工具调度 + confirmation + microcompact。

    构造时依赖：tool_executor（ToolExecutor 或兼容对象）
    运行时依赖：从 ChatSpec 取 tool_registry, session_id, microcompact 配置
    """

    def __init__(self, tool_executor: Any) -> None:
        self._executor = tool_executor

    async def stream(
        self, input: Any, spec: Any, ctx: Any,
    ) -> AsyncIterator[dict[str, Any] | StepResult]:
        response = input  # ReasonResponse

        messages_to_inject: list[dict[str, Any]] = []
        tools_used: list[str] = []
        compacted_count = 0

        for tc in response.tool_calls:
            tool_name = tc.get("name") or tc.get("tool", "")
            args = self._parse_args(tc)
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"

            if not tool_name:
                yield {
                    "type": "tool_call_error",
                    "tool": "",
                    "error": "Skipped malformed tool call with empty name",
                    "call_id": call_id,
                }
                continue

            yield {
                "type": "tool_call_start",
                "tool": tool_name,
                "args": args,
                "call_id": call_id,
            }

            # 执行工具
            try:
                result = await self._execute_tool(
                    tool_name, args, spec, ctx,
                )
            except Exception as exc:
                logger.warning("Tool %s failed", tool_name, exc_info=True)
                yield {
                    "type": "tool_call_error",
                    "tool": tool_name,
                    "error": str(exc),
                    "call_id": call_id,
                }
                continue

            # Confirmation check
            if isinstance(result, dict) and result.get("status") == "confirmation_required":
                yield {
                    "type": "confirmation_required",
                    "confirmation_id": result.get("confirmation_id", ""),
                    "tool": tool_name,
                    "args": args,
                    "impact": result.get("impact", {}),
                    "call_id": call_id,
                }
                yield StepResult.ok(ActResult(
                    success=True,
                    needs_confirmation=True,
                    tool_name=tool_name,
                    messages_to_inject=messages_to_inject,
                ))
                return

            # Error status check
            if isinstance(result, dict) and result.get("status") == "error":
                yield {
                    "type": "tool_call_error",
                    "tool": tool_name,
                    "error": str(result.get("error", "")),
                    "call_id": call_id,
                }
                continue

            # microcompact — 双输出处理
            content, was_compacted, saved = self._microcompact(
                result, tool_name, call_id, spec,
            )
            if was_compacted:
                compacted_count += 1
                yield {
                    "type": "compacted",
                    "call_id": call_id,
                    "tool": tool_name,
                    "chars_saved": saved,
                }

            # compacted content → messages
            messages_to_inject.append({
                "role": "tool",
                "name": tool_name,
                "content": content,
                "tool_call_id": call_id,
            })

            # original result → SSE event
            tools_used.append(tool_name)
            yield {
                "type": "tool_call_end",
                "tool": tool_name,
                "result": result,
                "call_id": call_id,
            }

        yield StepResult.ok(ActResult(
            success=True,
            messages_to_inject=messages_to_inject,
            tool_calls_for_next_round=[],
        ))

    def _parse_args(self, tc: dict[str, Any]) -> dict[str, Any]:
        """解析 tool_call 参数。"""
        raw_args = tc.get("args", {}) or {}
        if isinstance(raw_args, str):
            try:
                return json.loads(raw_args)
            except (TypeError, ValueError):
                return {"_raw": raw_args}
        return raw_args

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        spec: Any,
        ctx: Any,
    ) -> Any:
        """执行工具 — 包装 tool_executor.execute()。"""
        tool_registry = getattr(spec, "tool_registry", None)
        session_id = getattr(spec, "session_id", "")

        executor = self._executor
        if hasattr(executor, "execute"):
            result = executor.execute(tool_name, args, tool_registry, session_id, ctx)
            if inspect.iscoroutine(result):
                result = await result
            return result
        if callable(executor):
            result = executor(tool_name, args, tool_registry, session_id, ctx)
            if inspect.iscoroutine(result):
                result = await result
            return result
        raise RuntimeError(
            f"tool_executor must expose execute() or be callable, got {type(executor)}",
        )

    def _microcompact(
        self,
        result: Any,
        tool_name: str,
        call_id: str,
        spec: Any,
    ) -> tuple[str, bool, int]:
        """Microcompact — 双输出处理。

        Returns:
            (content, was_compacted, chars_saved)
            - content: 用于 tool message（可能被压缩）
            - was_compacted: 是否被压缩
            - chars_saved: 节省的字符数
        """
        if not getattr(spec, "microcompact", False):
            return json.dumps(result, ensure_ascii=False, default=str), False, 0

        compactable = getattr(spec, "microcompact_compactable_tools", set())
        if tool_name not in compactable:
            return json.dumps(result, ensure_ascii=False, default=str), False, 0

        try:
            from llmwikify.apps.chat.agent.microcompact import microcompact_serialize
            return microcompact_serialize(result, tool_name, call_id, spec)
        except Exception:
            return json.dumps(result, ensure_ascii=False, default=str), False, 0
