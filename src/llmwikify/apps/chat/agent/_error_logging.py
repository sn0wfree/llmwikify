"""Unified error logging utilities for the chat agent.

Provides ``@log_exception_returning(default=None)`` — a decorator for
sync or async functions that catches all exceptions, logs them with
traceback, and returns a default value.

Usage::

    @log_exception_returning(default=None)
    async def _build_preferences_section(self):
        prefs = await self.memory_manager.preferences.aall(user_id)
        if not prefs:
            return None
        return "\\n".join(f"- **{k}**: {v}" for k, v in prefs.items())

    @log_exception_returning(default=None)
    def _build_tools_section(self):
        tool_names = self.wiki_service.list_tool_names()
        return ", ".join(tool_names)
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def log_exception_returning(
    default: Any = None,
    msg: str | None = None,
    log_level: int = logging.WARNING,
) -> Callable[[F], F]:
    """Decorator: catch exceptions in a sync or async function, log them,
    and return *default*.

    Automatically detects whether the wrapped function is async or sync
    and wraps accordingly.

    Args:
        default: value to return on exception (default: None).
        msg: log message template. If None, uses ``"{fn.__name__}: {exc}"``.
        log_level: logging level (default: WARNING).

    Example::

        @log_exception_returning(default=None, msg="Failed to load prefs")
        async def _build_prefs(self):
            ...

        @log_exception_returning(default=[], msg="Failed to list items")
        def _get_items(self):
            ...
    """
    def decorator(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    _log(fn, msg, e, log_level)
                    return default
            return async_wrapper  # type: ignore[return-value]
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    _log(fn, msg, e, log_level)
                    return default
            return sync_wrapper  # type: ignore[return-value]
    return decorator


def _log(fn: Callable, msg: str | None, exc: Exception, level: int) -> None:
    logger = logging.getLogger(fn.__module__)
    if msg:
        logger.log(level, "%s: %s", msg, exc, exc_info=True)
    else:
        logger.log(level, "%s: %s", fn.__name__, exc, exc_info=True)

