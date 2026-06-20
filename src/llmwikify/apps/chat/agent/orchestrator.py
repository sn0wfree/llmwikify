"""ChatOrchestrator — agent chat loop and SSE streaming.

Extracted from ChatService (v0.41) as the main entry point for chat().
Coordinates PromptBuilder, ContextManager, and ToolExecutor.

Owns:
  - ChatRunnerV2 5-step state machine (PRECHECK/REASON/ACT/OBSERVE/COMPLETE)
  - SSE event streaming
  - Session creation/restore
  - Abort/status management
  - V2 persistence hook (tool result persistence, assistant message save)
  - Research run_id extraction (for /study autoresearch integration)

Plan B migration (B-5): now uses ChatRunnerV2 (runner_v2.py) as the
sole loop engine. The legacy ChatReActBridge + ReActEngine stack
(chat_react.py / react_engine.py / react_loop.py) was archived in
B-5 and removed in B-7.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from llmwikify.apps.chat.agent.context_manager import AgentContext
from llmwikify.foundation.callback import AgentHook

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
    def save_warning(reason: str) -> dict:
        return {"type": "save_warning", "reason": reason}


# ─── V2 persistence hook (Plan B B-4) ──────────────────────────


class _V2PersistenceHook(AgentHook):
    """Persist tool results to MemoryManager.context after each tool call.

    Mirrors the bridge's manual ``_persist_tool_result`` call
    (chat_react.py:572) but as a hook in the v2 runner's lifecycle
    (after_tool_executed). Errors are isolated (logged, not raised)
    so a failed persist does not break the run.

    Phase A-3 (2026-06-20): made this a proper subclass of
    :class:`AgentHook` so :class:`CompositeHook` can safely call
    ``wants_streaming()`` / other hook points without ``AttributeError``
    when only ``after_tool_executed`` is overridden.
    """

    def __init__(self, tool_executor: Any, session_id: str) -> None:
        self._tool_executor = tool_executor
        self._session_id = session_id

    async def after_tool_executed(self, ctx: Any, tool_call: Any, result: Any) -> None:
        try:
            await self._tool_executor.persist_tool_result(
                self._session_id,
                tool_call.get("name", "") if isinstance(tool_call, dict) else "",
                tool_call.get("args", {}) if isinstance(tool_call, dict) else {},
                result,
            )
        except Exception:
            logger.warning("_persist_tool_result failed", exc_info=True)


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
        skill_service: Any = None,
    ):
        from llmwikify.apps.chat.agent.confirmation_manager import (
            ConfirmationManager,
        )
        from llmwikify.apps.chat.agent.context_manager import ContextManager
        from llmwikify.apps.chat.agent.event_log import EventLog
        from llmwikify.apps.chat.agent.prompt_builder import PromptBuilder
        from llmwikify.apps.chat.agent.session_manager import SessionManager
        from llmwikify.apps.chat.agent.tool_executor import ToolExecutor
        from llmwikify.apps.chat.config import merge_six_step_config

        self.wiki_service = wiki_service
        self.db = chat_db
        self.memory_manager = memory_manager
        self.config = config or merge_six_step_config()
        self.skill_service = skill_service

        self.prompt_builder = PromptBuilder(
            wiki_service, memory_manager, chat_db=chat_db,
        )
        self.context_manager = ContextManager(config=self.config)
        self.tool_executor = ToolExecutor(
            chat_db=chat_db,
            memory_manager=memory_manager,
            config=self.config,
        )
        self.event_log = EventLog(chat_db)

        self._session_status: dict[str, str] = {}
        self._abort_events: dict[str, asyncio.Event] = {}
        self._tool_registries: dict[tuple[str, str], Any] = {}

        # Phase 5: extract confirmation + session management into
        # dedicated classes. Both managers observe the dicts above by
        # reference, so state changes stay consistent.
        self._confirmation_mgr = ConfirmationManager(self._tool_registries)
        self._session_mgr = SessionManager(
            db=chat_db,
            context_manager=self.context_manager,
            session_status=self._session_status,
            abort_events=self._abort_events,
        )

        # P1-2 (vendored from nanobot command/router.py): slash command
        # dispatch table. Commands are intercepted before the ReAct loop
        # so they bypass LLM round-trips (e.g. /stop, /help, /clear).
        from llmwikify.apps.chat.command_router import (
            CommandContext,
            CommandRouter,
        )
        self.command_router = self._build_default_command_router()

    def _get_tool_registry(
        self,
        ctx: AgentContext,
        session_id: str | None = None,
        *,
        expose_subagent: bool = False,
        subagent_manager: Any = None,
        child_tool_registry: Any = None,
    ) -> Any:
        """Build (or fetch from cache) the tool registry exposed to the LLM.

        Phase 10-E (2026-06-20): when ``expose_subagent=True`` the
        ``subagent`` skill is added to the SkillToolAdapter's exposed
        skills and the supplied ``subagent_manager`` +
        ``child_tool_registry`` are stitched into the adapter so
        ``spawn_subagent`` can reach a real manager. Children get a
        registry built with ``expose_subagent=False`` so they can't
        spawn grandchildren.

        The cache key includes ``expose_subagent`` so parent and
        child registries don't collide.
        """
        wiki_id = ctx.wiki_id or self.wiki_service.get_default_wiki_id()
        wiki_registry = self.wiki_service.get_tool_registry(wiki_id)
        if self.skill_service is None:
            return wiki_registry
        cache_key = (
            session_id or ctx.session_id or "",
            wiki_id or "",
            bool(expose_subagent),
        )
        if cache_key in self._tool_registries and not expose_subagent:
            # Only the child (no-subagent) registry is safe to cache
            # cross-invocation. Parent registries hold a live
            # SubagentManager ref and must rebuild each chat.
            return self._tool_registries[cache_key]
        from llmwikify.apps.agent.tools.skill_adapter import (
            CompositeToolRegistry,
            SkillToolAdapter,
        )
        adapter_kwargs: dict[str, Any] = {
            "wiki": self.wiki_service.get_wiki(wiki_id),
            "db": self.db,
            "wiki_id": wiki_id,
            "session_id": session_id or ctx.session_id,
            "wiki_service": self.wiki_service,
        }
        if expose_subagent:
            adapter_kwargs["subagent_manager"] = subagent_manager
            adapter_kwargs["child_tool_registry"] = child_tool_registry
        registry = CompositeToolRegistry(
            wiki_registry,
            SkillToolAdapter(self.skill_service, **adapter_kwargs),
        )
        if not expose_subagent:
            self._tool_registries[cache_key] = registry
        return registry

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

            # P1-2 (vendored from nanobot command/router.py): intercept
            # slash commands before the LLM loop runs. Priority commands
            # (e.g. /stop) run first; then exact/prefix commands (e.g.
            # /help, /clear). If a handler produces events, yield them
            # and short-circuit the rest of the chat flow.
            async for ev in self._dispatch_command(
                text=message,
                session_id=session_id,
                wiki_id=ctx.wiki_id,
                db=self.db,
                ctx=ctx,
                abort_event=abort_event,
            ):
                yield ev
                if ev.get("type") == "command_done":
                    return

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

            tool_registry = self._get_tool_registry(ctx, session_id)

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

            # Delegate to ChatRunnerV2 (Plan B)
            async for event in self._chat_via_runner_v2(
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
                if event.get("type") == "confirmation_required":
                    tool = event.get("tool", "tool")
                    self.tool_executor.save_message(
                        session_id,
                        "assistant",
                        f"Confirmation required for {tool}: {event.get('confirmation_id', '')}",
                    )
                elif event.get("type") == "error":
                    self.tool_executor.save_message(
                        session_id,
                        "assistant",
                        f"Error: {event.get('message', '')}",
                    )
                yield event

        except Exception as e:
            logger.exception("Chat error")
            err_event = ChatEvent.error(str(e))
            self.event_log.log(session_id, err_event)
            self.tool_executor.save_message(session_id, "assistant", f"Error: {e}")
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

        ctx = await self.context_manager.get_or_create(
            session_id, wiki_id,
            history_loader=self._load_history,
            db=self.db,
        )
        result = await self._confirmation_mgr.approve_confirmation(
            confirmation_id, wiki_id, arguments
        )
        if self._is_unknown_confirmation(result):
            result = await self.wiki_service.approve_confirmation(
                confirmation_id, wiki_id, arguments
            )

        if result.get("status") == "error":
            message = result.get("error", "Confirmation failed")
            self.tool_executor.save_message(session_id, "assistant", f"Error: {message}")
            yield ChatEvent.error(message)
            return

        tool_result_str = json.dumps(result.get("result", result))
        ctx.add_assistant_message(
            f"[Confirmation approved] Tool result: {tool_result_str}"
        )

        wiki = self._get_wiki_for_context(ctx)
        if wiki is None:
            yield ChatEvent.error("No wiki available")
            return

        tool_registry = self._get_tool_registry(ctx, session_id)
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
            async for event in self._chat_via_runner_v2(
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

    # ─── Confirmations ───────────────────────────────────────────
    # Phase 5: these methods now delegate to ``self._confirmation_mgr``
    # (see ``confirmation_manager.py``). The public signatures are
    # preserved so external callers (``AgentService``,
    # ``chat_sse.py`` HTTP routes) keep working.

    @staticmethod
    def _is_unknown_confirmation(result: Any) -> bool:
        """Static helper kept for backward compatibility.

        Prefer ``ConfirmationManager.is_unknown_confirmation``. The
        logic is identical; this method is a thin shim so existing
        callers (e.g. ``approve_confirmation_continue``) and external
        consumers (e.g. tests) continue to work.
        """
        from llmwikify.apps.chat.agent.confirmation_manager import (
            ConfirmationManager as _CM,
        )
        return _CM.is_unknown_confirmation(result)

    def list_confirmations(self, wiki_id: str | None = None) -> dict[str, list[dict]]:
        return self._confirmation_mgr.list_confirmations(wiki_id)

    async def approve_confirmation(
        self,
        confirmation_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        return await self._confirmation_mgr.approve_confirmation(
            confirmation_id, wiki_id, arguments,
        )

    async def reject_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None,
    ) -> dict:
        return await self._confirmation_mgr.reject_confirmation(confirmation_id, wiki_id)

    async def batch_approve_confirmations(
        self, confirmation_ids: list[str], wiki_id: str | None = None,
    ) -> dict:
        return await self._confirmation_mgr.batch_approve_confirmations(
            confirmation_ids, wiki_id,
        )

    # ─── Session management ──────────────────────────────────────
    # Phase 5: also delegated to ``self._session_mgr``
    # (see ``session_manager.py``). The public signatures are
    # preserved.

    def delete_session(self, session_id: str) -> bool:
        return self._session_mgr.delete_session(session_id)

    def revert_session(self, session_id: str, message_id: str) -> int:
        return self._session_mgr.revert_session(session_id, message_id)

    def edit_message(self, message_id: str, new_content: str) -> bool:
        return self._session_mgr.edit_message(message_id, new_content)

    def abort_session(self, session_id: str) -> bool:
        return self._session_mgr.abort_session(session_id)

    # ─── Slash commands (P1-2, vendored from nanobot) ───────────

    def _build_default_command_router(self) -> Any:
        """Build the default CommandRouter with a few built-in commands.

        Built-ins:
          - ``/stop`` (priority) — abort the active session.
          - ``/help`` (exact) — list available commands.
          - ``/clear`` (exact) — clear the in-memory context.
          - ``/status`` (exact) — report session status.
          - ``/title <text>`` (prefix) — set session title.

        Custom routers can be installed by replacing ``self.command_router``
        after construction; the orchestrator only calls it via
        ``_dispatch_command``.
        """
        from llmwikify.apps.chat.command_router import CommandRouter

        router = CommandRouter()

        async def stop_handler(ctx: Any) -> dict:
            if ctx.abort_event is not None:
                ctx.abort_event.set()
            return {
                "type": "command_done",
                "command": "/stop",
                "ok": True,
                "message": "Session aborted",
            }

        async def help_handler(ctx: Any) -> dict:
            return {
                "type": "command_done",
                "command": "/help",
                "ok": True,
                "message": (
                    "Available commands: /stop, /help, /clear, /status, "
                    "/title <text>, /memory_dream [session <id>], "
                    "/goal [<objective> | done [recap]]"
                ),
            }

        async def clear_handler(ctx: Any) -> dict:
            if ctx.ctx is not None and hasattr(ctx.ctx, "clear"):
                ctx.ctx.clear()
            return {
                "type": "command_done",
                "command": "/clear",
                "ok": True,
                "message": "Context cleared",
            }

        async def status_handler(ctx: Any) -> dict:
            return {
                "type": "command_done",
                "command": "/status",
                "ok": True,
                "message": f"session_id={ctx.session_id} wiki_id={ctx.wiki_id}",
            }

        async def title_handler(ctx: Any) -> dict:
            new_title = (ctx.args or "").strip()
            if not new_title:
                return {
                    "type": "command_done",
                    "command": "/title",
                    "ok": False,
                    "message": "Usage: /title <text>",
                }
            if ctx.db is not None and ctx.session_id:
                try:
                    ctx.db.update_chat_session_title(ctx.session_id, new_title)
                except Exception:
                    pass
            return {
                "type": "command_done",
                "command": "/title",
                "ok": True,
                "message": f"Title set: {new_title[:50]}",
            }

        # Phase 6 (2026-06-19): /memory_dream prefix command.
        # Triggers the long-term fact extractor (borrowed from
        # nanobot agent/memory.py:859). Note: this is distinct
        # from the existing ``/dream`` slash command which wraps
        # ``apps/agent/dream_editor/`` (wiki edit proposals).
        async def memory_dream_handler(ctx: Any) -> AsyncIterator[dict]:
            from llmwikify.apps.chat.memory import MemoryManager
            from llmwikify.apps.chat.skills.crud.memory_dream_skill import (
                _get_dream,
                _run,
                _run_for_session,
            )

            # Build a minimal SkillContext-like object for the skill handlers
            class _StubSkillContext:
                def __init__(self, c: Any) -> None:
                    self.session_id = c.session_id
                    self.config: dict[str, Any] = {
                        "memory_manager": getattr(c, "memory_manager", None),
                    }

            stub = _StubSkillContext(ctx)
            dream = _get_dream(stub)
            if isinstance(dream, dict) and dream.get("ok") is False:
                yield {
                    "type": "command_done",
                    "command": "/memory_dream",
                    "ok": False,
                    "message": dream.get("message", "dream not configured"),
                }
                return

            args_text = (ctx.args or "").strip()
            if args_text.startswith("session "):
                sid = args_text[len("session "):].strip()
                result = await _run_for_session({"session_id": sid}, stub)
            else:
                result = await _run({}, stub)

            yield {
                "type": "command_done",
                "command": "/memory_dream",
                "ok": result.ok if hasattr(result, "ok") else True,
                "message": (
                    result.message
                    if hasattr(result, "message") and not result.ok
                    else "dream complete"
                ),
                "data": getattr(result, "data", None),
            }

        # Phase 8 (2026-06-20): /goal slash command — register / inspect /
        # complete a sustained goal. Thin wrapper around GoalSkill so
        # users get the same ``ChatRunner`` ergonomics from the chat
        # input box.
        #   /goal                       → show current goal
        #   /goal <objective text>      → start_long_task (objective=text)
        #   /goal done [recap text]     → complete_goal (recap=text)
        async def goal_handler(ctx: Any) -> dict:
            from llmwikify.apps.chat.skills.crud.goal_skill import (
                _complete_goal,
                _get_goal,
                _start_long_task,
            )

            class _StubSkillContext:
                def __init__(self, c: Any) -> None:
                    self.session_id = c.session_id or ""
                    self.db = c.db
                    self.config: dict[str, Any] = {}

            def _summarize(args_text: str, res: Any) -> str:
                data = getattr(res, "data", None) or {}
                if not args_text:
                    if not data.get("active"):
                        return "No active goal"
                    g = data.get("goal", {})
                    return f"Active: {g.get('objective', '')[:100]}"
                if args_text.lower() == "done" or args_text.lower().startswith(
                    "done ",
                ):
                    if data.get("completed"):
                        return f"Completed: {data.get('objective', '')[:80]}"
                    return data.get("reason", "no active goal")
                return f"Goal registered: {data.get('objective', '')[:100]}"

            stub = _StubSkillContext(ctx)
            args_text = (ctx.args or "").strip()

            if not args_text:
                result = await _get_goal({}, stub)
            elif args_text.lower() == "done" or args_text.lower().startswith(
                "done ",
            ):
                recap = args_text[4:].strip() if len(args_text) > 4 else ""
                result = await _complete_goal({"recap": recap}, stub)
            else:
                result = await _start_long_task(
                    {"goal": args_text, "ui_summary": args_text[:120]},
                    stub,
                )

            ok = getattr(result, "status", "ok") == "ok"
            return {
                "type": "command_done",
                "command": "/goal",
                "ok": ok,
                "message": (
                    getattr(result, "error", "") or "goal command failed"
                    if not ok
                    else _summarize(args_text, result)
                ),
                "data": getattr(result, "data", None),
            }

        router.priority("/stop", stop_handler)
        router.exact("/help", help_handler)
        router.exact("/clear", clear_handler)
        router.exact("/status", status_handler)
        router.prefix("/title", title_handler)
        router.prefix("/memory_dream", memory_dream_handler)
        router.prefix("/goal", goal_handler)
        return router

    async def _dispatch_command(
        self,
        text: str,
        session_id: str | None,
        wiki_id: str | None,
        db: Any,
        ctx: Any,
        abort_event: Any,
    ) -> AsyncIterator[dict]:
        """Dispatch ``text`` through the command router.

        Yields the events produced by the matched handler, followed by
        a ``command_done`` event so the caller can short-circuit. If
        the text is not a command, yields nothing.
        """
        from llmwikify.apps.chat.command_router import CommandContext

        stripped = text.strip()
        if not stripped or not stripped.startswith("/"):
            return
        # ``is_command`` is case-insensitive on its input; we feed it
        # the lowercased copy so the registered command set (also
        # lowercased) matches.
        if not self.command_router.is_command(stripped.lower()):
            return

        # ``raw`` is the lowercased command name (router matches it
        # case-insensitively). We keep ``text`` original-case so
        # prefix handlers can read user-supplied args with their
        # original casing intact.
        cmd_ctx = CommandContext(
            text=stripped,
            session_id=session_id,
            wiki_id=wiki_id,
            db=db,
            ctx=ctx,
            abort_event=abort_event,
            key=session_id or "default",
            raw=stripped.lower(),
        )

        # Priority tier first (runs without any lock / setup work).
        events: list[dict] = []
        if self.command_router.is_priority(stripped):
            events = await self.command_router.dispatch_priority(cmd_ctx)
        else:
            events = await self.command_router.dispatch(cmd_ctx)

        for ev in events:
            yield ev
        if events:
            yield {
                "type": "command_done",
                "command": stripped.split()[0],
                "ok": True,
            }

    def get_session_status(self, session_id: str) -> str:
        return self._session_mgr.get_session_status(session_id)

    def get_all_session_status(self) -> dict[str, str]:
        return self._session_mgr.get_all_session_status()

    # ─── V2 runner path (Plan B, default since B-5) ────────────────

    async def _chat_via_runner_v2(
        self,
        messages_for_llm: list[dict[str, str]],
        system_prompt: str,
        tool_registry: Any,
        session_id: str,
        ctx: AgentContext,
    ) -> AsyncIterator[dict]:
        """V2 path: use ChatRunnerV2 (Plan B) instead of ReActEngine.

        Reuses ChatBridgeBackend as the chat_service adapter (it already
        implements the 4 methods ChatRunnerV2 needs: wiki_service,
        _truncate_messages, _get_toolspec, _llm_stream_with_retry).

        Persists tool results via a V2PersistenceHook (replaces the
        bridge's manual _persist_tool_result call). On done, saves the
        assistant message via tool_executor.save_message (same as v1).
        """
        from llmwikify.apps.chat.agent.bridge_backend import ChatBridgeBackend
        from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
        from llmwikify.apps.chat.agent.spec import ChatRunSpec
        from llmwikify.foundation.callback import AgentHook, CompositeHook
        from llmwikify.foundation.callback.integrations.wiki import WikiHook

        bridge_backend = ChatBridgeBackend(
            tool_executor=self.tool_executor,
            context_manager=self.context_manager,
            wiki_service=self.wiki_service,
            config=self.config,
        )
        hook = CompositeHook([
            WikiHook(wiki=self.wiki_service.get_wiki(ctx.wiki_id)),
            _V2PersistenceHook(self.tool_executor, session_id),
        ])
        runner = ChatRunnerV2(
            chat_service=bridge_backend,
            tool_executor=self.tool_executor,
            prompt_builder=self.prompt_builder,
            hook=hook,
            config=self.config,
        )
        # Phase 10-E (2026-06-20): wire in-process SubagentManager so
        # the LLM can call ``spawn_subagent``. The child registry is
        # built with ``expose_subagent=False`` so children cannot
        # spawn grandchildren. The parent tool_registry is rebuilt
        # with ``expose_subagent=True`` and the manager+child
        # registry stitched into SkillContext.config.
        from llmwikify.apps.chat.agent.subagent_manager import (
            SubagentManager,
        )
        subagent_manager = SubagentManager(runner)
        child_tool_registry = self._get_tool_registry(
            ctx, session_id, expose_subagent=False,
        )
        tool_registry = self._get_tool_registry(
            ctx,
            session_id,
            expose_subagent=True,
            subagent_manager=subagent_manager,
            child_tool_registry=child_tool_registry,
        )
        # Phase 10 (2026-06-20): wire goal_active_predicate so a session
        # whose goal_state.status is no longer "active" stops at the
        # next PRECHECK. Closure captures ``session_id`` + ``self.db``;
        # exception path returns True (don't kill loop on DB hiccup).
        # Sessions without a goal default to True (Phase 8 back-compat).
        chat_db = self.db
        captured_sid = session_id

        def _goal_active_predicate() -> bool:
            try:
                getter = getattr(chat_db, "get_session_metadata", None)
                if getter is None:
                    return True
                md = getter(captured_sid) or {}
                gs = md.get("goal_state")
                if not isinstance(gs, dict):
                    return True
                return gs.get("status") == "active"
            except Exception:
                return True

        spec = ChatRunSpec(
            messages=list(messages_for_llm),
            tool_registry=tool_registry,
            session_id=session_id,
            wiki_id=ctx.wiki_id,
            max_iterations=self.config.get("max_chat_rounds", 10),
            microcompact=True,
            goal_active_predicate=_goal_active_predicate,
        )

        accumulated_tools: list[dict] = []
        try:
            async for event in runner.run_stream(spec):
                kind = event.get("type")
                if kind == "tool_call_end":
                    tool = event.get("tool", "")
                    if "autoresearch_compound" in tool and "run" in tool:
                        result = event.get("result", {})
                        if isinstance(result, dict):
                            data = (
                                result.get("data", {})
                                if result.get("status") == "ok"
                                else result
                            )
                            run_id = data.get("run_id", "")
                            if run_id:
                                yield {
                                    "type": "research_run_started",
                                    "run_id": run_id,
                                    "status": data.get("status", "running"),
                                    "workflow_name": data.get(
                                        "workflow_name", "autoresearch-compound",
                                    ),
                                    "timeline": data.get("timeline", []),
                                    "writes_wiki": False,
                                    "proposal_only": True,
                                }
                    accumulated_tools.append({
                        "tool": event.get("tool", ""),
                        "args": event.get("args", {}),
                        "result": event.get("result"),
                        "call_id": event.get("call_id", ""),
                    })
                if kind == "done":
                    final = event.get("content", "") or ""
                    research_run_id = self._extract_research_run_id_from_tools(
                        accumulated_tools,
                    )
                    if research_run_id and not final.strip():
                        final = (
                            "研究已启动\n\n"
                            "研究进行中，可通过下方卡片查看实时进度与结果。"
                        )
                    self._save_assistant_message_v2(
                        session_id, final, accumulated_tools, research_run_id,
                    )
                    if self.tool_executor._save_error_count > 0:
                        yield ChatEvent.save_warning(
                            f"已丢弃 {self.tool_executor._save_error_count} 条消息的持久化失败",
                        )
                yield event
        except Exception as e:
            logger.exception("V2 runner chat error")
            yield ChatEvent.error(str(e))

    def _save_assistant_message_v2(
        self,
        session_id: str,
        content: str,
        tool_calls: list[dict],
        research_run_id: str | None,
    ) -> None:
        """Save assistant message to DB on done (V2 path).

        Counts tokens (no model name fallback per LAL/audit fix),
        attaches research_run_id for /study autoresearch integration,
        persists via tool_executor.save_message.
        """
        from llmwikify.foundation.llm.token_estimator import count_tokens

        tokens_output = count_tokens(content, "unknown")
        self.tool_executor.save_message(
            session_id,
            "assistant",
            content,
            tool_calls=tool_calls or None,
            tokens_output=tokens_output,
            research_run_id=research_run_id,
        )

    @staticmethod
    def _extract_research_run_id_from_tools(
        tool_calls: list[dict],
    ) -> str | None:
        """Scan v2 tool_call_end events for an autoresearch run_id.

        When /study triggers autoresearch_compound_run, extracts its
        run_id from the tool result so the assistant message can be
        bound to the run (frontend reload reconstructs the card).
        """
        for tc in tool_calls:
            name = tc.get("tool", "")
            if "autoresearch_compound" not in name or "run" not in name:
                continue
            result = tc.get("result")
            if not isinstance(result, dict):
                continue
            data = result.get("data") if result.get("status") == "ok" else result
            if not isinstance(data, dict):
                continue
            run_id = data.get("run_id")
            if isinstance(run_id, str) and run_id:
                return run_id
        return None

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
