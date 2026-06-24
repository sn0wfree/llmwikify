"""Akshare data loader for paper backtest.

Provides close_wide (date × code) DataFrames and tradable matrices
for the A-share market via akshare (sina data source).

Functions:
- fetch_universe_data(universe, start_date, end_date) -> (close_wide, tradable)
- fetch_hs300_constituents() -> list[str] of stock codes
- fetch_close_panel(codes, start_date, end_date) -> pd.DataFrame [date × code]
- fetch_tradable_matrices(codes, start_date, end_date) -> dict[str, pd.DataFrame]
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".llmwikify" / "akshare_cache"


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def fetch_hs300_constituents(refresh: bool = False) -> list[str]:
    """Fetch HS300 constituent stock codes (e.g. ['000001.SZ', '600000.SH', ...]).

    Args:
        refresh: Force re-fetch from akshare, ignoring cache.

    Returns:
        list of stock codes. Empty list on failure.
    """
    cache_path = _ensure_cache_dir() / "hs300_constituents.json"
    if not refresh and cache_path.exists() and time.time() - cache_path.stat().st_mtime < 86400 * 7:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed, cannot fetch HS300")
        return []

    try:
        df = ak.index_stock_cons_weight_csindex(symbol="000300")
        # 代码格式: '000001' 需补全市场后缀
        codes: list[str] = []
        for code in df["成分券代码"].tolist():
            if str(code).startswith(("60", "68", "9")):
                codes.append(f"{code}.SH")
            else:
                codes.append(f"{code}.SZ")
        cache_path.write_text(json.dumps(codes), encoding="utf-8")
        logger.info("Fetched %d HS300 constituents (cached)", len(codes))
        return codes
    except Exception as exc:
        logger.warning("Failed to fetch HS300: %s", exc)
        return []


def fetch_close_panel(
    codes: list[str],
    start_date: str,
    end_date: str,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch close prices for a list of codes, return DataFrame [date × code].

    Uses akshare `stock_zh_a_daily` (sina data source) for each code.
    Caches per-code data to disk for re-use.

    Args:
        codes: list of stock codes (e.g. ['000001.SZ', '600000.SH']).
        start_date: ISO date string (e.g. '2015-01-01').
        end_date: ISO date string.
        refresh: Force re-fetch.

    Returns:
        DataFrame indexed by date with code columns, values = close price.
    """
    cache_dir = _ensure_cache_dir() / "close_panel"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{start_date}_{end_date}.parquet"

    if not refresh and cache_path.exists():
        try:
            return pd.read_parquet(cache_path)
        except Exception as exc:
            logger.warning("Cache load failed, refetching: %s", exc)

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed")
        return pd.DataFrame()

    series_list: list[pd.Series] = []
    for i, code in enumerate(codes, 1):
        # Convert '000001.SZ' → 'sz000001' for akshare sina API
        sina_code = code.replace(".SZ", "sz").replace(".SH", "sh")
        try:
            df = ak.stock_zh_a_daily(
                symbol=sina_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
        except Exception as exc:
            logger.debug("Failed to fetch %s: %s", code, exc)
            continue
        if df is None or df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        s = pd.Series(df["close"].values, index=df["date"], name=code)
        series_list.append(s)
        if i % 50 == 0:
            logger.info("Fetched %d/%d codes", i, len(codes))

    if not series_list:
        return pd.DataFrame()

    panel = pd.concat(series_list, axis=1).sort_index()
    # Forward-fill missing dates (max 5 days)
    panel = panel.ffill(limit=5)
    try:
        panel.to_parquet(cache_path)
    except Exception as exc:
        logger.debug("Cache save failed: %s", exc)
    return panel


def fetch_tradable_matrices(
    codes: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """Build tradable matrices [date × code] for quantnodes.

    Simplified: returns empty matrices (no ST/suspend filter) since
    ifind data is unavailable.  Returns at least {st, suspend, ipo_days}
    as all-zero DataFrames so downstream backtest doesn't crash.

    Args:
        codes: list of stock codes.
        start_date: ISO date.
        end_date: ISO date.

    Returns:
        dict with empty tradable matrices (placeholder).
    """
    # Generate date range
    dates = pd.date_range(start=start_date, end=end_date, freq="B")
    return {
        "st": pd.DataFrame(0.0, index=dates, columns=codes),
        "suspend": pd.DataFrame(0.0, index=dates, columns=codes),
        "ud_limit": pd.DataFrame(0.0, index=dates, columns=codes),
        "ipo_days": pd.DataFrame(365, index=dates, columns=codes),
    }


def fetch_universe_data(
    universe: str = "hs300",
    start_date: str = "2015-01-01",
    end_date: str = "2024-12-31",
    refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame] | None]:
    """Convenience: fetch close + tradable for a named universe.

    Args:
        universe: 'hs300' or 'csi_all' (only hs300 implemented).
        start_date: ISO date.
        end_date: ISO date.
        refresh: Force re-fetch from akshare.

    Returns:
        (close_wide, tradable) tuple. Either may be empty/None on failure.
    """
    if universe == "hs300":
        codes = fetch_hs300_constituents(refresh=refresh)
    elif universe == "csi_all":
        logger.warning("csi_all universe not yet implemented, falling back to hs300")
        codes = fetch_hs300_constituents(refresh=refresh)
    else:
        logger.warning("Unknown universe %s, using hs300", universe)
        codes = fetch_hs300_constituents(refresh=refresh)

    if not codes:
        return pd.DataFrame(), None

    close_wide = fetch_close_panel(codes, start_date, end_date, refresh=refresh)
    if close_wide.empty:
        return close_wide, None

    tradable = fetch_tradable_matrices(list(close_wide.columns), start_date, end_date)
    return close_wide, tradable


__all__ = [
    "CACHE_DIR",
    "fetch_close_panel",
    "fetch_hs300_constituents",
    "fetch_tradable_matrices",
    "fetch_universe_data",
]
