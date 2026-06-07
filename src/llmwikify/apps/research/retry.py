"""Retry utility with exponential backoff for research operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


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
    """Retry an async function with exponential backoff and per-call timeout.

    Args:
        func: Async function to retry.
        *args: Positional arguments to pass to func.
        max_attempts: Maximum number of attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        call_timeout: Per-call timeout in seconds.
        exceptions: Tuple of exception types to retry on.
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The result of the function call.

    Raises:
        The last exception if all attempts fail.
    """
    last_exception: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=call_timeout)
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning("Attempt %d/%d failed: %s. Retrying in %.1fs...", attempt + 1, max_attempts, e, delay)
                await asyncio.sleep(delay)
            else:
                logger.error("All %d attempts failed: %s", max_attempts, e)
        except TimeoutError:
            last_exception = TimeoutError(f"Call timed out after {call_timeout}s")
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning("Attempt %d/%d timed out after %.0fs. Retrying in %.1fs...", attempt + 1, max_attempts, call_timeout, delay)
                await asyncio.sleep(delay)
            else:
                logger.error("All %d attempts timed out", max_attempts)
    raise last_exception  # type: ignore[misc]


def retry_sync(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Retry a synchronous function with exponential backoff."""
    import time
    last_exception: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning("Attempt %d/%d failed: %s. Retrying in %.1fs...", attempt + 1, max_attempts, e, delay)
                time.sleep(delay)
            else:
                logger.error("All %d attempts failed: %s", max_attempts, e)
    raise last_exception  # type: ignore[misc]
