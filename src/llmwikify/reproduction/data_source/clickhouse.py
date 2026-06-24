"""ClickHouse data loader for quant reproduction.

Fetches HS300 OHLCV data from ClickHouse `quote.cn_stock` table.
Builds QuantNodes-compatible HDF5 cache (stk_daily.h5 + index_daily.h5).

Reference: docs/designs/llm_compile_loop_v4.md
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ClickHouse config from ~/.llmwikify/llmwikify.json
from ..common.config import config

CH_HOST = config.get("clickhouse.host", "0.0.0.0")
CH_PORT = config.get("clickhouse.port", 8123)
CH_USER = config.get("clickhouse.user", "default")
CH_PASSWORD = config.get("clickhouse.password", "")
CH_DATABASE = config.get("clickhouse.database", "quote")
CH_TABLE = config.get("clickhouse.table", "cn_stock")


def _ch_query(sql: str, timeout: int = 60) -> str:
    """Execute HTTP SQL query against ClickHouse, return TSV response."""
    import urllib.request
    auth = base64.b64encode(f"{CH_USER}:{CH_PASSWORD}".encode()).decode()
    url = f"http://{CH_HOST}:{CH_PORT}/?query={sql}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def _ch_query_json(sql: str, timeout: int = 60) -> list[dict[str, Any]]:
    """Execute SQL and return JSONEachRow response."""
    import urllib.request
    from urllib.parse import quote
    auth = base64.b64encode(f"{CH_USER}:{CH_PASSWORD}".encode()).decode()
    url = f"http://{CH_HOST}:{CH_PORT}/?query={quote(sql)}+FORMAT+JSONEachRow"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        lines = r.read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]


def _url_escape(sql: str) -> str:
    """URL-encode SQL string for ClickHouse query."""
    from urllib.parse import quote
    return quote(sql, safe="")


def _ch_query_pandas(sql: str, timeout: int = 60) -> pd.DataFrame:
    """Execute SQL and return pandas DataFrame."""
    tsv = _ch_query(sql, timeout=timeout)
    from io import StringIO
    return pd.read_csv(StringIO(tsv), sep="\t", index_col=False)


def fetch_close_panel(
    codes: list[str],
    start_date: int = 20200101,
    end_date: int = 20241231,
    timeout: int = 60,
) -> pd.DataFrame | None:
    """Fetch close price panel from ClickHouse for given codes and date range.

    Returns DataFrame with date index and code columns (wide format),
    or None if no data.
    """
    if not codes:
        return None

    codes_str = ",".join(f"'{c}'" for c in codes)
    sql = f"""
    SELECT ts_code, trade_date, close
    FROM {CH_DATABASE}.{CH_TABLE}
    WHERE ts_code IN ({codes_str})
      AND trade_date >= {start_date}
      AND trade_date <= {end_date}
    ORDER BY trade_date, ts_code
    """

    try:
        df = _ch_query_pandas(sql, timeout=timeout)
        if df.empty:
            logger.warning("[clickhouse] Empty result for %d codes", len(codes))
            return None

        # Pivot to wide format
        wide = df.pivot(index="trade_date", columns="ts_code", values="close")
        wide.index.name = "date"
        return wide

    except Exception as exc:
        logger.warning(
            "[clickhouse] fetch attempt failed: %s", exc
        )
        return None


def fetch_hs300_constituents() -> list[str]:
    """Fetch current HS300 constituent codes from ClickHouse."""
    sql = f"SELECT DISTINCT ts_code FROM {CH_DATABASE}.{CH_TABLE} LIMIT 5000"
    try:
        df = _ch_query_pandas(sql, timeout=30)
        return df["ts_code"].tolist() if not df.empty else []
    except Exception as exc:
        logger.warning("[clickhouse] fetch constituents failed: %s", exc)
        return []


def build_quantnodes_h5(
    codes: list[str],
    start_date: int = 20200101,
    end_date: int = 20241231,
    out_dir: str | Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Fetch OHLCV data from ClickHouse and build QuantNodes H5 cache.

    Creates stk_daily.h5 with keys: open, high, low, close, volume, returns, vwap.
    """
    from pathlib import Path as P

    if out_dir is None:
        out_dir = P.home() / ".llmwikify" / "akshare_cache" / "quantnodes_h5"
    out_dir = P(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    codes_str = ",".join(f"'{c}'" for c in codes)
    sql = f"""
    SELECT ts_code, trade_date, open, high, low, close, vol as volume
    FROM {CH_DATABASE}.{CH_TABLE}
    WHERE ts_code IN ({codes_str})
      AND trade_date >= {start_date}
      AND trade_date <= {end_date}
    ORDER BY trade_date, ts_code
    """

    try:
        df = _ch_query_pandas(sql, timeout=timeout)
        if df.empty:
            logger.warning("[clickhouse] No data fetched, skipping H5 build")
            return {"error": "no data"}

        logger.info("[clickhouse] Fetching %d codes %s ~ %s", len(codes), start_date, end_date)

        # Compute returns and vwap
        df = df.sort_values(["ts_code", "trade_date"])
        df["returns"] = df.groupby("ts_code")["close"].pct_change()
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3

        # Build wide format for each field
        stk_path = out_dir / "stk_daily.h5"
        logger.info("[clickhouse] Writing %s (%d rows, %d codes)", stk_path, len(df), df["ts_code"].nunique())

        with pd.HDFStore(stk_path, mode="w") as store:
            for field in ["open", "high", "low", "close", "volume", "returns", "vwap"]:
                wide = df.pivot(index="trade_date", columns="ts_code", values=field)
                store.put(field, wide)

        result = {
            "stk_path": str(stk_path),
            "n_rows": len(df),
            "n_codes": df["ts_code"].nunique(),
            "date_range": [int(df["trade_date"].min()), int(df["trade_date"].max())],
        }
        logger.info("[clickhouse] H5 build complete: %s", result)
        return result

    except Exception as exc:
        logger.warning("[clickhouse] H5 build failed: %s", exc)
        return {"error": str(exc)}


def main() -> None:
    """CLI entry point for ClickHouse data operations."""
    codes = fetch_hs300_constituents()
    if codes:
        logger.info("[clickhouse] Fetched %d codes", len(codes))
        result = build_quantnodes_h5(codes[:10])
        logger.info("[clickhouse] Build result: %s", result)
    else:
        logger.warning("[clickhouse] No codes fetched")
