"""Shared SQLite connection factory (L1: foundation).

Provides a single place for SQLite connection setup, eliminating
the 5 divergent _connect() implementations across the codebase.

Usage::

    from llmwikify.foundation.db import connect, rows_to_dicts, row_to_dict

    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM items").fetchall()
    items = rows_to_dicts(rows)

    # Or use ManagedConnection for thread-local persistent connections:
    from llmwikify.foundation.db import get_connection

    mc = get_connection(db_path)
    with mc.transaction() as conn:
        conn.execute("INSERT ...")
    row = mc.select_one("SELECT * FROM ...", (id,))
"""
from __future__ import annotations

import atexit
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# ─── 工厂函数 (保持向后兼容) ─────────────────────────────────

def connect(
    db_path: Path | str,
    *,
    row_factory: bool = True,
    foreign_keys: bool = True,
    wal: bool = False,
    busy_timeout: int | None = None,
    synchronous: str | None = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with project-standard pragmas.

    Args:
        db_path: Path to SQLite database file.
        row_factory: Set row_factory=sqlite3.Row (default True).
        foreign_keys: Enable PRAGMA foreign_keys (default True).
        wal: Enable WAL journal mode (default False).
        busy_timeout: Set busy_timeout in ms (default None = no change).
        synchronous: Set synchronous mode (default None = no change).

    Returns:
        Configured sqlite3.Connection.
    """
    conn = sqlite3.connect(db_path)
    if row_factory:
        conn.row_factory = sqlite3.Row
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    if busy_timeout is not None:
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout}")
    if synchronous is not None:
        conn.execute(f"PRAGMA synchronous = {synchronous}")
    return conn


# ─── 行转换辅助 ─────────────────────────────────────────────

def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert sqlite3.Row list to list of dicts.

    Args:
        rows: List of sqlite3.Row objects.

    Returns:
        List of dicts with column names as keys.
    """
    return [dict(r) for r in rows]


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert single sqlite3.Row to dict, or None.

    Args:
        row: sqlite3.Row object or None.

    Returns:
        Dict with column names as keys, or None if row is None.
    """
    return dict(row) if row is not None else None


# ─── ManagedConnection (Thread-local 持久连接) ──────────────

class ManagedConnection:
    """Thread-local persistent SQLite connection with transaction support.

    Each thread gets its own connection (SQLite threadsafety=1).
    Connections are lazily initialized on first access.

    Usage::

        mc = ManagedConnection(db_path)
        with mc.transaction() as conn:
            conn.execute("INSERT ...")
        row = mc.select_one("SELECT * FROM ...", (id,))
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        row_factory: bool = True,
        foreign_keys: bool = True,
        wal: bool = True,
        busy_timeout: int = 5000,
        synchronous: str = "NORMAL",
    ):
        self._db_path = str(db_path)
        self._pragmas = {
            "row_factory": row_factory,
            "foreign_keys": foreign_keys,
            "wal": wal,
            "busy_timeout": busy_timeout,
            "synchronous": synchronous,
        }
        self._local = threading.local()

    @property
    def db_path(self) -> str:
        """Database file path."""
        return self._db_path

    @property
    def conn(self) -> sqlite3.Connection:
        """Thread-local lazy-init connection."""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = connect(self._db_path, **self._pragmas)
            self._local.conn = c
        return c

    @contextmanager
    def transaction(self) -> None:
        """Transaction context manager (auto-commit/rollback).

        Usage::

            with mc.transaction() as conn:
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
            # auto-commits on exit, rolls back on exception
        """
        conn = self.conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ─── CRUD 辅助 ──────────────────────────────────────────

    def select_one(self, sql: str, params: tuple = ()) -> dict | None:
        """SELECT single row -> dict or None.

        Args:
            sql: SELECT SQL statement.
            params: Query parameters.

        Returns:
            Dict with column names as keys, or None if no row.
        """
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def select_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """SELECT multiple rows -> list[dict].

        Args:
            sql: SELECT SQL statement.
            params: Query parameters.

        Returns:
            List of dicts with column names as keys.
        """
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute write SQL with auto-commit.

        Args:
            sql: INSERT/UPDATE/DELETE SQL statement.
            params: Query parameters.

        Returns:
            sqlite3.Cursor after execution.
        """
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def execute_many(self, sql: str, params_seq: list[tuple]) -> None:
        """Execute write SQL for multiple parameter sets (auto-commit).

        Args:
            sql: INSERT/UPDATE/DELETE SQL statement.
            params_seq: List of parameter tuples.
        """
        self.conn.executemany(sql, params_seq)
        self.conn.commit()

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in the database.

        Args:
            table_name: Name of the table to check.

        Returns:
            True if table exists, False otherwise.
        """
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def add_column_if_missing(
        self,
        table: str,
        column: str,
        col_type: str,
        default: str | None = None,
    ) -> bool:
        """Add column to table if it doesn't exist (safe ALTER TABLE).

        Args:
            table: Table name.
            column: Column name.
            col_type: Column type (e.g. 'INTEGER', 'TEXT').
            default: Optional DEFAULT value.

        Returns:
            True if column was added, False if it already exists.
        """
        try:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            if default is not None:
                sql += f" DEFAULT {default}"
            self.conn.execute(sql)
            return True
        except sqlite3.OperationalError:
            return False

    def close(self) -> None:
        """Close current thread's connection."""
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None


# ─── 模块级单例注册表 ────────────────────────────────────────

_connections: dict[str, ManagedConnection] = {}
_connections_lock = threading.Lock()


def get_connection(
    db_path: Path | str,
    **kwargs: Any,
) -> ManagedConnection:
    """Get or create per-path singleton ManagedConnection.

    Same db_path always returns the same instance.

    Args:
        db_path: Path to SQLite database file.
        **kwargs: Passed to ManagedConnection constructor.

    Returns:
        ManagedConnection singleton for the given path.
    """
    key = str(db_path)
    if key not in _connections:
        with _connections_lock:
            if key not in _connections:
                _connections[key] = ManagedConnection(key, **kwargs)
    return _connections[key]


def close_all() -> None:
    """Close all singleton connections (for atexit cleanup)."""
    for mc in _connections.values():
        mc.close()
    _connections.clear()


atexit.register(close_all)


__all__ = [
    "connect",
    "rows_to_dicts",
    "row_to_dict",
    "ManagedConnection",
    "get_connection",
    "close_all",
]
