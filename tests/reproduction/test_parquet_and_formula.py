"""Tests for Parquet data source and formula factor execution."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ─── ParquetLocalDataSource ────────────────────────────────────────────


class TestParquetLocalDataSource:
    def _make_parquet(self, tmpdir: str) -> str:
        """Create a test Parquet file."""
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        codes = ["000001.SZ", "600519.SH", "000858.SZ"]
        rows = []
        for d in dates:
            for c in codes:
                rows.append({"date": d, "Code": c, "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000})
        df = pd.DataFrame(rows)
        path = Path(tmpdir) / "test.parquet"
        df.to_parquet(path)
        return str(path)

    def test_get_returns_data(self):
        """ParquetLocalDataSource returns data for valid symbol."""
        from llmwikify.reproduction.data_source.router import ParquetLocalDataSource
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_parquet(tmpdir)
            src = ParquetLocalDataSource(path)
            df = src.get("000001.SZ", "2024-01-01", "2024-01-15")
            assert df is not None
            assert len(df) > 0
            assert "close" in df.columns

    def test_get_bare_code(self):
        """ParquetLocalDataSource handles bare codes without suffix."""
        from llmwikify.reproduction.data_source.router import ParquetLocalDataSource
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_parquet(tmpdir)
            src = ParquetLocalDataSource(path)
            df = src.get("000001", "2024-01-01", "2024-01-15")
            assert df is not None
            assert len(df) > 0

    def test_get_empty_for_unknown_symbol(self):
        """ParquetLocalDataSource returns None for unknown symbol."""
        from llmwikify.reproduction.data_source.router import ParquetLocalDataSource
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_parquet(tmpdir)
            src = ParquetLocalDataSource(path)
            df = src.get("999999.SZ", "2024-01-01", "2024-01-15")
            assert df is None

    def test_date_range_filter(self):
        """ParquetLocalDataSource filters by date range."""
        from llmwikify.reproduction.data_source.router import ParquetLocalDataSource
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_parquet(tmpdir)
            src = ParquetLocalDataSource(path)
            df = src.get("000001.SZ", "2024-01-01", "2024-01-05")
            assert df is not None
            # Should have fewer rows than full dataset
            assert len(df) < 30


# ─── DataRouter with parquet_path ──────────────────────────────────────


class TestDataRouterParquet:
    def test_parquet_first_in_chain(self):
        """ParquetLocalDataSource is first in the DataRouter chain."""
        from llmwikify.reproduction.data_source.router import DataRouter, ParquetLocalDataSource
        with tempfile.TemporaryDirectory() as tmpdir:
            dates = pd.date_range("2024-01-01", periods=10, freq="B")
            df = pd.DataFrame({"date": dates, "Code": ["000001.SZ"] * 10, "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000})
            path = Path(tmpdir) / "test.parquet"
            df.to_parquet(path)
            router = DataRouter(use_cache=False, parquet_path=str(path))
            assert isinstance(router._sources[0], ParquetLocalDataSource)


# ─── _compute_factor_from_code ──────────────────────────────────────────


class TestComputeFactorFromCode:
    def test_simple_momentum(self):
        """LLM-generated momentum code works."""
        from llmwikify.reproduction.backtest_pkg.factor_backtest import _compute_factor_from_code
        data = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.random.randn(30).cumsum() + 100,
        })
        code = """
def compute_factor(df):
    close = df["close"]
    return close.pct_change(5)
"""
        result = _compute_factor_from_code(data, code)
        assert isinstance(result, pd.Series)
        assert len(result) == 30
        assert result.iloc[0] != result.iloc[0]  # First value is NaN

    def test_rsi_code(self):
        """LLM-generated RSI code works."""
        from llmwikify.reproduction.backtest_pkg.factor_backtest import _compute_factor_from_code
        data = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.random.randn(30).cumsum() + 100,
        })
        code = """
def compute_factor(df):
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))
"""
        result = _compute_factor_from_code(data, code)
        assert isinstance(result, pd.Series)
        assert len(result) == 30

    def test_unsafe_code_rejected(self):
        """Unsafe code is rejected by sandbox."""
        from llmwikify.reproduction.backtest_pkg.factor_backtest import _compute_factor_from_code
        data = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=10, freq="B"), "close": range(10)})
        code = """
import os
os.system("rm -rf /")
"""
        with pytest.raises(ValueError, match="Unsafe"):
            _compute_factor_from_code(data, code)


# ─── formula factor_class ──────────────────────────────────────────────


class TestFormulaFactorClass:
    def test_formula_branch(self):
        """factor_class='formula' executes code correctly."""
        from llmwikify.reproduction.backtest_pkg.factor_backtest import _compute_factor_values
        data = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.random.randn(30).cumsum() + 100,
        })
        code = """
def compute_factor(df):
    return df["close"].pct_change(10)
"""
        result = _compute_factor_values(data, "formula", {"code": code})
        assert isinstance(result, pd.Series)
        assert len(result) == 30

    def test_formula_fallback_to_momentum(self):
        """formula without code falls back to momentum."""
        from llmwikify.reproduction.backtest_pkg.factor_backtest import _compute_factor_values
        data = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.random.randn(30).cumsum() + 100,
        })
        result = _compute_factor_values(data, "formula", {})
        assert isinstance(result, pd.Series)
        assert len(result) == 30
