"""Shared utility functions for the foundation layer."""
from __future__ import annotations

import inspect
from typing import Any


async def maybe_await(fn_or_value: Any, *args: Any, **kwargs: Any) -> Any:
    """Call sync/async callable with args, or await a value directly.

    If ``fn_or_value`` is callable it is invoked with ``(*args, **kwargs)``;
    the result is then awaited if it is a coroutine / awaitable.
    Otherwise the value itself is awaited when awaitable, or returned as-is.
    """
    if callable(fn_or_value):
        result = fn_or_value(*args, **kwargs)
    else:
        result = fn_or_value
    if inspect.isawaitable(result):
        return await result
    return result
