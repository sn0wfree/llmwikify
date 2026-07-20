"""Shared SQLite connection factory (L1: foundation).

Provides a single place for SQLite connection setup, eliminating
the 5 divergent _connect() implementations across the codebase.

Usage::

    from llmwikify.foundation.db import connect, rows_to_dicts, row_to_dict

    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM items").fetchall()
    items = rows_to_dicts(rows)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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


__all__ = [
    "connect",
    "rows_to_dicts",
    "row_to_dict",
]
