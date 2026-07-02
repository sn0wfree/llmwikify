"""Interactive first-admin prompt (decision 14, 15, 18).

Layer: L1 (foundation). Pure function — given a TTY (or not), prompt
the user for email + password, validate, and call auto_first_admin().

This module is intentionally tiny and side-effect-only because CLI is
the only caller. We use stdlib `input()` and `getpass.getpass()` (decision
18) — no questionary / rich / click. The TTY fallback (decision 15)
is a hard requirement: if stdin/stdout is not a TTY, we cannot prompt,
so we exit with a clear hint and a non-zero code.

Why in foundation (L1) and not in interfaces/cli/commands/auth.py?
Because:
  * The same prompt can be triggered by `serve` auto-init (CLI context)
    AND by `auth init` (CLI context) AND by a future
    `llmwikify hub onboard` flow.
  * Keeping the prompting logic testable from foundation tests
    (mock stdin via monkeypatch.setattr) is cleaner than testing
    the full CLI invocation.
  * The function is pure given its inputs (TTY detector + input sources).
"""

from __future__ import annotations

import getpass
import sys
import time
from dataclasses import dataclass

from ._errors import AuthError
from .db import UserRepository, auto_first_admin


@dataclass
class FirstAdminPromptResult:
    """Result of a successful interactive first-admin prompt."""

    user_email: str
    token: str
    """The owner JWT (already signed). Caller should print + write to
    ~/.llmwikify/local_token (decision 9)."""
    user_id: str
    is_first_admin: bool


def _is_tty() -> bool:
    """Both stdin and stdout must be TTYs to safely prompt."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _prompt_email(input_fn=input, out=sys.stdout) -> str:
    """Ask for email with basic format validation. Empty input → retry."""
    while True:
        out.write("Email: ")
        out.flush()
        raw = input_fn().strip()
        if not raw:
            out.write("  (empty; please provide an email)\n")
            continue
        if "@" not in raw or " " in raw or len(raw) < 3 or len(raw) > 254:
            out.write(f"  (invalid: {raw!r}; need something like 'you@example.com')\n")
            continue
        return raw.lower()


def _prompt_password(input_fn=input, out=sys.stdout) -> str:
    """Ask for password, hidden via getpass. Empty input → retry."""
    while True:
        raw = getpass.getpass("Password: ")
        if not raw:
            out.write("  (empty; please provide a password)\n")
            continue
        if len(raw) < 8:
            out.write("  (too short; need at least 8 characters)\n")
            continue
        if len(raw) > 1024:
            out.write("  (too long; cap at 1024 characters)\n")
            continue
        return raw


def _prompt_password_confirm(pw: str, input_fn=input, out=sys.stdout) -> bool:
    """Confirm password matches. Up to 3 retries on mismatch."""
    for _ in range(3):
        confirm = getpass.getpass("Password (again): ")
        if confirm == pw:
            return True
        out.write("  (mismatch; try again)\n")
    return False


def prompt_first_admin(
    *,
    input_fn=input,
    out=sys.stdout,
) -> FirstAdminPromptResult:
    """Interactively create the first admin user.

    Decision 14: triggered when serve detects --host is non-loopback
    and ~/.llmwikify/auth.db does not exist.

    Decision 15: TTY check; if not interactive, raise AuthError so the
    caller can print a hint and exit 1.

    Decision 18: stdlib prompts only.

    Returns:
        FirstAdminPromptResult with email + token + user_id.

    Raises:
        AuthError: not a TTY, or password confirm loop exhausted, or
            keyring unavailable (re-raised from the underlying helpers).
    """
    if not _is_tty():
        raise AuthError(
            code="no_tty",
            detail=(
                "Cannot prompt for first admin: stdin/stdout is not a TTY. "
                "Run `llmwikify auth init --email <you@example.com>` interactively first, "
                "or set the email/password via env vars (Phase 3+)."
            ),
            status_code=1,
        )

    out.write("\n[!] Auth required: serving on a non-loopback host.\n")
    out.write("[!] Let's create the first admin (one-time setup):\n\n")

    email = _prompt_email(input_fn=input_fn, out=out)
    password = _prompt_password(input_fn=input_fn, out=out)
    if not _prompt_password_confirm(password, input_fn=input_fn, out=out):
        raise AuthError(
            code="password_mismatch",
            detail="Password confirm did not match after 3 tries; aborting.",
            status_code=1,
        )

    # Lazy import: foundation.auth._jwt + _keyring so a missing
    # keyring backend only fails here (not at module import).
    from ._jwt import TokenClaims, encode
    from ._keyring import get_secret, set_secret

    # Ensure secret exists in keyring. If not, generate one.
    secret = get_secret()
    if not secret:
        secret = set_secret()

    # Create the user (idempotent on email).
    user = auto_first_admin(email=email, password=password)

    # Note: the wikis claim is always ["*"] at this point. We deliberately
    # do NOT import kernel.multi_wiki.registry here (L1 → L2 upward
    # import is forbidden by the G+Y 4-layer rule). The owner token's
    # wikis claim gets re-signed on the next `auth token` invocation
    # by the CLI, which can then safely import L2.
    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write",
        wikis=["*"],
    )
    token = encode(claims, secret)

    return FirstAdminPromptResult(
        user_email=user.email,
        token=token,
        user_id=user.id,
        is_first_admin=user.is_first_admin,
    )
