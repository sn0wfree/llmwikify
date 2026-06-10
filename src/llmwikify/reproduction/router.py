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

    DEFAULT_CH_PASSWORD = "Imsn0wfree"
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


__all__ = [
    "DataSource",
    "DataRouter",
    "SynthDataSource",
    "AKShareDataSource",
    "ClickHouseDataSource",
    "CachedClickHouseDataSource",
]