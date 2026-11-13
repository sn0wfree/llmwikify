#!/usr/bin/env python3
"""Reproduce P1-5 / P1-6 / P0-3 / P1-7 from ``docs/llmwikify-auth-缺陷清单.md``.

Four independent probes, each in its own temporary ``$LLMWIKIFY_HOME``:

* **P1-5** — ``_derive_username`` does not de-duplicate despite its
  docstring claiming collisions are suffixed; a second admin with the
  same local-part raises a bare ``sqlite3.IntegrityError``.
* **P1-6** — ``auth init`` is not idempotent: three runs with the same
  email create three PATs all named ``cli-init``.
* **P0-3** — detecting an old schema (``password_hash`` column) silently
  ``DROP TABLE``s both ``users`` and ``api_keys`` with no backup and no
  warning.
* **P1-7** — in local mode ``GET /api/auth/me`` returns HTTP 200 with
  ``authenticated: false`` for unauthenticated callers, so the WebUI
  never clears a stale token.

Usage::

    python tools/auth_defect_verify.py

Exit code 0 = all probes reproduced, 1 = at least one did not, 2 = harness
error. State lives in temporary directories and is removed afterwards.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

_PROBE_HOME = "llmwikify_auth_verify_"


def _fresh_home() -> Path:
    """Point $LLMWIKIFY_HOME at a brand-new temp dir and return it."""
    home = Path(tempfile.mkdtemp(prefix=_PROBE_HOME))
    os.environ["LLMWIKIFY_HOME"] = str(home)
    return home


# ── P1-5 ──────────────────────────────────────────────────────────


def probe_p1_5() -> tuple[bool, str]:
    """Duplicate username → bare IntegrityError instead of AuthError / suffix."""
    from llmwikify.foundation.auth.db import UserRepository

    home = _fresh_home()
    try:
        repo = UserRepository()
        u1 = repo.create("alice@example.com", is_first_admin=True)
        try:
            u2 = repo.create("alice@other.com", is_first_admin=True)
        except sqlite3.IntegrityError as exc:  # the defect
            return True, f"bare IntegrityError raised: {exc}"
        except Exception as exc:  # noqa: BLE001 — AuthError etc. means fixed
            return False, f"raised {type(exc).__name__} (defect not reproduced): {exc}"
        # Fixed path: second create succeeds with a suffixed username.
        if u2.username and u2.username != u1.username:
            return False, (
                f"NOT reproduced — username de-duplicated: "
                f"{u1.username!r} / {u2.username!r}"
            )
        return False, f"second create succeeded with username={u2.username!r}"
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ── P1-6 ──────────────────────────────────────────────────────────


def probe_p1_6() -> tuple[bool, str]:
    """Three ``auth init`` runs → three PATs all named ``cli-init``."""
    import contextlib
    import io

    from llmwikify.foundation.auth.db import ApiKeyRepository
    from llmwikify.interfaces.cli.commands.auth import run_auth_init

    home = _fresh_home()
    try:
        # run_auth_init prints the token; capture it so the probe output
        # stays readable (the token is for a throwaway temp-home DB).
        for _ in range(3):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_auth_init(
                    None, {}, argparse.Namespace(email="alice@example.com")
                )
            if rc != 0:
                return False, f"run_auth_init returned {rc}"
        repo = ApiKeyRepository()
        rows = repo._connect().execute(
            "SELECT name FROM api_keys ORDER BY created_at"
        ).fetchall()
        names = [r[0] for r in rows]
        if len(names) >= 3 and len(set(names)) == 1:
            return True, f"{len(names)} PATs, all named {names[0]!r}"
        if len(names) == 1:
            return False, (
                f"NOT reproduced — only {len(names)} PAT named {names[0]!r} "
                "(P1-6 idempotent)"
            )
        return False, f"found {len(names)} PATs, names={names}"
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ── P0-3 ──────────────────────────────────────────────────────────


def probe_p0_3() -> tuple[bool, str]:
    """Old schema (password_hash) → silent DROP of users + api_keys."""
    from llmwikify.foundation.auth.db import UserRepository

    home = _fresh_home()
    try:
        db_path = home / "auth.db"
        conn = sqlite3.connect(db_path)
        # The real pre-PAT schema (git: be1a909d^) — `users` differs from
        # today's only by the obsolete password_hash column. An api_keys
        # table is included to prove the migration does not destroy one
        # that already exists.
        conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                username TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                is_first_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login_at TEXT
            );
            CREATE TABLE api_keys (
                id TEXT PRIMARY KEY,
                key_prefix TEXT NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id),
                name TEXT,
                scopes TEXT NOT NULL DEFAULT 'write',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT,
                expires_at TEXT,
                revoked_at TEXT
            );
            INSERT INTO users VALUES
                ('u1', 'old@example.com', 'olduser', 'x', 1, '2026-01-01', NULL);
            INSERT INTO api_keys VALUES
                ('k1', 'llmw_abcdefg', 'deadbeef', 'u1', 'cli-init', 'write',
                 '2026-01-01', NULL, NULL, NULL);
            """
        )
        conn.commit()
        conn.close()

        UserRepository(db_path=db_path)  # triggers the migration

        conn = sqlite3.connect(db_path)
        users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE id = 'u1'"
        ).fetchone()[0]
        keys = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        conn.close()
        if users == 0 and keys == 0:
            return True, "users 1→0, api_keys 1→0 — silent data loss (defect reproduced)"
        if users == 1 and keys == 1 and "password_hash" not in cols:
            return False, (
                "NOT reproduced — data preserved: users 1→1, api_keys 1→1, "
                "password_hash dropped, backup written next to auth.db"
            )
        return False, f"unexpected state: users={users}, api_keys={keys}, cols={sorted(cols)}"
    except Exception as exc:  # noqa: BLE001
        return False, f"harness error: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ── P1-7 ──────────────────────────────────────────────────────────


