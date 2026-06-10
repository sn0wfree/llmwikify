"""Chat ReAct adapter — bridges ReActEngine with ChatService.

This module provides the glue between the generic ``ReActEngine``
and the chat-specific concerns (LLM streaming, tool execution,
SSE event emission, observation aggregation).

Usage in ChatService::

    from llmwikify.apps.chat.agent.chat_react import ChatReActBridge

    bridge = ChatReActBridge(chat_service=self)
    config = bridge.build_config(
        session_id=session_id,
        wiki_id=wiki_id,
        tool_registry=tool_registry,
        user_message=message,
        system_prompt=system_prompt,
        messages=messages_for_llm,
        ctx=ctx,
    )
    engine = ReActEngine(config)
    async for event in engine.run(skill_ctx):
        yield event

Components
----------

- ``REACT_SYSTEM_PROMPT`` — injected into the system prompt to
  instruct the LLM to follow Thought → Action → Observation.
- ``ChatReActState`` — tracks per-turn ReAct state (thoughts,
  observations, round count).
- ``ChatReActBridge`` — builds a ``ReActConfig`` wired to
  ChatService's LLM streaming (with retry), tool execution (with
  DB persistence and confirmation flow), text-mode
  ``[TOOL_CALL]`` parsing, and observation aggregation.

This is the functional equivalent of ``ChatBase.aask_with_tools``
(``base.py:455-624``) but driven by the unified ``ReActEngine``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.agent.react_engine import (
    ReActConfig,
    ReActEngine,
)
from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser
from llmwikify.apps.chat.skills.base import (
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── ReAct system prompt ──────────────────────────────────────────

REACT_SYSTEM_PROMPT = """\
## Reasoning Pattern

For each user request, follow this structured reasoning pattern:

1. **Thought**: Analyze what tools you need and why. Think step by step about the best approach.
2. **Action**: Choose and call the appropriate tool(s).
3. **Observation**: Review the tool result. If it doesn't fully answer the question, plan a follow-up action.

When you have enough information to answer, provide your final response.

