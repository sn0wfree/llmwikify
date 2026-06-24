"""Decorators for paper-level structured logging.

Usage::

    from llmwikify.reproduction.paper_understanding.llm_extraction.runlog import (
        make_run_logger, with_logging,
    )

    rl = make_run_logger(work_dir)

    @with_logging(stage="track_a", run_logger=rl)
    def run_track_a_one(client, plan, paper_id, parsed_text):
        ...

If ``run_logger`` is None, the decorator is a no-op (no logging side effect,
no latency measurement overhead beyond a single time.monotonic() call).
"""
from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from .runlog import RunLogger

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_logging(
    stage: str,
    run_logger: RunLogger | None = None,
) -> Callable[[F], F]:
    """Decorate a function to log start / success / fail via RunLogger.

    Behavior:
      - On entry: log ``start`` event
      - On return: log ``success`` event with measured latency_ms
      - On raise:  log ``fail`` event, then re-raise

    The decorated function's return value is passed through unchanged.
    If ``run_logger`` is None, the decorator only measures wall time and
    forwards calls to the original function (no RunLogger writes).

    Args:
        stage: stage name written to RunEvent.stage (e.g. "track_b_pass1").
        run_logger: optional RunLogger instance. If None, no-op.

    Returns:
        A decorator that wraps the function.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            if run_logger is not None:
                run_logger.start_stage(stage)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                if run_logger is not None:
                    run_logger.fail(stage, error=str(exc), latency_ms=latency_ms)
                raise
            latency_ms = int((time.monotonic() - t0) * 1000)
            if run_logger is not None:
                run_logger.success(stage, latency_ms=latency_ms)
            return result
        return wrapper  # type: ignore[return-value]
    return decorator
