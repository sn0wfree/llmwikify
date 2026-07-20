"""Shared utility functions for the foundation layer."""
from __future__ import annotations

import copy
import inspect
import ipaddress
import re
from typing import Any
from urllib.parse import urlparse


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


# ─── SSRF protection ────────────────────────────────────────────

# Hostnames that should be blocked (internal/loopback)
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "0.0.0.0",
    "metadata.google.internal",
    "instance-data",
})

# IP networks that should be blocked (private/link-local)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),    # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),   # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def is_safe_url(url: str) -> bool:
    """Check if a URL is safe to fetch (not targeting internal services).

    Blocks:
    - localhost and internal hostnames
    - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
    - Link-local addresses (169.254.x)
    - IPv6 loopback and private ranges

    Args:
        url: The URL to validate.

    Returns:
        True if the URL is safe to fetch, False otherwise.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Check blocked hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False

    # Check if hostname is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return False
    except ValueError:
        # Not an IP address, check for suspicious patterns
        # Block things like "127.0.0.1.nip.io" or similar
        if re.match(r"^\d+\.\d+\.\d+\.\d+\..+$", hostname):
            return False

    return True


def validate_url_or_raise(url: str) -> None:
    """Validate URL and raise ValueError if unsafe.

    Args:
        url: The URL to validate.

    Raises:
        ValueError: If the URL is unsafe.
    """
    if not is_safe_url(url):
        raise ValueError(
            f"URL blocked by SSRF protection: {url}. "
            "Only public HTTP/HTTPS URLs are allowed."
        )


__all__ = [
    "maybe_await",
    "deep_merge",
    "mask_api_key",
    "is_safe_url",
    "validate_url_or_raise",
]
