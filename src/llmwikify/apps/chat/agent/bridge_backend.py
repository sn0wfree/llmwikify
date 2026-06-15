"""ChatBridgeBackend — adapter from new components to ChatReActBridge's expected interface.

The bridge (``agent/chat_react.py``) was originally written against the
old monolithic ``ChatService`` (which had 5 underscore-prefixed methods:
``_truncate_messages``, ``_get_toolspec``, ``_llm_stream_with_retry``,
``_execute_tool``, ``_persist_tool_result``).

After the Phase 2 v0.41 refactor, those responsibilities were extracted
to standalone components:

  - ``ToolExecutor``        — tool execution + DB persistence
  - ``ContextManager``      — message truncation
  - ``wiki_service.get_llm()`` — the LLM client (needed for streaming)

This class is the single point of composition: it implements the 5-method
interface that ``ChatReActBridge`` expects, by delegating to the
appropriate new component.  This keeps the bridge itself free of any
knowledge of the new architecture.

Production wiring in ``ChatOrchestrator._chat_via_react``::

    backend = ChatBridgeBackend(
        tool_executor=self.tool_executor,
        context_manager=self.context_manager,
        llm_client=self.wiki_service.get_llm(),
        config=self.config,
    )
    bridge = ChatReActBridge(chat_service=backend, config=self.config)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class ChatBridgeBackend:
    """Adapter exposing the 5-method interface ChatReActBridge expects.

    Methods
    -------
    _truncate_messages(messages)
        Delegate to ``ContextManager.truncate``.

    _get_toolspec(tool_registry)
        Delegate to ``ToolExecutor.get_toolspec``.

    _llm_stream_with_retry(messages, tools)
        Delegate to ``ToolExecutor.llm_stream_with_retry``.

    _execute_tool(tool_name, args, tool_registry, session_id, ctx)
        Delegate to ``ToolExecutor.execute``.

    _persist_tool_result(session_id, tool_name, args, result)
        Delegate to ``ToolExecutor.persist_tool_result``.

    The methods are kept underscore-prefixed to mirror the old
    ``ChatService`` interface and avoid test rewrites — tests already
    pass mock objects with these names.
    """

    def __init__(
        self,
        tool_executor: Any,
        context_manager: Any,
        wiki_service: Any,
        config: dict | None = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._context_manager = context_manager
        self._wiki_service = wiki_service
        self._llm_client: Any = None  # lazily fetched
        self._config = config or {}

    @property
    def config(self) -> dict:
        """Expose config dict (some callers use ``chat.config``)."""
        return self._config

    @property
    def wiki_service(self) -> Any:
        """Expose the wiki_service for callers that need it
        (e.g. ``chat.wiki_service.get_llm()``).
        """
        return self._wiki_service

    def _get_llm_client(self) -> Any:
        """Return the LLM client, fetching from wiki_service on first use."""
        if self._llm_client is None and self._wiki_service is not None:
            self._llm_client = self._wiki_service.get_llm()
        return self._llm_client

    def _truncate_messages(
        self, messages: list[dict[str, Any]], max_messages: int | None = None
    ) -> list[dict[str, Any]]:
        """Truncate messages to fit the model's context window."""
        return self._context_manager.truncate(messages, max_messages=max_messages)

    def _get_toolspec(self, tool_registry: Any) -> list[dict[str, Any]]:
        """Build OpenAI-format tool spec from registry."""
        return self._tool_executor.get_toolspec(tool_registry)

    async def _llm_stream_with_retry(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """Stream from LLM with first-chunk retry.

        The bridge's reason callback iterates this directly; we delegate
        to ``ToolExecutor.llm_stream_with_retry`` (which already
        implements the retry policy).
        """
        llm = self._get_llm_client()
        async for ev in self._tool_executor.llm_stream_with_retry(
            messages, tools, llm,
        ):
            yield ev

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        tool_registry: Any,
        session_id: str,
        ctx: Any,
    ) -> dict | list:
        """Execute a tool call and persist to DB."""
        return await self._tool_executor.execute(
            tool_name, args, tool_registry, session_id, ctx,
        )

    async def _persist_tool_result(
        self,
        session_id: str,
        tool_name: str,
        args: dict,
        result: Any,
    ) -> None:
        """Persist a tool result to MemoryManager.context."""
        await self._tool_executor.persist_tool_result(
            session_id, tool_name, args, result,
        )


__all__ = ["ChatBridgeBackend"]
