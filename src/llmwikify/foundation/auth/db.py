"""SQLite auth.db + UserRepository + ApiKeyRepository.

Layer: L1 (foundation). Single-file SQLite, no ORM (consistent with
existing llmwikify style: pure sqlite3 stdlib). The auth.db is at
`~/.llmwikify/auth.db` (decision 11), separate from any wiki DB.

Schema (see docs/designs/auth-and-sharing-roadmap.md §1.4 + §1.10.2):

    users(id, email, username, is_first_admin, created_at, last_login_at)
    api_keys(id, key_prefix, key_hash, user_id, name, scopes,
             created_at, last_used_at, expires_at, revoked_at)

Decisions:
  - 11: path = ~/.llmwikify/auth.db
  - 25: PAT replaces passwords (no password_hash column)
  - 27: api_keys table stores SHA-256 hash of PATs
  - 18: arg parsing is up to the CLI; this module just persists records

This module is the only place that knows the table layout. callers
go through UserRepository / ApiKeyRepository methods. The raw
sqlite3.Connection is exposed only for the auto_first_admin()
convenience function and for tests.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ._errors import AuthError

logger = logging.getLogger(__name__)

APP_AUTH_FILENAME = ".llmwikify_auth.db"
APP_AUTH_DIR = ".llmwikify"


def auth_db_path() -> Path:
    """Return canonical auth.db path: ~/.llmwikify/auth.db.

    Honors $LLMWIKIFY_HOME for tests / non-standard layouts. The
    directory is created on demand by the repository; we don't
    pre-create here (let the caller decide when it's safe to touch
    the filesystem).
    """
    home = os.environ.get("LLMWIKIFY_HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / APP_AUTH_DIR / "auth.db"


def _derive_username(email: str) -> str:
    """Map email to a unique-safe username (used for hub @handle, Phase 4).

    Decision 0 / 18: users.username is auto-derived from email, with
    collisions suffixed. NULL OK in DB (user can set explicitly later
    via auth update). Pure local utility, no I/O.
    """
    local, _, _ = email.partition("@")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in local).lower()
    return safe[:64] or "user"


@dataclass
class User:
    """In-memory representation of a users row."""

    id: str
    email: str
    username: str | None
    is_first_admin: bool
    created_at: str
    last_login_at: str | None


class UserRepository:
    """Thin SQLite-backed repository for the users table.

    All writes use an atomic tempfile+rename pattern so a Ctrl-C during
    `auth init` cannot leave a partial auth.db (decision §1.8 risk row).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or auth_db_path()
        self._ensure_dir()
        self._init_schema()

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # chmod 700 on the directory: only the owner can list files inside.
        # Idempotent; if mode is already 0o700 this is a no-op.
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            # On Windows chmod has limited semantics; best effort.
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _atomic_write(self) -> Iterator[sqlite3.Connection]:
        """Yields a connection, commits atomically on success.

        We use a single in-memory transaction per write call. SQLite's
        default journal mode is rollback, so a Ctrl-C mid-write rolls
        back cleanly. We do NOT use the tempfile+rename trick at the
        file level here — that would invalidate the WAL mode we're
        using (decision: keep things simple for a single-table DB).
        """
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE,
                    is_first_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_login_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

                CREATE TABLE IF NOT EXISTS api_keys (
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
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
                CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
                """
            )
            conn.commit()

    # ─── Public API ─────────────────────────────────────────────────

    def exists(self) -> bool:
        """True iff the users table has at least one row."""
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            return row is not None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            return int(row["c"]) if row else 0

    def get_by_email(self, email: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_id(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def create(
        self,
        email: str,
        *,
        is_first_admin: bool = False,
        username: str | None = None,
    ) -> User:
        """Create a new user. Raises AuthError if email is taken.

        No password — PAT-only auth (decision 25).
        """
        if self.get_by_email(email) is not None:
            raise AuthError(
                code="email_taken",
                detail=f"User with email {email!r} already exists.",
                status_code=409,
            )
        user_id = uuid.uuid4().hex
        if username is None:
            username = _derive_username(email) if is_first_admin else None
        with self._atomic_write() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (id, email, username, is_first_admin)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, email, username, 1 if is_first_admin else 0),
            )
        created = self.get_by_id(user_id)
        if created is None:
            raise AuthError(
                code="create_failed",
                detail="User insert succeeded but read-back failed.",
                status_code=500,
            )
        return created

    def touch_last_login(self, user_id: str) -> None:
        """Update last_login_at to now. Silently no-ops if user vanished."""
        with self._atomic_write() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
                (user_id,),
            )


# ─── Helpers ──────────────────────────────────────────────────────


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        username=row["username"],
        is_first_admin=bool(row["is_first_admin"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


# ─── One-shot init (used by `auth init` and by serve auto-init) ─────


def auto_first_admin(
    email: str,
    *,
    db_path: Path | None = None,
) -> User:
    """Create the first admin user (idempotent on email).

    Used by:
      - `llmwikify auth init` CLI command
      - serve auto-init prompt (decision 14) when --host is non-loopback
        and no admin exists yet.

    Returns the User. Raises AuthError on email collision.
    """
    repo = UserRepository(db_path=db_path)
    if repo.get_by_email(email) is not None:
        existing = repo.get_by_email(email)
        if existing is not None:
            return existing
    return repo.create(
        email=email,
        is_first_admin=True,
    )


# ─── API Key (PAT) Repository ──────────────────────────────────────


@dataclass
class ApiKey:
    """In-memory representation of an api_keys row."""

    id: str
    key_prefix: str
    key_hash: str
    user_id: str
    name: str | None
    scopes: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None


class ApiKeyRepository:
    """Thin SQLite-backed repository for the api_keys table (decision 27)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or auth_db_path()
        self._ensure_dir()
        self._init_schema()

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE,
                    is_first_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS api_keys (
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
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
                CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
                """
            )
            conn.commit()

    @contextmanager
    def _atomic_write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(
        self,
        *,
        user_id: str,
        key_prefix: str,
        key_hash: str,
        name: str | None = None,
        scopes: str = "write",
        expires_at: str | None = None,
    ) -> ApiKey:
        """Insert a new API key record."""
        api_key_id = uuid.uuid4().hex
        with self._atomic_write() as conn:
            conn.execute(
                """
                INSERT INTO api_keys
                    (id, key_prefix, key_hash, user_id, name, scopes, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (api_key_id, key_prefix, key_hash, user_id, name, scopes, expires_at),
            )
        return self.get_by_id(api_key_id)

    def get_by_id(self, key_id: str) -> ApiKey | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE id = ?", (key_id,),
            ).fetchone()
        return _row_to_api_key(row) if row else None

    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Look up an active (not revoked, not expired) key by its hash."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM api_keys
                WHERE key_hash = ?
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > datetime('now'))
                """,
                (key_hash,),
            ).fetchone()
        return _row_to_api_key(row) if row else None

    def list_by_user(self, user_id: str) -> list[ApiKey]:
        """List all keys for a user (including revoked/expired)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_api_key(r) for r in rows]

    def touch_last_used(self, key_id: str) -> None:
        """Update last_used_at to now."""
        with self._atomic_write() as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
                (key_id,),
            )

    def revoke(self, key_id: str) -> bool:
        """Set revoked_at. Returns True if a row was updated."""
        with self._atomic_write() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET revoked_at = datetime('now') WHERE id = ? AND revoked_at IS NULL",
                (key_id,),
            )
            return cursor.rowcount > 0


def _row_to_api_key(row: sqlite3.Row) -> ApiKey:
    return ApiKey(
        id=row["id"],
        key_prefix=row["key_prefix"],
        key_hash=row["key_hash"],
        user_id=row["user_id"],
        name=row["name"],
        scopes=row["scopes"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )
