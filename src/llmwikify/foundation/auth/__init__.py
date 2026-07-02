"""Foundation auth — auth primitives for llmwikify.

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

Phase 2a: local-mode trust + JWT (read/write) + Argon2id password hashing.
Phase 2b: device pairing (X2).
Phase 3: share JWT (scope=read) — same encode/decode helpers.
Phase 4: hub OAuth (use Authlib, not this module).

Public API (re-exported from this __init__):

  * TokenClaims, encode, decode             — JWT shape + PyJWT wrapper
  * hash_password, verify_password          — Argon2id (t=3, m=64MB, p=4)
  * get_secret, set_secret, require_secret  — OS keyring (hard-fail on no backend)
  * UserRepository                            — SQLite users table CRUD
  * auth_db_path                              — canonical `~/.llmwikify/auth.db`
  * is_local_default                         — loopback host detector (Phase 2a 决策 13)
  * AuthError                                 — typed exception (subclass of Exception)

Decisions (see docs/designs/auth-and-sharing-roadmap.md §1.1):
  - 16: password hash = Argon2id (t=3, m=64MB, p=4)
  - 17: web 鉴权库 = fastapi-login (consumer, not in this module)
  - 6:  cookie secure = False (MVP), warn on HTTPS-less
  - 11: auth.db path = ~/.llmwikify/auth.db
"""

from __future__ import annotations

from ._errors import AuthError
from ._jwt import TokenClaims, decode, encode
from ._keyring import get_secret, require_secret, set_secret
from .db import UserRepository, auth_db_path, auto_first_admin
from .utils import (
    env_host,
    hash_password,
    is_local_default,
    needs_rehash,
    verify_password,
)

__all__ = [
    "AuthError",
    "TokenClaims",
    "encode",
    "decode",
    "hash_password",
    "verify_password",
    "needs_rehash",
    "get_secret",
    "set_secret",
    "require_secret",
    "UserRepository",
    "auth_db_path",
    "auto_first_admin",
    "is_local_default",
    "env_host",
]
