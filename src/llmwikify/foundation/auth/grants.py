"""``wiki_grants`` / ``groups`` / ``group_members`` — authorization data (L1).

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

Design: `docs/designs/multiuser-auth-design.md` (decisions D1–D9, Q1–Q6) —
specifically D1 (flat ``principal × wiki × read/write``), D2 (auth.db),
D3 (wiki-level), D4 (read/write), D5 (no deny; revoke = delete row),
D9 (``public`` principal row), Q1 (group support via K8s-style
``subject.kind``), Q3 (``wiki_id='*'`` wildcard allowed in the table;
token snapshots are expanded to concrete ids at signing time).

Performance (design §4.2, measures M1–M3):
  * M1 — WAL journal mode (readers don't block writers) via
    ``foundation.db.get_connection`` (``wal=True`` by default).
  * M2 — thread-local persistent connection (one per thread, reused);
    avoids the ~8× cost of ``sqlite3.connect()`` per call.
  * M3 — schema is created once per database file (fast-path check).

Concurrency: a single point query is ~25 µs warm; fail-closed on error
is the caller's job (middleware, P4).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from ._errors import AuthError
from .db import auth_db_path

logger = logging.getLogger(__name__)

PrincipalType = Literal["user", "group", "public"]

# K8s-style subject.kind — three kinds only (D1 + Q1).
PRINCIPAL_TYPES: frozenset[str] = frozenset({"user", "group", "public"})

# Wildcard wiki_id: "all wikis, including ones created later" (Q3-a / Q3-c).
WILDCARD = "*"

_GRANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_grants (
    principal_type TEXT NOT NULL
        CHECK (principal_type IN ('user', 'group', 'public')),
    principal_id   TEXT NOT NULL,
    wiki_id        TEXT NOT NULL,
    can_read       INTEGER NOT NULL DEFAULT 0,
    can_write      INTEGER NOT NULL DEFAULT 0,
    granted_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (principal_type, principal_id, wiki_id)
);
CREATE INDEX IF NOT EXISTS idx_wiki_grants_lookup
    ON wiki_grants(principal_type, principal_id, wiki_id);

CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL REFERENCES groups(id),
    user_id  TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_group_members_user
    ON group_members(user_id);
"""

# Tables that must exist before the schema is considered ready (M3).
_SCHEMA_TABLES = ("wiki_grants", "groups", "group_members")


