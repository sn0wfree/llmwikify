"""ChatBase — generic chat framework with v0.32 skill integration.

A thin abstraction that sits on top of an LLM client and
exposes a chat-style interface. Phase 10 wires ChatBase to
the v0.32 Skill framework (Phase 1) so the LLM can see and
call the 23 base actions + research_skill (Phase 5/6) via
OpenAI-compatible tool calling.

What it provides
----------------

- **Session management** — ``ChatSession`` collects user/
  assistant messages and tool calls.
- **Streaming** — ``.stream()`` yields chunks as they
  arrive (delegates to the underlying LLM client).
- **Tool registration** — manual ``register_tool(name, fn)``
  OR auto-bulk ``register_skills(registry)`` that pulls all
  registered Skills from a ``SkillRegistry``.
- **Provider abstraction** — the LLM client is supplied at
  construction time (``base.llm_client``), so ChatBase
  doesn't need to know about the L1 ``foundation.llm`` or
  the L3 ``apps.chat.providers.registry`` directly.
- **Tool-call loop** — ``ask_with_tools()`` runs the
  OpenAI-style loop: send tools to LLM, parse tool_calls
  in the response, invoke them via ``SkillRuntime``, feed
  results back, loop until the LLM returns a final answer.
- **Schema generation** — ``tools_schema()`` converts the
  registry's ``SkillManifest`` list into the OpenAI
  function-calling JSON schema format.

What it does NOT do
-------------------

- It does **not** re-implement the research loop. That
  lives in ``apps/chat/skills/research_skill.py``
  (which is a Skill callable via the registry).
- It does **not** hold any UI state. The CLI/WebUI layer
  (L4) wraps ChatBase to render messages and tool calls.

Why a class
-----------

The design doc §3.5 specified ``ChatBase`` as ~150 LOC.
The core abstraction is: ``ChatBase.ask(prompt)`` returns
an ``AsyncIterator[str]`` of the assistant's reply.
``ask_with_tools()`` extends this to the tool-call era.
The class makes it trivial for tests to swap in a fake LLM
client.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.skills.base import (
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    default_registry,
)
from llmwikify.apps.chat.skills.runtime import SkillRuntime

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """A single message in a chat session.

    Mirrors the OpenAI chat-completion message shape so
    the underlying LLM client can consume it without
    reformatting. ``tool_calls`` follows the OpenAI
    function-calling schema: a list of dicts each with
    ``{"id", "type": "function", "function": {"name", "arguments"}}``.
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChatSession:
    """A growing list of chat messages with a system prompt."""

    system_prompt: str = ""
    messages: list[ChatMessage] = field(default_factory=list)

    def add(self, role: str, content: str, **kwargs: Any) -> ChatMessage:
        """Append a message and return it."""
        msg = ChatMessage(role=role, content=content, **kwargs)
        self.messages.append(msg)
        return msg


# Default upper bound on the tool-call loop (matches
# OpenAI's recommended max_iterations behavior).
DEFAULT_MAX_TOOL_ITERATIONS = 8


