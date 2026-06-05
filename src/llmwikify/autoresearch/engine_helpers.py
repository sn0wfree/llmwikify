"""Cross-cutting helpers for ResearchEngine and adjacent modules.

Three reusable patterns consolidated here:

1. ``chat_json`` — async wrapper around LLM.chat() + safe_json_loads().
   The same 6-line pattern was duplicated at 6 call sites across
   engine.py / report.py / review.py / clarifier.py.

2. ``_safe_persist_status`` / ``_safe_persist_six_step`` — wrap
   session_manager DB writes in try/except so that transient DB
   failures (SQLITE_BUSY, I/O errors) don't crash the main loop.
   The same try/except pattern was duplicated at 8 call sites.

3. ``resolve_llm_params`` — single source of truth for LLM call
   params (max_tokens / temperature / json_mode). Resolves with
   a 3-layer priority chain: caller config > prompt registry > safety
   net. Replaces hardcoded ``api_params.get(..., 2048)`` / etc.
   patterns at 6 call sites.

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
            ``StreamableLLMClient`` from ``llmwikify.llm.streamable``).
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


DEFAULT_LLM_PARAMS: dict[str, Any] = {
    "max_tokens": 2048,
    "temperature": 0.3,
    "json_mode": False,
}


def resolve_llm_params(
    registry: Any,
    config: dict[str, Any] | None,
    prompt_name: str,
    config_section: str | None = None,
) -> dict[str, Any]:
    """Resolve LLM call params with 3-layer priority chain.

    The single source of truth for LLM call params (max_tokens,
    temperature, json_mode) at any autoresearch call site. Replaces
    the previous pattern:

        api_params = registry.get_api_params("research_plan")
        max_tokens=api_params.get("max_tokens", 2048),
        temperature=api_params.get("temperature", 0.3),
        json_mode=api_params.get("json_mode", True),

    Resolution order (highest priority first):

        1. ``config[config_section][prompt_name][<param>]`` —
           caller-supplied config override. The section is a
           per-prompt dict, e.g.::

               config = {
                   "llm_params": {
                       "research_plan": {"max_tokens": 7777, ...},
                       "research_report": {"max_tokens": 8192, ...},
                   }
               }

        2. ``registry.get_api_params(prompt_name)[<param>]`` —
           value declared in the prompt's YAML (with provider
           override applied).
        3. ``DEFAULT_LLM_PARAMS[<param>]`` — safety net if both
           config and YAML omit the param.

    Args:
        registry: A ``PromptRegistry`` instance. Must have
            ``get_api_params(prompt_name)`` returning a dict of
            recognized API params. Pass ``None`` to skip the
            registry layer (e.g. when the caller has not yet
            integrated a registry).
        config: The merged research config dict. May be ``None``.
            If provided, ``config[config_section][prompt_name]`` is
            read when ``config_section`` is not None.
        prompt_name: The prompt template name (e.g.
            ``"research_plan"``, ``"research_report"``). Used both
            as the registry key and as the inner config key.
        config_section: Top-level config key holding the per-prompt
            override dict. Pass ``None`` to skip the config layer.

    Returns:
        Dict with keys ``max_tokens`` (int), ``temperature`` (float),
        and ``json_mode`` (bool). Suitable for ``**``-unpacking into
        ``chat_json`` / ``llm.chat(...)``.
    """
    prompt_cfg: dict[str, Any] = {}
    if config is not None and config_section:
        section = config.get(config_section, {}) or {}
        if isinstance(section, dict):
            prompt_cfg = section.get(prompt_name, {}) or {}

    registry_params: dict[str, Any] = {}
    if registry is not None and prompt_name:
        try:
            registry_params = registry.get_api_params(prompt_name)
        except (FileNotFoundError, KeyError, AttributeError, TypeError) as e:
            logger.debug(
                "resolve_llm_params: registry lookup failed for %r: %s",
                prompt_name, e,
            )
            registry_params = {}

    return {
        "max_tokens": prompt_cfg.get(
            "max_tokens",
            registry_params.get("max_tokens", DEFAULT_LLM_PARAMS["max_tokens"]),
        ),
        "temperature": prompt_cfg.get(
            "temperature",
            registry_params.get("temperature", DEFAULT_LLM_PARAMS["temperature"]),
        ),
        "json_mode": prompt_cfg.get(
            "json_mode",
            registry_params.get("json_mode", DEFAULT_LLM_PARAMS["json_mode"]),
        ),
    }
