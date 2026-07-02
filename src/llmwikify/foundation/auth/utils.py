"""Shared utilities for the auth subsystem.

Layer: L1 (foundation).

Currently:
  * is_local_default — loopback / IPv4 / IPv6 host detection used by
    WikiServer and serve.py to decide between "local trust" mode
    and "auth enforced" mode (decision 12 + 13).
  * local_token_path / chmod_600 — POSIX permission helper for the
    owner-token file at ~/.llmwikify/local_token (decision 9).

This module is intentionally small. The two halves of the auth system
(L1 primitives vs L4 web layer) both need to import from here; placing
them in __init__ would create a circular-import risk.
"""

from __future__ import annotations

import ipaddress
import os
import stat
from pathlib import Path

# Loopback literals. We check these as well as the parsed ipaddress
# form, because hosts may be passed as DNS names that we should NOT
# treat as local (e.g. "localhost.example.com" should still go through
# auth). Only the exact strings + IP literals are trusted.
_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})


def is_local_default(host: str | None) -> bool:
    """Decide if the given host should be treated as "local trust" mode.

    Args:
        host: bind address for the server, e.g. "127.0.0.1", "::1",
            "0.0.0.0", "192.168.1.5", or None / empty.

    Returns:
        True iff the host is a loopback address (decision 13 default).
        False for any non-loopback IP, DNS name, or empty input.

    Notes:
        - "0.0.0.0" is NOT loopback (it means "all interfaces"); treating
          it as local would defeat the safety gate. Same for "::".
        - IPv4-mapped IPv6 (e.g. "::ffff:127.0.0.1") is unwrapped first
          and then checked as IPv4. (ipaddress.IPv6Address.is_loopback
          already does this for the IPv6Address object.)
        - DNS names that happen to resolve to 127.0.0.1 are NOT
          trusted; we only check the literal string. This is conservative
          on purpose — the user can still pass `127.0.0.1` explicitly.
    """
    if not host:
        return True  # empty / None = no bind specified = treat as local
    h = host.strip()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_loopback)


# ─── Env var helper (decision 13: serve default host) ──────────────────


def env_host(default: str = "127.0.0.1") -> str:
    """Read LLMWIKIFY_HOST env var, falling back to default.

    Used by interfaces/cli/commands/serve.py to decide bind address.
    Empty string or unset → default.
    """
    val = os.environ.get("LLMWIKIFY_HOST", "").strip()
    return val or default


# ─── Local token file helpers (decision 9) ────────────────────────


def local_token_path() -> Path:
    """Return canonical local_token path: ~/.llmwikify/local_token.

    Honors $LLMWIKIFY_HOME for tests / non-standard layouts.
    """
    home = os.environ.get("LLMWIKIFY_HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / ".llmwikify" / "local_token"


def chmod_600(path: Path) -> None:
    """Set POSIX permissions 0o600 on a file. No-op on Windows."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows has limited chmod semantics; best effort.
        pass


def ensure_dir_700(path: Path) -> None:
    """Create the parent dir if missing, chmod 0o700 (best effort)."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
