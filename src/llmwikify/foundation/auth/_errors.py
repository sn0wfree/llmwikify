"""AuthError — typed exceptions for the auth subsystem.

Layer: L1 (foundation).

Single exception class to keep the public surface small. Specific HTTP
status mapping is the caller's job (interfaces/server/http/auth_routes.py
and middleware).

Decisions:
  - 10: error response format = JSON {error, status_code, detail}
"""

from __future__ import annotations


class AuthError(Exception):
    """Base exception for the auth subsystem.

    Carries an error code (string, machine-readable) and a human-readable
    detail. The HTTP layer maps this to:
        401 Unauthorized  (no/invalid token, expired, bad signature)
        403 Forbidden     (token valid but scope insufficient)
        423 Locked        (too many failed login attempts)
        500 Internal      (auth.db corruption, keyring unreachable)

    Args:
        code: machine-readable token, e.g. "invalid_credentials",
            "token_expired", "forbidden_scope", "rate_limited".
        detail: human-readable explanation (safe to show to end user).
        status_code: HTTP status the caller should return.
    """

    def __init__(self, code: str, detail: str, status_code: int = 401) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        """Serialize to the canonical error response format (decision 10)."""
        return {
            "error": self.code,
            "status_code": self.status_code,
            "detail": self.detail,
        }
