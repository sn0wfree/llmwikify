"""Factor Value Store — persist computed factor values to DuckDB.

Provides functions to:
  1. Store factor values (wide DataFrame → DuckDB)
  2. Query factor values (for cross-factor analysis, L5 batch queries)
  3. List stored factors and date ranges

DuckDB schema:
  factor_values (date DATE, stock VARCHAR, factor_name VARCHAR, value DOUBLE)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("quant/factor.duckdb")


def _get_conn(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection."""
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def _ensure_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Ensure the factor_values table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_values (
            date DATE,
            stock VARCHAR,
            factor_name VARCHAR,
            value DOUBLE
        )
    """)


def store_factor_values(
    factor_wide: pd.DataFrame,
    factor_name: str,
    db_path: Path | str | None = None,
) -> int:
    """Store factor values from a wide DataFrame to DuckDB.

    Args:
        factor_wide: DataFrame [date × Code] of factor values.
        factor_name: Factor identifier (e.g., 'stock_price_momentum_20d').
        db_path: Optional DuckDB path override.

    Returns:
        Number of rows inserted.
    """
    if factor_wide is None or factor_wide.empty:
        return 0

    # Melt to long format: (date, stock, factor_name, value)
    factor_wide.index.name = "date"
    melted = factor_wide.reset_index().melt(
        id_vars=["date"],
        var_name="stock",
        value_name="value",
    )
    melted = melted.dropna(subset=["value"])

    if melted.empty:
        return 0

    # Ensure correct column order and types
    melted["date"] = pd.to_datetime(melted["date"])
    melted["stock"] = melted["stock"].astype(str)
    melted["factor_name"] = factor_name
    melted["value"] = melted["value"].astype(float)
    melted = melted[["date", "stock", "factor_name", "value"]]

    conn = _get_conn(db_path)
    try:
        _ensure_table(conn)
        # Delete existing data for this factor (upsert semantics)
        conn.execute(
            "DELETE FROM factor_values WHERE factor_name = ?",
            [factor_name],
        )
        # Insert new data
        conn.execute(
            "INSERT INTO factor_values SELECT * FROM melted",
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM factor_values WHERE factor_name = ?",
            [factor_name],
        ).fetchone()[0]
        logger.info("Stored %d rows for factor %s", count, factor_name)
        return count
    finally:
        conn.close()


def query_factor_values(
    factor_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    stocks: list[str] | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Query stored factor values.

    Returns:
        DataFrame with columns [date, stock, factor_name, value].
    """
    conn = _get_conn(db_path)
    try:
        _ensure_table(conn)
        conditions = ["factor_name = ?"]
        params: list[Any] = [factor_name]

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)
        if stocks:
            placeholders = ", ".join(["?"] * len(stocks))
            conditions.append(f"stock IN ({placeholders})")
            params.extend(stocks)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM factor_values WHERE {where} ORDER BY date, stock"
        return conn.execute(sql, params).fetchdf()
    finally:
        conn.close()


def list_stored_factors(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """List all factors stored in DuckDB with metadata.

    Returns:
        List of dicts with keys: factor_name, row_count, min_date, max_date, n_stocks.
    """
    conn = _get_conn(db_path)
    try:
        _ensure_table(conn)
        rows = conn.execute("""
            SELECT
                factor_name,
                COUNT(*) as row_count,
                MIN(date) as min_date,
                MAX(date) as max_date,
                COUNT(DISTINCT stock) as n_stocks
            FROM factor_values
            GROUP BY factor_name
            ORDER BY factor_name
        """).fetchall()

        return [
            {
                "factor_name": r[0],
                "row_count": r[1],
                "min_date": str(r[2]) if r[2] else None,
                "max_date": str(r[3]) if r[3] else None,
                "n_stocks": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()


def compute_and_store_factor(
    close_wide: pd.DataFrame,
    factor_name: str,
    factor_class: str,
    factor_params: dict[str, Any],
    db_path: Path | str | None = None,
) -> int:
    """Compute factor values from close_wide and store to DuckDB.

    This is the main entry point for the factor value pipeline.

    Args:
        close_wide: DataFrame [date × Code] of close prices.
        factor_name: Factor identifier for storage.
        factor_class: Factor type (momentum, volatility, etc.).
        factor_params: Factor construction parameters.
        db_path: Optional DuckDB path override.

    Returns:
        Number of rows stored.
    """
    from .factor_backtest import _compute_factor_matrix

    factor_wide = _compute_factor_matrix(close_wide, factor_class, factor_params)
    if factor_wide.empty:
        logger.warning("Factor matrix empty for %s", factor_name)
        return 0

    return store_factor_values(factor_wide, factor_name, db_path)


__all__ = [
    "store_factor_values",
    "query_factor_values",
    "list_stored_factors",
    "compute_and_store_factor",
]
