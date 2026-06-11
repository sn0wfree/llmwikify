"""Retry managers for the 6-step framework.

Three specialized managers layered on top of a base exponential-backoff
helper. Each is tailored to a specific failure mode:

1. StageRetryManager — wraps stage transitions; on failure it may downgrade
   to a *partial* result (warning) instead of raising. Used to keep the
   6-step framework progressing even when a stage partially fails.

2. LLMRetryManager — handles transient LLM errors (rate limit, timeout,
   connection reset). Distinguishes retriable from non-retriable errors
   (e.g. validation errors are NOT retried).

3. DBRetryManager — handles SQLite 'database is locked' / I/O errors with
   short backoff. Used to make state persistence robust to concurrent
   access without introducing a global lock.

The base `retry_async` helper is a thin copy of
`agent.backend.research.retry.retry_async` so the two projects don't share
a retry implementation. It exists to avoid an import cycle and to let
the two managers diverge independently.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ─── base exponential-backoff helper ──────────────────────────────────


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    call_timeout: float = 120.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Retry an async function with exponential backoff and per-call timeout."""
    last_exception: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs), timeout=call_timeout
            )
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1, max_attempts, e, delay,
                )
                await asyncio.sleep(delay)
    assert last_exception is not None
    raise last_exception


# ─── 1. StageRetryManager ─────────────────────────────────────────────


class StageRetryManager:
    """Wraps a stage with retry + optional partial-result downgrade.

    The 6-step framework calls each stage through a manager. If the stage
    raises, the manager retries up to `max_attempts`. If it still fails,
    the manager may return a *partial* result (the fallback value) along
    with a warning, rather than raising. This matches the "soft" gate
    policy: framework keeps progressing, downstream stages see the
    warning.
    """

    def __init__(
        self,
        stage_name: str,
        max_attempts: int = 2,
        base_delay: float = 1.0,
        allow_partial: bool = True,
    ):
        self.stage_name = stage_name
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.allow_partial = allow_partial

    async def run(
        self,
        func: Callable[..., Any],
        *args: Any,
        fallback: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a stage function, returning a dict with result + diagnostics.

        Returns:
            {
                "ok": bool,
                "value": T | None,
                "attempts": int,
                "warnings": list[str],
                "error": str | None,
            }
        """
        warnings: list[str] = []
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                value = await func(*args, **kwargs)
                if attempt > 1:
                    logger.info(
                        "%s succeeded on attempt %d", self.stage_name, attempt
                    )
                return {
                    "ok": True,
                    "value": value,
                    "attempts": attempt,
                    "warnings": warnings,
                    "error": None,
                }
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning(
                    "%s attempt %d/%d failed: %s",
                    self.stage_name, attempt, self.max_attempts, e,
                )
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.base_delay * (2 ** (attempt - 1)))

        # All attempts failed
        if self.allow_partial:
            warnings.append(
                f"{self.stage_name} 失败 {self.max_attempts} 次，使用部分结果"
            )
            return {
                "ok": False,
                "value": fallback,
                "attempts": self.max_attempts,
                "warnings": warnings,
                "error": str(last_error) if last_error else "unknown",
            }
        return {
            "ok": False,
            "value": None,
            "attempts": self.max_attempts,
            "warnings": warnings,
            "error": str(last_error) if last_error else "unknown",
        }


# ─── 2. LLMRetryManager ──────────────────────────────────────────────


# Common retriable LLM errors (transient)
LLM_RETRIABLE_PATTERNS = (
    "rate limit",
    "rate_limit",
    "429",
    "timeout",
    "timed out",
    "connection reset",
    "connection error",
    "service unavailable",
    "503",
    "502",
    "500",
    "internal server error",
)


def _is_retriable_llm_error(exc: Exception) -> bool:
    """Determine if an LLM error is transient (worth retry)."""
    msg = str(exc).lower()
    # Validation/parsing errors are NOT retriable
    non_retriable = (
        "json decode",
        "value error",
        "key error",
        "index error",
        "type error",
        "attribute error",
    )
    if any(p in msg for p in non_retriable):
        return False
    return any(p in msg for p in LLM_RETRIABLE_PATTERNS)


class LLMRetryManager:
    """Retry transient LLM errors; fail fast on validation errors.

    Uses _is_retriable_llm_error to distinguish transient infra issues
    (rate limit, timeout, 5xx) from caller errors (bad JSON, wrong key,
    schema mismatch).
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 2.0,
        call_timeout: float = 120.0,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.call_timeout = call_timeout

    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        """Public wrapper so ChatService can check retriable errors."""
        return _is_retriable_llm_error(exc)

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call an async LLM function with smart retry.

        Retries on transient errors. Re-raises immediately on caller errors.
        Each attempt is bounded by ``call_timeout`` seconds; on per-attempt
        timeout the attempt is treated as a transient error and retried.
        """
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs), timeout=self.call_timeout,
                )
            except Exception as e:  # noqa: BLE001
                last_error = e
                if not _is_retriable_llm_error(e):
                    logger.info(
                        "LLM call failed with non-retriable error, not retrying: %s", e
                    )
                    raise
                if attempt < self.max_attempts:
                    delay = min(self.base_delay * (2 ** (attempt - 1)), 30.0)
                    logger.warning(
                        "LLM transient error attempt %d/%d: %s. Retrying in %.1fs...",
                        attempt, self.max_attempts, e, delay,
                    )
                    await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error


# ─── 3. DBRetryManager ───────────────────────────────────────────────


class DBRetryManager:
    """Retry SQLite transient errors ('database is locked', I/O errors).

    SQLite's 'database is locked' error (SQLITE_BUSY) is returned when
    another connection holds a write lock. The recommended fix is short
    backoff + retry. We do not use a global lock to avoid blocking the
    main loop.
    """

    RETRIABLE_SQLITE_ERRORS: tuple[str, ...] = (
        "database is locked",
        "disk i/o error",
        "database is busy",
        "attempt to write a readonly database",
    )

    def __init__(self, max_attempts: int = 5, base_delay: float = 0.1):
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    @staticmethod
    def is_retriable(exc: Exception) -> bool:
        """Public static wrapper for external callers."""
        if isinstance(exc, sqlite3.OperationalError):
            msg = str(exc).lower()
            return any(p in msg for p in DBRetryManager.RETRIABLE_SQLITE_ERRORS)
        return False

    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        """Alias for ChatService usage."""
        return DBRetryManager.is_retriable(exc)

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Call a sync DB function with retry on transient SQLite errors.

        Designed for sync DB operations (the project uses sqlite3
        synchronously). Async DB operations should use a different
        mechanism (e.g. run_in_executor + this manager).
        """
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                last_error = e
                if not self.is_retriable(e):
                    raise
                if attempt < self.max_attempts:
                    import time as time_mod
                    delay = min(self.base_delay * (2 ** (attempt - 1)), 2.0)
                    logger.warning(
                        "DB transient error attempt %d/%d: %s. Retrying in %.2fs...",
                        attempt, self.max_attempts, e, delay,
                    )
                    time_mod.sleep(delay)
        assert last_error is not None
        raise last_error
