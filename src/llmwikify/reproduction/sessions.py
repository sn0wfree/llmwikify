"""ReproductionDatabase — session/artifact tracking for paper reproduction.

Independent SQLite file at ``~/.llmwikify/reproduction.db`` to avoid
polluting the main ``.llmwiki_agent.db`` used by chat/research/wiki
facades.

Schema:
    reproduction_sessions  — one row per "reproduce this paper" run
    reproduction_artifacts — wiki pages generated during a session
    reproduction_events    — append-only event log for debugging
    reproduction_results   — backtest results (factor/strategy)

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

from .config import config

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    """Get default DB path from config."""
    return Path(config.get("db.path", "~/.llmwikify/agent/reproduction.db")).expanduser()


DEFAULT_DB_PATH = _get_default_db_path()

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


@dataclass
class Result:
    """Backtest result record."""
    run_id: str
    session_id: str | None = None
    type: str = "factor_backtest"  # factor_backtest | strategy_backtest | reproduction
    factor_ref: str | None = None
    strategy_ref: str | None = None
    universe: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    created_at: str = ""
    status: str = "success"  # success | error
    error: str | None = None

    # factor_backtest fields
    ic_mean: float | None = None
    rank_ic_mean: float | None = None
    icir: float | None = None
    rank_icir: float | None = None
    win_rate: float | None = None
    annual_return: float | None = None
    longshort_ann_return: float | None = None
    longshort_sharpe: float | None = None
    longshort_max_dd: float | None = None
    n_stocks_per_date: str | None = None  # JSON string
    ic_series: str | None = None  # JSON string
    group_metrics: str | None = None  # JSON string

    # strategy_backtest fields
    equity_curve: str | None = None  # JSON string
    monthly_returns: str | None = None  # JSON string
    total_return: float | None = None
    final_cash: float | None = None
    total_trades: int | None = None

    # reproduction fields
    paper_ref: str | None = None
    factor_run_id: str | None = None
    strategy_run_id: str | None = None

    # common fields
    wiki_path: str | None = None
    adj_mode: str | None = None
    hedge: str | None = None
    data_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with JSON parsing for complex fields."""
        d = asdict(self)
        # Parse JSON fields
        for field in ("n_stocks_per_date", "ic_series", "group_metrics", "equity_curve", "monthly_returns"):
            val = d.get(field)
            if val and isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return d


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

                CREATE TABLE IF NOT EXISTS reproduction_results (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    type TEXT CHECK(type IN ('factor_backtest','strategy_backtest','reproduction')),
                    factor_ref TEXT,
                    strategy_ref TEXT,
                    universe TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    status TEXT CHECK(status IN ('success','error')),
                    error TEXT,

                    -- factor_backtest fields
                    ic_mean REAL,
                    rank_ic_mean REAL,
                    icir REAL,
                    rank_icir REAL,
                    win_rate REAL,
                    annual_return REAL,
                    longshort_ann_return REAL,
                    longshort_sharpe REAL,
                    longshort_max_dd REAL,
                    n_stocks_per_date TEXT,
                    ic_series TEXT,
                    group_metrics TEXT,

                    -- strategy_backtest fields
                    equity_curve TEXT,
                    monthly_returns TEXT,
                    total_return REAL,
                    final_cash REAL,
                    total_trades INTEGER,

                    -- reproduction fields
                    paper_ref TEXT,
                    factor_run_id TEXT,
                    strategy_run_id TEXT,

                    -- common fields
                    wiki_path TEXT,
                    adj_mode TEXT,
                    hedge TEXT,
                    data_source TEXT,

                    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_repro_results_factor_ref
                    ON reproduction_results(factor_ref);
                CREATE INDEX IF NOT EXISTS idx_repro_results_strategy_ref
                    ON reproduction_results(strategy_ref);
                CREATE INDEX IF NOT EXISTS idx_repro_results_session_id
                    ON reproduction_results(session_id);
                CREATE INDEX IF NOT EXISTS idx_repro_results_created_at
                    ON reproduction_results(created_at DESC);
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
        result = []
        for r in rows:
            d = dict(r)
            # Keep payload_json for frontend JSON.parse() compatibility
            # Also add parsed payload dict for direct access
            raw = d.get("payload_json")
            try:
                d["payload"] = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            result.append(d)
        return result

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

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and cascade to events/artifacts (FK ON)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM reproduction_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM reproduction_artifacts WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM reproduction_results WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM reproduction_sessions WHERE id = ?", (session_id,))
            return conn.total_changes > 0

    # ─── Result CRUD ──────────────────────────────────────────

    def create_result(
        self,
        run_id: str,
        result_type: str = "factor_backtest",
        session_id: str | None = None,
        factor_ref: str | None = None,
        strategy_ref: str | None = None,
        universe: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str = "success",
        error: str | None = None,
        wiki_path: str | None = None,
        adj_mode: str | None = None,
        hedge: str | None = None,
        data_source: str | None = None,
        **metrics: Any,
    ) -> str:
        """Create a backtest result record."""
        # Serialize JSON fields
        json_fields = {}
        for field in ("n_stocks_per_date", "ic_series", "group_metrics", "equity_curve", "monthly_returns"):
            if field in metrics:
                val = metrics.pop(field)
                if isinstance(val, (list, dict)):
                    json_fields[field] = json.dumps(val, ensure_ascii=False)
                else:
                    json_fields[field] = val

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reproduction_results
                    (run_id, session_id, type, factor_ref, strategy_ref,
                     universe, start_date, end_date, status, error,
                     wiki_path, adj_mode, hedge, data_source,
                     ic_mean, rank_ic_mean, icir, rank_icir, win_rate,
                     annual_return, longshort_ann_return, longshort_sharpe, longshort_max_dd,
                     n_stocks_per_date, ic_series, group_metrics,
                     equity_curve, monthly_returns, total_return, final_cash, total_trades,
                     paper_ref, factor_run_id, strategy_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?)
                """,
                (
                    run_id, session_id, result_type, factor_ref, strategy_ref,
                    universe, start_date, end_date, status, error,
                    wiki_path, adj_mode, hedge, data_source,
                    metrics.get("ic_mean"), metrics.get("rank_ic_mean"),
                    metrics.get("icir"), metrics.get("rank_icir"), metrics.get("win_rate"),
                    metrics.get("annual_return"), metrics.get("longshort_ann_return"),
                    metrics.get("longshort_sharpe"), metrics.get("longshort_max_dd"),
                    json_fields.get("n_stocks_per_date"), json_fields.get("ic_series"),
                    json_fields.get("group_metrics"),
                    json_fields.get("equity_curve"), json_fields.get("monthly_returns"),
                    metrics.get("total_return"), metrics.get("final_cash"), metrics.get("total_trades"),
                    metrics.get("paper_ref"), metrics.get("factor_run_id"), metrics.get("strategy_run_id"),
                ),
            )
        return run_id

    def get_result(self, run_id: str) -> Optional[Result]:
        """Get a result by run_id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reproduction_results WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return Result(**dict(row))

    def list_results(
        self,
        factor_ref: str | None = None,
        strategy_ref: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[Result]:
        """List results with optional filters."""
        conditions = []
        params: list[Any] = []

        if factor_ref:
            conditions.append("factor_ref = ?")
            params.append(factor_ref)
        if strategy_ref:
            conditions.append("strategy_ref = ?")
            params.append(strategy_ref)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM reproduction_results{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Result(**dict(r)) for r in rows]

    def update_result_status(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update result status."""
        if status not in ("success", "error"):
            raise ValueError(f"invalid status {status!r}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE reproduction_results SET status = ?, error = ? WHERE run_id = ?",
                (status, error, run_id),
            )

    def delete_result(self, run_id: str) -> bool:
        """Delete a result."""
        with self._connect() as conn:
            conn.execute("DELETE FROM reproduction_results WHERE run_id = ?", (run_id,))
            return conn.total_changes > 0

    # ─── Transaction control ──────────────────────────────────

    def commit(self) -> None:
        """No-op for sqlite3 (auto-commits per call), kept for API symmetry.

        Provided so callers can use try/commit/rollback pattern uniformly.
        """
        return None

    def rollback(self) -> None:
        """No-op for sqlite3 (each call is its own transaction), kept for API symmetry.

        Provided so callers can use try/commit/rollback pattern uniformly.
        """
        return None


__all__ = [
    "ReproductionDatabase",
    "Session",
    "Artifact",
    "Result",
    "VALID_STATUSES",
    "TERMINAL_STATUSES",
    "DEFAULT_DB_PATH",
]