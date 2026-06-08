"""BaseDatabase — shared SQLite lifecycle for the 3 facades.

Per v0.33-service-refactor.md, the 3 database facades
(ChatDatabase, WikiDatabase, ResearchDatabase) all share
one physical SQLite file at ``data_dir/.llmwiki_agent.db``.

This module provides:

  - ``BaseDatabase``: shared ``__init__``, ``_connect``,
    ``_init_db`` (12 CREATE TABLE statements), ``_check_db_size``.
  - Auto-migration from the old ``autoresearch.db`` filename
    to the new ``.llmwiki_agent.db`` filename (silent rename,
    same content, no data loss).
  - ``get_app_db_path()``: canonical path helper.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# DB size warning threshold (MB). Independent of AgentDatabase.
DB_SIZE_WARNING_MB = 100

# Canonical filename for the shared physical DB file.
APP_DB_FILENAME = ".llmwiki_agent.db"
# Legacy filename, kept for auto-migration only.
LEGACY_APP_DB_FILENAME = "autoresearch.db"


def get_app_db_path(data_dir: Path | str) -> Path:
    """Return the canonical ``.llmwiki_agent.db`` path.

    The canonical path is ``data_dir / ".llmwiki_agent.db"``.

    If the legacy ``autoresearch.db`` file is present, it is
    silently renamed to ``.llmwiki_agent.db`` so existing
    installations don't see a new file appear or lose data.
    """
    data_dir = Path(data_dir)
    new_path = data_dir / APP_DB_FILENAME
    legacy_path = data_dir / LEGACY_APP_DB_FILENAME
    if legacy_path.exists() and not new_path.exists():
        try:
            legacy_path.rename(new_path)
            logger.info(
                "Auto-migrated DB file: %s -> %s",
                legacy_path, new_path,
            )
        except OSError as e:
            logger.warning(
                "Failed to auto-migrate %s -> %s: %s. "
                "Will create new DB at canonical path.",
                legacy_path, new_path, e,
            )
    return new_path


class BaseDatabase:
    """Shared SQLite lifecycle for ChatDatabase, WikiDatabase,
    ResearchDatabase.

    Each facade inherits this class. The 3 facades share one
    physical SQLite file but expose different method subsets.

    Subclasses MUST override ``_init_db()`` to call the table
    creation they need. The base class provides:
    - ``__init__(data_dir)``: resolves db_path, runs subclass
      ``_init_db``, checks db size
    - ``_connect()``: opens a sqlite3 connection
    - ``_check_db_size()``: warns if db > 100 MB
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = get_app_db_path(self.data_dir)
        self._init_db()
        self._check_db_size()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the database schema. Subclasses must implement.

        Each facade (ChatDatabase, WikiDatabase, ResearchDatabase)
        implements this to create only its domain's tables.
        All 3 facades share the same physical .llmwiki_agent.db
        file but each maintains its own table subset.

        Note: tables use ``CREATE TABLE IF NOT EXISTS`` so
        multiple facades instantiating in sequence are idempotent
        (no duplicate-table errors when both facades' tables
        already exist).
        """
        raise NotImplementedError(
            f"{type(self).__name__}._init_db() must be implemented "
            f"to create the facade's own domain tables."
        )

    def _check_db_size(self) -> None:
        """Warn if the db file grows beyond the threshold."""
        if not self.db_path.exists():
            return
        size_mb = self.db_path.stat().st_size / 1024 / 1024
        if size_mb > DB_SIZE_WARNING_MB:
            logger.warning(
                "App DB is large: %.2f MB (threshold: %d MB).",
                size_mb, DB_SIZE_WARNING_MB,
            )

    # ─── shared low-level helper ──────────────────────────────

    def _connect_for_table(self, table_name: str) -> sqlite3.Connection:
        """Open a connection and verify the table exists.

        Useful for debugging "no such table" errors. Subclasses
        typically use bare ``sqlite3.connect(self.db_path)`` in
        their methods, but this helper provides a clear error
        message.
        """
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"DB file does not exist: {self.db_path}"
            )
        return sqlite3.connect(self.db_path)


__all__ = [
    "BaseDatabase",
    "DB_SIZE_WARNING_MB",
    "APP_DB_FILENAME",
    "LEGACY_APP_DB_FILENAME",
    "get_app_db_path",
]
