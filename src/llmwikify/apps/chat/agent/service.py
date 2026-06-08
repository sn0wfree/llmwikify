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
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.base import ChatBase
from llmwikify.apps.chat.db import ChatDatabase

logger = logging.getLogger(__name__)


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


# ─── Per-session conversation state ───────────────────────────────


@dataclass
class AgentContext:
    """In-memory conversation state for one session."""

    wiki_id: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    recent_wiki_id: str | None = None
    _tool_calls: dict[str, Any] = field(default_factory=dict)

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

    def __init__(self, wiki_service: Any, data_dir: Path):
        self.wiki_service = wiki_service
        self.db = ChatDatabase(data_dir)
        self._contexts: dict[str, AgentContext] = {}

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
        """Stream a chat response as SSE events."""
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

        try:
            llm = self.wiki_service.get_llm()
            tool_specs = self._get_toolspec(tool_registry)

            accumulated = ""
            async for event in self._stream_llm(llm, messages_for_llm, tool_specs):
                event_type = event.get("type")

                if event_type == "thinking":
                    yield ChatEvent.thinking(event["text"])

                elif event_type == "content":
                    accumulated += event["text"]
                    yield ChatEvent.message_delta(event["text"])

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

                    yield ChatEvent.tool_call_start(tool_name, args)
                    ctx._tool_calls[tool_name] = {
                        "tool": tool_name, "args": args, "status": "pending"
                    }
                    result = await self._execute_tool(
                        tool_name, args, tool_registry, session_id, ctx
                    )
                    ctx._tool_calls[tool_name]["result"] = result
                    ctx._tool_calls[tool_name]["status"] = "done"
                    yield ChatEvent.tool_call_end(tool_name, result)

                    if isinstance(result, dict) and result.get("status") == "confirmation_required":
                        conf_id = result.get("confirmation_id", "")
                        yield ChatEvent.confirmation_required(
                            conf_id, result.get("impact", {})
                        )
                    else:
                        tool_result_str = json.dumps(
                            result.get("result", result)
                            if isinstance(result, dict) else result
                        )
                        ctx.add_assistant_message(
                            f"[TOOL: {tool_name}] Result: {tool_result_str}"
                        )

                elif event_type == "done":
                    final = event.get("content", accumulated)
                    ctx.add_assistant_message(final)
                    self._save_message(
                        session_id, "assistant", final,
                        tool_calls=list(ctx._tool_calls.values())
                        if ctx._tool_calls else None,
                    )
                    yield ChatEvent.done(final)

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
        """Approve a confirmation, execute tool, feed result back to LLM."""
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

        try:
            llm = self.wiki_service.get_llm()
            tool_specs = self._get_toolspec(tool_registry)
            accumulated = ""
            async for event in self._stream_llm(llm, messages_for_llm, tool_specs):
                event_type = event.get("type")
                if event_type == "thinking":
                    yield ChatEvent.thinking(event["text"])
                elif event_type == "content":
                    accumulated += event["text"]
                    yield ChatEvent.message_delta(event["text"])
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
                    yield ChatEvent.tool_call_start(tool_name, args)
                    tool_result = await self._execute_tool(
                        tool_name, args, tool_registry, session_id, ctx
                    )
                    yield ChatEvent.tool_call_end(tool_name, tool_result)
                    if isinstance(tool_result, dict) and tool_result.get("status") == "confirmation_required":
                        conf_id = tool_result.get("confirmation_id", "")
                        yield ChatEvent.confirmation_required(
                            conf_id, tool_result.get("impact", {})
                        )
                    else:
                        trs = json.dumps(
                            tool_result.get("result", tool_result)
                            if isinstance(tool_result, dict) else tool_result
                        )
                        ctx.add_assistant_message(f"[TOOL: {tool_name}] Result: {trs}")
                elif event_type == "done":
                    final = event.get("content", accumulated)
                    ctx.add_assistant_message(final)
                    self._save_message(session_id, "assistant", final)
                    yield ChatEvent.done(final)
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
            db_messages = self.db.get_chat_messages(session_id, limit=100)
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
        async for event in llm.astream_chat(messages, tools=tools):
            yield event

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

    def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> None:
        try:
            self.db.save_chat_message({
                "id": str(uuid.uuid4())[:8],
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_calls": tool_calls,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    def _get_wiki_for_context(self, ctx: AgentContext) -> Any:
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_service.get_wiki(wiki_id)
        return self.wiki_service.get_wiki()
