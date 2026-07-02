"""Personal Access Token (PAT) primitives — decision 25-27.

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

PAT format: ``llmw_`` prefix + 24-byte hex = 51 characters.
Storage: SHA-256 hash in ``api_keys`` table (decision 27).
Verification: constant-time HMAC compare via ``hmac.compare_digest``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PAT_PREFIX = "llmw_"
_PAT_SECRET_BYTES = 24  # 192 bits of entropy


def generate_pat() -> tuple[str, str]:
    """Generate a new PAT and return ``(plain, hash)``.

    The plain-text PAT is shown to the user exactly once. The hash is
    stored in the ``api_keys`` table. The prefix makes PATs visually
    distinguishable from other tokens.
    """
    raw = secrets.token_hex(_PAT_SECRET_BYTES)
    plain = f"{PAT_PREFIX}{raw}"
    pat_hash = hash_pat(plain)
    return plain, pat_hash


def hash_pat(plain: str) -> str:
    """Return the SHA-256 hex digest of a PAT."""
    if not isinstance(plain, str):
        raise TypeError(f"plain must be str, got {type(plain).__name__}")
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_pat(stored_hash: str, candidate: str) -> bool:
    """Constant-time check whether *candidate* matches *stored_hash*.

    Returns ``False`` on any error (bad encoding, wrong length, etc.).
    """
    if not isinstance(stored_hash, str) or not isinstance(candidate, str):
        return False
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored_hash, candidate_hash)
