"""ReproductionDatabase — session/artifact tracking for paper reproduction.

Independent SQLite file at ``~/.llmwikify/reproduction.db`` to avoid
polluting the main ``.llmwiki_agent.db`` used by chat/research/wiki
facades.

Schema:
    reproduction_sessions  — one row per "reproduce this paper" run
    reproduction_artifacts — wiki pages generated during a session
    reproduction_events    — append-only event log for debugging

Status state machine:
    pending -> extracting -> backtesting -> done
                                 \\-> error (terminal)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".llmwikify" / "agent" / "reproduction.db"

VALID_STATUSES = {
    "pending",
    "extracting",
    "backtesting",
    "analyzing",
    "done",
    "error",
}

TERMINAL_STATUSES = {"done", "error"}


@dataclass
class Session:
    id: str
    wiki_id: str
    paper_id: str
    source_type: str
    source_ref: str
    symbol: str
    start_date: str
    end_date: str
    status: str = "pending"
    error: Optional[str] = None
    strategy_signal_type: str = ""
    strategy_params_json: str = "{}"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Artifact:
    id: str
    session_id: str
    kind: str
    wiki_page: str
    meta_json: str = "{}"
    created_at: str = ""


class ReproductionDatabase:
    """SQLite-backed session store. Independent file from main app DB."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reproduction_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    strategy_signal_type TEXT DEFAULT '',
                    strategy_params_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_repro_sessions_status
                    ON reproduction_sessions(status);
                CREATE INDEX IF NOT EXISTS idx_repro_sessions_paper
                    ON reproduction_sessions(paper_id);

                CREATE TABLE IF NOT EXISTS reproduction_artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    wiki_page TEXT NOT NULL,
                    meta_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_repro_artifacts_session
                    ON reproduction_artifacts(session_id);

                CREATE TABLE IF NOT EXISTS reproduction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_repro_events_session
                    ON reproduction_events(session_id, created_at DESC);
                """
            )

    def create_session(
        self,
        wiki_id: str,
        paper_id: str,
        source_type: str,
        source_ref: str,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> str:
        sid = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reproduction_sessions
                    (id, wiki_id, paper_id, source_type, source_ref,
                     symbol, start_date, end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, wiki_id, paper_id, source_type, source_ref,
                 symbol, start_date, end_date),
            )
        return sid

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reproduction_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return Session(**dict(row))

    def update_status(
        self,
        session_id: str,
        status: str,
        error: Optional[str] = None,
        signal_type: Optional[str] = None,
        signal_params: Optional[dict[str, Any]] = None,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        sets = ["status = ?", "updated_at = datetime('now')"]
        vals: list[Any] = [status]
        if error is not None:
            sets.append("error = ?")
            vals.append(error)
        if signal_type is not None:
            sets.append("strategy_signal_type = ?")
            vals.append(signal_type)
        if signal_params is not None:
            sets.append("strategy_params_json = ?")
            vals.append(json.dumps(signal_params, ensure_ascii=False))
        vals.append(session_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE reproduction_sessions SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    def record_event(self, session_id: str, event_type: str, **payload: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reproduction_events (session_id, event_type, payload_json)
                VALUES (?, ?, ?)
                """,
                (session_id, event_type, json.dumps(payload, ensure_ascii=False)),
            )

    def create_artifact(
        self,
        session_id: str,
        kind: str,
        wiki_page: str,
        **meta: Any,
    ) -> str:
        aid = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reproduction_artifacts
                    (id, session_id, kind, wiki_page, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (aid, session_id, kind, wiki_page, json.dumps(meta, ensure_ascii=False)),
            )
        return aid

    def get_artifacts(self, session_id: str) -> list[Artifact]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reproduction_artifacts
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [Artifact(**dict(r)) for r in rows]

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reproduction_events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_sessions(self, status: Optional[str] = None) -> list[Session]:
        sql = "SELECT * FROM reproduction_sessions"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Session(**dict(r)) for r in rows]


__all__ = [
    "ReproductionDatabase",
    "Session",
    "Artifact",
    "VALID_STATUSES",
    "TERMINAL_STATUSES",
    "DEFAULT_DB_PATH",
]