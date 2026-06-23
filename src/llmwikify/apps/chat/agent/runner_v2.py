"""ChatRunner v2 — unified chat agent loop (Plan B Step B-2).

B-2 fills in the skeleton with the 5-step state machine:
  1. PRECHECK   timeout / cancel / pause / done-condition
  2. REASON     LLM stream with retry + text-mode [TOOL_CALL] parsing
  3. ACT        tool execution with native microcompact + DB persist
  4. OBSERVE    aggregate observations into a per-turn summary
  5. COMPLETE   finalize_content pipeline + emit done / error

CompositeHook integration covers all 13 AgentHook points:
  wants_streaming, before_iteration, on_stream, on_stream_end,
  emit_reasoning, emit_reasoning_end, before_execute_tools,
  after_tool_executed, on_tool_error, on_confirmation, after_iteration,
  finalize_content, on_error. Microcompact defaults to ON
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

from llmwikify.apps.chat.agent import events
from llmwikify.apps.chat.agent.agent_runner import AgentRunner
from llmwikify.apps.chat.agent.microcompact import build_microcompact_fn
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser
from llmwikify.foundation.callback import AgentHook, AgentHookContext, NoOpHook
from llmwikify.foundation.utils import maybe_await as _maybe_await
from llmwikify.foundation.utils_timing import measure_latency

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _StateTraceEntry:
    """Single state transition in the 5-step machine.

    Pattern borrowed from nanobot v0.2.1 ``StateTraceEntry``
    (``nanobot/agent/loop.py``) but trimmed to our 5 steps.
    """

    state: str
    started_at: float
    duration_ms: float
    event: str  # "ok" | "error" | "skipped"
    error: str | None = None


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
    state_trace: list[_StateTraceEntry] = field(default_factory=list)

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


class ChatRunnerV2(AgentRunner["ChatRunSpec", "ChatRunResult"]):
    """Unified chat agent loop with 5-step state machine + hook integration.

    Phase 15 (2026-06-21): now extends :class:`AgentRunner` so it
    participates in the shared "agent loop" abstraction borrowed from
    nanobot v0.2.1 ``AgentRunner``. The public contract (``run_stream`` /
    ``run_to_completion``) is unchanged; existing callers see no
    difference. New callers can use ``AgentRunner`` as the interface
    type and pass any implementation (including test stubs).
    """

    def __init__(
        self,
        chat_service: Any,
        tool_executor: Any,
        prompt_builder: Any,
        config: dict | None = None,
        hook: AgentHook | None = None,
        memory_manager: Any | None = None,
    ) -> None:
        # Pass7 (2026-06-22, M-2): ``chat_service`` duck-types the
        # :class:`ChatServiceAdapter` Protocol (apps/chat/agent/protocols.py).
        # We keep ``Any`` at the parameter boundary so 100+ existing test
        # stubs (which may not implement all 3 methods) keep working, but
        # the Protocol documents the contract for IDE / mypy navigation.
        # Production wiring uses ``ChatBridgeBackend`` which satisfies the
        # Protocol structurally.
        self._chat_service = chat_service
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder
        self._config = config or {}
        self._hook = hook or NoOpHook()
        self._microcompact_fn: Any = None
        # Phase 6 (2026-06-19): Optional MemoryManager for after-iteration
        # consolidation (borrowed from nanobot Consolidator architecture).
        # If supplied, ``run_stream`` will call ``consolidate_session``
        # after each iteration (after the existing ``after_iteration`` hook).
        # See ``docs/poc/apply-plan.md`` §6 for the rationale.
        self._memory_manager = memory_manager

    async def run_stream(
        self, spec: ChatRunSpec,
    ) -> Any:
        ctx = _RunContext(spec=spec, messages=list(spec.messages))
        self._microcompact_fn = build_microcompact_fn(spec)
        # Stash the live context so run_to_completion can read the
        # accumulated state_trace after consuming the stream.
        self._current_ctx = ctx

        if self._hook.wants_streaming():
            yield {"type": events.SESSION_INIT, "session_id": spec.session_id}

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

            with _StateTrace(ctx, "PRECHECK") as tr:
                should_break = await self._precheck(ctx)
            if should_break:
                tr.event = "skipped"
                break

            with _StateTrace(ctx, "REASON"):
                async for ev in self._reason(ctx, system_prompt, iteration):
                    yield ev
            if ctx.reason_failed:
                ctx.stop_reason = "error"
                break

            if ctx.last_tool_calls:
                self._append_assistant_tool_calls(ctx)

            if not ctx.last_tool_calls:
                ctx.final_content = ctx.last_accumulated
                if ctx.stop_reason not in {"cancelled", "paused", "timeout"}:
                    ctx.stop_reason = "completed"
                break

            with _StateTrace(ctx, "ACT"):
                async for ev in self._act(ctx, ctx.last_tool_calls, iteration):
                    yield ev
            if ctx.confirmation_required:
                ctx.stop_reason = "confirmation_required"
                break

            with _StateTrace(ctx, "OBSERVE"):
                self._observe(ctx, ctx.last_thinking)

            await _maybe_await(self._hook.after_iteration(ctx.hook_ctx(iteration)))

            # Phase 6 (2026-06-19): Optional memory consolidation after
            # each iteration. Borrowed from nanobot Consolidator
            # architecture; uses MemoryManager.consolidate_session()
            # which is a thin shim over Consolidator.maybe_consolidate.
            # Failures are logged + swallowed (don't break the chat loop).
            if self._memory_manager is not None and self._memory_manager.consolidator is not None:
                try:
                    session_id = getattr(spec, "session_id", None) or ctx.session_id
                    messages = list(ctx.messages) if hasattr(ctx, "messages") else []
                    total_tokens = sum(
                        len(str(m.get("content", ""))) // 4
                        for m in messages
                    )
                    if session_id and messages:
                        result = await self._memory_manager.consolidate_session(
                            session_id=session_id,
                            messages=messages,
                            session_tokens=total_tokens,
                        )
                        if result is not None:
                            ctx.compacted_count += 1
                except Exception:
                    logger.warning(
                        "memory consolidation failed in run_stream", exc_info=True,
                    )

        with _StateTrace(ctx, "FINALIZE"):
            async for ev in self._emit_done(ctx):
                yield ev

        # Note: ``self._current_ctx`` is left pointing at this run's
        # context so ``run_to_completion`` can read the trace. It is
        # overwritten on the next ``run_stream`` call.

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
                if kind == events.DONE:
                    final_content = event.get("content", final_content)
                    if "stop_reason" in event:
                        stop_reason = event["stop_reason"]
                elif kind == events.ERROR:
                    error = event.get("message") or event.get("error")
                    stop_reason = "error"
                elif kind == events.TOOL_CALL_END:
                    tool = event.get("tool")
                    if tool and tool not in tools_used:
                        tools_used.append(tool)
                elif kind == events.MESSAGE_DELTA and event.get("content"):
                    final_content = (final_content or "") + event["content"]
                elif kind == events.COMPACTED:
                    compacted_count += 1
                    chars_saved += int(event.get("chars_saved", 0))
                elif kind == events.PHASE:
                    new_phase = event.get("phase")
                    if new_phase in {"cancelled", "paused", "timeout"}:
                        stop_reason = new_phase
                elif kind == events.CONFIRMATION_REQUIRED:
                    stop_reason = "confirmation_required"
        except Exception as exc:
            logger.exception("ChatRunnerV2.run_to_completion failed")
            error = f"{type(exc).__name__}: {exc}"
            stop_reason = "error"

        # Pull the state trace from the live context if it was kept
        # on the instance; otherwise (e.g. an error before the first
        # iteration) emit an empty list.
        live_ctx = getattr(self, "_current_ctx", None)
        trace_entries = live_ctx.state_trace if live_ctx is not None else []

        return ChatRunResult(
            final_content=final_content,
            messages=list(spec.messages),
            tools_used=tools_used,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
            compacted_count=compacted_count,
            total_compacted_chars_saved=chars_saved,
            state_trace=[
                {
                    "state": e.state,
                    "started_at": e.started_at,
                    "duration_ms": e.duration_ms,
                    "event": e.event,
                    "error": e.error,
                }
                for e in trace_entries
            ],
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
        # Phase 10 (2026-06-20): goal-active predicate (borrowed from
        # nanobot ``AgentRunSpec.goal_active_predicate``). The
        # orchestrator typically wires this to a closure reading
        # ``chat_sessions.metadata['goal_state'].status``. Predicate
        # exceptions are swallowed (don't kill the loop on a transient
        # DB hiccup); returning False sets stop_reason="goal_abandoned".
        pred = ctx.spec.goal_active_predicate
        if pred is not None:
            try:
                if not pred():
                    ctx.stop_reason = "goal_abandoned"
                    return True
            except Exception:
                logger.warning(
                    "goal_active_predicate raised; ignoring",
                    exc_info=True,
                )
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
        in_thinking = False

        async def end_thinking() -> None:
            nonlocal in_thinking
            if not in_thinking:
                return
            in_thinking = False
            try:
                await _maybe_await(self._hook.emit_reasoning_end(
                    ctx.hook_ctx(iteration),
                ))
            except Exception:
                logger.warning(
                    "emit_reasoning_end hook raised", exc_info=True,
                )

        final_done_content = ""
        content_from_parser = False
        try:
            async for ev in self._stream_llm(messages, tools):
                if ev.get("type") in {events.DONE, events.PHASE, events.ERROR}:
                    await end_thinking()
                if ev.get("type") == events.DONE:
                    final_done_content = ev.get("content", "") or ""
                elif ev.get("type") == events.PHASE:
                    phase_value = ev.get("phase")
                    if phase_value in {"cancelled", "paused", "timeout"}:
                        ctx.stop_reason = phase_value
                    yield ev
                elif ev.get("type") == events.ERROR:
                    ctx.error = ev.get("message") or ev.get("error") or ctx.error
                    ctx.reason_failed = True
                    yield ev
                    return
                async for parsed in parser.feed(ev):
                    kind = parsed.get("type")
                    if kind != "thinking":
                        await end_thinking()
                    if kind == "content":
                        content_from_parser = True
                        chunk = parsed.get("text", "")
                        accumulated += chunk
                        await _maybe_await(self._hook.on_stream(
                            ctx.hook_ctx(iteration), chunk,
                        ))
                        yield_event = {"type": events.MESSAGE_DELTA, "content": chunk}
                    elif kind == "thinking":
                        in_thinking = True
                        chunk = parsed.get("text", "")
                        thinking += chunk
                        await _maybe_await(self._hook.emit_reasoning(
                            ctx.hook_ctx(iteration), chunk,
                        ))
                        yield_event = {"type": events.THINKING, "content": chunk}
                    elif kind == "tool_call":
                        tool_calls.append(parsed)
                        yield_event = None
                    else:
                        yield_event = None
                    if yield_event is not None:
                        yield yield_event
            await end_thinking()
            for flushed in parser.flush():
                kind = flushed.get("type")
                if kind == "content":
                    content_from_parser = True
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    await _maybe_await(self._hook.on_stream(
                        ctx.hook_ctx(iteration), chunk,
                    ))
                    yield {"type": events.MESSAGE_DELTA, "content": chunk}
        except Exception as exc:
            logger.exception("LLM stream failed")
            ctx.error = f"{type(exc).__name__}: {exc}"
            ctx.reason_failed = True
            for flushed in parser.flush():
                kind = flushed.get("type")
                if kind == "content":
                    chunk = flushed.get("text", "")
                    accumulated += chunk
                    yield {"type": events.MESSAGE_DELTA, "content": chunk}
            return
        else:
            try:
                await _maybe_await(self._hook.on_stream_end(
                    ctx.hook_ctx(iteration), resuming=False,
                ))
            except Exception:
                logger.warning("on_stream_end hook raised", exc_info=True)

        if not content_from_parser and final_done_content:
            accumulated = final_done_content

        ctx.last_accumulated = accumulated
        ctx.last_thinking = thinking
        ctx.last_tool_calls = list(tool_calls)
        ctx.reason_failed = False

    @staticmethod
    def _append_assistant_tool_calls(ctx: _RunContext) -> None:
        """Resolve tool_call ids and append the assistant message.

        Required so the next iteration's LLM call sees a matching
        ``assistant(tool_calls[i].id)`` declaration for every
        ``tool(tool_call_id)`` we are about to push. Without this,
        providers like minimax return 400
        ``tool result's tool id(call_xxx) not found (2013)`` on
        iteration 2 because no assistant message declared the
        tool_call that produced the pending tool result.

        Id resolution: streamable may not propagate ``id`` for
        text-mode / older streams, so we generate a stable local id
        here once and reuse it in :meth:`_act` for the tool message.
        """
        resolved: list[dict[str, Any]] = []
        for tc in ctx.last_tool_calls:
            resolved.append({
                **tc,
                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            })
        ctx.last_tool_calls = resolved
        ctx.messages.append({
            "role": "assistant",
            "content": ctx.last_accumulated or "",
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name") or tc.get("tool", ""),
                        "arguments": (
                            json.dumps(tc.get("args", {}), ensure_ascii=False)
                            if isinstance(tc.get("args"), (dict, list))
                            else str(tc.get("args", "") or "")
                        ),
                    },
                }
                for tc in resolved
            ],
        })

    async def _act(
        self, ctx: _RunContext, tool_calls: list[dict[str, Any]], iteration: int,
    ) -> None:
        await _maybe_await(self._hook.before_execute_tools(ctx.hook_ctx(iteration)))
        ctx.confirmation_required = False
        ctx.last_tool_calls = []

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
                    "type": events.TOOL_CALL_ERROR,
                    "tool": "",
                    "error": "Skipped malformed tool call with empty name",
                    "call_id": call_id,
                }
                continue

            yield {
                "type": events.TOOL_CALL_START,
                "tool": tool_name,
                "args": args,
                "call_id": call_id,
            }

            # Pass5 (2026-06-22): wrap tool execution with measure_latency
            # CM so the resulting TOOL_CALL_END / TOOL_CALL_ERROR events
            # carry a real ``duration_ms`` value (was previously always 0).
            # The CM is a no-op cost (~3 lines, ~1us) and is the
            # decorator-pattern Phase 5 step for runner_v2 (mirrors
            # nanobot's inline ``time.monotonic() - start`` pattern).
            with measure_latency() as get_ms:
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
                        "type": events.TOOL_CALL_ERROR,
                        "tool": tool_name,
                        "error": str(exc),
                        "call_id": call_id,
                        "duration_ms": get_ms(),
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
                    "type": events.CONFIRMATION_REQUIRED,
                    "confirmation_id": result.get("confirmation_id", ""),
                    "tool": tool_name,
                    "args": args,
                    "impact": result.get("impact", {}),
                    "call_id": call_id,
                }
                break

            if isinstance(result, dict) and result.get("status") == "error":
                yield {
                    "type": events.TOOL_CALL_ERROR,
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
                    "type": events.COMPACTED,
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
                "type": events.TOOL_CALL_END,
                "tool": tool_name,
                "result": result,
                "call_id": call_id,
                "duration_ms": get_ms(),
            }

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
                "type": events.ERROR,
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
            "type": events.DONE,
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
        # Pass7+R-1 (2026-06-23): the per-path ``measure_latency`` +
        # metrics-recording boilerplate was extracted into the
        # ``iter_with_metrics`` / ``call_with_metrics`` helpers in
        # ``apps/chat/agent/llm_metrics.py``. This method is now a
        # thin dispatcher that picks one of three LLM source paths
        # and delegates timing+recording to the helper.
        from llmwikify.apps.chat.agent.llm_metrics import (
            call_with_metrics,
            iter_with_metrics,
        )

        retry = getattr(self._chat_service, "_llm_stream_with_retry", None)
        llm = None
        if hasattr(self._chat_service, "wiki_service") and self._chat_service.wiki_service is not None:
            llm = getattr(self._chat_service.wiki_service, "get_llm", None)
            llm = llm() if callable(llm) else None

        # Compute chars_in for metrics (sum of message contents).
        chars_in = 0
        if messages:
            for m in messages:
                if isinstance(m, dict):
                    chars_in += len(str(m.get("content", "")))

        if retry is not None:
            async for ev in iter_with_metrics(
                lambda: retry(messages, tools),
                prompt_name="chat_reason",
                chars_in=chars_in,
            ):
                yield ev
            return
        if llm is None:
            yield {"type": events.DONE, "content": ""}
            return
        if hasattr(llm, "astream_chat"):
            async for ev in iter_with_metrics(
                llm.astream_chat(messages, tools=tools),
                prompt_name="chat_reason",
                chars_in=chars_in,
            ):
                yield ev
            return
        # Fallback single-shot — recorded under "chat_fallback" tag.
        async for ev in call_with_metrics(
            lambda: llm.chat(messages, tools=tools),
            prompt_name="chat_fallback",
            chars_in=chars_in,
        ):
            yield ev

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


class _StateTrace:
    """Context manager that records a state transition.

    Records ``{state, started_at, duration_ms, event, error}`` to
    ``ctx.state_trace``.  Pattern from nanobot v0.2.1
    ``StateTraceEntry`` — but ours is a context manager so the
    per-step wrapper stays a single line::

        with _StateTrace(ctx, "REASON") as tr:
            ...
    """

    __slots__ = ("_ctx", "state", "_start", "event", "error")

    def __init__(self, ctx: _RunContext, state: str) -> None:
        self._ctx = ctx
        self.state = state
        self._start = 0.0
        self.event = "ok"
        self.error: str | None = None

    def __enter__(self) -> _StateTrace:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = (time.monotonic() - self._start) * 1000.0
        if exc is not None:
            self.event = "error"
            self.error = f"{type(exc).__name__}: {exc}"
        self._ctx.state_trace.append(_StateTraceEntry(
            state=self.state,
            started_at=self._start,
            duration_ms=duration_ms,
            event=self.event,
            error=self.error,
        ))
        return False  # do not suppress exception
