"""Shared utility functions for the foundation layer."""
from __future__ import annotations

import copy
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


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base dictionary.
        override: Dictionary with values to override.

    Returns:
        Merged dictionary (deep copy, originals not modified).
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def mask_api_key(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of config with api_key masked for safe display.

    Args:
        config: Config dict potentially containing 'api_key'.

    Returns:
        Copy with api_key masked.
    """
    masked = copy.deepcopy(config)
    api_key = masked.get("api_key", "")
    if api_key:
        if api_key.startswith("env:"):
            masked["api_key"] = "env:***"
        elif len(api_key) > 8:
            masked["api_key"] = api_key[:4] + "***" + api_key[-4:]
        else:
            masked["api_key"] = "***"
    return masked


__all__ = [
    "maybe_await",
    "deep_merge",
    "mask_api_key",
]
