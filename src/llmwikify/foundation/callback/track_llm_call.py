"""Decorator for automatic LLM-call metrics recording (Pass5, 2026-06-22).

Mirrors the pattern of ``research_engine/actions.py:tracked`` (used
there for action-level metrics) but targets the chat-side
``runner_v2.py`` LLM stream call. Goal: surface per-call latency
metrics so Phase 8 microcompact metrics endpoint has data to
expose.

Usage::

    from llmwikify.foundation.callback.track_llm_call import track_llm_call

    class StreamableLLMClient:
        def __init__(self):
            self._metrics_collector = None

        @track_llm_call(lambda self: self._metrics_collector)
        async def chat(self, messages, **kwargs):
            ...

The decorator:
1. Records ``start = time.monotonic()`` before the call
2. Awaits the original function
3. On success: appends a ``LLMCallMetrics`` entry to
   ``metrics.llm_calls`` with ``prompt_name`` (from
   ``_prompt_name`` kwarg, defaults to ``func.__name__``),
   ``latency_ms``, and ``chars_in`` (sum of message lengths).
4. On exception: appends an entry with ``success=False`` and
   ``error=str(exc)``, then re-raises (so retry logic still works).
5. If ``metrics_collector is None`` (e.g. tests / dev), the
   decorator is a transparent pass-through.

Mirrors ``budget_decorator.check_token_budget`` style:
decorator-on-method that injects cross-cutting concern without
touching the wrapped function body.
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


def track_llm_call(
    metrics_getter: Callable[..., Any | None],
) -> Callable[[F], F]:
    """Decorator: record LLM-call latency + chars_in to a MetricsCollector.

    Args:
        metrics_getter: A callable that receives the instance (self)
            and returns the MetricsCollector (or None). Typically
            ``lambda self: self._metrics_collector``.

    The wrapped function MUST be ``async def`` (coroutine function).
    The wrapper handles both async generators and plain async
    functions transparently.

    Side effects:
        - Appends one ``LLMCallMetrics`` entry per call to
          ``metrics.llm_calls`` (if metrics is not None).
        - Logs a warning if metrics recording itself fails (best
          effort, never breaks the LLM call path).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract prompt_name (consumed by decorator, not passed through).
            # Mirrors budget_decorator's _prompt_name convention.
            prompt_name = kwargs.pop("_prompt_name", func.__name__)

            # Get metrics collector from instance (args[0] = self).
            metrics = None
            if args and callable(metrics_getter):
                try:
                    metrics = metrics_getter(args[0])
                except Exception:
                    logger.warning(
                        "track_llm_call: metrics_getter raised", exc_info=True,
                    )

            # Compute chars_in from first positional messages arg.
            chars_in = 0
            if len(args) > 1:
                messages = args[1]
                if isinstance(messages, list):
                    chars_in = sum(
                        len(str(m.get("content", "")))
                        for m in messages
                        if isinstance(m, dict)
                    )

            start = time.monotonic()
            success = True
            error_str = ""
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                success = False
                error_str = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                if metrics is not None:
                    latency_ms = int((time.monotonic() - start) * 1000.0)
                    try:
                        # Duck-typed: append LLMMCallMetrics or compatible.
                        # Imported lazily to avoid circular import at module
                        # load (state.py imports many chat modules).
                        from llmwikify.apps.chat.state import LLMCallMetrics
                        metrics.record_llm_call(LLMCallMetrics(
                            prompt_name=prompt_name,
                            llm_role="default",
                            attempt_count=1,
                            latency_ms=latency_ms,
                            chars_in=chars_in,
                            success=success,
                            error=error_str,
                        ))
                    except Exception:
                        logger.warning(
                            "track_llm_call: metrics.record_llm_call failed",
                            exc_info=True,
                        )

        return wrapper  # type: ignore[return-value]

    return decorator


def is_async_callable(fn: Any) -> bool:
    """Helper: detect async callable (async def + async gen)."""
    return inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)


__all__ = ["track_llm_call", "is_async_callable"]
