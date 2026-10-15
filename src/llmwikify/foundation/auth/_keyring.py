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

Security:
  On read, the fallback file's permissions are verified. If group or
  other have any access, a warning is logged. Set
  ``LLMWIKIFY_SECRET_STRICT=1`` to refuse to load and raise ``AuthError``
  instead — useful for CI / paranoid deployments.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
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

# Environment variable to refuse to load unsafe files instead of warning.
_STRICT_ENV_VAR = "LLMWIKIFY_SECRET_STRICT"


def _keyring_available() -> bool:
    """Check if a keyring backend is available (no daemon → False)."""
    try:
        keyring.get_password("_probe_", "_probe_")
        return True
    except keyring.errors.KeyringError:
        return False
    except Exception:
        return True  # other errors (e.g. "no password") mean keyring works


def _is_windows() -> bool:
    """Windows uses ACLs instead of POSIX mode bits; skip the check."""
    return sys.platform.startswith("win")


def _strict_mode_enabled() -> bool:
    """Whether to refuse loading a secret from an unsafe file."""
    return os.environ.get(_STRICT_ENV_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _check_secret_file_permissions(path: Path) -> bool:
    """Verify the fallback secret file is not readable by other users.

    Returns True if the permissions are safe (or the check is skipped
    on Windows / unsupported platforms). Returns False if the file has
    group/other access bits set.

    In strict mode (LLMWIKIFY_SECRET_STRICT=1) this raises AuthError
    instead of returning False.
    """
    if _is_windows():
        return True
    try:
        mode = path.stat().st_mode
    except OSError as e:
        logger.warning("Cannot stat secret file %s: %s", path, e)
        return True  # don't block on stat failure

    # Mask out owner bits; if anything is left, group/other can access.
    unsafe_bits = mode & 0o077
    if not unsafe_bits:
        return True

    actual_perms = oct(mode & 0o777)
    msg = (
        f"JWT secret file {path} has unsafe permissions {actual_perms}; "
        f"expected 0o600. Run: chmod 600 {path}"
    )

    if _strict_mode_enabled():
        logger.error("Refusing to load JWT secret: %s", msg)
        raise AuthError(
            code="keyring_secret_insecure_permissions",
            detail=msg,
            status_code=500,
        )

    logger.warning(
        "SECURITY WARNING: %s "
        "Other local users may be able to read your JWT signing key.",
        msg,
    )
    return False


def _read_file_secret() -> bytes:
    """Read secret from fallback file. Returns empty if not found."""
    if not _SECRET_FILE.exists():
        return b""
    try:
        raw = _SECRET_FILE.read_text(encoding="utf-8").strip()
        secret = bytes.fromhex(raw)
    except (ValueError, OSError):
        return b""

    # Permission check happens AFTER a successful read so a malformed
    # file doesn't trigger a confusing permission warning.
    _check_secret_file_permissions(_SECRET_FILE)
    return secret


def _write_file_secret(secret: bytes) -> None:
    """Write secret to fallback file with chmod 600 + parent dir 700."""
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_FILE.write_text(secret.hex(), encoding="utf-8")
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass
    # Best-effort parent-dir lockdown so other local users can't
    # symlink-swap the file or list its sibling files.
    if not _is_windows():
        try:
            os.chmod(_SECRET_FILE.parent, 0o700)
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
        logger.debug("OS keyring unavailable, falling back to file", exc_info=True)
    except Exception:
        logger.debug("OS keyring read failed, falling back to file", exc_info=True)

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
