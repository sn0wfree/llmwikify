"""ChatBase — generic chat framework (Sprint C, new in C1).

A thin abstraction that sits on top of an LLM client and
exposes a chat-style interface. Designed to be reused by
``ResearchAgent`` (the existing 6-step research engine,
re-exported from ``engine.py``) and any future chat-driven
app.

What it provides
----------------

- **Session management** — ``ChatSession`` collects user/
  assistant messages and tool calls.
- **Streaming** — ``.stream()`` yields chunks as they
  arrive (delegates to the underlying LLM client).
- **Tool registration** — register callables that the LLM
  can invoke; returned tool results are folded back into
  the conversation.
- **Provider abstraction** — the LLM client is supplied at
  construction time (``base.llm_client``), so ChatBase
  doesn't need to know about the L1 ``foundation.llm`` or
  the L3 ``apps.agent.providers.registry`` directly.

What it does NOT do
-------------------

- It does **not** re-implement the research loop. That
  lives in ``engine.py`` (the 6-step research engine). To
  run a research session, use ``ResearchAgent`` which
  composes ChatBase with the engine.
- It does **not** hold any UI state. The CLI/WebUI layer
  (L4) wraps ChatBase to render messages and tool calls.

Why a class
-----------

The design doc §3.5 specified ``ChatBase`` as ~150 LOC.
The core abstraction is: ``ChatBase.ask(prompt)`` returns
an ``AsyncIterator[str]`` of the assistant's reply. The
class makes it trivial for tests to swap in a fake LLM
client.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """A single message in a chat session.

    Mirrors the OpenAI chat-completion message shape so
    the underlying LLM client can consume it without
    reformatting.
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


class ChatBase:
    """Generic chat framework. Subclassed by ResearchAgent.

    Args:
        llm_client: anything with a ``.chat(messages, **kwargs)``
            method. In production, this is
            ``llmwikify.foundation.llm.streamable.StreamableLLMClient``;
            in tests, it can be a stub.
        system_prompt: default system prompt prepended to
            every session.
    """

    def __init__(self, llm_client: Any, system_prompt: str = "") -> None:
        self.llm_client = llm_client
        self._default_system_prompt = system_prompt
        self._tools: dict[str, Any] = {}

    # ── session helpers ─────────────────────────────────────

    def new_session(self, system_prompt: str | None = None) -> ChatSession:
        """Create a fresh session, optionally with a custom system prompt."""
        return ChatSession(system_prompt=system_prompt or self._default_system_prompt)

    # ── tool registration ────────────────────────────────────

    def register_tool(self, name: str, fn: Any) -> None:
        """Register a callable as a tool the LLM can invoke.

        The function should accept ``**kwargs`` and return a
        JSON-serializable value. Tool calling is delegated to
        the underlying LLM client if it supports it; otherwise
        registered tools are available for direct invocation
        by higher-level code (e.g. ``ResearchAgent``).
        """
        self._tools[name] = fn

    @property
    def tools(self) -> dict[str, Any]:
        """The currently registered tools (read-only view)."""
        return dict(self._tools)

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
