"""Cross-cutting helpers for ResearchEngine and adjacent modules.

Two reusable patterns consolidated here:

1. ``chat_json`` — async wrapper around LLM.chat() + safe_json_loads().
   The same 6-line pattern was duplicated at 6 call sites across
   engine.py / report.py / review.py / clarifier.py.

2. ``_safe_persist_status`` / ``_safe_persist_six_step`` — wrap
   session_manager DB writes in try/except so that transient DB
   failures (SQLITE_BUSY, I/O errors) don't crash the main loop.
   The same try/except pattern was duplicated at 8 call sites.

These helpers are deliberately small and pure. They are
imported by engine.py and the stage modules (report, review,
clarifier); the original inline code is replaced.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llmwikify.autoresearch._json_utils import safe_json_loads

logger = logging.getLogger(__name__)


async def chat_json(
    llm: Any,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    json_mode: bool = True,
) -> Any:
    """Async LLM chat call with safe JSON parsing.

    Wraps the standard 6-line pattern used across the autoresearch
    pipeline:

        def _sync():
            return llm.chat(messages, json_mode=..., max_tokens=..., temperature=...)
        raw = await asyncio.to_thread(_sync)
        return safe_json_loads(raw)

    Args:
        llm: An LLM client with a sync ``chat()`` method (typically
            ``StreamableLLMClient`` from ``agent.backend.adapters``).
        messages: List of ``{"role": ..., "content": ...}`` dicts.
        max_tokens: Token budget for the response. Default 2048.
        temperature: Sampling temperature. Default 0.3.
        json_mode: Whether to send ``response_format={type: json_object}``
            to the API. Default True (most autoresearch calls want JSON).

    Returns:
        The parsed JSON value (typically a dict).

    Raises:
        json.JSONDecodeError: If the response cannot be parsed.
        Any exception from ``llm.chat()`` is propagated unchanged.
    """
    def _sync() -> str:
        return llm.chat(
            messages,
            json_mode=json_mode,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    raw = await asyncio.to_thread(_sync)
    return safe_json_loads(raw)


def safe_persist_status(
    session_manager: Any,
    session_id: str,
    status: str,
    step: str | None = None,
    **kwargs: Any,
) -> None:
    """Persist status update; log and continue on failure.

    Replaces the 3-line try/except pattern repeated at 6+ sites:

        try:
            self.session_manager.update_status(...)
        except Exception as e:
            logger.warning("Failed to persist status: %s", e)

    Args:
        session_manager: A ``ResearchSessionManager`` instance.
        session_id: The session UUID.
        status: New status string (e.g. "gathering", "done").
        step: Optional step label.
        **kwargs: Forwarded to ``update_status`` (e.g.
            ``iteration_round``, ``synthesis_json``, ``review_json``).
    """
    try:
        session_manager.update_status(
            session_id, status, step, **kwargs
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Persist status %s/%s failed (continuing): %s",
            status, step, e,
        )


def safe_persist_six_step(
    session_manager: Any,
    session_id: str,
    **fields: Any,
) -> None:
    """Persist 6-step framework fields; log and continue on failure.

    Replaces the 3-line try/except pattern repeated at 2+ sites:

        try:
            self.session_manager.update_six_step_fields(
                state.session_id, evidence_scores=...
            )
        except Exception as e:
            logger.warning("Failed to persist six-step: %s", e)

    Args:
        session_manager: A ``ResearchSessionManager`` instance.
        session_id: The session UUID.
        **fields: Forwarded to ``update_six_step_fields`` (e.g.
            ``evidence_scores``, ``clarification``, ``reasoning``,
            ``structure``, ``self_loop_counts``, ``self_loop_history``).
    """
    try:
        session_manager.update_six_step_fields(session_id, **fields)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Persist six-step fields %s failed (continuing): %s",
            list(fields.keys()), e,
        )
