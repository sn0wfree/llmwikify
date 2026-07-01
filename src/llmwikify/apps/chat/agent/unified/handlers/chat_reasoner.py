"""ChatReasoner — Chat REASON 阶段（StreamingHandler）。

流式 LLM 调用 + TextModeParser 解析，yield MESSAGE_DELTA / THINKING events。

有状态：TextModeParser 内部维护 buffer。
流式：逐 chunk yield events。
输出：最后一个 yield StepResult(output=ReasonResponse)。

用法::

    reasoner = ChatReasoner(chat_service, prompt_builder)
    async for event in reasoner.stream(messages, spec, ctx):
        if isinstance(event, StepResult):
            response = event.output  # ReasonResponse
        else:
            yield event  # 透传给 SSE
"""
from __future__ import annotations

import inspect
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from llmwikify.apps.chat.agent.unified.core import (
    StepResult,
    StreamingHandler,
    UnifiedContext,
    _maybe_await,
)
from llmwikify.apps.chat.agent.unified.spec import BaseSpec, ReasonResponse

logger = logging.getLogger(__name__)


class ChatReasoner(StreamingHandler):
    """Chat REASON: 流式 LLM 调用 + TextModeParser 解析。

    构造时依赖：chat_service（LLM 客户端适配器）、prompt_builder（可选）
    运行时依赖：从 ChatSpec 取 tool_registry, session_id 等
    """

    def __init__(self, chat_service: Any, prompt_builder: Any = None) -> None:
        self._chat_service = chat_service
        self._prompt_builder = prompt_builder

    async def stream(
        self, input: Any, spec: Any, ctx: Any,
    ) -> AsyncIterator[dict[str, Any] | StepResult]:
        from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser

        messages = list(input)  # input is messages list

        # 补充 system prompt
        system_prompt = await self._build_system_prompt(spec)
        if system_prompt and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": system_prompt}] + messages

        # 截断消息
        messages = self._safe_truncate(messages)

        # 获取 tool specs
        tools = self._get_tool_specs(getattr(spec, "tool_registry", None))

        # TextModeParser 状态机
        parser = TextModeParser()
        accumulated = ""
        thinking = ""
        tool_calls: list[dict[str, Any]] = []
        in_thinking = False

        async def end_thinking() -> None:
            nonlocal in_thinking
            if not in_thinking:
                return
            in_thinking = False

        final_done_content = ""
        content_from_parser = False

        try:
            async for ev in self._stream_llm(messages, tools):
                # 处理 terminal events
                if ev.get("type") in {"done", "phase", "error"}:
                    await end_thinking()
                if ev.get("type") == "done":
                    final_done_content = ev.get("content", "") or ""
                elif ev.get("type") == "phase":
                    phase_value = ev.get("phase")
                    if phase_value in {"cancelled", "paused", "timeout"}:
                        yield ev
                elif ev.get("type") == "error":
                    yield ev
                    return

                # TextModeParser 解析
                async for parsed in parser.feed(ev):
                    kind = parsed.get("type")
                    if kind != "thinking":
                        await end_thinking()
                    if kind == "content":
                        content_from_parser = True
                        chunk = parsed.get("text", "")
                        accumulated += chunk
                        yield {"type": "message_delta", "content": chunk}
                    elif kind == "thinking":
                        in_thinking = True
                        chunk = parsed.get("text", "")
                        thinking += chunk
                        yield {"type": "thinking", "content": chunk}
                    elif kind == "tool_call":
                        tool_calls.append(parsed)

            await end_thinking()

            # flush parser
            for flushed in parser.flush():
                if flushed.get("type") == "content":
                    content_from_parser = True
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    yield {"type": "message_delta", "content": chunk}

        except Exception as exc:
            logger.exception("LLM stream failed")
            # flush parser on error
            for flushed in parser.flush():
                if flushed.get("type") == "content":
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    yield {"type": "message_delta", "content": chunk}
            yield StepResult.fail(f"{type(exc).__name__}: {exc}")
            return

        # fallback: if parser never produced content, use done content
        if not content_from_parser and final_done_content:
            accumulated = final_done_content

        yield StepResult.ok(ReasonResponse(
            raw_content=accumulated,
            tool_calls=list(tool_calls),
            thinking=thinking,
        ))

    async def _build_system_prompt(self, spec: Any) -> str:
        """构建 system prompt — 包装 prompt_builder。"""
        if self._prompt_builder is None:
            return ""
        try:
            if hasattr(self._prompt_builder, "build_with_context"):
                from llmwikify.apps.chat.agent.prompt_builder import BuildContext
                ctx = BuildContext(
                    wiki_id=getattr(spec, "wiki_id", None),
                    workspace=getattr(spec, "workspace", None),
                    user_message="",
                    session_id=getattr(spec, "session_id", ""),
                )
                return await self._prompt_builder.build_with_context(ctx)
            if hasattr(self._prompt_builder, "build"):
                return await self._prompt_builder.build(
                    wiki_id=getattr(spec, "wiki_id", None),
                    user_message="",
                    session_id=getattr(spec, "session_id", ""),
                    workspace=getattr(spec, "workspace", None),
                )
        except Exception:
            logger.warning("prompt_builder failed", exc_info=True)
        return ""

    def _safe_truncate(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """截断消息 — 包装 chat_service._truncate_messages。"""
        method = getattr(self._chat_service, "_truncate_messages", None)
        if method is None:
            return messages
        try:
            result = method(messages)
            if inspect.iscoroutine(result):
                return messages
            return result or messages
        except Exception:
            return messages

    def _get_tool_specs(self, tool_registry: Any) -> list[dict[str, Any]]:
        """获取 tool specs — 包装 chat_service._get_toolspec。"""
        method = getattr(self._chat_service, "_get_toolspec", None)
        if method is None:
            return []
        try:
            result = method(tool_registry)
            if inspect.iscoroutine(result):
                return []
            return result or []
        except Exception:
            return []

    async def _stream_llm(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """流式 LLM 调用 — 包装 runner_v2._stream_llm 逻辑。"""
        from llmwikify.apps.chat.agent.llm_metrics import (
            call_with_metrics,
            iter_with_metrics,
        )

        chars_in = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))

        # 路径 1: chat_service._llm_stream_with_retry
        retry = getattr(self._chat_service, "_llm_stream_with_retry", None)
        if retry is not None:
            async for ev in iter_with_metrics(
                lambda: retry(messages, tools),
                prompt_name="chat_reason",
                chars_in=chars_in,
            ):
                yield ev
            return

        # 路径 2: wiki_service.get_llm().astream_chat
        llm = None
        if hasattr(self._chat_service, "wiki_service") and self._chat_service.wiki_service is not None:
            llm_getter = getattr(self._chat_service.wiki_service, "get_llm", None)
            llm = llm_getter() if callable(llm_getter) else None

        if llm is not None and hasattr(llm, "astream_chat"):
            async for ev in iter_with_metrics(
                llm.astream_chat(messages, tools=tools),
                prompt_name="chat_reason",
                chars_in=chars_in,
            ):
                yield ev
            return

        # 路径 3: fallback single-shot
        if llm is not None:
            async for ev in call_with_metrics(
                lambda: llm.chat(messages, tools=tools),
                prompt_name="chat_fallback",
                chars_in=chars_in,
            ):
                yield ev
            return

        # 无 LLM 可用
        yield {"type": "done", "content": ""}
