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
        self._tools: dict[str, Any] = {}
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

    # ── tool registration (manual) ──────────────────────────

    def register_tool(self, name: str, fn: Any) -> None:
        """Register a callable as a tool the LLM can invoke.

        The function should accept ``**kwargs`` and return a
        JSON-serializable value. For the recommended bulk
        registration path, use ``register_skills(registry)``
        instead.
        """
        self._tools[name] = fn

    @property
    def tools(self) -> dict[str, Any]:
        """The currently-registered MANUAL tools (read-only view)."""
        return dict(self._tools)

    # ── skill integration (Phase 10) ────────────────────────

    def register_skills(self, registry: SkillRegistry | None = None) -> int:
        """Bulk-register all skills from a registry as callable tools.

        Each skill's actions become individually callable
        via ``skill.action_name`` notation. The LLM-facing
        tool name is the qualified name
        ``<skill_name>.<action_name>``.

        Returns the number of skills registered.

        Args:
            registry: a ``SkillRegistry`` to read from. If
                None, uses ``self.skill_registry``.
        """
        reg = registry if registry is not None else self.skill_registry
        count = 0
        for skill in reg:
            for action in skill.actions.values():
                tool_name = f"{skill.name}.{action.name}"
                # Wrap so the LLM can call it via qualified name
                # and we route back to the registry on invoke.
                self._tools[tool_name] = _SkillToolProxy(
                    registry=reg, skill_name=skill.name, action_name=action.name,
                )
                count += 1
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

    def invoke_tool(
        self, tool_name: str, args: dict[str, Any], ctx: SkillContext | None = None,
    ) -> SkillResult:
        """Invoke a tool by qualified name (e.g. ``research.run_research``).

        Synchronous wrapper around the async ``SkillRuntime.execute``.
        Returns a ``SkillResult``. The LLM-facing representation
        is the dict form (``result.to_dict()``).
        """
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
        # ``SkillRuntime.execute`` is async; ChatBase.invoke_tool
        # is sync (called from the LLM tool-call loop, which is
        # sync). Bridge via asyncio.run if there's no running loop.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(
                self.skill_runtime.execute(skill_name, action_name, args, ctx)
            )
        # Running loop present (e.g. in an async context). The
        # caller is expected to use ``ainvoke_tool`` instead.
        raise RuntimeError(
            "invoke_tool() cannot be called from a running event loop. "
            "Use ainvoke_tool() in async code."
        )

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

    # ── main entry points ────────────────────────────────────

    def ask(
        self,
        prompt: str,
        session: ChatSession | None = None,
        **kwargs: Any,
    ) -> str:
        """Send ``prompt`` and return the assistant's reply as a string.

        Args:
            prompt: the user message.
            session: optional existing session to append to.
                If None, a new session is created.
            **kwargs: forwarded to the LLM client (``temperature``,
                ``max_tokens``, etc.).
        """
        sess = session or self.new_session()
        if not sess.messages and sess.system_prompt:
            sess.add("system", sess.system_prompt)
        sess.add("user", prompt)
        reply = self.llm_client.chat(sess.messages, **kwargs)
        sess.add("assistant", reply)
        return reply

    def ask_with_tools(
        self,
        prompt: str,
        session: ChatSession | None = None,
        *,
        ctx: SkillContext | None = None,
        max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
        **kwargs: Any,
    ) -> str:
        """OpenAI-style tool-call loop.

        Flow per iteration:
          1. Send the session + tools_schema() to the LLM.
          2. If the LLM response includes ``tool_calls``,
             invoke each via ``invoke_tool()``, append the
             results as 'tool' messages, and continue.
          3. If the LLM response has no tool calls (just
             content), return the content as the final answer.
          4. Cap the loop at ``max_iterations`` to prevent
             runaway recursion.

        The LLM client is expected to either:
          - Accept a ``tools=`` kwarg in ``.chat(messages, ...)``
          - OR be a real OpenAI client (we use the kwarg)
        For unsupported LLMs, the call still works as long as
        the LLM returns a structured response with
        ``tool_calls`` populated.
        """
        sess = session or self.new_session()
        if not sess.messages and sess.system_prompt:
            sess.add("system", sess.system_prompt)
        sess.add("user", prompt)

        tools = self.tools_schema()
        exec_ctx = ctx or SkillContext()

        for iteration in range(max_iterations):
            # Call LLM with tools. Supports two calling conventions:
            # 1) OpenAI-style: llm.chat(messages, tools=tools, **kwargs)
            # 2) Plain: llm.chat(messages, **kwargs) returning a
            #    message that may have .tool_calls attribute
            reply_msg = self._call_llm_with_tools(sess.messages, tools, kwargs)

            # Normalize reply: either a string or a ChatMessage-shaped object
            content, tool_calls = self._extract_content_and_tool_calls(reply_msg)
            assistant_msg = sess.add(
                "assistant",
                content,
                tool_calls=tool_calls,
            )

            # No tool calls → final answer
            if not tool_calls:
                return content

            # Invoke each tool call and append 'tool' messages
            for call in tool_calls:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                tool_name = fn.get("name", "") if isinstance(fn, dict) else ""
                # Parse arguments (may be JSON string or already-dict)
                raw_args = fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args) if raw_args.strip() else {}
                    except json.JSONDecodeError as e:
                        args = {}
                        logger.warning("Bad tool args for %s: %s", tool_name, e)
                else:
                    args = raw_args or {}

                result = self.invoke_tool(tool_name, args, exec_ctx)
                sess.add(
                    "tool",
                    json.dumps(result.to_dict(), ensure_ascii=False),
                    tool_call_id=call.get("id", "") if isinstance(call, dict) else None,
                    name=tool_name,
                )

        # Iteration cap: return the last assistant content
        logger.warning(
            "ask_with_tools hit max_iterations=%d, returning last content",
            max_iterations,
        )
        return sess.messages[-1].content if sess.messages else ""

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
    #   on_tool_event: optional async callback for tool
    #     lifecycle events. Receives the same dicts that
    #     ``tool_call_start``/``tool_call_end`` would yield.
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
        on_tool_event: Any = None,
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
            if on_tool_event is not None:
                cb = on_tool_event(ev)
                if hasattr(cb, "__await__"):
                    await cb

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

    def _call_llm_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], kwargs: dict[str, Any],
    ) -> Any:
        """Call the LLM with tools. Supports two conventions:
        - OpenAI-style: ``llm.chat(messages, tools=tools, **kwargs)``
        - Plain: ``llm.chat(messages, **kwargs)`` returning a
          string (no tool support) or an object with
          ``.content`` / ``.tool_calls`` attributes.

        Returns the raw LLM response. Normalization is done
        in ``_extract_content_and_tool_calls``.
        """
        # OpenAI-style first
        try:
            return self.llm_client.chat(messages, tools=tools, **kwargs)
        except TypeError:
            # LLM client doesn't accept ``tools=`` kwarg
            return self.llm_client.chat(messages, **kwargs)

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


# ─── Skill tool proxy ────────────────────────────────────────────


class _SkillToolProxy:
    """Internal proxy for invoking a Skill action by qualified name.

    The LLM-facing tool name is ``<skill>.<action>``. This
    proxy resolves the name back to the registered action
    via the ``SkillRuntime``. Held in ``ChatBase._tools``
    after ``register_skills()`` is called.

    Not intended to be invoked directly by user code —
    the path goes through ``ChatBase.invoke_tool()``.
    """

    def __init__(self, registry: SkillRegistry, skill_name: str, action_name: str) -> None:
        self._registry = registry
        self._skill_name = skill_name
        self._action_name = action_name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Direct call (rare): pass through the runtime
        runtime = SkillRuntime(self._registry)
        return runtime.execute(
            self._skill_name, self._action_name, kwargs or {},
        )

    def __repr__(self) -> str:
        return (
            f"<SkillToolProxy skill={self._skill_name!r} "
            f"action={self._action_name!r}>"
        )


__all__ = [
    "ChatBase",
    "ChatMessage",
    "ChatSession",
    "SkillToolProxy",  # for testing only
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
