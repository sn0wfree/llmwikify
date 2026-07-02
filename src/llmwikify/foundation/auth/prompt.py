"""Interactive first-admin prompt (decision 14, 15, 18, 25).

Layer: L1 (foundation). Pure function — given a TTY (or not), prompt
the user for email (no password — PAT-only auth, decision 25), and
call auto_first_admin().

This module is intentionally tiny and side-effect-only because CLI is
the only caller. We use stdlib `input()` (decision 18) — no questionary
/ rich / click. The TTY fallback (decision 15) is a hard requirement:
if stdin/stdout is not a TTY, we cannot prompt, so we exit with a clear
hint and a non-zero code.

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

import sys
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
    pat: str
    """The personal access token (shown once). WebUI users paste this."""
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

    Decision 25: PAT-only auth — no password prompt.

    Returns:
        FirstAdminPromptResult with email + token + user_id.

    Raises:
        AuthError: not a TTY, or keyring unavailable (re-raised from
            the underlying helpers).
    """
    if not _is_tty():
        raise AuthError(
            code="no_tty",
            detail=(
                "Cannot prompt for first admin: stdin/stdout is not a TTY. "
                "Run `llmwikify auth init --email <you@example.com>` interactively first, "
                "or set the email via env var."
            ),
            status_code=1,
        )

    out.write("\n[!] Auth required: serving on a non-loopback host.\n")
    out.write("[!] Let's create the first admin (one-time setup):\n\n")

    email = _prompt_email(input_fn=input_fn, out=out)

    # Lazy import: foundation.auth._jwt + _keyring so a missing
    # keyring backend only fails here (not at module import).
    from ._jwt import TokenClaims, encode
    from ._keyring import get_secret, set_secret

    # Ensure secret exists in keyring. If not, generate one.
    secret = get_secret()
    if not secret:
        secret = set_secret()

    # Create the user (idempotent on email).
    user = auto_first_admin(email=email)

    # Generate a PAT for the user (decision 25).
    from ._pat import generate_pat
    from .db import ApiKeyRepository
    from .utils import save_pat

    pat, pat_hash = generate_pat()
    ak_repo = ApiKeyRepository()
    ak_repo.create(
        user_id=user.id,
        key_prefix=pat[:12],
        key_hash=pat_hash,
        name="init",
        scopes="write",
    )

    # Save PAT to file for later retrieval (cat ~/.llmwikify/pat).
    save_pat(pat)

    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write",
        wikis=["*"],
    )
    token = encode(claims, secret)

    return FirstAdminPromptResult(
        user_email=user.email,
        token=token,
        pat=pat,
        user_id=user.id,
        is_first_admin=user.is_first_admin,
    )
