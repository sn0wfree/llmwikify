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
    """Duplicate username → bare IntegrityError instead of AuthError."""
    from llmwikify.foundation.auth.db import UserRepository

    home = _fresh_home()
    try:
        repo = UserRepository()
        repo.create("alice@example.com", is_first_admin=True)
        try:
            repo.create("alice@other.com", is_first_admin=True)
        except sqlite3.IntegrityError as exc:  # the defect
            return True, f"bare IntegrityError raised: {exc}"
        except Exception as exc:  # noqa: BLE001 — anything else means fixed
            return False, f"raised {type(exc).__name__} (defect not reproduced): {exc}"
        return False, "second create succeeded — no collision at all"
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
        # Old v0.30-era schema the migration is supposed to detect.
        conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE api_keys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                key_hash TEXT NOT NULL
            );
            INSERT INTO users VALUES ('u1', 'old@example.com', 'x');
            INSERT INTO api_keys VALUES ('k1', 'u1', 'y');
            """
        )
        conn.commit()
        conn.close()

        UserRepository(db_path=db_path)  # triggers the migration

        conn = sqlite3.connect(db_path)
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        keys = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        conn.close()
        if users == 0 and keys == 0:
            return True, "users 1→0, api_keys 1→0 — silent data loss"
        return False, f"users={users}, api_keys={keys} — data survived"
    except Exception as exc:  # noqa: BLE001
        return False, f"harness error: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ── P1-7 ──────────────────────────────────────────────────────────


def probe_p1_7() -> tuple[bool, str]:
    """Local mode ``GET /api/auth/me`` → HTTP 200 + authenticated=false."""
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.core import WikiServer
    from llmwikify.kernel.multi_wiki.registry import WikiRegistry

    home = _fresh_home()
    client = None
    wiki_root: Path | None = None
    try:
        from llmwikify import Wiki

        # The server requires at least one registered wiki.
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
        # __init__ builds self.app and mounts the auth routes on it;
        # _build_app() alone would return a bare app without them.
        app = server.app
        # base_url must be a loopback host: /api/auth/me branches on
        # is_local_default(host), and TestClient's default Host is
        # "testserver" which is not loopback.
        client = TestClient(app, base_url="http://127.0.0.1")
        client.__enter__()
        resp = client.get("/api/auth/me")
        if resp.status_code == 200 and resp.json().get("authenticated") is False:
            return True, "HTTP 200, authenticated=false (stale token never cleared)"
        return False, f"HTTP {resp.status_code}, body={resp.text[:120]!r}"
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
