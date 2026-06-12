"""ChatOrchestrator — agent chat loop and SSE streaming.

Extracted from ChatService (v0.41) as the main entry point for chat().
Coordinates PromptBuilder, ContextManager, and ToolExecutor.

Owns:
  - Agent while loop (via ChatReActBridge + ReActEngine)
  - SSE event streaming
  - Session creation/restore
  - Abort/status management
  - Event translation (ReActEngine → frontend vocabulary)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from llmwikify.apps.chat.agent.context_manager import AgentContext

logger = logging.getLogger(__name__)


# ─── SSE event factory ────────────────────────────────────────


class ChatEvent:
    """Static factory for SSE event dicts."""

    @staticmethod
    def message_delta(content: str) -> dict:
        return {"type": "message_delta", "content": content}

    @staticmethod
    def thinking(content: str) -> dict:
        return {"type": "thinking", "content": content}

    @staticmethod
    def tool_call_start(tool: str, args: dict, call_id: str = "") -> dict:
        return {"type": "tool_call_start", "tool": tool, "args": args, "call_id": call_id}

    @staticmethod
    def tool_call_end(tool: str, result: Any, call_id: str = "", duration_ms: int = 0) -> dict:
        return {"type": "tool_call_end", "tool": tool, "result": result, "call_id": call_id, "duration_ms": duration_ms}

    @staticmethod
    def tool_call_error(tool: str, error: str, call_id: str = "", duration_ms: int = 0) -> dict:
        return {"type": "tool_call_error", "tool": tool, "error": error, "call_id": call_id, "duration_ms": duration_ms}

    @staticmethod
    def confirmation_required(
        conf_id: str, tool: str, args: dict, impact: dict, call_id: str = "",
    ) -> dict:
        return {
            "type": "confirmation_required",
            "confirmation_id": conf_id,
            "tool": tool,
            "args": args,
            "impact": impact,
            "call_id": call_id,
        }

    @staticmethod
    def done(final_response: str) -> dict:
        return {"type": "done", "final_response": final_response}

    @staticmethod
    def error(message: str) -> dict:
        return {"type": "error", "message": message}

    @staticmethod
    def save_warning(message: str) -> dict:
        return {"type": "save_warning", "message": message}


# ─── ChatOrchestrator ─────────────────────────────────────────


class ChatOrchestrator:
    """Agent chat orchestrator — the main entry point for chat().

    Coordinates PromptBuilder, ContextManager, and ToolExecutor.
    Delegates the ReAct loop to ChatReActBridge + ReActEngine.
    """

    def __init__(
        self,
        wiki_service: Any,
        chat_db: Any,
        memory_manager: Any = None,
        config: dict | None = None,
    ):
        from llmwikify.apps.chat.config import merge_six_step_config
        from llmwikify.apps.chat.agent.prompt_builder import PromptBuilder
        from llmwikify.apps.chat.agent.context_manager import ContextManager
        from llmwikify.apps.chat.agent.tool_executor import ToolExecutor
        from llmwikify.apps.chat.agent.event_log import EventLog

        self.wiki_service = wiki_service
        self.db = chat_db
        self.memory_manager = memory_manager
        self.config = config or merge_six_step_config()

        self.prompt_builder = PromptBuilder(wiki_service, memory_manager)
        self.context_manager = ContextManager(config=self.config)
        self.tool_executor = ToolExecutor(
            chat_db=chat_db,
            memory_manager=memory_manager,
            config=self.config,
        )
        self.event_log = EventLog(chat_db)

        self._session_status: dict[str, str] = {}
        self._abort_events: dict[str, asyncio.Event] = {}

    # ─── SSE chat ────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[dict]:
        """Stream a chat response as SSE events."""
        self._session_status[session_id or "new"] = "busy"
        abort_event = asyncio.Event()
        if session_id:
            self._abort_events[session_id] = abort_event

        try:
            if session_id is None:
                session_id = self.db.create_chat_session(wiki_id, jwt_token)
                yield {"type": "session_created", "session_id": session_id}
            else:
                session = self.db.get_chat_session(session_id)
                if session is None:
                    session_id = self.db.create_chat_session(wiki_id, jwt_token)
                    yield {"type": "session_created", "session_id": session_id}

            self.event_log.log(session_id, {"type": "user_message", "content": message[:200]})

            ctx = await self.context_manager.get_or_create(
                session_id, wiki_id,
                history_loader=self._load_history,
                db=self.db,
            )

            wiki_id_from_prefix, message = self.prompt_builder.parse_wiki_prefix(message)
            if wiki_id_from_prefix:
                ctx.set_recent_wiki(wiki_id_from_prefix)
                self.db.update_chat_session_wiki(session_id, wiki_id_from_prefix)

            if wiki_id and not wiki_id_from_prefix:
                ctx.set_recent_wiki(wiki_id)
                self.db.update_chat_session_wiki(session_id, wiki_id)

            if jwt_token:
                self.db.update_chat_session_jwt(session_id, jwt_token)

            ctx.add_user_message(message)
            self.tool_executor.save_message(session_id, "user", message)

            # Auto-set session title from first user message
            session = self.db.get_chat_session(session_id)
            if session and not session.get("title"):
                title = message[:100].strip()
                if title:
                    self.db.update_chat_session_title(session_id, title)

            wiki = self._get_wiki_for_context(ctx)
            if wiki is None:
                yield ChatEvent.error("No wiki available")
                return

            tool_registry = self.wiki_service.get_tool_registry(
                ctx.wiki_id or self.wiki_service.get_default_wiki_id()
            )

            system_prompt = await self.prompt_builder.build(
                ctx.wiki_id,
                user_message=message,
                session_id=session_id,
            )
            raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
            # Inject observations from previous tool calls
            obs_summary = ctx.get_observations_summary()
            if obs_summary:
                raw_messages.insert(-1, {
                    "role": "system",
                    "content": obs_summary,
                })
            # Compact + truncate
            raw_messages = await self.context_manager.prepare_messages(
                raw_messages, wiki_service=self.wiki_service,
            )
            messages_for_llm = raw_messages

            # Check if already aborted
            if abort_event.is_set():
                yield ChatEvent.error("Session aborted")
                return

            # Delegate to ChatReActBridge + ReActEngine
            async for event in self._chat_via_react(
                messages_for_llm=messages_for_llm,
                system_prompt=system_prompt,
                tool_registry=tool_registry,
                session_id=session_id,
                ctx=ctx,
            ):
                if abort_event.is_set():
                    yield ChatEvent.error("Session aborted")
                    return
                # Log non-streaming events (skip message_delta for volume)
                if event.get("type") != "message_delta":
                    self.event_log.log(session_id, event)
                yield event

        except Exception as e:
            logger.exception("Chat error")
            err_event = ChatEvent.error(str(e))
            self.event_log.log(session_id, err_event)
            yield err_event
        finally:
            self._session_status[session_id] = "idle"
            self._abort_events.pop(session_id, None)

    # ─── Confirmation continue ───────────────────────────────────

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

        ctx = await self.context_manager.get_or_create(
            session_id, wiki_id,
            history_loader=self._load_history,
            db=self.db,
        )
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
        system_prompt = await self.prompt_builder.build(
            ctx.wiki_id,
            user_message=ctx.messages[-1]["content"] if ctx.messages else None,
            session_id=session_id,
        )
        raw_messages = [{"role": "system", "content": system_prompt}] + ctx.get_messages()
        obs_summary = ctx.get_observations_summary()
        if obs_summary:
            raw_messages.insert(-1, {
                "role": "system",
                "content": obs_summary,
            })
        raw_messages = await self.context_manager.prepare_messages(
            raw_messages, wiki_service=self.wiki_service,
        )

        try:
            async for event in self._chat_via_react(
                messages_for_llm=raw_messages,
                system_prompt=system_prompt,
                tool_registry=tool_registry,
                session_id=session_id,
                ctx=ctx,
            ):
                yield event
        except Exception as e:
            logger.exception("Confirmation continue error")
            yield ChatEvent.error(str(e))

    # ─── Session management ──────────────────────────────────────

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from DB and evict its in-memory context."""
        self.context_manager.remove(session_id)
        self.db.delete_chat_session(session_id)
        return True

    def abort_session(self, session_id: str) -> dict:
        """Signal abort for an active session."""
        if session_id in self._abort_events:
            self._abort_events[session_id].set()
        return {"aborted": True, "session_id": session_id}

    def get_session_status(self, session_id: str) -> str:
        return self._session_status.get(session_id, "idle")

    def get_all_session_status(self) -> dict[str, str]:
        return dict(self._session_status)

    # ─── ReAct bridge ────────────────────────────────────────────

    async def _chat_via_react(
        self,
        messages_for_llm: list[dict[str, str]],
        system_prompt: str,
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> AsyncIterator[dict]:
        """ReAct path for chat()."""
        from llmwikify.apps.chat.agent.chat_react import ChatReActBridge
        from llmwikify.apps.chat.agent.react_engine import ReActEngine
        from llmwikify.apps.chat.skills.base import SkillContext

        bridge = ChatReActBridge(chat_service=self, config=self.config)
        config = bridge.build_config(
            session_id=session_id,
            wiki_id=ctx.wiki_id,
            tool_registry=tool_registry,
            user_message="",
            system_prompt=system_prompt,
            messages=messages_for_llm,
            ctx=ctx,
            max_iterations=self.config.get("max_chat_rounds", 10),
        )
        engine = ReActEngine(config)

        skill_ctx = SkillContext(
            session_id=session_id,
            wiki=self.wiki_service.get_wiki(ctx.wiki_id),
            db=self.db,
            llm_client=self.wiki_service.get_llm(),
            config={},
            metrics=None,
        )

        try:
            async for event in engine.run(skill_ctx):
                translated = self._translate_react_event(event, ctx, session_id)
                if translated is None:
                    continue
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
        """Translate ReActEngine event → frontend SSE event."""
        kind = event.get("type")
        if kind == "reasoning":
            return None
        if kind == "round_complete":
            return None
        if kind == "observation_error":
            return ChatEvent.save_warning(event.get("error", "observation failed"))
        if kind == "action_error":
            return {
                "type": "tool_call_error",
                "tool": event.get("action", ""),
                "error": event.get("error", ""),
                "call_id": event.get("call_id", ""),
            }
        if kind == "timeout":
            return ChatEvent.error(
                f"ReAct loop timed out after {event.get('limit', 0):.0f}s"
            )
        if kind == "phase":
            phase = event.get("phase")
            final_state = event.get("final_state")
            if phase == "done":
                if not isinstance(final_state, dict):
                    return None
                final = final_state.get("final_answer") or ""
                if not final:
                    final = final_state.get("llm_content", "")
                if not final:
                    final = ""
                if final.startswith("[error]"):
                    err_msg = final[len("[error]"):].strip()
                    return ChatEvent.error(err_msg or "LLM stream failed")
                thinking = ""
                if hasattr(ctx, "_thinking"):
                    thinking = ctx._thinking
                if thinking:
                    ctx._thinking = thinking
                ctx.add_assistant_message(final)
                # Save assistant message
                from llmwikify.foundation.llm.token_estimator import count_tokens
                model_name = "gpt-4o"
                tokens_output = count_tokens(final, model_name)
                self.tool_executor.save_message(
                    session_id, "assistant", final,
                    tool_calls=list(ctx._tool_calls.values())
                    if ctx._tool_calls else None,
                    tokens_output=tokens_output,
                )
                if self.tool_executor._save_error_count > 0:
                    return [
                        ChatEvent.save_warning(
                            f"已丢弃 {self.tool_executor._save_error_count} 条消息的持久化失败"
                        ),
                        ChatEvent.done(final),
                    ]
                return ChatEvent.done(final)
            if phase == "cancelled":
                return None
            if phase == "paused":
                return None
            if phase == "timeout":
                return ChatEvent.error("ReAct loop timed out")
            if phase == "incomplete":
                msg = "研究未完成所有阶段"
                if isinstance(final_state, dict):
                    if final_state.get("synthesis"):
                        msg = "研究分析已完成，但未生成完整报告"
                    elif final_state.get("sources"):
                        msg = f"已收集 {len(final_state.get('sources', []))} 个来源，但未完成分析"
                    elif final_state.get("sub_queries"):
                        msg = "已规划子查询，但未收集到来源"
                    elif final_state.get("final_answer"):
                        msg = final_state["final_answer"]
                return ChatEvent.done(msg)
        # Pass through: message_delta, thinking, tool_call_start,
        # tool_call_end, confirmation_required, error, save_warning
        return event

    # ─── Internal helpers ────────────────────────────────────────

    async def _load_history(self, session_id: str) -> list[dict]:
        """Load conversation history from MemoryManager or DB."""
        if self.memory_manager is not None:
            return list(reversed(
                await self.memory_manager.conversation.alist(
                    session_id, limit=100,
                )
            ))
        return list(reversed(
            self.db.get_chat_messages(session_id, limit=100)
        ))

    def _get_wiki_for_context(self, ctx: AgentContext) -> Any:
        wiki_id = ctx.recent_wiki_id or ctx.wiki_id
        if wiki_id:
            return self.wiki_service.get_wiki(wiki_id)
        return self.wiki_service.get_wiki()
