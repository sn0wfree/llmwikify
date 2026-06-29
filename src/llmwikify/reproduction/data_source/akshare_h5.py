"""akshare H5 cache data source adapter for 101 alphas style papers.

Wraps `preload_market_data(data_path, h5_filename)` + `build_long_dataframe`
into a `DataSource`-compatible interface (with `name` + `get(symbol, start, end)`).

For 101 alphas, market data is preloaded once at the start of the batch (not
fetched per-symbol). The `get()` method returns the cached polars DataFrame
regardless of symbol/start/end args (the cache is shared across all signals).

This is intentionally a thin adapter — the existing `data_source/router.py`
DataRouter is for per-symbol fetching. The 101-alphas pattern uses a different
flow (bulk preload → build long DF once → reuse for all signals).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


class AkShareH5DataSource:
    """H5 cache adapter matching `DataSource` Protocol (structural).

    Preloads wide-format DataFrames from H5 files, builds a long-format
    polars DataFrame once, and reuses it for all signals.

    Attributes:
        name: Protocol-required identifier ("akshare_h5_cache").
        data_path: H5 file directory.
        h5_filename: H5 file name (default "stk_daily.h5").
    """

    name: str = "akshare_h5_cache"

    def __init__(self, data_path: Path, h5_filename: str = "stk_daily.h5") -> None:
        self._data_path: Path = Path(data_path)
        self._h5_filename: str = h5_filename
        self._df_pl: "pl.DataFrame | None" = None
        self._data_cache: dict[str, Any] | None = None

    @property
    def data_path(self) -> Path:
        return self._data_path

    @property
    def df_pl(self) -> "pl.DataFrame | None":
        """Long-format polars DataFrame (lazy-loaded)."""
        return self._df_pl

    def get(
        self,
        symbol: str,        # noqa: ARG002 — ignored, preloaded cache
        start: str,         # noqa: ARG002
        end: str,           # noqa: ARG002
    ) -> "pl.DataFrame | None":
        """Return preloaded long DataFrame (ignores symbol/start/end).

        Returns None if preload fails (caller should handle).
        """
        if self._df_pl is None:
            self._preload()
        return self._df_pl

    def _preload(self) -> None:
        """Load H5 keys and build long polars DataFrame.

        Import here to avoid circular import (data_source → pipeline → data_source).
        """
        from scripts.run_101_alphas_v2 import (
            build_long_dataframe,
            preload_market_data,
        )
        self._data_cache = preload_market_data(
            self._data_path, self._h5_filename,
        )
        self._df_pl = build_long_dataframe(self._data_cache)

    def __repr__(self) -> str:
        return f"AkShareH5DataSource(data_path={self._data_path}, h5={self._h5_filename})"