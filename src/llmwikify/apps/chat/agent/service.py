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
from llmwikify.apps.chat.agent.chat_react import REACT_SYSTEM_PROMPT
from llmwikify.apps.chat.agent.text_mode_tool import (
    TOOL_CALL_RE as _TOOL_CALL_RE,
    parse_text_tool_call as _parse_text_tool_call,
    parse_perl_args as _parse_perl_args,
    TextModeParser,
)

logger = logging.getLogger(__name__)


# Default user_id for chat-layer preferences (Phase 3.1 / v0.36).
# The chat layer has no per-user identity; preferences are
# scoped to the local install / single user.
DEFAULT_USER_ID = "default"


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
    def confirmation_required(
        conf_id: str, tool: str, args: dict, impact: dict,
    ) -> dict:
        return {
            "type": "confirmation_required",
            "confirmation_id": conf_id,
            "tool": tool,
            "args": args,
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

    # ReAct state tracking (v0.37)
    react_observations: list[str] = field(default_factory=list)
    react_thoughts: list[str] = field(default_factory=list)
    react_round: int = 0
    # Thinking snapshot from the last LLM turn (ReAct "Thought")
    _thinking: str = ""

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        return list(self.messages)

    def set_recent_wiki(self, wiki_id: str) -> None:
        self.recent_wiki_id = wiki_id

    def add_observation(self, observation: str) -> None:
        """Track a ReAct observation from a tool call result."""
        self.react_observations.append(observation)
        # Keep only the last 10 observations to avoid prompt bloat
        if len(self.react_observations) > 10:
            self.react_observations = self.react_observations[-10:]

    def add_thought(self, thought: str) -> None:
        """Track a ReAct thought from the LLM reasoning step."""
        if thought:
            self.react_thoughts.append(thought)
            if len(self.react_thoughts) > 10:
                self.react_thoughts = self.react_thoughts[-10:]

    def get_observations_summary(self) -> str:
        """Generate a summary of recent observations for prompt injection."""
        if not self.react_observations:
            return ""
        lines = ["## Recent tool observations"]
        for i, obs in enumerate(self.react_observations[-5:], 1):
            lines.append(f"{i}. {obs}")
        return "\n".join(lines)


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
        memory_manager: Any | None = None,
        use_react_engine: bool = True,
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
        # Phase 3 (v0.36): MemoryManager exposes 6 stores used
        # by the chat layer (system prompt injection, history
        # restore, tool result persistence, related-history
        # retrieval). Optional to keep backward compat — when
        # None, the chat layer falls back to direct ChatDatabase
        # access.
        self.memory_manager = memory_manager
        # Phase 4.1 (v0.36): LLMRetryManager wraps transient
        # LLM failures (rate limit, timeout, 5xx) with
        # exponential backoff. Applied to the initial stream
        # connection so the first-chunk failure is retried.
        from llmwikify.apps.chat.retry_managers import (
            LLMRetryManager,
            DBRetryManager,
        )
        self._llm_retry = LLMRetryManager(
            max_attempts=3, base_delay=2.0, call_timeout=120.0,
        )
        # Phase 4.2 (v0.36): DBRetryManager retries SQLite
        # 'database is locked' / I/O errors with short backoff.
        self._db_retry = DBRetryManager(
            max_attempts=3, base_delay=0.2,
        )

        # Initialize ChatBase with LLM from WikiService
        llm = wiki_service.get_llm()
        super().__init__(llm_client=llm)
        # Phase 6 (v0.37): dual-track support. When True, chat()
        # delegates the iterative loop to ChatReActBridge + ReActEngine
        # instead of ChatBase.aask_with_tools. Default off during
        # rollout; can be flipped via constructor kwarg.
        self.use_react_engine = use_react_engine

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

        ctx = await self._get_or_create_context(session_id, wiki_id)

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

        # Phase 3.1 (v0.36): pass user_message + session_id so
        # the prompt can include related-past-conversations.
        system_prompt = await self._build_system_prompt(
            ctx.wiki_id,
            user_message=message,
            session_id=session_id,
        )
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        # ReAct: inject observations from previous tool calls so the
        # LLM can use them in its reasoning.
        obs_summary = ctx.get_observations_summary()
        if obs_summary:
            raw_messages.insert(-1, {
                "role": "system",
                "content": obs_summary,
            })
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
            if self.use_react_engine:
                # Phase 6 (v0.37): delegate to ChatReActBridge +
                # ReActEngine. Same SSE event vocabulary as
                # aask_with_tools path.
                async for event in self._chat_via_react(
                    messages_for_llm=messages_for_llm,
                    system_prompt=system_prompt,
                    tool_registry=tool_registry,
                    session_id=session_id,
                    ctx=ctx,
                ):
                    yield event
                return

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

        Phase 6 (v0.37): when use_react_engine=True, delegates
        to ChatReActBridge + ReActEngine via _chat_via_react.
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

        ctx = await self._get_or_create_context(session_id, wiki_id)
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
        system_prompt = await self._build_system_prompt(
            ctx.wiki_id,
            user_message=ctx.messages[-1]["content"] if ctx.messages else None,
            session_id=session_id,
        )
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        # ReAct: inject observations
        obs_summary = ctx.get_observations_summary()
        if obs_summary:
            raw_messages.insert(-1, {
                "role": "system",
                "content": obs_summary,
            })
        messages_for_llm = self._truncate_messages(raw_messages)

        try:
            if self.use_react_engine:
                # Phase 6 (v0.37): use the ReAct path
                async for event in self._chat_via_react(
                    messages_for_llm=messages_for_llm,
                    system_prompt=system_prompt,
                    tool_registry=tool_registry,
                    session_id=session_id,
                    ctx=ctx,
                ):
                    yield event
                return

            # Phase 2.2 (v0.36): aask_with_tools path (legacy)
            # Phase 2.3 (v0.36): reset the text-mode buffer.
            self._reset_text_mode_buffer()

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

    async def _get_or_create_context(
        self, session_id: str, wiki_id: str | None = None
    ) -> AgentContext:
        if session_id not in self._contexts:
            ctx = AgentContext(wiki_id=wiki_id)
            # Phase 3.2 (v0.36): restore conversation history
            # through MemoryManager when available, falling
            # back to direct ChatDatabase access when not.
            # MemoryManager is preferred because it adds async
            # I/O wrapping and a unified abstraction over the
            # 6 stores.
            db_messages = await self._load_history(session_id)
            for msg in db_messages:
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

    async def _load_history(self, session_id: str) -> list[dict]:
        """Load conversation history, preferring MemoryManager
        when available (Phase 3.2 / v0.36).

        Returns messages in chronological (ASC) order,
        regardless of whether the underlying store returns
        DESC — callers depend on chronological order.
        """
        if self.memory_manager is not None:
            # ``alist`` returns DESC (newest first); reverse
            # to chronological for the in-memory context.
            return list(reversed(
                await self.memory_manager.conversation.alist(
                    session_id, limit=100,
                )
            ))
        # Fallback: direct DB access. ``get_chat_messages``
        # also returns DESC; reverse for consistency.
        return list(reversed(
            self.db.get_chat_messages(session_id, limit=100)
        ))

    def _parse_wiki_prefix(self, message: str) -> tuple[str | None, str]:
        import re
        match = re.match(r"^@(\S+)\s+(.*)$", message, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, message

    async def _build_system_prompt(
        self,
        wiki_id: str | None = None,
        user_message: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build the system prompt (Phase 3.1 / v0.36).

        Composes multiple sections:
          1. Role + tool usage policy (always)
          2. Wiki context (when wiki_id is known)
          3. User preferences (via MemoryManager.preferences)
          4. Available tools (from the tool registry)
          5. Current date
          6. Related past conversations (via MemoryIndex.search)
             — only when user_message is provided
        """
        parts: list[str] = []
        # 1. Role + policy + ReAct reasoning pattern
        parts.append(
            "You are a helpful wiki assistant. You have access "
            "to wiki tools.\n"
            + REACT_SYSTEM_PROMPT
            + "\nWhen a user asks to write, modify, or create wiki "
            "pages, you MUST request confirmation first."
        )
        # 2. Wiki context
        if wiki_id:
            parts.append(f"## Current wiki context\n{wiki_id}")
        # 3. User preferences
        prefs_section = await self._build_preferences_section()
        if prefs_section:
            parts.append(prefs_section)
        # 4. Available tools
        tools_section = self._build_tools_section()
        if tools_section:
            parts.append(tools_section)
        # 5. Current date
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        parts.append(f"## Today's date (UTC)\n{today}")
        # 6. Related past conversations
        if user_message and session_id:
            related_section = await self._build_related_section(
                user_message, session_id,
            )
            if related_section:
                parts.append(related_section)
        return "\n\n".join(parts)

    async def _build_preferences_section(self) -> str | None:
        """Phase 3.1 (v0.36): inject user preferences as a
        prompt section."""
        if self.memory_manager is None:
            return None
        try:
            prefs = await self.memory_manager.preferences.aall(
                DEFAULT_USER_ID,
            )
        except Exception:  # noqa: BLE001
            return None
        if not prefs:
            return None
        # Render as a markdown list.
        lines = ["## User preferences"]
        for k, v in prefs.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    def _build_tools_section(self) -> str | None:
        """Phase 3.1 (v0.36): summarise available tools in the
        prompt. Lazy-loaded from the wiki's tool registry.
        """
        # Don't bother loading tools here — that's expensive
        # and the LLM already has the tool schema. We only
        # render this section if a wiki is available.
        if not hasattr(self.wiki_service, "list_tool_names"):
            return None
        try:
            tool_names = self.wiki_service.list_tool_names()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        if not tool_names:
            return None
        return (
            "## Available tools\n"
            + ", ".join(f"`{n}`" for n in tool_names[:20])
            + (f" (+{len(tool_names) - 20} more)" if len(tool_names) > 20 else "")
        )

    async def _build_related_section(
        self,
        user_message: str,
        session_id: str,
    ) -> str | None:
        """Phase 3.4 (v0.36): surface top-K related past
        conversations as a prompt section."""
        if self.memory_manager is None:
            return None
        try:
            results = await self.memory_manager.index.asearch(
                user_message, session_id=session_id, limit=3,
            )
        except Exception:  # noqa: BLE001
            return None
        if not results:
            return None
        lines = ["## Related past conversations"]
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            if len(content) > 200:
                content = content[:200] + "…"
            source = r.get("source", "unknown")
            lines.append(f"{i}. [{source}] {content}")
        return "\n".join(lines)

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

    async def _chat_via_react(
        self,
        messages_for_llm: list[dict[str, str]],
        system_prompt: str,
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> AsyncIterator[dict]:
        """ReAct path for chat() (Phase 6 / v0.37).

        Builds a ``ChatReActBridge`` config and runs ``ReActEngine``
        on the same messages, tool registry, and AgentContext that
        ``aask_with_tools`` would have used. Yields the same SSE
        event vocabulary the frontend expects.
        """
        from llmwikify.apps.chat.agent.chat_react import ChatReActBridge
        from llmwikify.apps.chat.agent.react_engine import ReActEngine
        from llmwikify.apps.chat.skills.base import SkillContext

        bridge = ChatReActBridge(chat_service=self)
        config = bridge.build_config(
            session_id=session_id,
            wiki_id=ctx.wiki_id,
            tool_registry=tool_registry,
            user_message="",
            system_prompt=system_prompt,
            messages=messages_for_llm,
            ctx=ctx,
            max_iterations=self.DEFAULT_MAX_CHAT_ITERATIONS,
        )
        engine = ReActEngine(config)

        # Build a SkillContext so the engine has the LLM client and DB.
        skill_ctx = SkillContext(
            session_id=session_id,
            wiki=self.wiki_service.get_wiki(ctx.wiki_id),
            db=self.db,
            llm_client=self.wiki_service.get_llm(),
            config={},
            metrics=None,
        )

        # Forward events to the SSE stream, translate ReActEngine
        # internals to the frontend vocabulary.
        try:
            async for event in engine.run(skill_ctx):
                translated = self._translate_react_event(event, ctx, session_id)
                if translated is None:
                    continue
                # If the translator returned a list, yield each one.
                if isinstance(translated, list):
                    for item in translated:
                        yield item
                else:
                    yield translated
        except Exception as e:
            logger.exception("ReAct chat error")
            yield ChatEvent.error(str(e))

    def _translate_react_event(
        self,
        event: dict[str, Any],
        ctx: AgentContext,
        session_id: str,
    ) -> dict | None:
        """Translate a ReActEngine event to a frontend SSE event.

        ReActEngine internal events (``reasoning``, ``round_complete``,
        ``observation_error``, ``phase=cancelled/paused/timeout``)
        are filtered. ``phase=done`` triggers a ``done`` event with
        the final answer. ``action_error`` is mapped to
        ``tool_call_error``.
        """
        kind = event.get("type")
        if kind == "reasoning":
            return None  # internal — not sent to frontend
        if kind == "round_complete":
            return None  # internal — not sent to frontend
        if kind == "observation_error":
            return ChatEvent.error(event.get("error", "observation failed"))
        if kind == "action_error":
            return {
                "type": "tool_call_error",
                "tool": event.get("action", ""),
                "error": event.get("error", ""),
            }
        if kind == "timeout":
            return ChatEvent.error(
                f"ReAct loop timed out after {event.get('limit', 0):.0f}s"
            )
        if kind == "phase":
            phase = event.get("phase")
            final_state = event.get("final_state")
            if phase == "done":
                # The engine emits phase=done twice: once as an
                # intermediate signal (no final_state) and once as
                # the terminal event (with final_state). Only emit
                # a frontend ``done`` for the terminal event.
                if not isinstance(final_state, dict):
                    return None
                # Persist and emit done with the final answer
                final = final_state.get("final_answer") or ""
                if not final:
                    final = final_state.get("llm_content", "")
                if not final:
                    final = ""
                # If the reason callback caught an LLM exception
                # (state["final_answer"] is prefixed with "[error]"),
                # surface an ``error`` event to the frontend.
                if final.startswith("[error]"):
                    err_msg = final[len("[error]"):].strip()
                    return ChatEvent.error(err_msg or "LLM stream failed")
                thinking = ""
                if hasattr(ctx, "_thinking"):
                    thinking = ctx._thinking
                if thinking:
                    ctx._thinking = thinking
                ctx.add_assistant_message(final)
                self._save_message(
                    session_id, "assistant", final,
                    tool_calls=list(ctx._tool_calls.values())
                    if ctx._tool_calls else None,
                )
                if self._save_error_count > 0:
                    return [
                        ChatEvent.save_warning(
                            f"已丢弃 {self._save_error_count} 条消息的持久化失败"
                        ),
                        ChatEvent.done(final),
                    ]
                return ChatEvent.done(final)
            if phase == "cancelled":
                return None  # internal — terminate SSE
            if phase == "paused":
                return None
            if phase == "timeout":
                return ChatEvent.error("ReAct loop timed out")
            if phase == "incomplete":
                return ChatEvent.done(
                    final_state.get("final_answer", "")
                    if isinstance(final_state, dict) else "",
                )
        # Pass through: message_delta, thinking, tool_call_start,
        # tool_call_end, confirmation_required, error, save_warning
        return event

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

    async def _llm_stream_with_retry(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """Wrap the LLM stream with retry on the first chunk
        (Phase 4.1 / v0.36).

        If the LLM fails to produce the first chunk (e.g.
        rate limit, timeout, 5xx), the entire stream is
        retried up to 3 times with exponential backoff. If
        the first chunk succeeds but a later chunk fails, the
        error propagates — we cannot safely rewind mid-stream.
        """
        last_exc: Exception | None = None
        for attempt in range(self._llm_retry.max_attempts):
            try:
                first = True
                async for ev in self._astream_with_tools(messages, tools):
                    first = False
                    yield ev
                return  # Stream completed normally
            except Exception as e:  # noqa: BLE001
                if first:
                    # No chunks produced yet — safe to retry
                    last_exc = e
                    if not self._llm_retry._is_retriable(e):
                        raise
                    if attempt < self._llm_retry.max_attempts - 1:
                        delay = min(
                            self._llm_retry.base_delay * (2 ** attempt),
                            30.0,
                        )
                        logger.warning(
                            "LLM stream failed on attempt %d/%d "
                            "(no chunks produced): %s. Retrying in %.1fs...",
                            attempt + 1, self._llm_retry.max_attempts,
                            e, delay,
                        )
                        await asyncio.sleep(delay)
                else:
                    # Stream partially delivered — cannot retry
                    raise
        if last_exc:
            raise last_exc

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

        Phase 3.3 (v0.36): persists the tool result to
        ``MemoryManager.context`` so future related-history
        searches can surface it.
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

        # ReAct observation: track the tool result for the next
        # reasoning step.  The observation is a concise summary
        # that the LLM can use to decide its next action.
        result_summary = json.dumps(
            result.get("result", result)
            if isinstance(result, dict) else result,
            ensure_ascii=False, default=str,
        )[:500]
        ctx.add_observation(f"Called {tool_name}: {result_summary}")

        # Phase 3.3 (v0.36): persist tool result to
        # MemoryManager.context (best-effort; failures are
        # logged but never block the chat).
        await self._persist_tool_result(session_id, tool_name, args, result)

        if (
            isinstance(result, dict)
            and result.get("status") == "confirmation_required"
        ):
            conf_id = result.get("confirmation_id", "")
            yield ChatEvent.confirmation_required(
                conf_id, tool_name, args,
                result.get("impact", {}),
            )
        else:
            tool_result_str = json.dumps(
                result.get("result", result)
                if isinstance(result, dict) else result
            )
            ctx.add_assistant_message(
                f"[TOOL: {tool_name}] Result: {tool_result_str}"
            )

    async def _persist_tool_result(
        self,
        session_id: str,
        tool_name: str,
        args: dict,
        result: Any,
    ) -> None:
        """Phase 3.3 (v0.36): persist a tool result to the
        MemoryManager context store. Best-effort: failures are
        logged but never raised, so a broken memory store
        cannot interrupt the chat flow.
        """
        if self.memory_manager is None:
            return
        try:
            content = json.dumps(
                {"tool": tool_name, "args": args, "result": result},
                ensure_ascii=False, default=str,
            )
            # Cap stored content to keep the DB small.
            if len(content) > 10_000:
                content = content[:10_000] + "…"
            await self.memory_manager.context.aadd(
                session_id,
                entry_type="tool_result",
                content=content,
                metadata={"tool": tool_name},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to persist tool result to memory.context: %s", e,
            )

    def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> None:
        """Persist a chat message with retry (Phase 4.2 / v0.36).

        Uses DBRetryManager to retry SQLite transient errors
        (database is locked, I/O errors) with exponential
        backoff. Non-retriable errors are logged and counted
        (Phase 1.2) but never raise — the chat flow is never
        interrupted by a persistence failure.
        """
        msg = {
            "id": uuid.uuid4().hex,
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._db_retry.call(self.db.save_chat_message, msg)
        except Exception as e:
            logger.error("Failed to save chat message for session %s: %s", session_id, e)
            self._save_error_count += 1

    def _get_wiki_for_context(self, ctx: AgentContext) -> Any:
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_service.get_wiki(wiki_id)
        return self.wiki_service.get_wiki()

    # ─── Iterative tool-call loop (Phase 6 / v0.37) ──────────────
    #
    # Phase 6 (v0.37): the iterative tool-call loop is now
    # implemented by ChatReActBridge + ReActEngine. The legacy
    # ``_run_chat_iteration`` and ``_run_chat_loop`` methods
    # (Phase 1.1 / v0.36) have been removed in favor of the
    # unified ReAct framework.

    DEFAULT_MAX_CHAT_ITERATIONS = 4
