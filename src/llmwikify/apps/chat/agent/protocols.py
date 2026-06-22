"""Chat agent structural typing (Pass7, 2026-06-22).

Pass7 (M-2): define a :class:`Protocol` for the duck-typed
``chat_service`` collaborator ``ChatRunnerV2`` reads off via
``getattr``. The Protocol:

  - Documents the 3-method contract (``_truncate_messages`` /
    ``_get_toolspec`` / ``_llm_stream_with_retry``) plus the
    optional ``wiki_service`` accessor.
  - Makes ``ChatBridgeBackend`` a satisfying adapter for mypy /
    pyright / IDE type checkers (without forcing runtime checks).
  - Lets future callers stub a ChatServiceAdapter without inheriting
    from any base class.

Mirrors the GoF Adapter pattern: ``ChatBridgeBackend`` is the
Adapter (chat-service shape), and the Protocol formalises the
target interface ChatRunnerV2 expects. Tests continue to use
duck-typed stubs (Protocol is structural, not nominal).

Design notes:
  - ``Protocol`` does NOT add runtime cost (PEP 544). The
    ``getattr(self._chat_service, ...)`` calls in runner_v2 remain
    unchanged for back-compat with 100+ test stubs.
  - The ``wiki_service`` accessor is optional (``@property``
    with no default — callers must implement it).
  - ``astream_chat`` / ``chat`` on the wiki_service's LLM client
    are also typed via a sub-Protocol (LLMClient) for the metrics
    integration (Phase 8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatServiceAdapter(Protocol):
    """Structural interface that ``ChatRunnerV2`` expects on its
    ``chat_service`` collaborator.

    Three underscore-prefixed methods plus an optional wiki_service
    accessor. The underscores are intentional — they mark these as
    "internal chat domain" methods, not public API.

    Implementations:
      - ``ChatBridgeBackend`` (apps/chat/agent/bridge_backend.py) is
        the production adapter wiring ContextManager + ToolExecutor
        + WikiService.
      - Test stubs in ``tests/test_apps_chat_agent_runner_v2.py``
        (100+ classes) provide just the methods they exercise.
    """

    def _truncate_messages(
        self,
        messages: list[dict[str, Any]],
        max_messages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Truncate ``messages`` to fit the model's context window.

        Args:
            messages: OpenAI-format chat messages.
            max_messages: Optional override; ``None`` = use default.

        Returns:
            Possibly shorter list of messages (front-truncated).
        """
        ...

    def _get_toolspec(self, tool_registry: Any) -> list[dict[str, Any]]:
        """Build OpenAI-format tool spec from ``tool_registry``.

        Args:
            tool_registry: A tool registry (composite of wiki + skill tools).

        Returns:
            OpenAI-format ``tools`` list (each entry has ``type``,
            ``function.name``, ``function.description``,
            ``function.parameters``).
        """
        ...

    def _llm_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM response with first-chunk retry.

        Args:
            messages: OpenAI-format chat messages.
            tools: OpenAI-format tool spec.

        Yields:
            SSE-style event dicts (typically ``message_delta``,
            ``thinking``, ``tool_call_*``, ``done``, ``error``).
        """
        ...

    @property
    def wiki_service(self) -> Any:
        """WikiService accessor (used by runner_v2._stream_llm).

        Tests may return ``None`` if they don't exercise the
        LLM-streaming path.
        """
        ...


@runtime_checkable
class LLMClient(Protocol):
    """Structural interface for an LLM client that ``ChatRunnerV2``
    can call directly when ``_llm_stream_with_retry`` is not provided.

    Used as fallback in ``runner_v2._stream_llm`` (L660-664) for
    ad-hoc streaming when the chat_service doesn't have
    ``_llm_stream_with_retry``.
    """

    def astream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Any]:
        """Async stream chat (preferred fallback)."""
        ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Synchronous single-shot chat (last-resort fallback)."""
        ...


__all__ = ["ChatServiceAdapter", "LLMClient"]
