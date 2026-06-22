"""Shared utility functions for the foundation layer."""
from __future__ import annotations

import inspect
from typing import Any


async def maybe_await(value: Any) -> Any:
    """Await ``value`` if it's a coroutine, otherwise return as-is."""
    if inspect.isawaitable(value):
        return await value
    return value
