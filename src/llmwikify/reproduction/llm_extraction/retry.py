"""Retry decorator for paper extraction LLM calls.

Layer 1 of 3-layer retry policy:
  - L1 (this module): per-call retry on transient failures (timeout,
    JSON parse, network). Catches ``Exception`` after ``StreamableLLMClient``
    has already exhausted its HTTP-level retries. Configurable max attempts
    with exponential backoff and jitter.
  - L2: deferred queue — caller catches ``DeferError`` and decides policy
    (skip / queue for next batch / abort paper).
  - L3: full-text fallback — caller passes ``on_defer`` hook to retry with
    modified args (e.g. smaller batch, full-text context).

Usage::

    from llmwikify.reproduction.llm_extraction.retry import (
        RetryConfig, with_retry, DeferError,
    )

    @with_retry(stage="track_b_pass1", config=RetryConfig(max_attempts=3))
    def call_llm(messages, max_tokens=...):
        return client.chat(messages, max_tokens=max_tokens, temperature=0.1)

Layer stacking with logger::

    @with_logging(stage="track_b_pass1", run_logger=rl)
    @with_retry(stage="track_b_pass1", config=cfg, run_logger=rl)
    def call_llm(...):
        ...
"""
from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .runlog import RunLogger

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

DeferHook = Callable[[Exception, tuple, dict], tuple[tuple, dict] | None]


# ── Errors ─────────────────────────────────────────────


class DeferError(Exception):
    """Raised when L1 retries are exhausted.

    Caller may:
      - catch and queue (deferred to next batch)
      - catch and apply fallback (L3) by calling the function again
      - catch and abort the paper extraction
    """


# ── Config ─────────────────────────────────────────────


@dataclass
class RetryConfig:
    """Configuration for the with_retry decorator.

    Attributes:
        max_attempts: total attempts including the first try (1 = no retry).
        backoff_base: initial sleep in seconds before attempt 2.
        backoff_factor: multiplier for each subsequent backoff.
        backoff_max: ceiling on backoff sleep to prevent absurd waits.
        backoff_jitter: random fraction [0, jitter] of backoff to add.
        retry_on: exception classes that trigger retry. Default (Exception,)
            catches everything; callers can narrow to (TimeoutError, ValueError).
        on_defer: optional hook called when L1 exhausts. Receives
            (exc, args, kwargs) and may return (new_args, new_kwargs) for
            one final attempt (L3 fallback). Return None to skip fallback.
    """

    max_attempts: int = 3
    backoff_base: float = 1.0
    backoff_factor: float = 2.0
    backoff_max: float = 30.0
    backoff_jitter: float = 0.1
    retry_on: tuple = field(default_factory=lambda: (Exception,))
    on_defer: DeferHook | None = None


# ── Decorator ─────────────────────────────────────────


def with_retry(
    stage: str,
    *,
    config: RetryConfig | None = None,
    run_logger: RunLogger | None = None,
) -> Callable[[F], F]:
    """Decorate a function with Layer 1 retry.

    Args:
        stage: stage name (for logging).
        config: retry policy; default RetryConfig() = 3 attempts, exp backoff.
        run_logger: optional RunLogger; each attempt logs ``llm_call``,
            each fail logs ``retry`` (if attempt < max) or
            ``fail`` (final attempt before raising DeferError).

    Returns:
        Decorator wrapping the function.
    """
    cfg = config or RetryConfig()

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, cfg.max_attempts + 1):
                t0 = time.monotonic()
                try:
                    result = fn(*args, **kwargs)
                except cfg.retry_on as exc:
                    last_exc = exc
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    if run_logger is not None:
                        run_logger.log(
                            stage, "llm_call",
                            latency_ms=latency_ms,
                            detail={"attempt": attempt, "max": cfg.max_attempts},
                            error=str(exc),
                        )
                    if attempt >= cfg.max_attempts:
                        # L1 exhausted. Try L3 fallback if provided.
                        if cfg.on_defer is not None:
                            try:
                                fallback = cfg.on_defer(exc, args, kwargs)
                            except Exception as hook_exc:
                                if run_logger is not None:
                                    run_logger.fail(
                                        stage,
                                        error=f"on_defer hook failed: {hook_exc}",
                                        latency_ms=latency_ms,
                                    )
                                raise DeferError(
                                    f"{stage} failed after {attempt} attempts; "
                                    f"on_defer hook raised: {hook_exc}"
                                ) from exc
                            if fallback is not None:
                                fb_args, fb_kwargs = fallback
                                if run_logger is not None:
                                    run_logger.log(
                                        stage, "fallback",
                                        detail={"attempt": attempt},
                                    )
                                try:
                                    return fn(*fb_args, **fb_kwargs)
                                except Exception as fb_exc:
                                    if run_logger is not None:
                                        run_logger.fail(
                                            stage,
                                            error=f"fallback attempt failed: {fb_exc}",
                                        )
                                    raise DeferError(
                                        f"{stage} fallback failed: {fb_exc}"
                                    ) from fb_exc
                        # No fallback or fallback returned None
                        if run_logger is not None:
                            run_logger.fail(
                                stage,
                                error=f"L1 exhausted after {attempt} attempts: {exc}",
                            )
                        raise DeferError(
                            f"{stage} failed after {attempt} attempts: {exc}"
                        ) from exc
                    # Compute backoff and sleep
                    sleep = min(
                        cfg.backoff_base * (cfg.backoff_factor ** (attempt - 1)),
                        cfg.backoff_max,
                    )
                    if cfg.backoff_jitter > 0:
                        sleep += random.uniform(0, sleep * cfg.backoff_jitter)
                    if run_logger is not None:
                        run_logger.log(
                            stage, "retry",
                            detail={
                                "attempt": attempt,
                                "next_in_s": round(sleep, 2),
                                "error": str(exc),
                            },
                        )
                    time.sleep(sleep)
                    continue
                # Success
                latency_ms = int((time.monotonic() - t0) * 1000)
                if run_logger is not None:
                    run_logger.log(
                        stage, "llm_call",
                        latency_ms=latency_ms,
                        detail={"attempt": attempt, "max": cfg.max_attempts},
                    )
                return result
            # Unreachable: loop returns or raises
            raise DeferError(
                f"{stage} exited loop without result: {last_exc}"
            )
        return wrapper  # type: ignore[return-value]

    return decorator
