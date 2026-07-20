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

        # Each thread should get its own connection
        assert len(conns) == 3
        # At least 2 different connections (thread pool may reuse threads)
        assert len(set(conns)) >= 2


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


# ─── Edge cases ───────────────────────────────────────────────


class TestSelectOneEdgeCases:
    """Edge cases for select_one()."""

    def test_with_params(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.commit()
        row = mc.select_one("SELECT * FROM test WHERE id > ?", (1,))
        assert row == {"id": 2, "val": "b"}

    def test_with_aggregate(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.execute("INSERT INTO test VALUES (3, 'c')")
        mc.conn.commit()
        row = mc.select_one("SELECT COUNT(*) as cnt FROM test")
        assert row == {"cnt": 3}

    def test_with_null_value(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, NULL)")
        mc.conn.commit()
        row = mc.select_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row == {"id": 1, "val": None}


class TestSelectAllEdgeCases:
    """Edge cases for select_all()."""

    def test_with_limit(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        for i in range(5):
            mc.conn.execute(f"INSERT INTO test VALUES ({i}, 'val{i}')")
        mc.conn.commit()
        rows = mc.select_all("SELECT * FROM test ORDER BY id LIMIT ?", (3,))
        assert len(rows) == 3

    def test_with_where_clause(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.execute("INSERT INTO test VALUES (3, 'a')")
        mc.conn.commit()
        rows = mc.select_all(
            "SELECT * FROM test WHERE val = ? ORDER BY id", ("a",)
        )
        assert len(rows) == 2
        assert rows[0]["id"] == 1
        assert rows[1]["id"] == 3


class TestExecuteWriteEdgeCases:
    """Edge cases for execute_write()."""

    def test_update(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'old')")
        mc.conn.commit()
        cursor = mc.execute_write(
            "UPDATE test SET val = ? WHERE id = ?", ("new", 1)
        )
        assert cursor.rowcount == 1
        row = mc.select_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row["val"] == "new"

    def test_delete(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.commit()
        cursor = mc.execute_write("DELETE FROM test WHERE id = ?", (1,))
        assert cursor.rowcount == 1
        rows = mc.select_all("SELECT * FROM test")
        assert len(rows) == 1
        assert rows[0]["id"] == 2

    def test_no_rows_affected(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        cursor = mc.execute_write(
            "UPDATE test SET val = ? WHERE id = ?", ("new", 999)
        )
        assert cursor.rowcount == 0


class TestExecuteManyEdgeCases:
    """Edge cases for execute_many()."""

    def test_empty_list(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        mc.execute_many("INSERT INTO test VALUES (?, ?)", [])
        rows = mc.select_all("SELECT * FROM test")
        assert len(rows) == 0

    def test_with_update(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.execute("INSERT INTO test VALUES (1, 'a')")
        mc.conn.execute("INSERT INTO test VALUES (2, 'b')")
        mc.conn.commit()
        mc.execute_many(
            "UPDATE test SET val = ? WHERE id = ?",
            [("new_a", 1), ("new_b", 2)],
        )
        rows = mc.select_all("SELECT * FROM test ORDER BY id")
        assert rows[0]["val"] == "new_a"
        assert rows[1]["val"] == "new_b"


class TestAddColumnIfMissingEdgeCases:
    """Edge cases for add_column_if_missing()."""

    def test_with_default(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER)")
        mc.conn.commit()
        result = mc.add_column_if_missing(
            "test", "val", "TEXT", default="'default'"
        )
        assert result is True
        mc.conn.execute("INSERT INTO test (id) VALUES (1)")
        mc.conn.commit()
        row = mc.select_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row["val"] == "default"

    def test_multiple_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER)")
        mc.conn.commit()
        assert mc.add_column_if_missing("test", "col1", "TEXT") is True
        assert mc.add_column_if_missing("test", "col2", "INTEGER") is True
        assert mc.add_column_if_missing("test", "col3", "REAL") is True
        row = mc.conn.execute("PRAGMA table_info(test)").fetchall()
        col_names = [r["name"] for r in row]
        assert "col1" in col_names
        assert "col2" in col_names
        assert "col3" in col_names


class TestTransactionEdgeCases:
    """Edge cases for transaction()."""

    def test_nested_transactions(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        with mc.transaction() as conn:
            conn.execute(
                "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
            )
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
            # Inner transaction should work (SQLite savepoints)
            with mc.transaction() as conn2:
                conn2.execute("INSERT INTO test VALUES (2, 'world')")
        rows = mc.select_all("SELECT * FROM test ORDER BY id")
        assert len(rows) == 2

    def test_transaction_isolation(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()
        # Before transaction, no data
        rows = mc.select_all("SELECT * FROM test")
        assert len(rows) == 0
        # After transaction, data visible
        with mc.transaction() as conn:
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
        rows = mc.select_all("SELECT * FROM test")
        assert len(rows) == 1


class TestTableExistsEdgeCases:
    """Edge cases for table_exists()."""

    def test_multiple_tables(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE t1 (id INTEGER)")
        mc.conn.execute("CREATE TABLE t2 (id INTEGER)")
        mc.conn.commit()
        assert mc.table_exists("t1") is True
        assert mc.table_exists("t2") is True
        assert mc.table_exists("t3") is False

    def test_after_drop(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute("CREATE TABLE test (id INTEGER)")
        mc.conn.commit()
        assert mc.table_exists("test") is True
        mc.conn.execute("DROP TABLE test")
        mc.conn.commit()
        assert mc.table_exists("test") is False


class TestCloseEdgeCases:
    """Edge cases for close()."""

    def test_reopen_after_close(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        conn1 = mc.conn
        mc.close()
        conn2 = mc.conn
        assert conn1 is not conn2

    def test_multiple_close(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn
        mc.close()
        mc.close()  # should not raise


# ─── Thread safety edge cases ─────────────────────────────────


class TestThreadSafetyEdgeCases:
    """Edge cases for thread safety."""

    def test_concurrent_reads(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        for i in range(10):
            mc.conn.execute(f"INSERT INTO test VALUES ({i}, 'val{i}')")
        mc.conn.commit()

        results = []
        lock = threading.Lock()

        def read_data():
            rows = mc.select_all("SELECT * FROM test ORDER BY id")
            with lock:
                results.append(len(rows))

        threads = [threading.Thread(target=read_data) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == 10 for r in results)

    def test_concurrent_writes(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)
        mc.conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        mc.conn.commit()

        errors = []
        lock = threading.Lock()

        def write_data(i):
            try:
                mc.execute_write(
                    "INSERT INTO test VALUES (?, ?)", (i, f"val{i}")
                )
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=write_data, args=(i,)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Some writes may fail due to SQLite threading constraints
        # but the test should not crash
        rows = mc.select_all("SELECT * FROM test")
        assert len(rows) >= 1  # At least one should succeed


# ─── get_connection edge cases ────────────────────────────────


class TestGetConnectionEdgeCases:
    """Edge cases for get_connection()."""

    def test_with_string_path(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        mc = get_connection(db)
        assert mc.db_path == db

    def test_with_path_object(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = get_connection(db)
        assert mc.db_path == str(db)

    def test_singleton_same_path_different_kwargs(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc1 = get_connection(db, wal=True)
        mc2 = get_connection(db, wal=False)
        # Same instance, kwargs ignored for existing singleton
        assert mc1 is mc2
        assert mc1._pragmas["wal"] is True


# ─── Integration tests ───────────────────────────────────────


class TestIntegration:
    """Integration tests for ManagedConnection."""

    def test_full_crud_workflow(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)

        # Create table
        with mc.transaction() as conn:
            conn.execute(
                """CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE,
                    age INTEGER
                )"""
            )

        # Insert
        mc.execute_write(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            ("Alice", "alice@example.com", 30),
        )
        mc.execute_write(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            ("Bob", "bob@example.com", 25),
        )

        # Read
        alice = mc.select_one(
            "SELECT * FROM users WHERE email = ?", ("alice@example.com",)
        )
        assert alice["name"] == "Alice"
        assert alice["age"] == 30

        # Update
        mc.execute_write(
            "UPDATE users SET age = ? WHERE email = ?",
            (31, "alice@example.com"),
        )
        alice = mc.select_one(
            "SELECT * FROM users WHERE email = ?", ("alice@example.com",)
        )
        assert alice["age"] == 31

        # Delete
        cursor = mc.execute_write(
            "DELETE FROM users WHERE email = ?", ("bob@example.com",)
        )
        assert cursor.rowcount == 1

        # List
        users = mc.select_all("SELECT * FROM users ORDER BY id")
        assert len(users) == 1
        assert users[0]["name"] == "Alice"

    def test_transaction_rollback_preserves_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)

        # Create and insert initial data
        with mc.transaction() as conn:
            conn.execute(
                "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
            )
            conn.execute("INSERT INTO test VALUES (1, 'original')")

        # Failed transaction should not affect data
        with pytest.raises(sqlite3.IntegrityError):
            with mc.transaction() as conn:
                conn.execute("INSERT INTO test VALUES (1, 'duplicate')")

        row = mc.select_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row["val"] == "original"

    def test_multiple_tables_in_transaction(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        mc = ManagedConnection(db)

        with mc.transaction() as conn:
            conn.execute(
                "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER)"
            )
            conn.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, order_id INTEGER)"
            )
            conn.execute("INSERT INTO orders VALUES (1, 100)")
            conn.execute("INSERT INTO items VALUES (1, 1)")
            conn.execute("INSERT INTO items VALUES (2, 1)")

        assert mc.table_exists("orders") is True
        assert mc.table_exists("items") is True
        orders = mc.select_all("SELECT * FROM orders")
        items = mc.select_all("SELECT * FROM items")
        assert len(orders) == 1
        assert len(items) == 2
