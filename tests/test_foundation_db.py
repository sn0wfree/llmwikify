"""Tests for foundation.db — shared SQLite connection factory."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from llmwikify.foundation.db import connect, row_to_dict, rows_to_dicts


class TestConnect:
    """Tests for connect() function."""

    def test_default_connection(self, tmp_path: Path) -> None:
        """Default connection has row_factory and foreign_keys."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path)
        try:
            assert conn.row_factory == sqlite3.Row
            # Verify foreign_keys is ON
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_no_row_factory(self, tmp_path: Path) -> None:
        """Can disable row_factory."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path, row_factory=False)
        try:
            assert conn.row_factory is None
        finally:
            conn.close()

    def test_no_foreign_keys(self, tmp_path: Path) -> None:
        """Can disable foreign_keys."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path, foreign_keys=False)
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 0
        finally:
            conn.close()

    def test_wal_mode(self, tmp_path: Path) -> None:
        """Can enable WAL journal mode."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path, wal=True)
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"
        finally:
            conn.close()

    def test_busy_timeout(self, tmp_path: Path) -> None:
        """Can set busy_timeout."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path, busy_timeout=5000)
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()

    def test_synchronous(self, tmp_path: Path) -> None:
        """Can set synchronous mode."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path, synchronous="NORMAL")
        try:
            row = conn.execute("PRAGMA synchronous").fetchone()
            # NORMAL = 1
            assert row[0] == 1
        finally:
            conn.close()

    def test_creates_file(self, tmp_path: Path) -> None:
        """connect() creates the database file."""
        db_path = tmp_path / "new.db"
        assert not db_path.exists()
        conn = connect(db_path)
        conn.close()
        assert db_path.exists()


class TestRowsToDicts:
    """Tests for rows_to_dicts() function."""

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert rows_to_dicts([]) == []

    def test_single_row(self, tmp_path: Path) -> None:
        """Single row converts to dict."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'Alice')")
        conn.commit()
        rows = conn.execute("SELECT * FROM t").fetchall()
        result = rows_to_dicts(rows)
        assert len(result) == 1
        assert result[0] == {"id": 1, "name": "Alice"}
        conn.close()

    def test_multiple_rows(self, tmp_path: Path) -> None:
        """Multiple rows convert to list of dicts."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'Alice')")
        conn.execute("INSERT INTO t VALUES (2, 'Bob')")
        conn.commit()
        rows = conn.execute("SELECT * FROM t ORDER BY id").fetchall()
        result = rows_to_dicts(rows)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Alice"}
        assert result[1] == {"id": 2, "name": "Bob"}
        conn.close()


class TestRowToDict:
    """Tests for row_to_dict() function."""

    def test_none(self) -> None:
        """None returns None."""
        assert row_to_dict(None) is None

    def test_single_row(self, tmp_path: Path) -> None:
        """Single row converts to dict."""
        db_path = tmp_path / "test.db"
        conn = connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'Alice')")
        conn.commit()
        row = conn.execute("SELECT * FROM t").fetchone()
        result = row_to_dict(row)
        assert result == {"id": 1, "name": "Alice"}
        conn.close()
