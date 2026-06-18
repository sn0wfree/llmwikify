"""Minimal command routing table for slash commands.

Vendored and adapted from nanobot ``command/router.py`` (88 LOC, MIT).
Provides a 3-tier dispatch model:

  1. **priority** — exact-match commands handled before any LLM/agent work
     (e.g. ``/stop``).
  2. **exact** — exact-match commands (e.g. ``/help``).
  3. **prefix** — longest-prefix-first match (e.g. ``/model gpt-4o``).

Adaptation from the upstream source:
  - ``CommandContext.msg: InboundMessage`` → ``CommandContext.text: str``
    (llmwikify doesn't have a separate ``InboundMessage``; the raw user
    text is the dispatch input).
  - ``CommandContext.session: Session`` → ``session_id: str`` + ``db`` +
    ``ctx`` + ``abort_event`` (the existing llmwikify session primitives
    that a handler might need).
  - ``Handler`` returns ``AsyncIterator[dict] | dict | None`` instead of
    ``OutboundMessage``: handlers either yield SSE events one at a time,
    return a single event dict, or return ``None`` to fall through.
  - ``loop: Any = None`` dropped (no AgentLoop in llmwikify; the
    orchestrator owns the dispatch surface).

The router is **framework-agnostic** — no I/O, no logging, no LLM
calls. The orchestrator layer wires it up to specific handlers (see
``apps/chat/agent/orchestrator.py:_dispatch_command``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

Handler = Any  # Callable[[CommandContext], AsyncIterator[dict] | dict | None]


@dataclass
class CommandContext:
    """Everything a command handler needs to produce a response.

    Mirrors nanobot's shape: ``raw`` + ``args`` are pre-parsed (cmd
    name stripped before prefix-tier dispatch), the rest are
    dependency-injection handles.
    """

    text: str  # original user input
    session_id: str | None = None
    wiki_id: str | None = None
    db: Any = None
    ctx: Any = None  # AgentContext (in-memory state)
    abort_event: Any = None
    key: str = ""  # routing key (e.g. "api:user-42")
    raw: str = ""  # lowercased command name (for exact/priority match)
    args: str = ""  # everything after the prefix (for prefix handlers)


class CommandRouter:
    """Pure dict-based command dispatch.

    Three tiers checked in order:
      1. *priority* — exact-match commands handled before the dispatch
         lock (e.g. ``/stop``, ``/restart``).
      2. *exact* — exact-match commands handled inside the dispatch lock.
      3. *prefix* — longest-prefix-first match (e.g. ``/model gpt-4o``).
    """

    def __init__(self) -> None:
        self._priority: dict[str, Handler] = {}
        self._exact: dict[str, Handler] = {}
        self._prefix: list[tuple[str, Handler]] = []

    def priority(self, cmd: str, handler: Handler) -> None:
        """Register a priority-tier command (matched before any other work)."""
        self._priority[cmd.lower()] = handler

    def exact(self, cmd: str, handler: Handler) -> None:
        """Register an exact-match command."""
        self._exact[cmd.lower()] = handler

    def prefix(self, pfx: str, handler: Handler) -> None:
        """Register a prefix-match command (longest prefix wins)."""
        self._prefix.append((pfx.lower(), handler))
        self._prefix.sort(key=lambda p: len(p[0]), reverse=True)

    def is_priority(self, text: str) -> bool:
        """True if ``text`` is a registered priority-tier command."""
        return text.strip().lower() in self._priority

    def is_command(self, text: str) -> bool:
        """True if ``text`` matches any tier (priority / exact / prefix)."""
        return self.is_priority(text) or self._is_dispatchable(text)

    def _is_dispatchable(self, text: str) -> bool:
        """Check whether ``text`` matches any non-priority command tier.

        Does NOT check priority tier. If this returns True,
        ``dispatch()`` is guaranteed to match a handler.
        """
        cmd = text.strip().lower()
        if cmd in self._exact:
            return True
        for pfx, _ in self._prefix:
            if cmd.startswith(pfx):
                return True
        return False

    async def dispatch_priority(self, ctx: CommandContext) -> list[dict]:
        """Dispatch a priority command. Called before the dispatch lock."""
        handler = self._priority.get(ctx.raw.lower())
        if handler:
            return await _call_handler(handler, ctx)
        return []

    async def dispatch(self, ctx: CommandContext) -> list[dict]:
        """Try exact, then prefix handlers. Returns ``[]`` if unhandled."""
        cmd = ctx.raw.lower()

        if handler := self._exact.get(cmd):
            return await _call_handler(handler, ctx)

        for pfx, handler in self._prefix:
            if cmd.startswith(pfx):
                # Use ctx.text (original-case) for args so user-supplied
                # content retains its case. Falls back to ctx.raw if
                # the orchestrator forgot to set text.
                source = ctx.text if ctx.text else ctx.raw
                ctx.args = source[len(pfx):]
                return await _call_handler(handler, ctx)

        return []


async def _call_handler(handler: Handler, ctx: CommandContext) -> list[dict]:
    """Invoke a handler, normalising its return shape to a list of events.

    Handlers may return:
      - ``None`` → no events (fall through).
      - ``dict`` → single SSE event.
      - ``Awaitable[dict|list|None]`` → awaited; if it's a coroutine
        returning ``dict``/``list``/``None``, treated as above.
      - ``AsyncIterator[dict]`` → stream of SSE events.
      - ``list[dict]`` → multiple SSE events.

    All shapes are normalised to ``list[dict]`` for the caller to
    ``yield from`` or inspect uniformly.
    """
    import asyncio
    import inspect

    result = handler(ctx)
    # Handler returned a coroutine (async def handler(...)) — await it.
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return result
    if hasattr(result, "__aiter__"):
        events: list[dict] = []
        async for ev in result:
            events.append(ev)
        return events
    return [result]


__all__ = [
    "CommandContext",
    "CommandRouter",
    "Handler",
]