class GrantRepository:
    """CRUD over ``wiki_grants`` + ``groups`` + ``group_members``.

    All reads/writes go through a shared thread-local connection
    (WAL + persistent), so the hot path costs one indexed point query.

    Principal model (D1):
        ``user``   — one row per (user, wiki)
        ``group``  — one row per (group, wiki); expanded via group_members
        ``public`` — the PG ``PUBLIC`` pseudo-role / K8s
                     ``system:authenticated`` group (D9)

    Wildcard (Q3):
        ``wiki_id = '*'`` means "every wiki, including future ones" in the
        **live upper bound**. Token snapshots never contain ``'*`` — they are
        expanded to concrete ids at signing time (Q3-b), so an old token does
        not silently gain access to a newly created wiki.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else auth_db_path()
        self._ensure_dir()
        # M1 + M2: WAL journal + thread-local persistent connection.
        from llmwikify.foundation.db import get_connection

        self._mgr = get_connection(self.db_path)
        self._init_schema()

    # ── plumbing ─────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass  # Windows chmod has limited semantics; best effort.

    def _connect(self) -> Any:
        """Thread-local persistent connection (M2)."""
        return self._mgr.conn

    def _schema_ready(self) -> bool:
        """M3: cheap check that all three tables exist (skip executescript)."""
        conn = self._connect()
        for table in _SCHEMA_TABLES:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if row is None:
                return False
        return True

    def _init_schema(self) -> None:
        if self._schema_ready():
            return
        with self._mgr.transaction() as conn:
            conn.executescript(_GRANT_SCHEMA)

    def _validate_principal(self, principal_type: str, principal_id: str) -> None:
        if principal_type not in PRINCIPAL_TYPES:
            raise AuthError(
                code="invalid_principal",
                detail=(
                    f"principal_type must be one of "
                    f"{sorted(PRINCIPAL_TYPES)}, got {principal_type!r}"
                ),
                status_code=400,
            )
        if principal_type == "public" and principal_id != WILDCARD:
            raise AuthError(
                code="invalid_principal",
                detail="principal_id for 'public' must be '*'",
                status_code=400,
            )
        if principal_type != "public" and not principal_id:
            raise AuthError(
                code="invalid_principal",
                detail="principal_id must not be empty",
                status_code=400,
            )
        if not principal_id:
            raise AuthError(
                code="invalid_principal",
                detail="principal_id must not be empty",
                status_code=400,
            )

    # ── groups (Q1) ──────────────────────────────────────────────

    def create_group(self, name: str) -> str:
        """Create a group. Returns its id. Raises AuthError if the name is taken."""
        import uuid

        name = (name or "").strip()
        if not name:
            raise AuthError(
                code="invalid_group",
                detail="group name must not be empty",
                status_code=400,
            )
        group_id = uuid.uuid4().hex
        try:
            self._mgr.execute_write(
                "INSERT INTO groups (id, name) VALUES (?, ?)",
                (group_id, name),
            )
        except Exception as exc:  # noqa: BLE001 — UNIQUE on name
            if "UNIQUE" in str(exc).upper() or "unique" in str(exc).lower():
                raise AuthError(
                    code="group_exists",
                    detail=f"Group {name!r} already exists.",
                    status_code=409,
                ) from exc
            raise
        return group_id

    def list_groups(self) -> list[dict[str, Any]]:
        """All groups with their member counts."""
        rows = self._connect().execute(
            """
            SELECT g.id, g.name, g.created_at,
                   (SELECT COUNT(*) FROM group_members m
                    WHERE m.group_id = g.id) AS member_count
            FROM groups g
            ORDER BY g.name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def add_member(self, group_id: str, user_id: str) -> bool:
        """Add a user to a group (idempotent). Returns True if newly added."""
        if not group_id or not user_id:
            raise AuthError(
                code="invalid_member",
                detail="group_id and user_id are required",
                status_code=400,
            )
        cursor = self._mgr.execute_write(
            "INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)",
            (group_id, user_id),
        )
        return cursor.rowcount > 0

    def remove_member(self, group_id: str, user_id: str) -> bool:
        """Remove a user from a group. Returns True if a row was removed."""
        cursor = self._mgr.execute_write(
            "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        return cursor.rowcount > 0

    def list_members(self, group_id: str) -> list[str]:
        """User ids that belong to ``group_id``."""
        rows = self._connect().execute(
            "SELECT user_id FROM group_members WHERE group_id = ? ORDER BY user_id",
            (group_id,),
        ).fetchall()
        return [r["user_id"] for r in rows]

    def groups_of(self, user_id: str) -> list[str]:
        """Group ids that ``user_id`` belongs to."""
        rows = self._connect().execute(
            "SELECT group_id FROM group_members WHERE user_id = ? ORDER BY group_id",
            (user_id,),
        ).fetchall()
        return [r["group_id"] for r in rows]

    # ── grants (D1 / D5) ────────────────────────────────────────

    def grant(
        self,
        principal_type: str,
        principal_id: str,
        wiki_id: str,
        *,
        read: bool = False,
        write: bool = False,
        granted_by: str | None = None,
    ) -> None:
        """Upsert one grant row (additive only — no deny rows, D5).

        ``wiki_id`` may be ``'*'`` (Q3-a). ``write`` implies ``read``.
        """
        self._validate_principal(principal_type, principal_id)
        if not wiki_id:
            raise AuthError(
                code="invalid_wiki",
                detail="wiki_id must not be empty (use '*' for all wikis)",
                status_code=400,
            )
        can_read = 1 if (read or write) else 0
        can_write = 1 if write else 0
        self._mgr.execute_write(
            """
            INSERT INTO wiki_grants
                (principal_type, principal_id, wiki_id, can_read, can_write, granted_by)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(principal_type, principal_id, wiki_id) DO UPDATE SET
                can_read  = excluded.can_read,
                can_write = excluded.can_write,
                granted_by = excluded.granted_by
            """,
            (principal_type, principal_id, wiki_id, can_read, can_write, granted_by),
        )

    def revoke(self, principal_type: str, principal_id: str, wiki_id: str) -> bool:
        """Delete one grant row. Returns True if a row was removed.

        Revocation is immediate (D6 = A): the next request re-reads this table.
        """
        self._validate_principal(principal_type, principal_id)
        cursor = self._mgr.execute_write(
            """
            DELETE FROM wiki_grants
            WHERE principal_type = ? AND principal_id = ? AND wiki_id = ?
            """,
            (principal_type, principal_id, wiki_id),
        )
        return cursor.rowcount > 0

    def list_grants(
        self,
        *,
        principal_type: str | None = None,
        principal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Grant rows, optionally filtered. Newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if principal_type is not None:
            clauses.append("principal_type = ?")
            params.append(principal_type)
        if principal_id is not None:
            clauses.append("principal_id = ?")
            params.append(principal_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connect().execute(
            f"""
            SELECT principal_type, principal_id, wiki_id,
                   can_read, can_write, granted_by, created_at
            FROM wiki_grants
            {where}
            ORDER BY created_at DESC, principal_type, principal_id, wiki_id
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ── resolution (D7 / Q3) ────────────────────────────────────

    @staticmethod
    def _principal_clause(user_id: str | None) -> tuple[str, dict[str, Any]]:
        """SQL fragment matching user + its groups + public (additive union).

        ``user_id=None`` means unauthenticated — only the ``public`` row
        applies (D9).
        """
        if user_id:
            clause = """
                (principal_type = 'public'
                 OR (principal_type = 'user' AND principal_id = :uid)
                 OR (principal_type = 'group' AND principal_id IN (
                     SELECT group_id FROM group_members WHERE user_id = :uid)))
                """
            return clause, {"uid": user_id}
        return "principal_type = 'public'", {}

    def effective(
        self, user_id: str | None, wiki_id: str
    ) -> tuple[bool, bool]:
        """``(can_read, can_write)`` for one wiki, evaluating the wildcard.

        This is the **live upper bound** (D7): it reflects the current
        ``wiki_grants`` rows, so a revoke or a disable takes effect on the
        very next request (D6 = A). ``wiki_id='*'`` rows apply to every
        wiki, including ones created later (Q3-c).
        """
        clause, extra = self._principal_clause(user_id)
        params: dict[str, Any] = {"wid": wiki_id, **extra}
        row = self._connect().execute(
            f"""
            SELECT MAX(can_read) AS r, MAX(can_write) AS w
            FROM wiki_grants
            WHERE (wiki_id = :wid OR wiki_id = '{WILDCARD}')
              AND {clause}
            """,
            params,
        ).fetchone()
        if row is None or row["r"] is None:
            return (False, False)
        return (bool(row["r"]), bool(row["w"]))

    def expand(
        self, user_id: str | None, wiki_ids: Iterable[str]
    ) -> dict[str, tuple[bool, bool]]:
        """Resolve a concrete wiki list for a token snapshot (Q3-b).

        Returns ``{wiki_id: (can_read, can_write)}`` for each id in
        ``wiki_ids``. ``'*'`` rows are expanded into every requested id —
        the snapshot therefore never contains the literal ``'*'``, so a
        newly created wiki is **not** silently added to an existing token
        (accessing it requires re-signing via ``auth token``).
        """
        ids = list(dict.fromkeys(w for w in wiki_ids if w))
        if not ids:
            return {}
        clause, extra = self._principal_clause(user_id)
        placeholders = ", ".join(f":w{i}" for i in range(len(ids)))
        params: dict[str, Any] = {**extra, **{f"w{i}": w for i, w in enumerate(ids)}}
        rows = self._connect().execute(
            f"""
            SELECT wiki_id, MAX(can_read) AS r, MAX(can_write) AS w
            FROM wiki_grants
            WHERE (wiki_id = '{WILDCARD}' OR wiki_id IN ({placeholders}))
              AND {clause}
            GROUP BY wiki_id
            """,
            params,
        ).fetchall()
        by_wiki = {r["wiki_id"]: (bool(r["r"]), bool(r["w"])) for r in rows}
        wildcard = by_wiki.get(WILDCARD, (False, False))
        out: dict[str, tuple[bool, bool]] = {}
        for wid in ids:
            r, w = by_wiki.get(wid, (False, False))
            # Additive union with the wildcard row (PG R2: sum of privileges).
            out[wid] = (r or wildcard[0], w or wildcard[1])
        return out


def snapshot_for_user(
    user_id: str,
    known_wikis: Iterable[str],
    *,
    is_admin: bool,
    db_path: Path | str | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """Build a token snapshot from the live grants (P3 / Q3-b).

    Returns ``(wikis, wgrants, scope)``:

    * **admin** → ``(["*"], {}, "write")`` — unchanged from pre-P3
      behaviour (G5). The middleware short-circuits on ``is_first_admin``
      (PG owner, design §5.2 step 5), and the ``*`` keeps registry/search
      filters able to see wikis created after signing.
    * **non-admin** → concrete expanded lists; ``scope`` is the global
      ceiling = ``"write"`` iff any per-wiki grant is ``"rw"`` (P3
      clarification: the old "non-admin is always read-only" was the D8
      no-grant *status quo*, not a rule — D4 allows per-wiki write).
    """
    if is_admin:
        return [WILDCARD], {}, "write"
    repo = GrantRepository(db_path=db_path)
    expanded = repo.expand(user_id, known_wikis)
    wikis: list[str] = []
    wgrants: dict[str, str] = {}
    for wid, (r, w) in expanded.items():
        if not r:
            continue
        wikis.append(wid)
        wgrants[wid] = "rw" if w else "r"
    scope = "write" if any(v == "rw" for v in wgrants.values()) else "read"
    return wikis, wgrants, scope


__all__ = [
    "GrantRepository",
    "PRINCIPAL_TYPES",
    "WILDCARD",
    "snapshot_for_user",
]
