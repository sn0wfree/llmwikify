"""Regression tests for the connection-lifecycle work in ``foundation/db.py``.

Two facts drive the design:

1. ``close_all()`` is deliberately **thread-scoped** — closing a connection
   another thread is actively using would break its in-flight work.
2. sqlite3 refuses to close a connection from a foreign thread
   ("SQLite objects created in a thread can only be used in that same
   thread"), so a cross-thread teardown needs ``check_same_thread=False``.

Without (2), ``ManagedConnection.close_all_threads()`` would be a no-op that
silently swallowed the ``ProgrammingError`` — the file stays locked on
Windows and temp-dir cleanup fails with ``WinError 32``.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from llmwikify.foundation.db import (
    PROFILE_DEFAULT,
    ManagedConnection,
    close_all,
    get_connection,
)


def _touch_in_worker(mc: ManagedConnection) -> None:
    """Open a connection on a worker thread (thread-local -> own handle)."""
    mc.conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    mc.conn.commit()


def test_close_all_releases_file_lock(tmp_path: Path) -> None:
    """close_all() must release the file handle (Windows WinError 32 guard)."""
    db = tmp_path / "locked.db"
    mc = get_connection(db, profile=PROFILE_DEFAULT)
    mc.conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    mc.conn.commit()
    close_all()
    # Must be removable now — this is what used to fail on Windows.
    db.unlink()
    assert not db.exists()


def test_close_all_is_thread_scoped(tmp_path: Path) -> None:
    """close_all() must NOT close a connection another thread still holds.

    Closing it from the wrong thread would break that thread's in-flight
    work — so close_all() stays deliberately thread-scoped.
    """
    db = tmp_path / "worker.db"
    mc = get_connection(db, profile=PROFILE_DEFAULT)
    t = threading.Thread(target=_touch_in_worker, args=(mc,))
    t.start()
    t.join(timeout=30)
    assert not t.is_alive()

    close_all()  # thread-scoped: the worker's handle survives

    # The worker's handle is still open -> the file is still locked.
    mc.close_all_threads()
    db.unlink()
    assert not db.exists()


def test_close_all_threads_releases_worker_handle(tmp_path: Path) -> None:
    """close_all_threads() must release a handle owned by another thread."""
    db = tmp_path / "worker.db"
    mc = get_connection(db, profile=PROFILE_DEFAULT)
    t = threading.Thread(target=_touch_in_worker, args=(mc,))
    t.start()
    t.join(timeout=30)
    assert not t.is_alive()

    mc.close_all_threads()

    # If the worker's handle were still open, unlink would fail on Windows.
    db.unlink()
    assert not db.exists()


def test_sqlite_row_factory_preserved(tmp_path: Path) -> None:
    """The profile must not change row_factory behaviour."""
    mc = get_connection(tmp_path / "rows.db", profile=PROFILE_DEFAULT)
    mc.conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    mc.conn.execute("INSERT INTO t VALUES (7)")
    row = mc.conn.execute("SELECT x FROM t").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["x"] == 7
