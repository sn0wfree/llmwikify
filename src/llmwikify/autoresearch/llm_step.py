"""Unified LLM call layer for the 6-step framework.

This module collapses the 7 distinct LLM call patterns (in
``clarifier.py``, ``actions.py``, ``engine.py``, ``report.py``,
``review.py``) into a single ``run_prompt`` entry point. Each step is
declared in ``autoresearch.prompts.PROMPT_REGISTRY``; this module
implements the call.

Pipeline per call (in order):

  1. Resolve LLM client from ``ctx`` (default/planning/report).
  2. Render messages via ``PromptRegistry.get_messages(name, **vars)``.
  3. If ``spec.framework_kind`` is set and ``six_step_context`` was
     passed, prepend a framework guidance block as an additional
     system message.
  4. Resolve API params via ``resolve_llm_params`` (3-layer
     priority: caller config > YAML > safety net default).
  5. Call LLM inside ``LLMRetryManager`` (smart retry: transient
     errors retried with exponential backoff, permanent errors
     (JSON parse / validation) fail-fast).
  6. Parse response as JSON if ``spec.expects_json``, else return raw
     text.
  7. On persistent failure: if ``spec.fallback`` is set, log warning
     and return the fallback; else re-raise.

The streaming report path (``report.generate_streaming``) is NOT
migrated to this layer because it returns an ``AsyncIterator[chunk]``
of the OpenAI streaming response — fundamentally different interface.
It keeps using the same ``PromptRegistry`` and
``resolve_llm_params`` helpers, so the prompt-rendering part is still
shared; only the call layer is inlined.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llmwikify.autoresearch._json_utils import safe_json_loads
from llmwikify.autoresearch.engine_helpers import resolve_llm_params
from llmwikify.autoresearch.prompts import (
    PROMPT_REGISTRY,
    ResearchPrompt,
    render_framework_block,
)
from llmwikify.autoresearch.retry_managers import LLMRetryManager

logger = logging.getLogger(__name__)


# ─── client resolution ────────────────────────────────────────────────


def _resolve_llm_client(ctx: Any, llm_role: str) -> Any:
    """Pick the LLM client matching ``llm_role`` from ``ctx``.

    Matches the engine's 3-layer model setup (default / planning /
    report). Falls back to ``ctx.default_llm`` if a specific role is
    not configured.
    """
    if llm_role == "planning":
        return getattr(ctx, "planning_llm", None) or ctx.default_llm
    if llm_role == "report":
        return getattr(ctx, "report_llm", None) or ctx.default_llm
    return ctx.default_llm


# ─── main entry point ─────────────────────────────────────────────────


async def run_prompt(
    ctx: Any,
    name: str,
    *,
    six_step_context: dict[str, Any] | None = None,
    **vars: Any,
) -> Any:
    """Make a single LLM call for the named prompt.

    This is the unified entry point for all 7 LLM call sites in the
    6-step framework (clarify, plan, replan, reason, report, review,
    revise). See module docstring for the full pipeline.

    Args:
        ctx: An ``ActionContext`` (or any object with attributes
            ``default_llm``, ``planning_llm``, ``report_llm``,
            ``config``). The 3 LLM clients are looked up by name; the
            ``config`` dict provides per-prompt overrides for retry
            and LLM params.
        name: The prompt registry key (e.g. ``"research_clarify"``).
        six_step_context: Optional consolidated 6-step framework
            context (from ``actions._build_six_step_context``). Only
            used by prompts whose ``framework_kind`` is set
            (``research_report``, ``research_review``).
        **vars: Keyword arguments passed to the YAML template's
            Jinja2 renderer (e.g. ``query=...``, ``report=...``,
            ``gaps=...``).

    Returns:
        The parsed JSON value if ``spec.expects_json`` is True, or the
        raw text otherwise. On persistent failure, returns
        ``spec.fallback(**vars)`` if set, else re-raises.

    Raises:
        KeyError: If ``name`` is not in ``PROMPT_REGISTRY``.
        Whatever ``llm.chat()`` or ``safe_json_loads`` raise after
        retries are exhausted, if no fallback is set.
    """
    spec = PROMPT_REGISTRY[name]

    # 1. Resolve LLM client
    client = _resolve_llm_client(ctx, spec.llm_role)

    # 2. Render messages
    from llmwikify.core.prompt_registry import PromptRegistry
    registry = PromptRegistry(provider=getattr(client, "provider", "openai"))
    messages = registry.get_messages(name, **vars)

    # 3. Framework augmentation (auto-inject for report/review)
    if spec.framework_kind and six_step_context:
        block = render_framework_block(six_step_context, spec.framework_kind)
        if block:
            messages = [{"role": "system", "content": block}, *messages]

    # 4. Resolve API params (max_tokens / temperature / json_mode)
    llm_params = resolve_llm_params(registry, ctx.config, name, "llm_params")

    # 5. Call LLM with smart retry
    retry = LLMRetryManager(
        max_attempts=ctx.config.get("max_retry_attempts", 3),
        base_delay=ctx.config.get("llm_retry_base_delay", 2.0),
        call_timeout=ctx.config.get("llm_call_timeout_seconds", 120),
    )

    async def _call() -> Any:
        raw = await asyncio.to_thread(client.chat, messages, **llm_params)
        if spec.expects_json:
            return safe_json_loads(raw)
        return raw

    try:
        return await retry.call(_call)
    except Exception as e:
        # 6. Persistent failure: try fallback, else re-raise
        if spec.fallback is not None:
            logger.warning(
                "Prompt %s failed after retries (%s), using fallback", name, e,
            )
            return spec.fallback(**vars)
        raise
