"""Shared utilities for the auth subsystem.

Layer: L1 (foundation).

Currently:
  * is_local_default — loopback / IPv4 / IPv6 host detection used by
    WikiServer and serve.py to decide between "local trust" mode
    and "auth enforced" mode (decision 12 + 13).
  * hash_password / verify_password — Argon2id wrapper (decision 16).

This module is intentionally small. The two halves of the auth system
(L1 primitives vs L4 web layer) both need to import from here; placing
them in __init__ would create a circular-import risk.
"""

from __future__ import annotations

import ipaddress
import os

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerifyMismatchError,
)

# Argon2id parameters (decision 16): t=3, m=64MB, p=4. RFC 9106
# recommended mid-strength; modern CPU should hash in ~50ms. Ph
# instance is module-level so parameters are loaded once at import
# (re-instantiation per call would cost ~ms).
_PH = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)


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


# ─── Password hashing (Argon2id) ────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Hash a password with Argon2id (decision 16).

    The returned string is a PHC-formatted hash that includes all
    parameters, salt, and the encoded digest. Verifier can be any
    compatible Argon2 implementation.
    """
    if not isinstance(plain, str):
        raise TypeError(f"plain must be str, got {type(plain).__name__}")
    return _PH.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against an Argon2id hash.

    Returns:
        True if the password matches, False otherwise (including
        invalid hash, wrong algorithm, mismatch, etc.). We never raise
        on a bad password — caller just sees False. Other errors
        (e.g. hash corruption) return False too; logging the original
        exception is the caller's responsibility if they want to
        distinguish.
    """
    if not isinstance(plain, str) or not isinstance(hashed, str):
        return False
    try:
        return _PH.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Check if a stored hash should be upgraded to current parameters.

    Use after a successful verify_password to opportunistically upgrade
    the hash when the cost parameters have changed. Returns True if
    the caller's hash was generated with weaker parameters than the
    current PasswordHasher instance. The caller is expected to re-store
    the upgraded hash.
    """
    try:
        return _PH.check_needs_rehash(hashed)
    except InvalidHashError:
        return True  # corrupt hash → rehash


# ─── Env var helper (decision 13: serve default host) ──────────────────


def env_host(default: str = "127.0.0.1") -> str:
    """Read LLMWIKIFY_HOST env var, falling back to default.

    Used by interfaces/cli/commands/serve.py to decide bind address.
    Empty string or unset → default.
    """
    val = os.environ.get("LLMWIKIFY_HOST", "").strip()
    return val or default
