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
