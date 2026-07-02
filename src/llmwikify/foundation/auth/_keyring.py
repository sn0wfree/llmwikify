"""OS keyring wrapper for the JWT signing secret.

Layer: L1 (foundation). Primary: OS keyring. Fallback: file-based
(~/.llmwikify/jwt_secret, chmod 600) when no keyring daemon is available.

Storage location (OS keyring):
    service: llmwikify
    user:    jwt_secret
    value:   32 random bytes (hex-encoded)

Fallback (file-based):
    path:    ~/.llmwikify/jwt_secret
    mode:    0o600 (owner read/write only)
    value:   32 random bytes (hex-encoded)

When the OS keyring backend is unavailable (headless Linux, Docker,
CI), we fall back to the file silently with a warning. The user can
install gnome-keyring-daemon for better security later.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

import keyring
import keyring.errors

from ._errors import AuthError

logger = logging.getLogger(__name__)

# Constants for the keyring slot.
KEYRING_SERVICE = "llmwikify"
KEYRING_USER = "jwt_secret"
SECRET_BYTES = 32  # 256 bits, matches HS256 minimum

# File fallback path.
_SECRET_FILE = Path("~/.llmwikify/jwt_secret").expanduser()


def _keyring_available() -> bool:
    """Check if a keyring backend is available (no daemon → False)."""
    try:
        keyring.get_password("_probe_", "_probe_")
        return True
    except keyring.errors.KeyringError:
        return False
    except Exception:
        return True  # other errors (e.g. "no password") mean keyring works


def _read_file_secret() -> bytes:
    """Read secret from fallback file. Returns empty if not found."""
    if not _SECRET_FILE.exists():
        return b""
    try:
        raw = _SECRET_FILE.read_text(encoding="utf-8").strip()
        return bytes.fromhex(raw)
    except (ValueError, OSError):
        return b""


def _write_file_secret(secret: bytes) -> None:
    """Write secret to fallback file with chmod 600."""
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_FILE.write_text(secret.hex(), encoding="utf-8")
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass


def get_secret() -> bytes:
    """Fetch the JWT signing secret. Empty bytes if not set yet.

    Tries OS keyring first, falls back to file if keyring unavailable.

    Returns:
        32 raw bytes (decoded from hex). Empty if never initialized.
    """
    # 1. Try OS keyring.
    try:
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if value:
            return bytes.fromhex(value)
    except keyring.errors.KeyringError:
        pass  # fall through to file
    except Exception:
        pass

    # 2. Fallback: file.
    return _read_file_secret()


def set_secret(secret: bytes | None = None) -> bytes:
    """Generate (or accept) a 32-byte secret and store it.

    Tries OS keyring first, falls back to file if keyring unavailable.

    Returns:
        The bytes that were stored. Always exactly SECRET_BYTES long.
    """
    if secret is None:
        secret = secrets.token_bytes(SECRET_BYTES)
    if not isinstance(secret, (bytes, bytearray)):
        raise AuthError(
            code="keyring_secret_type",
            detail="secret must be bytes",
            status_code=500,
        )
    if len(secret) < SECRET_BYTES:
        raise AuthError(
            code="keyring_secret_length",
            detail=f"secret must be at least {SECRET_BYTES} bytes (got {len(secret)})",
            status_code=500,
        )
    secret = bytes(secret[:SECRET_BYTES])

    # 1. Try OS keyring.
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, secret.hex())
        return secret
    except keyring.errors.KeyringError:
        logger.warning(
            "OS keyring unavailable, falling back to file secret (~/.llmwikify/jwt_secret). "
            "Install gnome-keyring-daemon for better security."
        )

    # 2. Fallback: file.
    _write_file_secret(secret)
    return secret


def require_secret() -> bytes:
    """Get the JWT secret, raising if not initialized.

    Returns:
        32 raw bytes.
    """
    secret = get_secret()
    if not secret:
        raise AuthError(
            code="auth_not_initialized",
            detail=(
                "JWT secret not found. Run `llmwikify auth init --email <you@example.com>` "
                "first to create the first admin user and signing secret."
            ),
            status_code=500,
        )
    return secret
