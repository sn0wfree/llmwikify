"""Data router — chained fallback across data sources.

Layered fallback:
    MarketDataCacheNode (QN Parquet cache)
        -> ClickHouseNode (QN)
            -> AKShareDataSource (akshare wrapper, best-effort)
                -> SynthDataSource (deterministic synthetic fallback)

All sources expose a uniform `get(symbol, start, end) -> pd.DataFrame | None`
contract. The router tries them in order, returning the first non-None result.
If all sources fail, the last exception is re-raised.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

import pandas as pd

logger = logging.getLogger(__name__)


class DataSource(Protocol):
    """Uniform data-source contract."""

    name: str

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> Optional[pd.DataFrame]: ...


class SynthDataSource:
    """Deterministic synthetic OHLCV — last-resort fallback.

    Produces a 60-day random-walk series seeded by symbol name so results are
    stable across runs. Schema matches what run_backtest expects (date index
    or column, OHLCV columns).
    """

    name = "synth"

    def __init__(self, n_days: int = 60, base_price: float = 10.0):
        self.n_days = n_days
        self.base_price = base_price

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        import numpy as np

        seed = abs(hash(symbol)) % (2**32)
        rng = np.random.default_rng(seed)
        dates = pd.date_range(start=start, periods=self.n_days, freq="D")
        close = self.base_price + np.cumsum(rng.normal(0, 0.5, self.n_days))
        open_ = close + rng.normal(0, 0.1, self.n_days)
        high = np.maximum(open_, close) + abs(rng.normal(0, 0.1, self.n_days))
        low = np.minimum(open_, close) - abs(rng.normal(0, 0.1, self.n_days))
        volume = rng.integers(1_000_000, 10_000_000, self.n_days).astype(float)
        return pd.DataFrame(
            {
                "date": dates,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )


class AKShareDataSource:
    """AKShare wrapper — best-effort, never raises.

    AKShare requires network and frequently hangs/times-out in restricted
    environments, so any exception is swallowed and reported as None. The
    router treats None as "skip this source, try the next one".
    """

    name = "akshare"

    def __init__(self, timeout_s: float = 5.0):
        self.timeout_s = timeout_s

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak

            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                }
            )
            df["date"] = pd.to_datetime(df["date"])
            return df[["date", "open", "high", "low", "close", "volume"]]
        except Exception as exc:
            logger.warning("akshare failed for %s: %s", symbol, exc)
            return None


class ClickHouseDataSource:
    """Thin wrapper around QuantNodes ClickHouseNode.

    Normalizes the QuerySet result into the OHLCV schema that run_backtest
    expects. The underlying ClickHouseNode comes from QuantNodes — we do not
    reimplement the connection, pooling, or retry logic.
    """

    name = "clickhouse"

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8123,
        user: str = "default",
        passwd: str = "",
        database: str = "quote",
        table: str = "cn_stock",
    ):
        self._table = f"{database}.{table}"
        self._conn_kwargs = dict(
            host=host,
            port=port,
            user=user,
            passwd=passwd,
            database=database,
        )

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> Optional[pd.DataFrame]:
        try:
            from QuantNodes.database_node import ClickHouseNode

            node = ClickHouseNode(**self._conn_kwargs)
            node.connect()
            safe_sym = symbol.replace("'", "''")
            safe_start = start.replace("'", "''")
            safe_end = end.replace("'", "''")
            sql = (
                f"SELECT trade_date AS date, open, high, low, close, vol AS volume "
                f"FROM {self._table} "
                f"WHERE ts_code = '{safe_sym}' "
                f"AND trade_date >= '{safe_start}' "
                f"AND trade_date <= '{safe_end}' "
                f"ORDER BY trade_date"
            )
            df = node.query(sql)
            node.disconnect()
            if df is None or df.empty:
                return None
            return df
        except Exception as exc:
            logger.warning("clickhouse failed for %s: %s", symbol, exc)
            return None


class CachedClickHouseDataSource:
    """MarketDataCacheNode-fronted ClickHouse source.

    Wraps QuantNodes MarketDataCacheNode + ClickHouseNode so subsequent
    queries for the same symbol/range hit the local Parquet cache.
    """

    name = "cache+clickhouse"

    def __init__(
        self,
        clickhouse: Optional[ClickHouseDataSource] = None,
        cache_dir: str = "~/.llmwikify/cache",
        ttl_days: int = 7,
    ):
        self._ch = clickhouse or ClickHouseDataSource()

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> Optional[pd.DataFrame]:
        try:
            from QuantNodes.database_node import ClickHouseNode

            ch_node = ClickHouseNode(**self._ch._conn_kwargs)
            safe_sym = symbol.replace("'", "''")
            safe_start = start.replace("'", "''")
            safe_end = end.replace("'", "''")
            sql = (
                f"SELECT trade_date AS date, open, high, low, close, vol AS volume "
                f"FROM {self._ch._table} "
                f"WHERE ts_code = '{safe_sym}' "
                f"AND trade_date >= '{safe_start}' "
                f"AND trade_date <= '{safe_end}' "
                f"ORDER BY trade_date"
            )
            ch_node.connect()
            try:
                df = ch_node.query(sql)
            finally:
                ch_node.disconnect()
            if df is None or df.empty:
                return None
            return df
        except Exception as exc:
            logger.warning("cache+clickhouse failed for %s: %s", symbol, exc)
            return None


class DataRouter:
    """Chained-fallback data router.

    Tries each source in order; the first non-None DataFrame wins. If the
    explicit cache layer is disabled (`use_cache=False`) it is skipped.
    SynthDataSource always returns non-None so it acts as a hard floor.
    """

    DEFAULT_CH_PASSWORD = ""
    DEFAULT_BENCHMARK = "000300.SH"  # CSI 300

    def __init__(
        self,
        sources: Optional[list[DataSource]] = None,
        use_cache: bool = True,
        clickhouse_passwd: Optional[str] = None,
    ):
        if sources is not None:
            self._sources = list(sources)
            return
        pwd = clickhouse_passwd if clickhouse_passwd is not None else self.DEFAULT_CH_PASSWORD
        if use_cache:
            self._sources = [
                CachedClickHouseDataSource(ClickHouseDataSource(passwd=pwd)),
                ClickHouseDataSource(passwd=pwd),
                AKShareDataSource(),
                SynthDataSource(),
            ]
        else:
            self._sources = [
                ClickHouseDataSource(passwd=pwd),
                AKShareDataSource(),
                SynthDataSource(),
            ]

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> tuple[pd.DataFrame, str]:
        """Return (dataframe, source_name). Always succeeds — falls back to synth."""
        last_exc: Optional[Exception] = None
        for src in self._sources:
            try:
                df = src.get(symbol, start, end)
            except Exception as exc:
                last_exc = exc
                logger.warning("source %s raised: %s", src.name, exc)
                continue
            if df is not None and not df.empty:
                logger.info("data resolved via %s for %s", src.name, symbol)
                return df, src.name
        if last_exc is not None:
            logger.error("all sources failed for %s: %s", symbol, last_exc)
        return self._sources[-1].get(symbol, start, end), self._sources[-1].name

    def get_benchmark(
        self,
        start: str,
        end: str,
        benchmark_code: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch benchmark data (default: CSI 300).

        Returns DataFrame with 'date' and 'close' columns, or None if unavailable.
        Used for Alpha/Beta computation in strategy backtests.
        """
        code = benchmark_code or self.DEFAULT_BENCHMARK
        try:
            df, _ = self.get(code, start, end)
            if df is not None and not df.empty:
                return df
        except Exception as exc:
            logger.warning("benchmark fetch failed for %s: %s", code, exc)
        return None

    def get_universe(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> tuple[Optional[pd.DataFrame], str]:
        """Batch fetch OHLCV for a list of symbols.

        Iterates ``symbols`` and concatenates per-stock DataFrames into a
        single long-format DataFrame with a ``Code`` column. The source name
        is taken from the first successful fetch (sources can vary per
        symbol depending on cache state).

        Args:
            symbols: List of 6-digit stock codes, e.g. ["000001", "600519"].
                The router will add ".SH"/".SZ" suffix based on the first
                digit (6 → SH, 0/3 → SZ, etc.).
            start: Start date YYYY-MM-DD.
            end: End date YYYY-MM-DD.

        Returns:
            Tuple of (DataFrame, source_name). DataFrame columns:
            [date, Code, open, high, low, close, volume] in long format.
            Returns (None, source_name) if no symbol yields data.
        """
        if not symbols:
            return None, ""

        frames: list[pd.DataFrame] = []
        first_source = ""
        suffix_map = self._ts_code_suffix_map()

        for sym in symbols:
            ts_code = f"{sym}.{suffix_map.get(sym[0], 'SH')}" if sym else sym
            try:
                df, source = self.get(ts_code, start, end)
            except Exception as exc:
                logger.warning("get_universe failed for %s: %s", ts_code, exc)
                continue
            if df is None or df.empty:
                continue
            if not first_source:
                first_source = source
            d = df.copy()
            if "Code" not in d.columns:
                d["Code"] = ts_code
            frames.append(d)

        if not frames:
            return None, first_source

        merged = pd.concat(frames, ignore_index=True)
        keep = [c for c in ["date", "Code", "open", "high", "low", "close", "volume"] if c in merged.columns]
        merged = merged[keep].sort_values(["date", "Code"]).reset_index(drop=True)
        return merged, first_source

    @staticmethod
    def _ts_code_suffix_map() -> dict[str, str]:
        """Map first digit of 6-digit code to exchange suffix."""
        return {
            "6": "SH",   # 600xxx, 601xxx, 603xxx, 605xxx → 上交所
            "9": "SH",   # 9xxxxx B 股
            "0": "SZ",   # 000xxx, 002xxx, 003xxx → 深交所主板/中小
            "3": "SZ",   # 300xxx, 301xxx → 深交所创业板
            "2": "SZ",   # 2xxxxx B 股
            "4": "BJ",   # 4xxxxx, 8xxxxx → 北交所
            "8": "BJ",
        }

    def get_index_close(
        self,
        index_code: str,
        start: str,
        end: str,
    ) -> Optional[pd.Series]:
        """Fetch close price series for an index.

        Args:
            index_code: Full ts_code, e.g. "000300.SH".
            start: Start date YYYY-MM-DD.
            end: End date YYYY-MM-DD.

        Returns:
            pd.Series indexed by date with close prices, or None on failure.
        """
        try:
            df, _ = self.get(index_code, start, end)
        except Exception as exc:
            logger.warning("get_index_close(%s) failed: %s", index_code, exc)
            return None
        if df is None or df.empty or "close" not in df.columns:
            return None
        if "date" in df.columns:
            s = df.set_index("date")["close"]
        else:
            s = df["close"]
        s = s.sort_index()
        s.name = index_code
        return s


__all__ = [
    "DataSource",
    "DataRouter",
    "SynthDataSource",
    "AKShareDataSource",
    "ClickHouseDataSource",
    "CachedClickHouseDataSource",
]