"""Agent Service - Core agent logic with tool execution and context management."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..tools import WikiToolRegistry
from .adapters import StreamableLLMClient
from .db import AgentDatabase

logger = logging.getLogger(__name__)


class ChatEvent:
    """SSE event types for chat streaming."""

    @staticmethod
    def message_delta(content: str) -> dict:
        return {"type": "message_delta", "content": content}

    @staticmethod
    def tool_call_start(tool: str, args: dict) -> dict:
        return {"type": "tool_call_start", "tool": tool, "args": args}

    @staticmethod
    def tool_call_end(tool: str, result: dict) -> dict:
        return {"type": "tool_call_end", "tool": tool, "result": result}

    @staticmethod
    def confirmation_required(confirmation_id: str, impact: dict) -> dict:
        return {"type": "confirmation_required", "confirmation_id": confirmation_id, "impact": impact}

    @staticmethod
    def done(final_response: str) -> dict:
        return {"type": "done", "final_response": final_response}

    @staticmethod
    def error(message: str) -> dict:
        return {"type": "error", "message": message}


class AgentContext:
    """Maintains conversation history and wiki context for a session."""

    def __init__(self, wiki_id: str | None = None):
        self.wiki_id = wiki_id
        self.messages: list[dict[str, str]] = []
        self.recent_wiki_id: str | None = wiki_id

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        return self.messages

    def set_recent_wiki(self, wiki_id: str) -> None:
        self.recent_wiki_id = wiki_id
        self.wiki_id = wiki_id


class AgentService:
    """Core agent service handling chat, tool execution, and context.

    Phase 1 focus:
    - Streaming chat response via SSE
    - Tool call execution (read operations)
    - Basic context management
    """

    def __init__(self, wiki_registry: Any, data_dir: Path):
        self.wiki_registry = wiki_registry
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = AgentDatabase(data_dir / ".llmwiki_agent.db")
        self._contexts: dict[str, AgentContext] = {}
        self._llm: StreamableLLMClient | None = None

    def _get_llm(self) -> StreamableLLMClient:
        if self._llm is None:
            from llmwikify.config import load_config
            config = load_config()
            self._llm = StreamableLLMClient.from_config(config)
        return self._llm

    def _get_or_create_context(self, session_id: str, wiki_id: str | None = None) -> AgentContext:
        if session_id not in self._contexts:
            self._contexts[session_id] = AgentContext(wiki_id)
        return self._contexts[session_id]

    def _parse_wiki_prefix(self, message: str) -> tuple[str | None, str]:
        match = re.match(r"^@(\S+)\s+(.*)$", message, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, message

    def _build_system_prompt(self, wiki_id: str | None = None) -> str:
        parts = [
            "You are a helpful wiki assistant. You have access to wiki tools.",
            "Use the available tools to help the user.",
            "When a user asks to write, modify, or create wiki pages, you MUST request confirmation first by returning a confirmation_required event.",
        ]
        if wiki_id:
            parts.append(f"Current wiki context: {wiki_id}")
        return "\n".join(parts)

    def _get_toolspec(self, tool_registry: WikiToolRegistry) -> list[dict[str, Any]]:
        tools = tool_registry.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
            for t in tools
        ]

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
        """Process a chat message and yield SSE events.

        Args:
            message: User message (may contain @wiki_id prefix)
            session_id: Chat session ID (creates new if None)
            wiki_id: Wiki ID hint (overrides @ prefix detection)
            jwt_token: JWT token from URL param

        Yields:
            SSE event dicts
        """
        if session_id is None:
            session_id = self.db.create_session(wiki_id, jwt_token)
            yield {"type": "session_created", "session_id": session_id}
        else:
            session = self.db.get_session(session_id)
            if session is None:
                session_id = self.db.create_session(wiki_id, jwt_token)
                yield {"type": "session_created", "session_id": session_id}

        ctx = self._get_or_create_context(session_id, wiki_id)

        wiki_id_from_prefix, message = self._parse_wiki_prefix(message)
        if wiki_id_from_prefix:
            ctx.set_recent_wiki(wiki_id_from_prefix)
            self.db.update_session_wiki(session_id, wiki_id_from_prefix)

        if wiki_id and not wiki_id_from_prefix:
            ctx.set_recent_wiki(wiki_id)
            self.db.update_session_wiki(session_id, wiki_id)

        if jwt_token:
            self.db.update_session_jwt(session_id, jwt_token)

        ctx.add_user_message(message)

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = WikiToolRegistry(wiki)

        system_prompt = self._build_system_prompt(ctx.wiki_id)
        messages_for_llm = [{"role": "system", "content": system_prompt}] + ctx.get_messages()

        try:
            llm = self._get_llm()
            tool_specs = self._get_toolspec(tool_registry)

            accumulated = ""
            async for event in self._stream_llm(llm, messages_for_llm, tool_specs):
                event_type = event.get("type")

                if event_type == "content":
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
                    result = await self._execute_tool(tool_name, args, tool_registry, session_id)
                    yield ChatEvent.tool_call_end(tool_name, result)

                    if result.get("status") == "confirmation_required":
                        conf_id = result.get("confirmation_id", "")
                        yield ChatEvent.confirmation_required(conf_id, result.get("impact", {}))
                    else:
                        tool_result_str = json.dumps(result.get("result", result))
                        ctx.add_assistant_message(
                            f"[TOOL: {tool_name}] Result: {tool_result_str}"
                        )

                elif event_type == "done":
                    final = event.get("content", accumulated)
                    ctx.add_assistant_message(final)
                    yield ChatEvent.done(final)

        except Exception as e:
            logger.exception("Chat error")
            yield ChatEvent.error(str(e))

    async def _stream_llm(
        self,
        llm: StreamableLLMClient,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict]:
        for event in llm.stream_chat(messages, tools=tools):
            yield event

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        tool_registry: WikiToolRegistry,
        session_id: str,
    ) -> dict:
        call_id = self.db.log_tool_call(session_id, tool_name, args, "pending")
        try:
            result = await tool_registry.execute(tool_name, args)
            status = "confirmation_required" if isinstance(result, dict) and result.get("status") == "confirmation_required" else "executed"
            self.db.update_tool_call(call_id, result, status)
            return result
        except Exception as e:
            self.db.update_tool_call(call_id, {"error": str(e)}, "error")
            return {"status": "error", "error": str(e)}

    def _get_wiki_for_context(self, ctx: AgentContext):
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_registry.get_wiki(wiki_id)
        return self.wiki_registry.get_default_wiki()

    async def get_confirmation(self, confirmation_id: str) -> dict | None:
        from ..tools import WikiToolRegistry
        for ctx in self._contexts.values():
            wiki = self._get_wiki_for_context(ctx)
            if wiki:
                registry = WikiToolRegistry(wiki)
                for conf in registry.get_pending_confirmations():
                    if conf["id"] == confirmation_id:
                        return conf
        return None

    async def approve_confirmation(self, confirmation_id: str) -> dict:
        from ..tools import WikiToolRegistry
        for ctx in self._contexts.values():
            wiki = self._get_wiki_for_context(ctx)
            if wiki:
                registry = WikiToolRegistry(wiki)
                result = registry.confirm_execution(confirmation_id)
                if result.get("status") != "error":
                    return result
        return {"status": "error", "error": "Confirmation not found"}

    async def reject_confirmation(self, confirmation_id: str) -> dict:
        from ..tools import WikiToolRegistry
        for ctx in self._contexts.values():
            wiki = self._get_wiki_for_context(ctx)
            if wiki:
                registry = WikiToolRegistry(wiki)
                result = registry.reject_execution(confirmation_id)
                if result.get("status") != "error":
                    return result
        return {"status": "error", "error": "Confirmation not found"}

    def get_pending_confirmations(self) -> list[dict]:
        from ..tools import WikiToolRegistry
        all_confirmations = []
        for ctx in self._contexts.values():
            wiki = self._get_wiki_for_context(ctx)
            if wiki:
                registry = WikiToolRegistry(wiki)
                all_confirmations.extend(registry.get_pending_confirmations())
        return all_confirmations

    def get_pending_by_group(self) -> dict[str, list[dict]]:
        from ..tools import WikiToolRegistry
        groups: dict[str, list[dict]] = {}
        for ctx in self._contexts.values():
            wiki = self._get_wiki_for_context(ctx)
            if wiki:
                registry = WikiToolRegistry(wiki)
                for conf in registry.get_pending_confirmations():
                    group = conf.get("group", "other_pages")
                    if group not in groups:
                        groups[group] = []
                    groups[group].append(conf)
        return groups