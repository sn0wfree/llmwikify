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
  7. On persistent failure: always re-raise. Callers use
     ``spec.fallback(**vars, error=e)`` to obtain a deterministic
     fallback. (see LLMCallMetrics.fallback_used for how this is
     recorded when the caller invokes the fallback.)

Metrics (commit 7 of the prompt-system refactor):

  Every call appends one ``LLMCallMetrics`` entry to
  ``ctx.metrics.llm_calls`` (when ``ctx.metrics`` is not None). The
  recording is wrapped in try/except so a misbehaving collector can
  never break the LLM call path. Fields populated:
  ``prompt_name``, ``llm_role``, ``attempt_count`` (via a counter
  on the retry closure), ``latency_ms``, ``chars_in`` / ``chars_out``
  (cheap token proxies), ``success``, ``json_parsed``, ``error``.

The streaming report path (``report.generate_streaming``) is NOT
migrated to this layer because it returns an ``AsyncIterator[chunk]``
of the OpenAI streaming response — fundamentally different interface.
It keeps using the same ``PromptRegistry`` and
``resolve_llm_params`` helpers, so the prompt-rendering part is still
shared; only the call layer is inlined.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from llmwikify.apps.chat.engine_helpers import resolve_llm_params
from llmwikify.apps.chat.prompts import (
    PROMPT_REGISTRY,
    ResearchPrompt,
    render_framework_block,
)
from llmwikify.apps.chat.retry_managers import LLMRetryManager
from llmwikify.apps.chat.state import LLMCallMetrics

def _safe_json_loads(raw: str, *, allow_truncate: bool = True) -> Any:
    """Robustly parse JSON returned by an LLM.

    Per Sprint C cleanup (C3 dead code): inlined here from
    the deleted ``_json_utils`` module. Handles empty
    responses, markdown code fences, and trailing prose.
    """
    text = raw.strip() if raw else ""
    if not text:
        raise json.JSONDecodeError("empty response", "", 0)

    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    if not text:
        raise json.JSONDecodeError("empty response (after fence strip)", "", 0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if not allow_truncate:
            raise
        start = -1
        for i, c in enumerate(text):
            if c in "{[":
                start = i
                break
        if start < 0:
            raise
        try:
            obj, _end = json.JSONDecoder().raw_decode(text, idx=start)
            return obj
        except json.JSONDecodeError:
            raise


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


def _chars_in(messages: list[dict[str, str]]) -> int:
    """Approximate input size: sum of ``len(content)`` per message."""
    return sum(len(m.get("content", "")) for m in messages)


def _chars_out(result: Any) -> int:
    """Approximate output size: ``len(str(result))`` (JSON-stringified
    for JSON outputs, raw for markdown).
    """
    if isinstance(result, str):
        return len(result)
    try:
        return len(json.dumps(result, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(result))


def _record_metric(ctx: Any, metric: LLMCallMetrics) -> None:
    """Best-effort append of one LLM call metric.

    Catches any exception from the collector so metric recording
    can never break the LLM call path.
    """
    metrics = getattr(ctx, "metrics", None)
    if metrics is None:
        return
    try:
        metrics.record_llm_call(metric)
    except Exception:
        logger.debug("Failed to record LLM call metric", exc_info=True)


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
            ``config``, optional ``metrics``). The 3 LLM clients are
            looked up by name; the ``config`` dict provides per-prompt
            overrides for retry and LLM params. ``metrics`` (when not
            None) receives one ``LLMCallMetrics`` entry per call.
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
        raw text otherwise. On persistent failure, the exception is
        re-raised; callers handle ``spec.fallback(**vars, error=e)``
        themselves.

    Raises:
        KeyError: If ``name`` is not in ``PROMPT_REGISTRY``.
        Whatever ``llm.chat()`` or ``safe_json_loads`` raise after
        retries are exhausted, if no fallback is set.
    """
    spec = PROMPT_REGISTRY[name]

    # Metrics accumulators (initialized for the finally block).
    start_time = time.monotonic()
    attempt_count = 0
    chars_in_value = 0
    chars_out_value = 0
    success = False
    json_parsed = False
    error_msg = ""

    try:
        # 1. Resolve LLM client
        client = _resolve_llm_client(ctx, spec.llm_role)

        # 2. Render messages
        from llmwikify.kernel.wiki.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider=getattr(client, "provider", "openai"))
        messages = registry.get_messages(name, **vars)

        # 3. Framework augmentation (auto-inject for report/review)
        if spec.framework_kind and six_step_context:
            block = render_framework_block(six_step_context, spec.framework_kind)
            if block:
                messages = [{"role": "system", "content": block}, *messages]

        # Snapshot input size for metrics (after augmentation).
        chars_in_value = _chars_in(messages)

        # 4. Resolve API params (max_tokens / temperature / json_mode)
        llm_params = resolve_llm_params(registry, ctx.config, name, "llm_params")

        # 5. Call LLM with smart retry. The closure counts attempts
        #    for metrics (each retry increments attempt_count).
        retry = LLMRetryManager(
            max_attempts=ctx.config.get("max_retry_attempts", 3),
            base_delay=ctx.config.get("llm_retry_base_delay", 2.0),
            call_timeout=ctx.config.get("llm_call_timeout_seconds", 120),
        )

        async def _call() -> Any:
            nonlocal attempt_count
            attempt_count += 1
            raw = await asyncio.to_thread(client.chat, messages, **llm_params)
            if spec.expects_json:
                return _safe_json_loads(raw)
            return raw

        result = await retry.call(_call)
        success = True
        json_parsed = spec.expects_json
        chars_out_value = _chars_out(result)
        return result
    except Exception as e:
        # Persistent failure: always re-raise. Callers use the
        # ``spec.fallback(**vars, error=e)`` callable from prompts.py
        # to obtain a deterministic fallback. This keeps the
        # fallback dict's keys (e.g. "fallback", "fallback_reason")
        # intact and visible to the caller, rather than being
        # silently dropped by run_prompt's internal handling.
        error_msg = str(e)
        logger.warning("Prompt %s failed after retries: %s", name, e)
        raise
    finally:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        _record_metric(
            ctx,
            LLMCallMetrics(
                prompt_name=name,
                llm_role=spec.llm_role,
                attempt_count=attempt_count,
                latency_ms=latency_ms,
                chars_in=chars_in_value,
                chars_out=chars_out_value,
                success=success,
                json_parsed=json_parsed,
                error=error_msg,
            ),
        )
