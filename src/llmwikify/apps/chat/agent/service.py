"""ChatService — SSE chat service inheriting from ChatBase.

ChatService extends ChatBase with:

  - DB persistence (ChatDatabase)
  - SSE event streaming
  - AgentContext conversation state
  - @wiki_id prefix parsing
  - Message truncation
  - Tool execution with confirmation flow

It delegates wiki operations to WikiService.

Design ref: ``v0.32-execution-plan.md`` Phase 13e
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.base import ChatBase
from llmwikify.apps.chat.db import ChatDatabase

logger = logging.getLogger(__name__)


# ─── Text-mode tool-call parsing ────────────────────────────────
#
# Some LLMs (especially smaller or non-tool-aware ones) emit tool
# calls as inline text instead of using the OpenAI-style structured
# ``tool_calls`` field. The most common pattern is::
#
#     [TOOL_CALL] {tool => "wiki_read_page",
#                  args => { --page_name "overview" }} [/TOOL_CALL]
#
# We detect and execute these blocks the same way as native tool
# calls, suppressing the leaked markup from the user-visible stream.

_TOOL_CALL_RE = re.compile(
    r"\[TOOL_CALL\]\s*(.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL,
)


def _parse_perl_args(body: str) -> dict[str, str]:
    """Parse a Perl-style ``{key => value, ...}`` hash into a dict.

    Supports::
        tool => "wiki_read_page"
        "page_name" => "overview"
        --page_name "overview"
    """
    out: dict[str, str] = {}
    s = body.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    for part in re.split(r",\s*", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"--(\w+)\s+(.+)$", part, re.DOTALL)
        if m:
            out[m.group(1)] = _unquote(m.group(2).strip())
            continue
        m = re.match(
            r'(?:"(\w+)"|(\w+))\s*=>\s*(.+)$',
            part,
            re.DOTALL,
        )
        if m:
            key = m.group(1) or m.group(2)
            val = m.group(3).strip().rstrip(",").strip()
            out[key] = _unquote(val)
    return out


def _unquote(s: str) -> str:
    """Strip a single layer of matching surrounding quotes."""
    if len(s) >= 2 and (
        (s.startswith('"') and s.endswith('"'))
        or (s.startswith("'") and s.endswith("'"))
    ):
        return s[1:-1]
    return s


def _parse_text_tool_call(body: str) -> tuple[str, dict[str, str]] | None:
    """Extract ``(tool_name, args)`` from the body of a [TOOL_CALL] block.

    Returns ``None`` if the body is not a recognisable tool-call form,
    in which case the caller should pass the text through verbatim.
    """
    m = re.search(r'tool\s*=>\s*"([^"]+)"', body)
    if not m:
        return None
    tool_name = m.group(1).strip()
    args = _extract_args_block(body)
    return tool_name, args


def _extract_args_block(body: str) -> dict[str, str]:
    """Find ``args => { ... }`` in ``body`` and parse the inner hash.

    Counts nested braces so we capture the full inner hash even when
    argument values themselves contain braces. Returns an empty dict
    if no ``args =>`` block is found.
    """
    m = re.search(r"args\s*=>\s*\{", body)
    if not m:
        return {}
    start = m.end()  # position right after the opening '{'
    depth = 1
    i = start
    in_str: str | None = None
    while i < len(body):
        ch = body[i]
        if in_str:
            if ch == "\\" and i + 1 < len(body):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return _parse_perl_args(body[start:i])
        i += 1
    return {}


# ─── SSE event factory ────────────────────────────────────────────


class ChatEvent:
    """Static factory for SSE event dicts."""

    @staticmethod
    def message_delta(content: str) -> dict:
        return {"type": "message_delta", "content": content}

    @staticmethod
    def thinking(content: str) -> dict:
        return {"type": "thinking", "content": content}

    @staticmethod
    def tool_call_start(tool: str, args: dict) -> dict:
        return {"type": "tool_call_start", "tool": tool, "args": args}

    @staticmethod
    def tool_call_end(tool: str, result: Any) -> dict:
        return {"type": "tool_call_end", "tool": tool, "result": result}

    @staticmethod
    def confirmation_required(conf_id: str, impact: dict) -> dict:
        return {
            "type": "confirmation_required",
            "confirmation_id": conf_id,
            "impact": impact,
        }

    @staticmethod
    def done(final_response: str) -> dict:
        return {"type": "done", "final_response": final_response}

    @staticmethod
    def error(message: str) -> dict:
        return {"type": "error", "message": message}

    @staticmethod
    def save_warning(message: str) -> dict:
        """Non-fatal DB persistence warning (Phase 1.2 / v0.36).

        Returned alongside the chat flow so the frontend can
        optionally surface persistence issues without aborting
        the user-visible response.
        """
        return {"type": "save_warning", "message": message}


# ─── Per-session conversation state ───────────────────────────────


@dataclass
class AgentContext:
    """In-memory conversation state for one session."""

    wiki_id: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    recent_wiki_id: str | None = None
    # Phase 1.1 (v0.36): tool call registry keyed by tool name.
    # ``_recent_tool_entries`` is an ordered list that records
    # *every* invocation (even if the same tool runs again with
    # different args). ``tool_invocations`` is a monotonic counter
    # used by the chat loop to detect "did this iteration dispatch
    # new tools?".
    _tool_calls: dict[str, Any] = field(default_factory=dict)
    _recent_tool_entries: list[dict[str, Any]] = field(default_factory=list)
    tool_invocations: int = 0

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        return list(self.messages)

    def set_recent_wiki(self, wiki_id: str) -> None:
        self.recent_wiki_id = wiki_id


# ─── ChatService ──────────────────────────────────────────────────


class ChatService(ChatBase):
    """SSE chat service with DB persistence and wiki integration.

    Extends ChatBase with database-backed session management,
    SSE event streaming, and wiki tool execution. Wiki
    operations are delegated to WikiService.
    """

    def __init__(
        self,
        wiki_service: Any,
        data_dir: Path,
        chat_db: ChatDatabase | None = None,
    ):
        self.wiki_service = wiki_service
        # Phase 1.5 (v0.36): allow caller to inject a shared
        # ChatDatabase instance to avoid opening two connections
        # against the same .llmwiki_agent.db file.
        self.db = chat_db if chat_db is not None else ChatDatabase(data_dir)
        self._contexts: dict[str, AgentContext] = {}
        # Phase 1.2 (v0.36): track silent DB write failures so
        # they are surfaced to operators via logs / metrics.
        self._save_error_count: int = 0

        # Initialize ChatBase with LLM from WikiService
        llm = wiki_service.get_llm()
        super().__init__(llm_client=llm)

    # ─── SSE chat ────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
        """Stream a chat response as SSE events.

        Phase 2 (v0.36): delegates the iterative tool-call loop
        to ``ChatBase.aask_with_tools``. ChatService still owns
        the SSE event shape, wiki prefix parsing, session
        persistence, and text-mode ``[TOOL_CALL]`` parsing (via
        a custom ``invoke_tool`` callback).
        """
        if session_id is None:
            session_id = self.db.create_chat_session(wiki_id, jwt_token)
            yield {"type": "session_created", "session_id": session_id}
        else:
            session = self.db.get_chat_session(session_id)
            if session is None:
                session_id = self.db.create_chat_session(wiki_id, jwt_token)
                yield {"type": "session_created", "session_id": session_id}

        ctx = self._get_or_create_context(session_id, wiki_id)

        wiki_id_from_prefix, message = self._parse_wiki_prefix(message)
        if wiki_id_from_prefix:
            ctx.set_recent_wiki(wiki_id_from_prefix)
            self.db.update_chat_session_wiki(session_id, wiki_id_from_prefix)

        if wiki_id and not wiki_id_from_prefix:
            ctx.set_recent_wiki(wiki_id)
            self.db.update_chat_session_wiki(session_id, wiki_id)

        if jwt_token:
            self.db.update_chat_session_jwt(session_id, jwt_token)

        ctx.add_user_message(message)
        self._save_message(session_id, "user", message)

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = self.wiki_service.get_tool_registry(
            ctx.wiki_id or self.wiki_service.get_default_wiki_id()
        )

        system_prompt = self._build_system_prompt(ctx.wiki_id)
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        messages_for_llm = self._truncate_messages(raw_messages)
        # Phase 2.3 (v0.36): reset the text-mode buffer so a
        # previous turn's leftover state doesn't leak in.
        self._reset_text_mode_buffer()

        # Inject any tool calls already dispatched in previous
        # iterations as ``tool`` role messages so the LLM sees
        # them when iterating.
        # (Phase 2.2 / v0.36: the loop appends to messages_for_llm
        # in place via the ``invoke_tool`` callback.)

        try:
            # Phase 2.2 (v0.36): delegate the iterative loop to
            # ChatBase.aask_with_tools. The ``invoke_tool``
            # callback preserves the existing text-mode parsing,
            # confirmation handling, and DB persistence. The
            # callback yields its own events (tool_call_start,
            # tool_call_end, confirmation_required) which we
            # forward to the SSE stream in order.
            extra_events: list[dict] = []

            async def invoke(name: str, args: dict) -> Any:
                """Tool callback: run dispatch, append events,
                return the result so ChatBase can feed it back.

                The callback's emitted events are forwarded to
                the SSE stream before each aask_with_tools
                event so the natural ordering is preserved
                (tool_call_start → tool_call_end →
                confirmation_required).
                """
                result: Any = None
                async for ev in self._dispatch_tool_call(
                    name, args, tool_registry, session_id, ctx,
                ):
                    extra_events.append(ev)
                    if ev.get("type") == "tool_call_end":
                        result = ev.get("result")
                return result

            async for ev in self.aask_with_tools(
                messages_for_llm,
                tools=self._get_toolspec(tool_registry),
                max_iterations=self.DEFAULT_MAX_CHAT_ITERATIONS,
                invoke_tool=invoke,
            ):
                # Forward all events queued by the callback
                # BEFORE yielding aask_with_tools' own event.
                # This keeps ordering: tool_call_start (aask)
                # → tool_call_end (callback) → next event
                while extra_events:
                    yield extra_events.pop(0)
                kind = ev.get("type")
                if kind == "done":
                    final = ev.get("final_response", "")
                    thinking = ev.get("thinking", "")
                    if thinking:
                        ctx._thinking = thinking
                    ctx.add_assistant_message(final)
                    self._save_message(
                        session_id, "assistant", final,
                        tool_calls=list(ctx._tool_calls.values())
                        if ctx._tool_calls else None,
                    )
                    if self._save_error_count > 0:
                        yield ChatEvent.save_warning(
                            f"已丢弃 {self._save_error_count} 条消息的持久化失败"
                        )
                    yield ChatEvent.done(final)
                    continue
                yield ev
            # Final drain in case aask_with_tools ended
            # without a follow-up event.
            while extra_events:
                yield extra_events.pop(0)

        except Exception as e:
            logger.exception("Chat error")
            yield ChatEvent.error(str(e))

    # ─── Confirmation continue (calls WikiService) ───────────────

    async def approve_confirmation_continue(
        self,
        confirmation_id: str,
        session_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Approve a confirmation, execute tool, feed result back to LLM.

        Phase 2.2 (v0.36): uses ChatBase.aask_with_tools so
        the post-confirmation LLM follow-up also benefits from
        the iterative loop (a confirmation-approved tool may
        trigger further tool calls).
        """
        wiki_id = wiki_id or self.wiki_service.get_default_wiki_id()
        if not wiki_id:
            yield ChatEvent.error("No wiki_id available")
            return

        result = await self.wiki_service.approve_confirmation(
            confirmation_id, wiki_id, arguments
        )

        if result.get("status") == "error":
            yield ChatEvent.error(result.get("error", "Confirmation failed"))
            return

        yield ChatEvent.tool_call_end("confirmation_approved", result)

        ctx = self._get_or_create_context(session_id, wiki_id)
        tool_result_str = json.dumps(result.get("result", result))
        ctx.add_assistant_message(
            f"[Confirmation approved] Tool result: {tool_result_str}"
        )

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = self.wiki_service.get_tool_registry(
            ctx.wiki_id or self.wiki_service.get_default_wiki_id()
        )
        system_prompt = self._build_system_prompt(ctx.wiki_id)
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        messages_for_llm = self._truncate_messages(raw_messages)
        # Phase 2.3 (v0.36): reset the text-mode buffer.
        self._reset_text_mode_buffer()

        try:
            extra_events: list[dict] = []

            async def invoke(name: str, args: dict) -> Any:
                result: Any = None
                async for ev in self._dispatch_tool_call(
                    name, args, tool_registry, session_id, ctx,
                ):
                    extra_events.append(ev)
                    if ev.get("type") == "tool_call_end":
                        result = ev.get("result")
                return result

            async for ev in self.aask_with_tools(
                messages_for_llm,
                tools=self._get_toolspec(tool_registry),
                max_iterations=self.DEFAULT_MAX_CHAT_ITERATIONS,
                invoke_tool=invoke,
            ):
                while extra_events:
                    yield extra_events.pop(0)
                if ev.get("type") == "done":
                    final = ev.get("final_response", "")
                    ctx.add_assistant_message(final)
                    self._save_message(session_id, "assistant", final)
                    if self._save_error_count > 0:
                        yield ChatEvent.save_warning(
                            f"已丢弃 {self._save_error_count} 条消息的持久化失败"
                        )
                    yield ChatEvent.done(final)
                    continue
                yield ev
            while extra_events:
                yield extra_events.pop(0)
        except Exception as e:
            logger.exception("Confirmation continue error")
            yield ChatEvent.error(str(e))

    # ─── Private helpers ─────────────────────────────────────────

    def _get_or_create_context(
        self, session_id: str, wiki_id: str | None = None
    ) -> AgentContext:
        if session_id not in self._contexts:
            ctx = AgentContext(wiki_id=wiki_id)
            # Restore conversation history from DB
            # get_chat_messages returns DESC (newest first);
            # reverse to get chronological (ASC) order
            db_messages = self.db.get_chat_messages(session_id, limit=100)
            for msg in reversed(db_messages):
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    ctx.messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    ctx.messages.append({"role": "assistant", "content": content})
            # Restore wiki_id from session
            if not wiki_id:
                session = self.db.get_chat_session(session_id)
                if session and session.get("wiki_id"):
                    ctx.set_recent_wiki(session["wiki_id"])
            self._contexts[session_id] = ctx
        return self._contexts[session_id]

    def _parse_wiki_prefix(self, message: str) -> tuple[str | None, str]:
        import re
        match = re.match(r"^@(\S+)\s+(.*)$", message, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, message

    def _build_system_prompt(self, wiki_id: str | None = None) -> str:
        parts = [
            "You are a helpful wiki assistant. You have access to wiki tools.",
            "Use the available tools to help the user.",
            "When a user asks to write, modify, or create wiki pages, "
            "you MUST request confirmation first.",
        ]
        if wiki_id:
            parts.append(f"Current wiki context: {wiki_id}")
        return "\n".join(parts)

    def _truncate_messages(
        self, messages: list[dict[str, str]], max_messages: int = 50
    ) -> list[dict[str, str]]:
        if len(messages) <= max_messages + 1:
            return messages
        system = messages[0]
        recent = messages[-(max_messages):]
        dropped = len(messages) - 1 - max_messages
        if dropped > 0:
            summary_note = {
                "role": "system",
                "content": f"[Note: {dropped} earlier messages omitted for context window management]",
            }
            return [system, summary_note] + recent
        return [system] + recent

    def _get_toolspec(self, tool_registry: Any) -> list[dict[str, Any]]:
        tools = tool_registry.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("parameters", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                },
            }
            for t in tools
        ]

    async def _stream_llm(
        self, llm: Any, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        """Backward-compat wrapper around the LLM stream.

        Kept for legacy callers. New code uses ChatBase's
        aask_with_tools, which calls _stream_preprocess for
        text-mode conversion.
        """
        async for event in llm.astream_chat(messages, tools=tools):
            yield event

    async def _stream_preprocess(
        self, event: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Override ChatBase's hook to convert text-mode
        ``[TOOL_CALL]...[/TOOL_CALL]`` blocks in ``content``
        events into native ``tool_call`` events
        (Phase 2.3 / v0.36).

        Maintains per-instance buffer state (a regex match may
        straddle two content chunks). Callers should reset
        the buffer at the start of each chat turn via
        ``_reset_text_mode_buffer``.

        On any non-content event (thinking, tool_call, done,
        error), the remaining buffer is flushed as a single
        ``content`` event so trailing text reaches the user.
        """
        if not hasattr(self, "_text_mode_buffer"):
            self._text_mode_buffer = ""
        if event.get("type") != "content":
            # Flush remaining buffered text before yielding
            # the non-content event. (End-of-iteration signal
            # from the LLM is implicit in the stream ending;
            # done is the explicit signal.)
            if self._text_mode_buffer and event.get("type") in (
                "done", "thinking", "tool_call", "error",
            ):
                yield {
                    "type": "content",
                    "text": self._text_mode_buffer,
                }
                self._text_mode_buffer = ""
            yield event
            return
        chunk = event.get("text", "")
        self._text_mode_buffer += chunk
        while True:
            m = _TOOL_CALL_RE.search(self._text_mode_buffer)
            if not m:
                break
            prefix = self._text_mode_buffer[: m.start()]
            if prefix:
                yield {"type": "content", "text": prefix}
            body = m.group(1)
            parsed = _parse_text_tool_call(body)
            if parsed is None:
                # Unparseable — pass through as text.
                yield {"type": "content", "text": m.group(0)}
            else:
                tool_name, args = parsed
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": json.dumps(args, ensure_ascii=False),
                }
            self._text_mode_buffer = self._text_mode_buffer[m.end():]

    def _reset_text_mode_buffer(self) -> None:
        """Reset the text-mode buffer at the start of a new
        chat iteration. (Phase 2.3 / v0.36)"""
        self._text_mode_buffer = ""

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> dict | list:
        call_id = self.db.log_tool_call(session_id, tool_name, args, "pending")
        try:
            result = await tool_registry.execute(tool_name, args)
            status = (
                "confirmation_required"
                if isinstance(result, dict) and result.get("status") == "confirmation_required"
                else "executed"
            )
            self.db.update_tool_call(call_id, result, status)

            tool_def = tool_registry._tools.get(tool_name, {})
            if tool_def.get("requires_confirmation") == "posthoc":
                entry_id = f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                self.db.log_ingest({
                    "id": entry_id,
                    "wiki_id": ctx.wiki_id or "default",
                    "tool": tool_name,
                    "arguments": args,
                    "result_summary": str(result)[:500] if result else "",
                    "status": "executed",
                })

            return result
        except Exception as e:
            self.db.update_tool_call(call_id, {"error": str(e)}, "error")
            return {"status": "error", "error": str(e)}

    async def _dispatch_tool_call(
        self,
        tool_name: str,
        args: dict,
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> AsyncIterator[dict]:
        """Run a single tool call and yield the matching SSE events.

        Used by both the native ``tool_call`` event path and the
        text-mode ``[TOOL_CALL]...[/TOOL_CALL]`` detection path so
        both sources go through the same confirmation / persistence
        logic.
        """
        yield ChatEvent.tool_call_start(tool_name, args)
        entry = {
            "tool": tool_name, "args": args, "status": "pending",
        }
        ctx._tool_calls[tool_name] = entry
        ctx._recent_tool_entries.append(entry)
        ctx.tool_invocations += 1
        result = await self._execute_tool(
            tool_name, args, tool_registry, session_id, ctx,
        )
        entry["result"] = result
        entry["status"] = "done"
        yield ChatEvent.tool_call_end(tool_name, result)

        if (
            isinstance(result, dict)
            and result.get("status") == "confirmation_required"
        ):
            conf_id = result.get("confirmation_id", "")
            yield ChatEvent.confirmation_required(
                conf_id, result.get("impact", {}),
            )
        else:
            tool_result_str = json.dumps(
                result.get("result", result)
                if isinstance(result, dict) else result
            )
            ctx.add_assistant_message(
                f"[TOOL: {tool_name}] Result: {tool_result_str}"
            )

    def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> None:
        # Phase 1.3 (v0.36): use full 32-hex uuid (was 8-hex,
        # ~4B ID space with non-zero collision risk for
        # long-running sessions). Errors are now logged + counted
        # rather than silently swallowed (Phase 1.2).
        try:
            self.db.save_chat_message({
                "id": uuid.uuid4().hex,
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_calls": tool_calls,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error("Failed to save chat message for session %s: %s", session_id, e)
            self._save_error_count += 1

    def _get_wiki_for_context(self, ctx: AgentContext) -> Any:
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_service.get_wiki(wiki_id)
        return self.wiki_service.get_wiki()

    # ─── Iterative tool-call loop (Phase 1.1 / v0.36) ────────────
    #
    # The previous flow called ``_stream_llm`` once and yielded the
    # result, never feeding tool outputs back. This meant the LLM
    # could not use tool results in its final answer, breaking the
    # ReAct / agent pattern. The new ``_run_chat_iteration`` method
    # does ONE LLM stream-and-dispatch pass; ``_run_chat_loop`` calls
    # it repeatedly until the LLM returns a plain ``done`` (no more
    # tool calls) or the iteration cap is hit.
    #
    # Backward-compat: the existing single-pass call shape is
    # preserved when max_iterations=1.

    DEFAULT_MAX_CHAT_ITERATIONS = 4

    async def _run_chat_iteration(
        self,
        llm: Any,
        messages_for_llm: list[dict],
        tool_specs: list[dict],
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> AsyncIterator[dict]:
        """Run a single LLM stream + tool dispatch pass.

        Yields SSE events (message_delta, thinking, tool_call_*,
        confirmation_required, done, error) and returns. The
        outer ``_run_chat_loop`` decides whether to call again
        to feed tool results back.

        The ``done`` event is SUPPRESSED when this iteration
        dispatched new tool calls — in that case the LLM's
        "done" is intermediate and the user-visible final
        answer will come from a follow-up iteration.
        """
        accumulated = ""
        text_buffer = ""
        # Snapshot of ctx.tool_invocations at the START of this
        # iteration. The number of NEW invocations added during
        # this iteration determines whether ``done`` is the
        # final answer or an intermediate signal.
        iteration_pre_invocations = ctx.tool_invocations
        async for event in self._stream_llm(llm, messages_for_llm, tool_specs):
            event_type = event.get("type")

            if event_type == "thinking":
                yield ChatEvent.thinking(event["text"])

            elif event_type == "content":
                chunk = event.get("text", "")
                accumulated += chunk
                # Buffer chunks; extract any complete
                # [TOOL_CALL]...[/TOOL_CALL] block and dispatch it
                # as a real tool call. Text outside the block
                # continues to flow to the user.
                text_buffer += chunk
                while True:
                    m = _TOOL_CALL_RE.search(text_buffer)
                    if not m:
                        break
                    prefix = text_buffer[: m.start()]
                    if prefix:
                        yield ChatEvent.message_delta(prefix)
                    body = m.group(1)
                    parsed = _parse_text_tool_call(body)
                    if parsed is None:
                        # Unparseable block — pass through as text.
                        yield ChatEvent.message_delta(m.group(0))
                    else:
                        tool_name, args = parsed
                        async for ev in self._dispatch_tool_call(
                            tool_name, args, tool_registry,
                            session_id, ctx,
                        ):
                            yield ev
                    text_buffer = text_buffer[m.end():]

            elif event_type == "tool_call":
                tool_name = event["tool"]
                raw_args = event.get("args", "{}")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {"raw": raw_args}
                else:
                    args = raw_args

                async for ev in self._dispatch_tool_call(
                    tool_name, args, tool_registry,
                    session_id, ctx,
                ):
                    yield ev

            elif event_type == "done":
                # Flush any trailing buffered text before done.
                if text_buffer:
                    yield ChatEvent.message_delta(text_buffer)
                    text_buffer = ""
                final = event.get("content", accumulated)
                # Determine whether this iteration produced new
                # tool invocations. If so, suppress the ``done``
                # event — it's intermediate; the user-visible
                # final answer will come from a follow-up
                # iteration.
                new_invocations = (
                    ctx.tool_invocations - iteration_pre_invocations
                )
                if new_invocations > 0:
                    # Intermediate done — don't yield it. The
                    # outer loop will iterate and call the LLM
                    # again with the tool results in ctx.messages.
                    return
                # No new tools in this iteration — this IS the
                # final answer. Save and yield done.
                ctx.add_assistant_message(final)
                self._save_message(
                    session_id, "assistant", final,
                    tool_calls=list(ctx._tool_calls.values())
                    if ctx._tool_calls else None,
                )
                # Surface silent save failures (Phase 1.2).
                if self._save_error_count > 0:
                    yield ChatEvent.save_warning(
                        f"已丢弃 {self._save_error_count} 条消息的持久化失败"
                    )
                yield ChatEvent.done(final)
                return

    async def _run_chat_loop(
        self,
        llm: Any,
        ctx: AgentContext,
        tool_registry: Any,
        session_id: str,
        max_iterations: int | None = None,
    ) -> AsyncIterator[dict]:
        """Run the iterative tool-call loop (Phase 1.1 / v0.36).

        Iterates the LLM call + tool dispatch + result-feedback
        cycle until the LLM produces a final ``done`` (no pending
        tool calls) or the iteration cap is hit. Each iteration
        rebuilds the message list from ``ctx`` so tool results
        are visible to the LLM on the next pass.
        """
        if max_iterations is None:
            max_iterations = self.DEFAULT_MAX_CHAT_ITERATIONS
        tool_specs = self._get_toolspec(tool_registry)
        # Snapshot of tool names seen at the start of this turn;
        # used to distinguish "new tool call in this iteration"
        # from "stale tool call from a prior turn".
        turn_start_tools = set(ctx._tool_calls.keys())

        for iteration in range(max_iterations):
            system_prompt = self._build_system_prompt(ctx.wiki_id)
            raw_messages = (
                [{"role": "system", "content": system_prompt}]
                + ctx.get_messages()
            )
            messages_for_llm = self._truncate_messages(raw_messages)
            # Track tool *invocations* by a monotonic counter so
            # re-calls of the same tool name are still detected
            # as "new tools in this iteration".
            pre_call_invocations = ctx.tool_invocations

            # Yield events from this iteration. ``_run_chat_iteration``
            # emits at most one ``done`` per call, and only when
            # this iteration did NOT dispatch new tool calls.
            got_done = False
            async for ev in self._run_chat_iteration(
                llm, messages_for_llm, tool_specs,
                tool_registry, session_id, ctx,
            ):
                yield ev
                if ev.get("type") == "done":
                    got_done = True

            if got_done:
                # The LLM produced a final answer in this iteration.
                return

            # No final done. Check whether this iteration dispatched
            # any new tool invocations. If not, the LLM stream ended
            # without done and without tools — defensive emit.
            new_invocations = ctx.tool_invocations - pre_call_invocations
            if new_invocations == 0:
                logger.warning(
                    "Chat loop iteration %d ended with no "
                    "done and no tools",
                    iteration,
                )
                yield ChatEvent.done("")
                return

            # New tool invocations this iteration. Check whether
            # the latest one needs confirmation — if so, stop
            # iterating; the frontend will resume via
            # approve_confirmation_continue.
            new_tool_entries = ctx._recent_tool_entries[-new_invocations:]
            if new_tool_entries:
                last_result = new_tool_entries[-1].get("result")
                if (
                    isinstance(last_result, dict)
                    and last_result.get("status")
                    == "confirmation_required"
                ):
                    return

            # Otherwise, loop and call the LLM again with the
            # tool results now in ctx.messages.

        # Iteration cap — emit final done with the accumulated
        # content from the last assistant message in ctx.
        logger.warning(
            "Chat loop hit max_iterations=%d; emitting fallback done",
            max_iterations,
        )
        last_assistant = next(
            (m for m in reversed(ctx.messages) if m.get("role") == "assistant"),
            None,
        )
        yield ChatEvent.done(last_assistant["content"] if last_assistant else "")
