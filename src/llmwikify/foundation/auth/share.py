"""``share_tokens`` — anonymous share-link credentials (P6 / Q5=a).

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

Design: ``docs/designs/multiuser-auth-design.md`` §12.8. Q5 decided
share grants live in their **own table**, not in ``wiki_grants``:

* ``wiki_grants`` — persistent grants for real principals (user/group/public)
* ``share_tokens`` — anonymous, expiring, revocable links with view audit

This module is the **data layer only**. Share JWT generation, the
``/share/{slug}`` route, the ``share`` CLI, and remote-wiki read-only
enforcement belong to roadmap Phase 3 (``auth-and-sharing-roadmap.md``).

Schema (roadmap §2.2, minus ``password_hash`` — PAT-only decision 25/28
removed the password stack; a bcrypt column would be a new dependency)::

    share_tokens(
        id TEXT PRIMARY KEY,            -- jti (JWT ID), uuid4 hex
        token_hash TEXT UNIQUE NOT NULL, -- sha256(token), never the JWT
        wiki_id TEXT NOT NULL,
        created_by TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT,                -- NULL = no expiry
        revoked_at TEXT,
        view_count INTEGER NOT NULL DEFAULT 0,
        last_viewed_at TEXT
    )

Performance follows M1–M3 (WAL + thread-local connection + schema-once),
same as the rest of ``foundation/auth``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._errors import AuthError
from .db import auth_db_path

logger = logging.getLogger(__name__)

_SHARE_SCHEMA = """
CREATE TABLE IF NOT EXISTS share_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    wiki_id TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    revoked_at TEXT,
    view_count INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_share_tokens_wiki ON share_tokens(wiki_id);
CREATE INDEX IF NOT EXISTS idx_share_tokens_active
    ON share_tokens(id) WHERE revoked_at IS NULL;
"""

_SHARE_TABLES = ("share_tokens",)


@dataclass(frozen=True)
class ShareToken:
    """In-memory representation of a share_tokens row."""

    id: str
    token_hash: str
    wiki_id: str
    created_by: str
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    view_count: int
    last_viewed_at: str | None


class ShareTokenRepository:
    """CRUD over ``share_tokens`` (P6)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else auth_db_path()
        self._ensure_dir()
        from llmwikify.foundation.db import get_connection

        self._mgr = get_connection(self.db_path)
        self._init_schema()

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass

    def _connect(self) -> Any:
        return self._mgr.conn

    def _schema_ready(self) -> bool:
        row = self._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='share_tokens'"
        ).fetchone()
        return row is not None

    def _init_schema(self) -> None:
        if self._schema_ready():
            return
        with self._mgr.transaction() as conn:
            conn.executescript(_SHARE_SCHEMA)

    # ── CRUD ─────────────────────────────────────────────────────

    def create(
        self,
        *,
        wiki_id: str,
        created_by: str,
        token_hash: str,
        expires_at: str | None = None,
    ) -> ShareToken:
        """Insert a share token. Raises AuthError on duplicate hash."""
        if not wiki_id or not token_hash:
            raise AuthError(
                code="invalid_share",
                detail="wiki_id and token_hash are required",
                status_code=400,
            )
        share_id = uuid.uuid4().hex
        try:
            with self._mgr.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO share_tokens
                        (id, token_hash, wiki_id, created_by, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (share_id, token_hash, wiki_id, created_by, expires_at),
                )
        except Exception as exc:  # noqa: BLE001 — UNIQUE on token_hash
            if "UNIQUE" in str(exc).upper():
                raise AuthError(
                    code="share_exists",
                    detail="A share token with this hash already exists.",
                    status_code=409,
                ) from exc
            raise
        created = self.get_by_id(share_id)
        if created is None:  # pragma: no cover — insert then read-back
            raise AuthError(
                code="share_create_failed",
                detail="Share insert succeeded but read-back failed.",
                status_code=500,
            )
        return created

    def get_by_id(self, share_id: str) -> ShareToken | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_tokens WHERE id = ?", (share_id,)
            ).fetchone()
        return _row_to_share(row) if row else None

    def get_by_hash(self, token_hash: str) -> ShareToken | None:
        """Active share by hash: not revoked, not expired (NULL = never).

        This is the lookup a share route performs on every request —
        revocation and expiry therefore take effect immediately (D6
        spirit, applied to the share surface).
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM share_tokens
                WHERE token_hash = ?
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL
                       OR CAST(expires_at AS INTEGER) > CAST(strftime('%s','now') AS INTEGER))
                """,
                (token_hash,),
            ).fetchone()
        return _row_to_share(row) if row else None

    def list(
        self,
        *,
        wiki_id: str | None = None,
        include_revoked: bool = False,
        created_by: str | None = None,
    ) -> list[ShareToken]:
        """Share tokens, newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if wiki_id is not None:
            clauses.append("wiki_id = ?")
            params.append(wiki_id)
        if created_by is not None:
            clauses.append("created_by = ?")
            params.append(created_by)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM share_tokens {where} "
                "ORDER BY created_at DESC, id DESC",
                params,
            ).fetchall()
        return [_row_to_share(r) for r in rows]

    def revoke(self, share_id: str) -> bool:
        """Soft-revoke. Returns True if a row changed (idempotent)."""
        with self._mgr.transaction() as conn:
            cursor = conn.execute(
                "UPDATE share_tokens SET revoked_at = datetime('now') "
                "WHERE id = ? AND revoked_at IS NULL",
                (share_id,),
            )
            return cursor.rowcount > 0

    def touch_view(self, share_id: str) -> None:
        """Increment view_count and stamp last_viewed_at (best-effort)."""
        with self._mgr.transaction() as conn:
            conn.execute(
                """
                UPDATE share_tokens
                SET view_count = view_count + 1,
                    last_viewed_at = datetime('now')
                WHERE id = ?
                """,
                (share_id,),
            )


def _row_to_share(row: Any) -> ShareToken:
    keys = row.keys()
    return ShareToken(
        id=row["id"],
        token_hash=row["token_hash"],
        wiki_id=row["wiki_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        view_count=int(row["view_count"]),
        last_viewed_at=row["last_viewed_at"] if "last_viewed_at" in keys else None,
    )


__all__ = ["ShareToken", "ShareTokenRepository"]
