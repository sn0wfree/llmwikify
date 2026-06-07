"""Agent Service - Core agent logic with tool execution and context management."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..dream_editor import DreamEditor
from ..notifications import NotificationManager
from ..scheduler import WikiScheduler
from ..tools import WikiToolRegistry
from llmwikify.foundation.llm.streamable import StreamableLLMClient
from .config_manager import get_global_config_manager, GlobalConfigManager
from .db import AgentDatabase

logger = logging.getLogger(__name__)


class ChatEvent:
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
    def __init__(self, wiki_registry: Any, data_dir: Path):
        self.wiki_registry = wiki_registry
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = AgentDatabase(data_dir / ".llmwiki_agent.db")
        self._contexts: dict[str, AgentContext] = {}
        self._llm: StreamableLLMClient | None = None
        self._dream_editors: dict[str, DreamEditor] = {}
        self._notification_managers: dict[str, NotificationManager] = {}
        self._schedulers: dict[str, WikiScheduler] = {}
        self._tool_registries: dict[str, WikiToolRegistry] = {}
        self._config_manager = get_global_config_manager(lambda: self)

    def _get_default_wiki_id(self) -> str | None:
        return self.wiki_registry.get_default_wiki_id()

    def _get_wiki(self, wiki_id: str | None) -> Any:
        if wiki_id:
            return self.wiki_registry.get_wiki(wiki_id)
        return self.wiki_registry.get_default_wiki()

    def _get_dream_editor(self, wiki_id: str | None = None) -> DreamEditor:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._dream_editors:
            wiki = self._get_wiki(wiki_id)
            self._dream_editors[wiki_id] = DreamEditor(
                wiki=wiki,
                data_dir=self.data_dir / wiki_id,
                db=self.db,
                wiki_id=wiki_id,
            )
        return self._dream_editors[wiki_id]

    def _get_notification_manager(self, wiki_id: str | None = None) -> NotificationManager:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._notification_managers:
            self._notification_managers[wiki_id] = NotificationManager(
                max_size=100,
                db=self.db,
                wiki_id=wiki_id,
            )
        return self._notification_managers[wiki_id]

    def _get_scheduler(self, wiki_id: str | None = None) -> WikiScheduler:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._schedulers:
            wiki = self._get_wiki(wiki_id)
            scheduler_dir = self.data_dir / wiki_id / "scheduler"
            scheduler_dir.mkdir(parents=True, exist_ok=True)
            scheduler = WikiScheduler(scheduler_dir)
            dream_editor = self._get_dream_editor(wiki_id)
            nm = self._get_notification_manager(wiki_id)
            scheduler.register_system_tasks(wiki, dream_editor, nm)
            scheduler.load_state()
            self._schedulers[wiki_id] = scheduler
        return self._schedulers[wiki_id]

    def _get_tool_registry(self, wiki_id: str | None = None) -> WikiToolRegistry:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._tool_registries:
            wiki = self._get_wiki(wiki_id)
            self._tool_registries[wiki_id] = WikiToolRegistry(wiki, self.db, wiki_id)
        return self._tool_registries[wiki_id]

    def _get_llm(self) -> StreamableLLMClient:
        if self._llm is None:
            default_id = self._get_default_wiki_id()
            wiki_root = None
            if default_id:
                wiki_instance = self.wiki_registry.get_wiki_instance(default_id)
                if wiki_instance and wiki_instance.root:
                    wiki_root = wiki_instance.root
            config = self._config_manager.load_effective_llm_config(wiki_root)
            from .providers.registry import create_llm
            self._llm = create_llm(config)
        return self._llm

    def reload_llm(self) -> None:
        """Clear the cached LLM client so it gets reloaded on the next request."""
        self._llm = None

    def _get_or_create_context(self, session_id: str, wiki_id: str | None = None) -> AgentContext:
        if session_id not in self._contexts:
            ctx = AgentContext(wiki_id)
            ctx._tool_calls = {}
            # Restore conversation history from DB
            db_messages = self.db.get_messages(session_id, limit=100)
            for msg in db_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    ctx.messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    ctx.messages.append({"role": "assistant", "content": content})
            # Restore wiki_id from session if not provided
            if not wiki_id:
                session = self.db.get_session(session_id)
                if session and session.get("wiki_id"):
                    ctx.set_recent_wiki(session["wiki_id"])
            self._contexts[session_id] = ctx
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

    def _truncate_messages(self, messages: list[dict[str, str]], max_messages: int = 50) -> list[dict[str, str]]:
        """Truncate message history to fit within context window.

        Keeps system prompt (first message) and last max_messages messages.
        """
        if len(messages) <= max_messages + 1:  # +1 for system prompt
            return messages

        system = messages[0]
        recent = messages[-(max_messages):]
        dropped = len(messages) - 1 - max_messages
        if dropped > 0:
            # Insert a summary note where messages were dropped
            summary_note = {
                "role": "system",
                "content": f"[Note: {dropped} earlier messages omitted for context window management]",
            }
            return [system, summary_note] + recent
        return [system] + recent

    def _get_toolspec(self, tool_registry: WikiToolRegistry) -> list[dict[str, Any]]:
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

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
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
        self._save_message(session_id, "user", message)

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = WikiToolRegistry(wiki, self.db, ctx.wiki_id or self._get_default_wiki_id())

        system_prompt = self._build_system_prompt(ctx.wiki_id)
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        messages_for_llm = self._truncate_messages(raw_messages)

        try:
            llm = self._get_llm()
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
                    ctx._tool_calls[tool_name] = {"tool": tool_name, "args": args, "status": "pending"}
                    result = await self._execute_tool(tool_name, args, tool_registry, session_id, ctx)
                    ctx._tool_calls[tool_name]["result"] = result
                    ctx._tool_calls[tool_name]["status"] = "done"
                    yield ChatEvent.tool_call_end(tool_name, result)

                    if isinstance(result, dict) and result.get("status") == "confirmation_required":
                        conf_id = result.get("confirmation_id", "")
                        yield ChatEvent.confirmation_required(conf_id, result.get("impact", {}))
                    else:
                        tool_result_str = json.dumps(result.get("result", result) if isinstance(result, dict) else result)
                        ctx.add_assistant_message(
                            f"[TOOL: {tool_name}] Result: {tool_result_str}"
                        )

                elif event_type == "done":
                    final = event.get("content", accumulated)
                    ctx.add_assistant_message(final)
                    self._save_message(session_id, "assistant", final, tool_calls=list(ctx._tool_calls.values()) if hasattr(ctx, "_tool_calls") else None)
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
        async for event in llm.astream_chat(messages, tools=tools):
            yield event

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        tool_registry: WikiToolRegistry,
        session_id: str,
        ctx: AgentContext,
    ) -> dict | list:
        call_id = self.db.log_tool_call(session_id, tool_name, args, "pending")
        try:
            result = await tool_registry.execute(tool_name, args)
            status = "confirmation_required" if isinstance(result, dict) and result.get("status") == "confirmation_required" else "executed"
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

    def _save_message(self, session_id: str, role: str, content: str, tool_calls: list | None = None) -> None:
        import uuid
        try:
            self.db.save_message({
                "id": str(uuid.uuid4())[:8],
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_calls": tool_calls,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    def _get_wiki_for_context(self, ctx: AgentContext):
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_registry.get_wiki(wiki_id)
        return self.wiki_registry.get_default_wiki()

    async def run_dream(self, wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        editor = self._get_dream_editor(wiki_id)
        result = editor.run_dream()
        if result.get("pending_review", 0) > 0:
            nm = self._get_notification_manager(wiki_id)
            nm.add("info", f"Dream generated {result['pending_review']} proposals for review", data=result)
        return result

    def get_dream_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return []
        editor = self._get_dream_editor(wiki_id)
        return editor.get_edit_log(limit)

    def get_dream_proposals(self, wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"proposals": {}, "stats": {}}
        editor = self._get_dream_editor(wiki_id)
        return {
            "proposals": editor.proposal_manager.get_pending_by_page(),
            "stats": editor.proposal_manager.get_stats(),
        }

    def approve_proposal(self, proposal_id: str) -> dict:
        for editor in self._dream_editors.values():
            p = editor.proposal_manager.approve(proposal_id)
            if p:
                return p
        return {"status": "error", "error": "Proposal not found"}

    def reject_proposal(self, proposal_id: str) -> dict:
        for editor in self._dream_editors.values():
            p = editor.proposal_manager.reject(proposal_id)
            if p:
                return p
        return {"status": "error", "error": "Proposal not found"}

    def batch_approve_proposals(self, proposal_ids: list[str]) -> dict:
        results = []
        for pid in proposal_ids:
            r = self.approve_proposal(pid)
            results.append(r)
        return {"approved": len(results), "results": results}

    async def apply_proposals(self, wiki_id: str | None = None, proposal_ids: list[str] | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        editor = self._get_dream_editor(wiki_id)
        result = editor.apply_proposals(proposal_ids)
        if result.get("applied", 0) > 0:
            nm = self._get_notification_manager(wiki_id)
            nm.add("success", f"Applied {result['applied']} dream proposals", data=result)
        return result

    def list_notifications(self, wiki_id: str | None = None, unread_only: bool = False) -> list[dict]:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return []
        nm = self._get_notification_manager(wiki_id)
        if unread_only:
            return nm.list_unread()
        return nm.list_all()

    def mark_notification_read(self, notification_id: str) -> dict:
        for nm in self._notification_managers.values():
            if nm.mark_read(notification_id):
                return {"status": "ok", "notification_id": notification_id}
        return {"status": "error", "error": "Notification not found"}

    def list_confirmations(self, wiki_id: str | None = None) -> dict[str, list[dict]]:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {}
        registry = self._get_tool_registry(wiki_id)
        return registry.get_pending_by_group()

    async def approve_confirmation(self, confirmation_id: str, wiki_id: str | None = None, arguments: dict | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        registry = self._get_tool_registry(wiki_id)
        return registry.confirm_execution(confirmation_id, arguments=arguments)

    async def approve_confirmation_and_continue(
        self,
        confirmation_id: str,
        session_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Approve a confirmation, execute the tool, and feed result back to LLM."""
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            yield ChatEvent.error("No wiki_id available")
            return

        registry = self._get_tool_registry(wiki_id)
        result = registry.confirm_execution(confirmation_id, arguments=arguments)

        if result.get("status") == "error":
            yield ChatEvent.error(result.get("error", "Confirmation failed"))
            return

        yield ChatEvent.tool_call_end("confirmation_approved", result)

        # Feed tool result back into context and trigger LLM follow-up
        ctx = self._get_or_create_context(session_id, wiki_id)
        tool_result_str = json.dumps(result.get("result", result))
        ctx.add_assistant_message(f"[Confirmation approved] Tool result: {tool_result_str}")

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = WikiToolRegistry(wiki, self.db, ctx.wiki_id or self._get_default_wiki_id())
        system_prompt = self._build_system_prompt(ctx.wiki_id)
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        messages_for_llm = self._truncate_messages(raw_messages)

        try:
            llm = self._get_llm()
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
                    tool_result = await self._execute_tool(tool_name, args, tool_registry, session_id, ctx)
                    yield ChatEvent.tool_call_end(tool_name, tool_result)
                    if isinstance(tool_result, dict) and tool_result.get("status") == "confirmation_required":
                        conf_id = tool_result.get("confirmation_id", "")
                        yield ChatEvent.confirmation_required(conf_id, tool_result.get("impact", {}))
                    else:
                        trs = json.dumps(tool_result.get("result", tool_result) if isinstance(tool_result, dict) else tool_result)
                        ctx.add_assistant_message(f"[TOOL: {tool_name}] Result: {trs}")
                elif event_type == "done":
                    final = event.get("content", accumulated)
                    ctx.add_assistant_message(final)
                    self._save_message(session_id, "assistant", final)
                    yield ChatEvent.done(final)
        except Exception as e:
            logger.exception("Confirmation continue error")
            yield ChatEvent.error(str(e))

    async def reject_confirmation(self, confirmation_id: str, wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        registry = self._get_tool_registry(wiki_id)
        return registry.reject_execution(confirmation_id)

    async def batch_approve_confirmations(self, confirmation_ids: list[str], wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        results = []
        for cid in confirmation_ids:
            r = await self.approve_confirmation(cid, wiki_id)
            results.append(r)
        return {"approved": len(results), "results": results}

    def get_ingest_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return []
        return self.db.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self.db.get_ingest_entry(ingest_id)

    def get_agent_status(self, wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self._get_default_wiki_id()
        if not wiki_id:
            return {"state": "idle", "scheduler_tasks": [], "pending_confirmations": 0, "dream_proposals": {}, "unread_notifications": 0}

        scheduler = self._get_scheduler(wiki_id)
        tasks = scheduler.list_tasks()

        editor = self._get_dream_editor(wiki_id)
        dream_stats = editor.proposal_manager.get_stats()

        nm = self._get_notification_manager(wiki_id)
        unread = nm.unread_count()

        registry = self._get_tool_registry(wiki_id)
        pending_confs = len(registry.get_pending_confirmations())

        return {
            "state": "idle",
            "scheduler_tasks": tasks,
            "pending_work": {},
            "action_log": [],
            "pending_confirmations": pending_confs,
            "dream_proposals": dream_stats,
            "unread_notifications": unread,
        }