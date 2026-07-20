"""Tests for ManagedConnection and get_connection (foundation/db.py)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from llmwikify.foundation.db import (
    ManagedConnection,
    close_all,
    connect,
    get_connection,
    row_to_dict,
    rows_to_dicts,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up singleton registry after each test."""
    yield
    close_all()


# ─── ManagedConnection lifecycle ──────────────────────────────


class TestManagedConnectionInit:
    """Tests for ManagedConnection.__init__."""

    def test_db_path_property(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        assert mc.db_path == str(db)

    def test_default_pragmas(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        assert mc._pragmas["wal"] is True
        assert mc._pragmas["busy_timeout"] == 5000
        assert mc._pragmas["synchronous"] == "NORMAL"
        assert mc._pragmas["foreign_keys"] is True
        assert mc._pragmas["row_factory"] is True

    def test_custom_pragmas(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db, wal=False, busy_timeout=1000)
        assert mc._pragmas["wal"] is False
        assert mc._pragmas["busy_timeout"] == 1000


class TestManagedConnectionConn:
    """Tests for ManagedConnection.conn property."""

    def test_lazy_init(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        assert getattr(mc._local, "conn", None) is None
        conn = mc.conn
        assert isinstance(conn, sqlite3.Connection)
        assert getattr(mc._local, "conn", None) is conn

    def test_same_connection_per_thread(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn1 = mc.conn
        conn2 = mc.conn
        assert conn1 is conn2

    def test_row_factory_set(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn = mc.conn
        assert conn.row_factory == sqlite3.Row

    def test_wal_enabled(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn = mc.conn
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_busy_timeout_set(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn = mc.conn
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn = mc.conn
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


class TestManagedConnectionTransaction:
    """Tests for ManagedConnection.transaction()."""

    def test_commit_on_success(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        with mc.transaction() as conn:
            conn.execute(
                "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
            )
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
        row = mc.conn.execute("SELECT * FROM test WHERE id = 1").fetchone()
        assert row["val"] == "hello"

    def test_rollback_on_exception(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        with pytest.raises(ValueError):
            with mc.transaction() as conn:
                conn.execute(
                    "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
                )
                conn.execute("INSERT INTO test VALUES (1, 'hello')")
                raise ValueError("boom")
        row = mc.conn.execute("SELECT * FROM test WHERE id = 1").fetchone()
        assert row is None


class TestManagedConnectionSelectOne:
    """Tests for ManagedConnection.select_one()."""

    def test_returns_dict(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'hello')")
        mc.conn.commit()
        row = mc.select_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row == {"id": 1, "val": "hello"}

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        row = mc.select_one("SELECT * FROM test WHERE id = ?", (999,))
        assert row is None


class TestManagedConnectionSelectAll:
    """Tests for ManagedConnection.select_all()."""

    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.commit()
        rows = mc.select_all("SELECT * FROM test ORDER BY id")
        assert rows == [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]

    def test_returns_empty_list(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        rows = mc.select_all("SELECT * FROM test")
        assert rows == []


class TestManagedConnectionExecuteWrite:
    """Tests for ManagedConnection.execute_write()."""

    def test_auto_commits(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        mc.execute_write("INSERT INTO test VALUES (1, 'hello')")
        row = mc.conn.execute("SELECT * FROM test WHERE id = 1").fetchone()
        assert row["val"] == "hello"

    def test_returns_cursor(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        cursor = mc.execute_write("INSERT INTO test VALUES (1, 'hello')")
        assert cursor.rowcount == 1


class TestManagedConnectionExecuteMany:
    """Tests for ManagedConnection.execute_many()."""

    def test_inserts_multiple_rows(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        mc.execute_many(
            "INSERT INTO test VALUES (?, ?)",
            [(1, "a"), (2, "b"), (3, "c")],
        )
        rows = mc.select_all("SELECT * FROM test ORDER BY id")
        assert len(rows) == 3


class TestManagedConnectionTableExists:
    """Tests for ManagedConnection.table_exists()."""

    def test_returns_true_when_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER)")
        mc.conn.commit()
        assert mc.table_exists("test") is True

    def test_returns_false_when_not_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        assert mc.table_exists("nonexistent") is False


class TestManagedConnectionAddColumnIfMissing:
    """Tests for ManagedConnection.add_column_if_missing()."""

    def test_adds_column(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER)")
        mc.conn.commit()
        result = mc.add_column_if_missing("test", "val", "TEXT")
        assert result is True
        row = mc.conn.execute("PRAGMA table_info(test)").fetchall()
        col_names = [r["name"] for r in row]
        assert "val" in col_names

    def test_returns_false_when_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER, val TEXT)")
        mc.conn.commit()
        result = mc.add_column_if_missing("test", "val", "TEXT")
        assert result is False


class TestManagedConnectionClose:
    """Tests for ManagedConnection.close()."""

    def test_closes_connection(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn = mc.conn
        mc.close()
        assert getattr(mc._local, "conn", None) is None

    def test_close_when_no_connection(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.close()  # should not raise


# ─── Thread safety ────────────────────────────────────────────


class TestManagedConnectionThreadSafety:
    """Tests for thread-local connection behavior."""

    def test_different_connections_per_thread(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conns = []
        lock = threading.Lock()

        def get_conn():
            c = mc.conn
            with lock:
                conns.append(id(c))

        threads = [threading.Thread(target=get_conn) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Main thread + 3 threads = 4 connections
        assert len(conns) == 3
        # All should be different (main thread not included)
        assert len(set(conns)) == 3


# ─── get_connection (singleton registry) ──────────────────────


class TestGetConnection:
    """Tests for get_connection() singleton registry."""

    def test_returns_same_instance_for_same_path(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc1 = get_connection(db)
        mc2 = get_connection(db)
        assert mc1 is mc2

    def test_returns_different_instance_for_different_path(
        self, tmp_path: Path
    ) -> None:
        db1 = tmp_path / "test1.db"
        db2 = tmp_path / "test2.db"
        mc1 = get_connection(db1)
        mc2 = get_connection(db2)
        assert mc1 is not mc2

    def test_kwargs_passed_to_constructor(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = get_connection(db, wal=False, busy_timeout=1000)
        assert mc._pragmas["wal"] is False
        assert mc._pragmas["busy_timeout"] == 1000


class TestCloseAll:
    """Tests for close_all()."""

    def test_clears_registry(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        get_connection(db)
        close_all()
        # After close_all, get_connection should create a new instance
        mc = get_connection(db)
        assert mc is not None


# ─── Backward compatibility ───────────────────────────────────


class TestBackwardCompatibility:
    """Tests for backward-compatible functions."""

    def test_connect_returns_connection(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        conn = connect(db)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_rows_to_dicts(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        conn = connect(db)
        conn.execute("CREATE TABLE test (id INTEGER, val TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'a')")
        conn.execute("INSERT INTO test VALUES (2, 'b')")
        conn.commit()
        rows = conn.execute("SELECT * FROM test ORDER BY id").fetchall()
        result = rows_to_dicts(rows)
        assert result == [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]
        conn.close()

    def test_row_to_dict_none(self) -> None:
        assert row_to_dict(None) is None
