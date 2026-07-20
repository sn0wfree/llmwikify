"""Shared utility functions for the foundation layer."""
from __future__ import annotations

import copy
import inspect
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


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

# Default blocked networks (empty by default - user must configure)
_DEFAULT_BLOCKED_NETWORKS: list[str] = []

# Default blocked hostnames (empty by default - user must configure)
_DEFAULT_BLOCKED_HOSTNAMES: list[str] = []


def _load_ssrf_config() -> dict[str, Any]:
    """Load SSRF protection configuration.

    Returns:
        Dict with 'blocked_networks' and 'blocked_hostnames' keys.
    """
    try:
        from .config import get_config
        config = get_config()
        ssrf_config = config.get("ssrf_protection", {})
        return {
            "blocked_networks": ssrf_config.get("blocked_networks", _DEFAULT_BLOCKED_NETWORKS),
            "blocked_hostnames": ssrf_config.get("blocked_hostnames", _DEFAULT_BLOCKED_HOSTNAMES),
            "enabled": ssrf_config.get("enabled", False),
        }
    except Exception as e:
        logger.debug("Failed to load SSRF config: %s", e)
        return {
            "blocked_networks": _DEFAULT_BLOCKED_NETWORKS,
            "blocked_hostnames": _DEFAULT_BLOCKED_HOSTNAMES,
            "enabled": False,
        }


def _parse_network(network_str: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a network string (e.g., '10.0.0.0/8') into an IP network object."""
    try:
        return ipaddress.ip_network(network_str, strict=False)
    except ValueError:
        return None


def is_safe_url(url: str) -> bool:
    """Check if a URL is safe to fetch (not targeting internal services).

    SSRF protection is configurable via the config file. By default,
    no URLs are blocked. Users must explicitly configure which networks
    and hostnames to block.

    Configuration example (in llmwikify.json):
    {
        "ssrf_protection": {
            "enabled": true,
            "blocked_networks": [
                "127.0.0.0/8",
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "169.254.0.0/16"
            ],
            "blocked_hostnames": [
                "localhost",
                "metadata.google.internal"
            ]
        }
    }

    Args:
        url: The URL to validate.

    Returns:
        True if the URL is safe to fetch, False otherwise.
    """
    config = _load_ssrf_config()

    # If SSRF protection is disabled, allow all URLs
    if not config.get("enabled", False):
        return True

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
    blocked_hostnames = set(config.get("blocked_hostnames", []))
    if hostname.lower() in blocked_hostnames:
        return False

    # Check if hostname is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        blocked_networks = config.get("blocked_networks", [])
        for network_str in blocked_networks:
            network = _parse_network(network_str)
            if network and ip in network:
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
            "See config 'ssrf_protection' for details."
        )


__all__ = [
    "maybe_await",
    "deep_merge",
    "mask_api_key",
    "is_safe_url",
    "validate_url_or_raise",
]