class ChatBase:
    """Generic chat framework with v0.32 skill integration.

    Args:
        llm_client: anything with a ``.chat(messages, **kwargs)``
            method. In production, this is
            ``llmwikify.foundation.llm.streamable.StreamableLLMClient``;
            in tests, it can be a stub.
        system_prompt: default system prompt prepended to
            every session.
        skill_registry: optional ``SkillRegistry`` to use for
            tool calling. If None, uses ``default_registry()``.
        skill_runtime: optional ``SkillRuntime`` to use for
            invoking tools. If None, a new one is created
            with the same registry.
    """

    def __init__(
        self,
        llm_client: Any,
        system_prompt: str = "",
        skill_registry: SkillRegistry | None = None,
        skill_runtime: SkillRuntime | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._default_system_prompt = system_prompt
        # Phase 10: skill integration
        self.skill_registry = (
            skill_registry if skill_registry is not None
            else default_registry()
        )
        self.skill_runtime = (
            skill_runtime if skill_runtime is not None
            else SkillRuntime(self.skill_registry)
        )

    # ── session helpers ─────────────────────────────────────

    def new_session(self, system_prompt: str | None = None) -> ChatSession:
        """Create a fresh session, optionally with a custom system prompt."""
        return ChatSession(system_prompt=system_prompt or self._default_system_prompt)

    # ── skill integration (Phase 10) ────────────────────────

    def register_skills(self, registry: SkillRegistry | None = None) -> int:
        """Bulk-register all skills from a registry.

        Returns the number of skills registered.

        Args:
            registry: a ``SkillRegistry`` to read from. If
                None, uses ``self.skill_registry``.
        """
        reg = registry if registry is not None else self.skill_registry
        count = 0
        for skill in reg:
            count += len(skill.actions)
        return count

    def tools_schema(self, *, registry: SkillRegistry | None = None) -> list[dict[str, Any]]:
        """Generate the OpenAI function-calling schema for all skills.

        Returns a list of tool descriptors in the OpenAI
        ``tools`` format (``[{"type": "function", "function": {...}}]``).
        The LLM client consumes this list to advertise the
        available tools to the model.
        """
        reg = registry if registry is not None else self.skill_registry
        out: list[dict[str, Any]] = []
        for skill in reg:
            for action in skill.actions.values():
                out.append({
                    "type": "function",
                    "function": {
                        "name": f"{skill.name}.{action.name}",
                        "description": action.description,
                        "parameters": action.input_schema,
                    },
                })
        return out

    async def ainvoke_tool(
        self, tool_name: str, args: dict[str, Any], ctx: SkillContext | None = None,
    ) -> SkillResult:
        """Async variant of ``invoke_tool``. Use this from within
        an async context (e.g. ``astream``)."""
        if "." not in tool_name:
            return SkillResult.fail(
                f"Tool name must be qualified 'skill.action', got {tool_name!r}"
            )
        skill_name, action_name = tool_name.split(".", 1)
        skill = self.skill_registry.get(skill_name)
        if skill is None:
            return SkillResult.fail(f"Skill not found: {skill_name!r}")
        action = skill.get_action(action_name)
        if action is None:
            return SkillResult.fail(
                f"Action {action_name!r} not found on skill {skill_name!r}"
            )
        return await self.skill_runtime.execute(
            skill_name, action_name, args, ctx,
        )

    async def astream(
        self,
        prompt: str,
        session: ChatSession | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Async-iterate over streaming reply chunks.

        Falls back to yielding the full reply in one chunk if
        the LLM client doesn't expose an async streaming
        method.
        """
        sess = session or self.new_session()
        if not sess.messages and sess.system_prompt:
            sess.add("system", sess.system_prompt)
        sess.add("user", prompt)
        if hasattr(self.llm_client, "astream_chat"):
            chunks: list[str] = []
            async for chunk in self.llm_client.astream_chat(sess.messages, **kwargs):
                chunks.append(chunk)
                yield chunk
            sess.add("assistant", "".join(chunks))
        else:
            reply = self.llm_client.chat(sess.messages, **kwargs)
            sess.add("assistant", reply)
            yield reply

    # ── async tool-call loop (Phase 2 / v0.36) ─────────────────
    #
    # The synchronous ``ask_with_tools`` above calls the LLM
    # once and waits for the full reply. The async streaming
    # variant below iterates ``astream_chat`` (the OpenAI-style
    # streaming tool-call format) so the LLM can be re-called
    # with tool results on subsequent turns. This is the async
    # version of the tool-call loop used by the agent chat SSE
    # stream (ChatService).
    #
    # Yields ``dict`` events with a ``type`` field compatible
    # with ChatService's SSE event shape so the two layers
    # share the same event vocabulary. Event types:
    #   - ``message_delta`` — incremental content chunk
    #   - ``thinking``       — incremental reasoning chunk
    #   - ``tool_call_start``/``tool_call_end`` — tool lifecycle
    #   - ``done``           — final answer (only once per call)
    #   - ``error``          — failure
    #
    # Args:
    #   messages: the message list to send (incl. system +
    #     history). Will be MUTATED in place — tool messages
    #     are appended in-place so the caller can re-send the
    #     same list on a follow-up iteration.
    #   tools: OpenAI-style tool schema list. ``None`` means
    #     no tools (plain chat).
    #   max_iterations: cap on LLM re-calls. Default 4.
    #   invoke_tool: optional async callable that takes
    #     ``(tool_name, args)`` and returns a JSON-serializable
    #     result. If None, uses ``ainvoke_tool`` (the default
    #     Skill-based tool caller).
    #
    # Returns nothing — the answer is yielded as a ``done`` event.

    async def aask_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
        invoke_tool: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async streaming tool-call loop (Phase 2 / v0.36).

        Iterates ``astream_chat`` with tool feedback until the
        LLM produces a final answer (no tool calls in the
        iteration) or ``max_iterations`` is hit.

        Mutates ``messages`` in place by appending tool
        results so the LLM sees them on the next iteration.
        """
        # Tool invocations this call. Used to detect "did this
        # iteration dispatch new tools?".
        invocations: list[dict[str, Any]] = []

        async def default_invoke(name: str, args: dict) -> Any:
            skill_ctx = SkillContext()
            res = await self.ainvoke_tool(name, args, skill_ctx)
            if hasattr(res, "to_dict"):
                return res.to_dict()
            return res

        tool_caller = invoke_tool or default_invoke

        async def emit(ev: dict[str, Any]) -> None:
            pass

        for iteration in range(max_iterations):
            pre_count = len(invocations)
            accumulated = ""
            emitted_text = ""
            emitted_thinking = ""
            iter_tool_calls: list[dict[str, Any]] = []

            # Stream from the LLM
            async for ev in self._astream_with_tools(messages, tools):
                kind = ev.get("type")
                if kind == "content":
                    chunk = ev.get("text", "")
                    accumulated += chunk
                    emitted_text += chunk
                    yield {
                        "type": "message_delta",
                        "content": chunk,
                    }
                elif kind == "thinking":
                    chunk = ev.get("text", "")
                    emitted_thinking += chunk
                    yield {"type": "thinking", "content": chunk}
                elif kind == "tool_call":
                    tool_name = ev.get("tool", "")
                    raw_args = ev.get("args", "{}")
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {"raw": raw_args}
                    else:
                        args = raw_args
                    iter_tool_calls.append({
                        "name": tool_name, "args": args,
                    })
                    # If a custom invoke_tool callback was
                    # provided, it's expected to emit
                    # ``tool_call_start`` itself. Only emit from
                    # the loop when using the default callback
                    # (Skill-based, no extra events).
                    if invoke_tool is None:
                        yield {
                            "type": "tool_call_start",
                            "tool": tool_name,
                            "args": args,
                        }
                    await emit({
                        "type": "tool_call_start",
                        "tool": tool_name,
                        "args": args,
                    })
                elif kind == "done":
                    final = ev.get("content", accumulated)
                    break
            else:
                # Stream ended without explicit done; treat
                # accumulated text as the final answer.
                final = accumulated

            # If this iteration dispatched tools, execute them
            # and feed results back into ``messages`` for the
            # next iteration.
            if iter_tool_calls:
                for call in iter_tool_calls:
                    name = call["name"]
                    args = call["args"]
                    invocations.append({
                        "tool": name, "args": args,
                    })
                    try:
                        result = await tool_caller(name, args)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Tool %s failed", name, exc_info=True)
                        result = {"status": "error", "error": str(exc)}
                    invocations[-1]["result"] = result
                    invocations[-1]["status"] = "done"
                    # Append a tool result message so the LLM
                    # sees it on the next iteration.
                    messages.append({
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(
                            result, ensure_ascii=False, default=str,
                        ),
                    })
                    # If a custom invoke_tool was provided, it's
                    # expected to emit ``tool_call_end`` itself.
                    if invoke_tool is None:
                        yield {
                            "type": "tool_call_end",
                            "tool": name,
                            "result": result,
                        }
                    await emit({
                        "type": "tool_call_end",
                        "tool": name,
                        "result": result,
                    })

                # If a tool returned confirmation_required, stop
                # the loop — the caller will resume via
                # approve_confirmation_continue.
                last = invocations[-1]
                if (
                    isinstance(last.get("result"), dict)
                    and last["result"].get("status")
                    == "confirmation_required"
                ):
                    return

                # No confirmation — re-call the LLM with the
                # tool results in context. Continue to the next
                # iteration of the outer for-loop.
                continue

            # No tool calls in this iteration. The LLM's done
            # is the FINAL answer. Yield done and return.
            yield {
                "type": "done",
                "final_response": final,
                "thinking": emitted_thinking,
            }
            return

        # Iteration cap — emit a fallback done.
        logger.warning(
            "aask_with_tools hit max_iterations=%d, emitting fallback",
            max_iterations,
        )
        yield {
            "type": "done",
            "final_response": accumulated,
            "thinking": emitted_thinking,
        }

    async def _astream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream from the LLM with tool support (Phase 2 / v0.36).

        Wraps ``llm_client.astream_chat`` so the same event
        vocabulary is exposed regardless of LLM client. The
        expected event shape is::

            {"type": "content", "text": "..."}
            {"type": "thinking", "text": "..."}
            {"type": "tool_call", "tool": "...", "args": "..."}
            {"type": "done", "content": "..."}

        This matches the existing ``StreamableLLMClient.astream_chat``
        output, so no translation is needed.

        Subclasses can override ``_stream_preprocess`` to
        transform the event stream (e.g. text-mode tool-call
        conversion in ChatService).
        """
        if hasattr(self.llm_client, "astream_chat"):
            async for ev in self.llm_client.astream_chat(
                messages, tools=tools,
            ):
                async for transformed in self._stream_preprocess(ev):
                    yield transformed
            return
        # Fallback: synchronous chat (no streaming). Wrap into
        # the same event shape.
        try:
            reply = self.llm_client.chat(messages, tools=tools)
        except TypeError:
            reply = self.llm_client.chat(messages)
        content, tool_calls = self._extract_content_and_tool_calls(reply)
        if content:
            async for transformed in self._stream_preprocess(
                {"type": "content", "text": content}
            ):
                yield transformed
        for call in tool_calls:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            async for transformed in self._stream_preprocess({
                "type": "tool_call",
                "tool": fn.get("name", ""),
                "args": fn.get("arguments", "{}"),
            }):
                yield transformed
        async for transformed in self._stream_preprocess(
            {"type": "done", "content": content}
        ):
            yield transformed

    async def _stream_preprocess(
        self, event: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Hook for subclasses to transform LLM stream events
        (Phase 2.3 / v0.36). Default: pass-through.

        Used by ChatService to convert text-mode
        ``[TOOL_CALL]...[/TOOL_CALL]`` blocks in ``content``
        events into native ``tool_call`` events.
        """
        yield event

    # ── internals ────────────────────────────────────────────

    @staticmethod
    def _extract_content_and_tool_calls(reply: Any) -> tuple[str, list[dict[str, Any]]]:
        """Normalize the LLM's reply into ``(content, tool_calls)``.

        Handles:
        - ``str`` (plain text)
        - dict with ``content`` and ``tool_calls`` keys
        - object with ``.content`` and ``.tool_calls`` attrs
        - ``None`` (treat as empty content)

        Each ``tool_call`` is normalized to a dict shape
        ``{"id", "type": "function", "function": {"name", "arguments"}}``
        regardless of whether the source was a dict or an
        OpenAI-style object.
        """
        if reply is None:
            return "", []
        if isinstance(reply, str):
            return reply, []
        if isinstance(reply, dict):
            content = str(reply.get("content", "") or "")
            raw_calls = list(reply.get("tool_calls", []) or [])
        else:
            # object with attrs (e.g. OpenAI ChatCompletionMessage)
            content = getattr(reply, "content", "") or ""
            raw_calls = getattr(reply, "tool_calls", []) or []
        # Normalize every tool_call to a dict
        out_calls: list[dict[str, Any]] = []
        for tc in raw_calls:
            if isinstance(tc, dict):
                # Already a dict; ensure it has the canonical shape
                out_calls.append(_normalize_tool_call_dict(tc))
            else:
                fn = getattr(tc, "function", None)
                if fn is not None:
                    out_calls.append({
                        "id": getattr(tc, "id", ""),
                        "type": "function",
                        "function": {
                            "name": getattr(fn, "name", ""),
                            "arguments": getattr(fn, "arguments", "{}"),
                        },
                    })
        return str(content), out_calls


__all__ = [
    "ChatBase",
    "ChatMessage",
    "ChatSession",
    "DEFAULT_MAX_TOOL_ITERATIONS",
]


def _normalize_tool_call_dict(tc: dict[str, Any]) -> dict[str, Any]:
    """Ensure a tool_call dict has the canonical OpenAI shape.

    Some LLM clients return tool_calls with ``arguments`` as
    a raw string (JSON-encoded) and ``id`` at the top level;
    others nest them differently. This helper produces the
    canonical ``{"id", "type": "function", "function": {"name",
    "arguments"}}`` shape that the rest of the framework
    (and the OpenAI tool-call spec) expects.
    """
    out: dict[str, Any] = {
        "id": tc.get("id", ""),
        "type": "function",
        "function": {
            "name": "",
            "arguments": "{}",
        },
    }
    fn = tc.get("function")
    if isinstance(fn, dict):
        out["function"]["name"] = fn.get("name", "")
        out["function"]["arguments"] = fn.get("arguments", "{}")
    else:
        # Top-level fallbacks (non-standard but seen in the wild)
        out["function"]["name"] = tc.get("name", "")
        out["function"]["arguments"] = tc.get("arguments", "{}")
    return out