### Rules
- Always start with a clear Thought before calling any tool.
- After each tool result, include an Observation about what you learned.
- If the first tool call doesn't fully answer the question, plan a follow-up.
- You may call multiple tools in sequence if needed.
- Request confirmation before any write/modify operations.
- When done, provide your final answer directly (no more tool calls).
"""


# ─── Chat ReAct state ────────────────────────────────────────────


@dataclass
class ChatReActState:
    """Per-turn ReAct state for chat.

    Tracked fields are merged into the engine's state dict so
    they persist across rounds and are available in the
    ``state_snapshot`` of ``round_complete`` events.
    """

    session_id: str = ""
    wiki_id: str = ""

    thoughts: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    round: int = 0

    final_answer: str = ""
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_content: str = ""
    llm_thinking: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "wiki_id": self.wiki_id,
            "thoughts": list(self.thoughts),
            "observations": list(self.observations),
            "tool_results": list(self.tool_results),
            "round": self.round,
            "final_answer": self.final_answer,
        }

    def add_thought(self, thought: str) -> None:
        self.thoughts.append(thought)

    def add_observation(self, obs: str) -> None:
        self.observations.append(obs)
        if len(self.observations) > 10:
            self.observations = self.observations[-10:]

    def add_tool_result(self, tool: str, result: Any) -> None:
        self.tool_results.append({"tool": tool, "result": result})

    def get_observation_summary(self) -> str:
        if not self.observations:
            return ""
        lines = ["## Recent tool observations"]
        for i, obs in enumerate(self.observations[-5:], 1):
            lines.append(f"{i}. {obs}")
        return "\n".join(lines)


# ─── Chat ReAct bridge ───────────────────────────────────────────


class ChatReActBridge:
    """Bridges ReActEngine with ChatService's tool execution.

    Builds a ``ReActConfig`` whose:

    - ``reason`` callback: streams the LLM response (with retry +
      text-mode ``[TOOL_CALL]`` parsing + message truncation) and
      returns ``{action, thought}``.
    - ``action_handler``: executes pending tool calls (parallel),
      updates ``AgentContext``, persists to DB, emits SSE events
      (``tool_call_start`` / ``tool_call_end`` / ``tool_call_error``
      / ``confirmation_required``), and generates observations.
    - ``observe`` callback: aggregates observations into a summary
      for the next reasoning step.
    - ``done_condition``: ``phase == "done"``.

    The bridge is the functional equivalent of
    ``ChatBase.aask_with_tools`` (``base.py:455-624``) — same
    event vocabulary, same retry semantics, same text-mode
    fallback, same DB persistence.
    """

    def __init__(self, chat_service: Any) -> None:
        self._chat_service = chat_service

    def build_config(
        self,
        session_id: str,
        wiki_id: str | None,
        tool_registry: Any,
        user_message: str,
        system_prompt: str,
        messages: list[dict[str, str]],
        ctx: Any,
        max_iterations: int = 4,
    ) -> ReActConfig:
        """Build a ReActConfig for one chat turn.

        Args:
            session_id: current chat session ID
            wiki_id: current wiki context
            tool_registry: the wiki tool registry
            user_message: the user's message (for state)
            system_prompt: the full system prompt (already built)
            messages: the full message list for the LLM
            ctx: the AgentContext for this session
            max_iterations: max ReAct rounds (default 4)

        Returns:
            A fully-wired ReActConfig ready for ReActEngine.
        """
        state = ChatReActState(
            session_id=session_id,
            wiki_id=wiki_id or "",
        )

        initial_state: dict[str, Any] = {
            **state.to_dict(),
            "user_message": user_message,
            "phase": "",
            "cancelled": False,
            "paused": False,
            "pending_tool_calls": [],
            "llm_content": "",
            "llm_thinking": "",
        }

        actions = self._build_actions(tool_registry)

        # MUTABLE message list (Phase 6.1 / v0.37): the reason
        # callback and the action handler both close over this
        # list. The action handler appends tool result messages
        # (``{role: "tool", name, content}``) on every round, so
        # the next reason call sees the LLM's prior tool_calls
        # AND the corresponding tool results — the standard
        # OpenAI-style multi-turn tool conversation.
        conversation_messages: list[dict[str, Any]] = list(messages)

        return ReActConfig(
            actions=actions,
            initial_state=initial_state,
            reason=self._make_reason_callback(
                conversation_messages=conversation_messages,
                tool_registry=tool_registry,
                ctx=ctx,
            ),
            action_handler=self._make_action_handler(
                tool_registry=tool_registry,
                session_id=session_id,
                ctx=ctx,
                conversation_messages=conversation_messages,
            ),
            observe=self._make_observe_callback(),
            done_condition=lambda s: s.get("phase") == "done",
            max_rounds=max_iterations,
            on_after_act=self._make_after_act_hook(),
        )

    def _build_actions(self, tool_registry: Any) -> list[SkillAction]:
        """Build SkillAction stubs from the tool registry.

        These are used by ReActEngine for action dispatch. In chat
        mode the actual execution goes through ``action_handler``,
        so the handler bodies are no-ops here.
        """
        actions: list[SkillAction] = []
        try:
            tools = tool_registry.list_tools()
            for tool in tools:
                name = tool.get("name", "")
                if not name:
                    continue
                actions.append(SkillAction(
                    name=name,
                    description=tool.get("description", ""),
                    handler=lambda args, ctx: SkillResult.ok({}),
                    input_schema=tool.get("parameters", {
                        "type": "object",
                        "properties": {},
                    }),
                ))
        except Exception as e:
            logger.warning("Failed to build actions from tool registry: %s", e)
        return actions

    # ─── reason callback ──────────────────────────────────────

    def _make_reason_callback(
        self,
        conversation_messages: list[dict[str, Any]],
        tool_registry: Any,
        ctx: Any,
    ):
        """Build the reason callback.

        Mirrors ``ChatBase.aask_with_tools`` iteration logic:

        1. Build the message list — start with the
           ``conversation_messages`` accumulated so far (includes
           the original messages PLUS any tool/assistant messages
           the action handler appended in previous rounds).
        2. Truncate.
        3. Stream from the LLM via ``_llm_stream_with_retry``
           (preserves first-chunk retry semantics).
        4. Parse text-mode ``[TOOL_CALL]`` blocks (via
           ``TextModeParser``) into native tool_call events.
        5. Collect all tool calls into ``state["pending_tool_calls"]``.
        6. Append the assistant message (with the tool_calls
           field populated) to ``conversation_messages`` so the
           next reason call sees the full assistant turn.
        7. Return ``{action, thought}``.

        Emits ``message_delta`` / ``thinking`` / ``tool_call_start``
        events via the ``emit`` callback so the SSE stream receives
        them in real time.
        """
        chat = self._chat_service

        async def reason(
            state: dict, react_ctx: SkillContext, emit,
        ) -> dict:
            # 1. Use the growing conversation_messages list
            #    (already includes prior tool_calls + tool results).
            #    Insert observation summary as a system message
            #    so the LLM also gets a short recap.
            full_messages = list(conversation_messages)
            obs_summary = state.get("observations_summary", "")
            if obs_summary:
                # Find the last user message and inject the
                # observation summary after it but before any
                # tool messages that follow.
                insertion_idx = len(full_messages)
                for i in range(len(full_messages) - 1, -1, -1):
                    if full_messages[i].get("role") in ("user", "assistant"):
                        insertion_idx = i + 1
                        break
                full_messages.insert(insertion_idx, {
                    "role": "system",
                    "content": obs_summary,
                })

            # 2. Truncate
            try:
                full_messages = chat._truncate_messages(full_messages)
            except Exception:
                pass

            # 3. Get tool schemas
            try:
                tools = chat._get_toolspec(tool_registry)
            except Exception:
                tools = []

            # 4. Stream with retry + text-mode parsing
            parser = TextModeParser()
            accumulated = ""
            thinking = ""
            tool_calls: list[dict] = []

            llm = chat.wiki_service.get_llm()
            try:
                retry_wrapper = chat._llm_stream_with_retry
            except AttributeError:
                retry_wrapper = None

            async def _llm_iter():
                """Iterate over the LLM stream, applying retry if available."""
                if retry_wrapper is not None:
                    async for ev in retry_wrapper(full_messages, tools):
                        yield ev
                elif hasattr(llm, "astream_chat"):
                    async for ev in llm.astream_chat(full_messages, tools=tools):
                        yield ev
                else:
                    reply = llm.chat(full_messages, tools=tools)
                    yield {
                        "type": "done",
                        "content": getattr(reply, "content", "") or "",
                    }

            try:
                final_content: str | None = None
                async for raw_ev in _llm_iter():
                    if raw_ev.get("type") == "done":
                        # Capture done content as fallback for accumulated
                        final_content = raw_ev.get("content", "")
                    async for parsed_ev in parser.feed(raw_ev):
                        kind = parsed_ev.get("type")
                        if kind == "content":
                            chunk = parsed_ev.get("text", "")
                            accumulated += chunk
                            await emit({
                                "type": "message_delta",
                                "content": chunk,
                            })
                        elif kind == "thinking":
                            chunk = parsed_ev.get("text", "")
                            thinking += chunk
                            await emit({
                                "type": "thinking",
                                "content": chunk,
                            })
                        elif kind == "tool_call":
                            # Collect tool call; do NOT emit
                            # tool_call_start here — the action
                            # handler is responsible for emitting it
                            # (mirrors aask_with_tools behavior where
                            # the loop only emits it on action dispatch).
                            tool_name = parsed_ev.get("tool", "")
                            raw_args = parsed_ev.get("args", "{}")
                            if isinstance(raw_args, str):
                                try:
                                    args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    args = {"raw": raw_args}
                            else:
                                args = raw_args or {}
                            tool_calls.append({
                                "name": tool_name, "args": args,
                            })
                # If the LLM produced a done event with content and
                # we never streamed any content, use the done content.
                if final_content and not accumulated:
                    accumulated = final_content
            except Exception as e:
                logger.warning(
                    "LLM stream failed in ReAct reason: %s", e, exc_info=True,
                )
                state["phase"] = "done"
                state["final_answer"] = f"[error] {e}"
                return {"action": "done", "thought": str(e)}

            # 5. Flush any remaining buffered text
            for fev in parser.flush():
                if fev.get("type") == "content":
                    chunk = fev.get("text", "")
                    accumulated += chunk
                    await emit({"type": "message_delta", "content": chunk})

            # 6. Persist accumulated content as the final answer
            state["llm_content"] = accumulated
            state["llm_thinking"] = thinking
            thought = (thinking[:500] if thinking else accumulated[:200])

            if hasattr(ctx, "_thinking"):
                ctx._thinking = thinking

            if tool_calls:
                # Append an assistant message with the tool_calls
                # so the next round's LLM sees this turn.
                conversation_messages.append({
                    "role": "assistant",
                    "content": accumulated,
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(
                                    tc["args"], ensure_ascii=False,
                                ),
                            },
                        }
                        for i, tc in enumerate(tool_calls)
                    ],
                })
                state["pending_tool_calls"] = list(tool_calls)
                return {
                    "action": tool_calls[0]["name"],
                    "thought": thought,
                }

            # No tool calls → final answer
            # Append the final assistant message so the
            # conversation_messages is consistent for any
            # post-loop work.
            if accumulated:
                conversation_messages.append({
                    "role": "assistant",
                    "content": accumulated,
                })
            state["final_answer"] = accumulated
            state["phase"] = "done"
            return {"action": "done", "thought": thought}

        return reason

    # ─── action handler ───────────────────────────────────────

    def _make_action_handler(
        self,
        tool_registry: Any,
        session_id: str,
        ctx: Any,
        conversation_messages: list[dict[str, Any]],
    ):
        """Build the action handler.

        Mirrors ``ChatService._dispatch_tool_call`` for each
        pending tool call:

        - Emits ``tool_call_start``.
        - Updates ``ctx._tool_calls`` / ``_recent_tool_entries`` /
          ``tool_invocations``.
        - Calls ``chat_service._execute_tool`` (DB log + ingest log
          + tool registry execution + confirmation flow).
        - **Appends a ``{role: "tool", name, content}`` message to
          ``conversation_messages``** so the LLM sees the tool
          result on the next round (Phase 6.1 / v0.37 fix:
          the original ReAct bridge was a closure that never
          mutated the message list, so the LLM never saw the
          raw tool result).
        - Emits ``tool_call_end`` / ``tool_call_error`` /
          ``confirmation_required`` as appropriate.
        - Persists to ``MemoryManager.context``.
        - Generates an observation for the next reasoning step.
        - Returns ``SkillResult`` (status=ok with ``confirmation_required``
          flag if needed so the ``on_after_act`` hook can stop the loop).
        """
        chat = self._chat_service

        async def handler(
            action_name: str,
            state: dict,
            react_ctx: SkillContext,
            emit,
        ) -> SkillResult:
            pending = state.get("pending_tool_calls", [])
            if not pending:
                return SkillResult.ok({"_no_tools": True})

            confirmation_required_result: dict | None = None
            results_summary: list[dict[str, Any]] = []

            for idx, call in enumerate(pending):
                tool_name = call["name"]
                args = call.get("args", {}) or {}

                # Skip malformed tool calls with empty names — these
                # are streaming artifacts (incomplete tool_call deltas)
                # and should not be dispatched or appended to the
                # conversation, as they would confuse the LLM on the
                # next round.
                if not tool_name:
                    await emit({
                        "type": "tool_call_error",
                        "tool": "",
                        "error": "Skipped malformed tool call with empty name",
                    })
                    continue

                # Update AgentContext (mirrors _dispatch_tool_call)
                await emit({
                    "type": "tool_call_start",
                    "tool": tool_name,
                    "args": args,
                })
                entry = {"tool": tool_name, "args": args, "status": "pending"}
                if hasattr(ctx, "_tool_calls"):
                    ctx._tool_calls[tool_name] = entry
                if hasattr(ctx, "_recent_tool_entries"):
                    ctx._recent_tool_entries.append(entry)
                if hasattr(ctx, "tool_invocations"):
                    ctx.tool_invocations += 1

                # Execute tool (handles DB log + ingest log)
                try:
                    result = await chat._execute_tool(
                        tool_name, args, tool_registry, session_id, ctx,
                    )
                except Exception as e:
                    result = {"status": "error", "error": str(e)}

                entry["result"] = result
                entry["status"] = "done"
                results_summary.append({
                    "tool": tool_name, "args": args, "result": result,
                })

                # Emit appropriate end event
                if (
                    isinstance(result, dict)
                    and result.get("status") == "error"
                ):
                    await emit({
                        "type": "tool_call_error",
                        "tool": tool_name,
                        "error": str(result.get("error", "")),
                    })
                else:
                    await emit({
                        "type": "tool_call_end",
                        "tool": tool_name,
                        "result": result,
                    })

                # Persist to MemoryManager.context
                try:
                    await chat._persist_tool_result(
                        session_id, tool_name, args, result,
                    )
                except Exception as e:
                    logger.debug("_persist_tool_result failed: %s", e)

                # Generate observation
                result_summary = json.dumps(
                    result.get("result", result)
                    if isinstance(result, dict) else result,
                    ensure_ascii=False, default=str,
                )[:500]
                observation = f"Called {tool_name}: {result_summary}"

                state.setdefault("observations", []).append(observation)
                if hasattr(ctx, "add_observation"):
                    ctx.add_observation(observation)

                # Track in ctx messages (mirrors _dispatch_tool_call)
                if (
                    isinstance(result, dict)
                    and result.get("status") != "confirmation_required"
                ):
                    tool_result_str = json.dumps(
                        result.get("result", result)
                        if isinstance(result, dict) else result
                    )
                    if hasattr(ctx, "add_assistant_message"):
                        ctx.add_assistant_message(
                            f"[TOOL: {tool_name}] Result: {tool_result_str}"
                        )

                # **Phase 6.1 fix**: append the tool result to the
                # growing conversation_messages list so the next
                # reason call sees it as {role: "tool", ...}.
                # Find the last assistant tool_calls message (if any)
                # and append a matching tool message; otherwise
                # just append the tool message (the LLM may then
                # tolerate the absence of an explicit tool_calls
                # pair, but the standard OpenAI spec expects them
                # paired).
                tool_call_id = f"call_{idx}"
                tool_msg = {
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(
                        result, ensure_ascii=False, default=str,
                    ),
                }
                # If the previous message is an assistant with
                # tool_calls, pair this tool message by tool_call_id.
                prev_msgs = [
                    m for m in conversation_messages
                    if m.get("role") == "assistant"
                    and m.get("tool_calls")
                ]
                if prev_msgs:
                    last_assistant = prev_msgs[-1]
                    tool_calls_in_msg = last_assistant.get("tool_calls", [])
                    if idx < len(tool_calls_in_msg):
                        tool_call_id = tool_calls_in_msg[idx].get(
                            "id", tool_call_id,
                        )
                tool_msg["tool_call_id"] = tool_call_id
                conversation_messages.append(tool_msg)

                # Check for confirmation_required
                if (
                    isinstance(result, dict)
                    and result.get("status") == "confirmation_required"
                ):
                    conf_id = result.get("confirmation_id", "")
                    await emit({
                        "type": "confirmation_required",
                        "confirmation_id": conf_id,
                        "tool": tool_name,
                        "args": args,
                        "impact": result.get("impact", {}),
                    })
                    confirmation_required_result = result
                    break

            # Clear pending list (consumed)
            state["pending_tool_calls"] = []

            if confirmation_required_result is not None:
                return SkillResult.ok({
                    "confirmation_required": True,
                    "confirmation_id": confirmation_required_result.get("confirmation_id"),
                    "results": results_summary,
                })

            return SkillResult.ok({"results": results_summary})

        return handler

    # ─── observe callback ─────────────────────────────────────

    def _make_observe_callback(self):
        """Build the observe callback.

        Aggregates observations and produces a summary that the
        next reason step injects into the LLM prompt.
        """
        async def observe(state: dict, ctx: SkillContext) -> dict:
            observations = state.get("observations", [])
            recent = observations[-5:] if observations else []
            summary_lines = ["## Recent tool results"]
            for obs in recent:
                summary_lines.append(f"- {obs}")
            summary = "\n".join(summary_lines) if recent else ""
            return {
                "observations": observations,
                "observations_summary": summary,
            }

        return observe

    # ─── on_after_act hook ────────────────────────────────────

    def _make_after_act_hook(self):
        """Build the on_after_act hook.

        If the action handler returned ``confirmation_required``,
        set ``state["phase"] = "done"`` so the engine exits
        immediately (mirrors ``aask_with_tools`` behavior).
        """
        def after_act(state: dict, action_name: str, result: SkillResult) -> None:
            if (
                result.status == "ok"
                and result.data
                and result.data.get("confirmation_required")
            ):
                state["phase"] = "done"

        return after_act


__all__ = [
    "REACT_SYSTEM_PROMPT",
    "ChatReActState",
    "ChatReActBridge",
]