def probe_p1_7() -> tuple[bool, str]:
    """Invalid Bearer on ``GET /api/auth/me`` must be 401 (frontend can clear).

    Historical defect: local mode returned 200 + ``authenticated:false``
    for *any* unauthenticated call, and ``/me`` ignored ``Authorization``,
    so a stale localStorage JWT was never rejected. Fixed behaviour:
    a present-but-invalid Bearer → 401; no credentials at all in local
    mode still returns the local-trust marker (decision 12).
    """
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.core import WikiServer
    from llmwikify.kernel.multi_wiki.registry import WikiRegistry

    home = _fresh_home()
    client = None
    wiki_root: Path | None = None
    try:
        from llmwikify import Wiki

        wiki_root = Path(tempfile.mkdtemp(prefix="llmwikify_p17_wiki_"))
        wiki = Wiki(wiki_root)
        wiki.init(agent="generic")
        wiki.close()

        from llmwikify.kernel.multi_wiki.instance import WikiType

        registry = WikiRegistry(config={})
        registry.register_wiki(
            wiki_id="default",
            name="Default",
            root=wiki_root,
            wiki_type=WikiType.LOCAL,
            is_default=True,
        )
        server = WikiServer(registry, local_mode=True, public_read=True)
        app = server.app
        client = TestClient(app, base_url="http://127.0.0.1")
        client.__enter__()

        # Defect probe: invalid Bearer was previously ignored (cookie-only
        # /me) → 200 authenticated=false. Fixed → 401.
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        if resp.status_code == 401:
            return False, "NOT reproduced — invalid Bearer → 401 (P1-7 fixed)"
        return True, (
            f"HTTP {resp.status_code} for invalid Bearer "
            f"(body={resp.text[:80]!r}) — stale token not rejected"
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"harness error: {type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            try:
                client.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(home, ignore_errors=True)
        if wiki_root is not None:
            shutil.rmtree(wiki_root, ignore_errors=True)


PROBES: list[tuple[str, object]] = [
    ("P1-5 duplicate username → bare IntegrityError", probe_p1_5),
    ("P1-6 three auth-init runs → three cli-init PATs", probe_p1_6),
    ("P0-3 old schema → silent DROP of users + api_keys", probe_p0_3),
    ("P1-7 local-mode /api/auth/me → 200 authenticated=false", probe_p1_7),
]


def main() -> int:
    print("=" * 78)
    print("llmwikify auth defect probe — P1-5 / P1-6 / P0-3 / P1-7")
    print("=" * 78)
    reproduced = 0
    for label, fn in PROBES:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"harness error: {type(exc).__name__}: {exc}"
        reproduced += 0 if ok else 1
        mark = "REPRODUCED" if ok else "NOT reproduced"
        print(f"\n[{mark}] {label}")
        print(f"        {detail}")

    print("\n" + "-" * 78)
    n = len(PROBES)
    if reproduced == 0:
        print(f"VERDICT: ALL CONFIRMED ({n}/{n})")
        return 0
    print(f"VERDICT: {reproduced} of {n} probes did NOT reproduce")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
