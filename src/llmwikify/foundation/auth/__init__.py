"""Foundation auth — auth primitives for llmwikify.

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

Phase 2a: local-mode trust + JWT (read/write).
Phase 2.5: PAT-only auth (no passwords, decision 25).
Phase 3: share JWT (scope=read) — same encode/decode helpers.
Phase 4: hub OAuth (use Authlib, not this module).

Public API (re-exported from this __init__):

  * TokenClaims, encode, decode             — JWT shape + PyJWT wrapper
  * generate_pat, hash_pat, verify_pat       — PAT primitives (decision 25-27)
  * get_secret, set_secret, require_secret   — OS keyring (hard-fail on no backend)
  * UserRepository, ApiKeyRepository         — SQLite CRUD
  * auth_db_path                              — canonical `~/.llmwikify/auth.db`
  * is_local_default                         — loopback host detector (decision 12-13)
  * AuthError                                 — typed exception (subclass of Exception)

Decisions (see docs/designs/auth-and-sharing-roadmap.md §1.1 + §1.10):
  - 25: PAT replaces passwords (no password_hash column)
  - 26: PAT format = llmw_ prefix + 24-byte hex, SHA-256 hash storage
  - 27: api_keys table stores SHA-256 hash of PATs
  - 17: web auth = direct PAT validation (no fastapi-login needed)
  - 6:  cookie secure = False (MVP), warn on HTTPS-less
  - 11: auth.db path = ~/.llmwikify/auth.db
"""

from __future__ import annotations

from ._errors import AuthError
from ._jwt import TokenClaims, decode, encode
from ._keyring import get_secret, require_secret, set_secret
from ._pat import generate_pat, hash_pat, verify_pat
from .db import ApiKeyRepository, UserRepository, auth_db_path, auto_first_admin
from .prompt import FirstAdminPromptResult, prompt_first_admin
from .utils import (
    chmod_600,
    ensure_dir_700,
    env_host,
    is_local_default,
    load_pat,
    local_token_path,
    pat_file_path,
    save_pat,
)

__all__ = [
    "AuthError",
    "TokenClaims",
    "encode",
    "decode",
    "generate_pat",
    "hash_pat",
    "verify_pat",
    "get_secret",
    "set_secret",
    "require_secret",
    "UserRepository",
    "ApiKeyRepository",
    "auth_db_path",
    "auto_first_admin",
    "prompt_first_admin",
    "FirstAdminPromptResult",
    "is_local_default",
    "env_host",
    "local_token_path",
    "pat_file_path",
    "save_pat",
    "load_pat",
    "chmod_600",
    "ensure_dir_700",
]
