"""ChatRunner v2 — unified chat agent loop (Plan B Step B-2).

B-2 fills in the skeleton with the 5-step state machine:
  1. PRECHECK   timeout / cancel / pause / done-condition
  2. REASON     LLM stream with retry + text-mode [TOOL_CALL] parsing
  3. ACT        tool execution with native microcompact + DB persist
  4. OBSERVE    aggregate observations into a per-turn summary
  5. COMPLETE   finalize_content pipeline + emit done / error

CompositeHook integration covers 11 of the 13 AgentHook points
(wants_streaming and on_confirmation are detected/special-cased in
the dispatcher, not invoked directly). Microcompact defaults to ON
via :func:`build_microcompact_fn`. Text-mode ``[TOOL_CALL]`` parsing
shares ``TextModeParser`` with the existing chat_react path so a
fallback ``<tool_call>`` block in a non-tool-aware model still works.

B-2 keeps the public surface from B-1 unchanged:
  ChatRunnerV2(...).run_stream(spec)        -> AsyncIterator[dict]
  ChatRunnerV2(...).run_to_completion(spec) -> ChatRunResult

See ``docs/poc/plan-b-refactor.md`` §2 for the design.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.agent.microcompact import build_microcompact_fn
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser
from llmwikify.foundation.callback import AgentHook, AgentHookContext, NoOpHook

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _RunContext:
    spec: ChatRunSpec
    messages: list[dict[str, Any]]
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    final_content: str | None = None
    stop_reason: str = "in_progress"
    error: str | None = None
    compacted_count: int = 0
    chars_saved: int = 0
    cancelled: bool = False
    paused: bool = False
    started_at: float = field(default_factory=time.monotonic)
    last_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_accumulated: str = ""
    last_thinking: str = ""
    reason_failed: bool = False
    confirmation_required: bool = False

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def hook_ctx(self, iteration: int) -> AgentHookContext:
        return AgentHookContext(
            iteration=iteration,
            messages=list(self.messages),
            response=None,
            usage=dict(self.usage),
            tool_calls=list(self.last_tool_calls),
            tool_results=[],
            tool_events=[],
            streamed_content=bool(self.final_content),
            streamed_reasoning=bool(self.last_thinking),
            final_content=self.final_content,
            stop_reason=self.stop_reason,
            error=self.error,
            observations=list(self.observations),
            cancelled=self.cancelled,
            paused=self.paused,
            compacted_count=self.compacted_count,
            chars_saved=self.chars_saved,
        )


class ChatRunnerV2:
    """Unified chat agent loop with 5-step state machine + hook integration."""

    def __init__(
        self,
        chat_service: Any,
        tool_executor: Any,
        prompt_builder: Any,
        config: dict | None = None,
        hook: AgentHook | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder
        self._config = config or {}
        self._hook = hook or NoOpHook()
        self._microcompact_fn: Any = None

    async def run_stream(
        self, spec: ChatRunSpec,
    ) -> Any:
        ctx = _RunContext(spec=spec, messages=list(spec.messages))
        self._microcompact_fn = build_microcompact_fn(spec)

        if self._hook.wants_streaming():
            yield {"type": "session_init", "session_id": spec.session_id}

        try:
            system_prompt = await self._build_system_prompt(spec)
        except Exception as exc:
            logger.exception("system_prompt build failed")
            ctx.error = f"{type(exc).__name__}: {exc}"
            ctx.stop_reason = "error"
            async for ev in self._emit_done(ctx):
                yield ev
            return

        for iteration in range(spec.max_iterations):
            await _maybe_await(self._hook.before_iteration(ctx.hook_ctx(iteration)))

            should_break = await self._precheck(ctx)
            if should_break:
                break

            async for ev in self._reason(ctx, system_prompt, iteration):
                yield ev
            if ctx.reason_failed:
                ctx.stop_reason = "error"
                break

            if not ctx.last_tool_calls:
                ctx.final_content = ctx.last_accumulated
                if ctx.stop_reason not in {"cancelled", "paused", "timeout"}:
                    ctx.stop_reason = "completed"
                break

            async for ev in self._act(ctx, ctx.last_tool_calls, iteration):
                yield ev
            if ctx.confirmation_required:
                ctx.stop_reason = "confirmation_required"
                break

            self._observe(ctx, ctx.last_thinking)

            await _maybe_await(self._hook.after_iteration(ctx.hook_ctx(iteration)))

        async for ev in self._emit_done(ctx):
            yield ev

    async def run_to_completion(self, spec: ChatRunSpec) -> ChatRunResult:
        final_content: str | None = None
        tools_used: list[str] = []
        usage: dict[str, int] = {}
        stop_reason = "completed"
        error: str | None = None
        compacted_count = 0
        chars_saved = 0
        try:
            async for event in self.run_stream(spec):
                kind = event.get("type")
                if kind == "done":
                    final_content = event.get("content", final_content)
                    if "stop_reason" in event:
                        stop_reason = event["stop_reason"]
                elif kind == "error":
                    error = event.get("message") or event.get("error")
                    stop_reason = "error"
                elif kind == "tool_call_end":
                    tool = event.get("tool")
                    if tool and tool not in tools_used:
                        tools_used.append(tool)
                elif kind == "message_delta" and event.get("content"):
                    final_content = (final_content or "") + event["content"]
                elif kind == "compacted":
                    compacted_count += 1
                    chars_saved += int(event.get("chars_saved", 0))
                elif kind == "phase":
                    new_phase = event.get("phase")
                    if new_phase in {"cancelled", "paused", "timeout"}:
                        stop_reason = new_phase
                elif kind == "confirmation_required":
                    stop_reason = "confirmation_required"
        except Exception as exc:
            logger.exception("ChatRunnerV2.run_to_completion failed")
            error = f"{type(exc).__name__}: {exc}"
            stop_reason = "error"

        return ChatRunResult(
            final_content=final_content,
            messages=list(spec.messages),
            tools_used=tools_used,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
            compacted_count=compacted_count,
            total_compacted_chars_saved=chars_saved,
        )

    async def _build_system_prompt(self, spec: ChatRunSpec) -> str:
        if hasattr(self._prompt_builder, "build_with_context"):
            from llmwikify.apps.chat.agent.prompt_builder import BuildContext
            ctx = BuildContext(
                wiki_id=spec.wiki_id,
                workspace=spec.workspace,
                user_message=_last_user_content(spec.messages),
                session_id=spec.session_id,
            )
            return await self._prompt_builder.build_with_context(ctx)
        if hasattr(self._prompt_builder, "build"):
            return await self._prompt_builder.build(
                wiki_id=spec.wiki_id,
                user_message=_last_user_content(spec.messages),
                session_id=spec.session_id,
                workspace=spec.workspace,
            )
        return ""

    async def _precheck(self, ctx: _RunContext) -> bool:
        timeout = self._config.get("timeout_seconds", 0)
        if timeout and ctx.elapsed() > timeout:
            return True
        return ctx.cancelled or ctx.paused

    async def _reason(
        self, ctx: _RunContext, system_prompt: str, iteration: int,
    ) -> None:
        messages = list(ctx.messages)
        if system_prompt and not any(
            m.get("role") == "system" for m in messages
        ):
            messages = [{"role": "system", "content": system_prompt}] + messages

        messages = self._safe_truncate(messages)

        try:
            tools = self._get_tool_specs(ctx.spec.tool_registry)
        except Exception:
            logger.warning("get_tool_specs failed", exc_info=True)
            tools = []

        parser = TextModeParser()
        accumulated = ""
        thinking = ""
        tool_calls: list[dict[str, Any]] = []

        final_done_content = ""
        content_from_parser = False
        try:
            async for ev in self._stream_llm(messages, tools):
                if ev.get("type") == "done":
                    final_done_content = ev.get("content", "") or ""
                elif ev.get("type") == "phase":
                    phase_value = ev.get("phase")
                    if phase_value in {"cancelled", "paused", "timeout"}:
                        ctx.stop_reason = phase_value
                    yield ev
                elif ev.get("type") == "error":
                    ctx.error = ev.get("message") or ev.get("error") or ctx.error
                    ctx.reason_failed = True
                    yield ev
                    return
                async for parsed in parser.feed(ev):
                    kind = parsed.get("type")
                    if kind == "content":
                        content_from_parser = True
                        chunk = parsed.get("text", "")
                        accumulated += chunk
                        await _maybe_await(self._hook.on_stream(
                            ctx.hook_ctx(iteration), chunk,
                        ))
                        yield_event = {"type": "message_delta", "content": chunk}
                    elif kind == "thinking":
                        chunk = parsed.get("text", "")
                        thinking += chunk
                        await _maybe_await(self._hook.emit_reasoning(
                            ctx.hook_ctx(iteration), chunk,
                        ))
                        yield_event = {"type": "thinking", "content": chunk}
                    elif kind == "tool_call":
                        tool_calls.append(parsed)
                        yield_event = None
                    else:
                        yield_event = None
                    if yield_event is not None:
                        yield yield_event
            for flushed in parser.flush():
                kind = flushed.get("type")
                if kind == "content":
                    content_from_parser = True
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    await _maybe_await(self._hook.on_stream(
                        ctx.hook_ctx(iteration), chunk,
                    ))
                    yield {"type": "message_delta", "content": chunk}
        except Exception as exc:
            logger.exception("LLM stream failed")
            ctx.error = f"{type(exc).__name__}: {exc}"
            ctx.reason_failed = True
            for flushed in parser.flush():
                kind = flushed.get("type")
                if kind == "content":
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    yield {"type": "message_delta", "content": chunk}
            if not content_from_parser and accumulated:
                pass
            return

        if not content_from_parser and final_done_content:
            accumulated = final_done_content

        ctx.last_accumulated = accumulated
        ctx.last_thinking = thinking
        ctx.last_tool_calls = list(tool_calls)
        ctx.reason_failed = False

    async def _act(
        self, ctx: _RunContext, tool_calls: list[dict[str, Any]], iteration: int,
    ) -> None:
        await _maybe_await(self._hook.before_execute_tools(ctx.hook_ctx(iteration)))
        ctx.confirmation_required = False

        for _idx, tc in enumerate(tool_calls):
            tool_name = tc.get("name") or tc.get("tool", "")
            raw_args = tc.get("args", {}) or {}
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except (TypeError, ValueError):
                    args = {"_raw": raw_args}
            else:
                args = raw_args
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

            try:
                result = await self._execute_tool(
                    tool_name, args, ctx.spec.tool_registry,
                    ctx.spec.session_id, ctx,
                )
            except Exception as exc:
                logger.warning("Tool %s failed", tool_name, exc_info=True)
                await _maybe_await(self._hook.on_tool_error(
                    ctx.hook_ctx(iteration), tc, exc,
                ))
                yield {
                    "type": "tool_call_error",
                    "tool": tool_name,
                    "error": str(exc),
                    "call_id": call_id,
                }
                continue

            await _maybe_await(self._hook.after_tool_executed(
                ctx.hook_ctx(iteration), tc, result,
            ))

            if isinstance(result, dict) and result.get("status") == "confirmation_required":
                ctx.confirmation_required = True
                await _maybe_await(self._hook.on_confirmation(
                    ctx.hook_ctx(iteration), tc,
                ))
                yield {
                    "type": "confirmation_required",
                    "confirmation_id": result.get("confirmation_id", ""),
                    "tool": tool_name,
                    "args": args,
                    "impact": result.get("impact", {}),
                    "call_id": call_id,
                }
                break

            if isinstance(result, dict) and result.get("status") == "error":
                yield {
                    "type": "tool_call_error",
                    "tool": tool_name,
                    "error": str(result.get("error", "")),
                    "call_id": call_id,
                }
                continue

            content, compacted, saved = self._microcompact_result(
                result, tool_name, call_id,
            )
            if compacted:
                ctx.compacted_count += 1
                ctx.chars_saved += saved
                yield {
                    "type": "compacted",
                    "call_id": call_id,
                    "tool": tool_name,
                    "chars_saved": saved,
                }

            tool_msg = {
                "role": "tool",
                "name": tool_name,
                "content": content,
                "tool_call_id": call_id,
            }
            ctx.messages.append(tool_msg)

            ctx.tools_used.append(tool_name)
            yield {
                "type": "tool_call_end",
                "tool": tool_name,
                "result": result,
                "call_id": call_id,
            }

        ctx.last_tool_calls = []

    def _observe(self, ctx: _RunContext, last_thinking: str) -> None:
        if last_thinking:
            truncated = last_thinking[:200]
            ctx.observations.append(f"thought: {truncated}")

    def _microcompact_result(
        self, result: Any, tool_name: str, call_id: str,
    ) -> tuple[str, bool, int]:
        if self._microcompact_fn is None:
            return json.dumps(result, ensure_ascii=False, default=str), False, 0
        return self._microcompact_fn(result, tool_name, call_id)

    async def _emit_done(self, ctx: _RunContext):
        if ctx.error is not None:
            try:
                await _maybe_await(self._hook.on_error(
                    ctx.hook_ctx(0), RuntimeError(ctx.error),
                ))
            except Exception:
                logger.warning("on_error hook raised", exc_info=True)
            yield {
                "type": "error",
                "message": ctx.error,
                "stop_reason": ctx.stop_reason,
            }
        try:
            final = await _maybe_await(self._hook.finalize_content(
                ctx.hook_ctx(0), ctx.final_content,
            ))
        except Exception:
            logger.warning("finalize_content hook raised", exc_info=True)
            final = ctx.final_content
        yield {
            "type": "done",
            "content": final or ctx.final_content or "",
            "stop_reason": ctx.stop_reason,
            "error": ctx.error,
            "compacted_count": ctx.compacted_count,
        }

    def _safe_truncate(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        truncate_fn = getattr(self._chat_service, "_truncate_messages", None)
        if truncate_fn is None:
            return messages
        try:
            result = truncate_fn(messages)
            if inspect.iscoroutine(result):
                return messages
            return result
        except Exception:
            logger.warning("truncate failed", exc_info=True)
            return messages

    def _get_tool_specs(self, tool_registry: Any) -> list[dict[str, Any]]:
        get_specs = getattr(self._chat_service, "_get_toolspec", None)
        if get_specs is None:
            return []
        try:
            result = get_specs(tool_registry)
            if inspect.iscoroutine(result):
                return []
            return result or []
        except Exception:
            logger.warning("get_toolspec failed", exc_info=True)
            return []

    async def _stream_llm(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> Any:
        retry = getattr(self._chat_service, "_llm_stream_with_retry", None)
        llm = None
        if hasattr(self._chat_service, "wiki_service") and self._chat_service.wiki_service is not None:
            llm = getattr(self._chat_service.wiki_service, "get_llm", None)
            llm = llm() if callable(llm) else None
        if retry is not None:
            async for ev in retry(messages, tools):
                yield ev
            return
        if llm is None:
            yield {"type": "done", "content": ""}
            return
        if hasattr(llm, "astream_chat"):
            async for ev in llm.astream_chat(messages, tools=tools):
                yield ev
            return
        reply = llm.chat(messages, tools=tools)
        yield {
            "type": "done",
            "content": getattr(reply, "content", "") or "",
        }

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_registry: Any,
        session_id: str,
        ctx: _RunContext,
    ) -> Any:
        executor = self._tool_executor
        if hasattr(executor, "execute"):
            result = executor.execute(
                tool_name, args, tool_registry, session_id, ctx,
            )
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


def _last_user_content(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
