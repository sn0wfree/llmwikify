"""ChatBridgeBackend — ``chat_service`` adapter for ChatRunnerV2.

``ChatRunnerV2`` reads its collaborators off a duck-typed
``chat_service`` object, expecting 3 underscore-prefixed methods plus a
``wiki_service`` accessor:

  - ``_truncate_messages``     → delegates to ``ContextManager.truncate``
  - ``_get_toolspec``          → delegates to ``ToolExecutor.get_toolspec``
  - ``_llm_stream_with_retry`` → delegates to ``ToolExecutor.llm_stream_with_retry``
  - ``wiki_service.get_llm()`` → the LLM client (needed for streaming)

This class is the single point of composition that wires those new
standalone components into the shape the runner expects.

Production wiring in ``ChatOrchestrator._chat_via_runner_v2``::

    backend = ChatBridgeBackend(
        tool_executor=self.tool_executor,
        context_manager=self.context_manager,
        wiki_service=self.wiki_service,
        config=self.config,
    )
    runner = ChatRunnerV2(chat_service=backend, ...)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class ChatBridgeBackend:
    """Adapter exposing the 3-method interface ChatRunnerV2 expects.

    Methods
    -------
    _truncate_messages(messages)
        Delegate to ``ContextManager.truncate``.

    _get_toolspec(tool_registry)
        Delegate to ``ToolExecutor.get_toolspec``.

    _llm_stream_with_retry(messages, tools)
        Delegate to ``ToolExecutor.llm_stream_with_retry``.

    The methods are kept underscore-prefixed to match the duck-typed
    ``chat_service`` contract ChatRunnerV2 reads from — test stubs
    already pass mock objects exposing these same names.
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

        ``ChatRunnerV2._stream_llm`` iterates this directly; we delegate
        to ``ToolExecutor.llm_stream_with_retry`` (which already
        implements the retry policy).
        """
        llm = self._get_llm_client()
        async for ev in self._tool_executor.llm_stream_with_retry(
            messages, tools, llm,
        ):
            yield ev


__all__ = ["ChatBridgeBackend"]
