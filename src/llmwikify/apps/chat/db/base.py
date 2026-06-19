"""Shared helpers for ChatDatabase's 7 repositories.

Each repository owns one table (or a small set of related tables).
They all share the same physical SQLite file at
``data_dir/.llmwiki_agent.db`` but each manages its own schema.

This module provides:
  - ``ChatDBBase``: tiny base class with shared connection helper.
    Subclasses override ``_init_schema()`` to create their tables.
  - ``DB_SIZE_WARNING_MB`` re-exported from apps.db_base.

Why a separate base (not BaseDatabase)?
  - BaseDatabase couples __init__ → _init_db → _check_db_size
    which doesn't match the repository pattern (each repo only
    initializes its own tables, not the whole DB).
  - Repositories need fine-grained control over when their
    schema runs (e.g. ChatDatabase.__init__ runs each repo's
    _init_schema in sequence).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from llmwikify.apps.db_base import DB_SIZE_WARNING_MB  # re-export

logger = logging.getLogger(__name__)


def get_chat_db_path(data_dir: Path | str) -> Path:
    """Return the canonical ``.llmwiki_agent.db`` path.

    Re-exported for backward compat (was in apps/chat/db.py).
    Delegates to ``apps.db_base.get_app_db_path``.
    """
    from llmwikify.apps.db_base import get_app_db_path
    return get_app_db_path(data_dir)


class ChatDBBase:
    """Tiny base for ChatDatabase's 7 repositories.

    Each repository manages one table (or a small set). The repo:
      - Holds a reference to ``db_path`` (the shared SQLite file).
      - Provides ``_connect()`` for opening a sqlite3 connection
        with ``row_factory=sqlite3.Row`` and ``foreign_keys=ON``.
      - Declares ``_init_schema()`` to create its own tables
        (called by ChatDatabase.__init__, idempotent via
        ``CREATE TABLE IF NOT EXISTS``).

    Repositories do NOT inherit from BaseDatabase because they
    don't need the full DB lifecycle (data_dir creation,
    db_size check, etc.) — those are owned by ChatDatabase.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with row_factory + foreign_keys."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        """Create this repository's tables.

        Subclasses MUST override. Use ``CREATE TABLE IF NOT EXISTS``
        for idempotency (called once per repo, but other facades
        may have created the same tables).
        """
        raise NotImplementedError(
            f"{type(self).__name__}._init_schema() must be implemented"
        )


__all__ = ["DB_SIZE_WARNING_MB", "get_chat_db_path", "ChatDBBase"]
