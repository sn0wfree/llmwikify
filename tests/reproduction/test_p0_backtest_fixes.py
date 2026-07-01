"""Tests for P0 fixes: BacktestResult equity_curve/monthly_returns + DuckDB pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from llmwikify.reproduction.paper_understanding.schemas import BacktestResult

# ─── BacktestResult equity_curve / monthly_returns ─────────────────────


class TestBacktestResultEquityCurve:
    """Verify restored equity_curve and monthly_returns fields."""

    def test_default_values(self):
        """New BacktestResult has empty equity_curve and monthly_returns."""
        result = BacktestResult()
        assert result.equity_curve == []
        assert result.monthly_returns == {}

    def test_to_dict_includes_fields(self):
        """to_dict() serializes equity_curve and monthly_returns."""
        result = BacktestResult(
            equity_curve=[{"date": "2024-01-01", "value": 100000.0}],
            monthly_returns={"2024-01": 2.3},
        )
        d = result.to_dict()
        assert "equity_curve" in d
        assert "monthly_returns" in d
        assert d["equity_curve"] == [{"date": "2024-01-01", "value": 100000.0}]
        assert d["monthly_returns"] == {"2024-01": 2.3}

    def test_construct_with_fields(self):
        """BacktestResult can be constructed with equity_curve and monthly_returns."""
        ec = [{"date": f"2024-01-{i:02d}", "value": 100000 + i * 100} for i in range(1, 6)]
        mr = {"2024-01": 1.5, "2024-02": -0.3}
        result = BacktestResult(equity_curve=ec, monthly_returns=mr)
        assert len(result.equity_curve) == 5
        assert result.monthly_returns["2024-01"] == 1.5

    def test_backward_compatible_no_args(self):
        """BacktestResult() without equity_curve/monthly_returns still works."""
        result = BacktestResult(status="success")
        assert result.equity_curve == []
        assert result.monthly_returns == {}
        d = result.to_dict()
        assert d["equity_curve"] == []
        assert d["monthly_returns"] == {}


# ─── _reconstruct_equity_curve ─────────────────────────────────────────


class TestReconstructEquityCurve:
    """Test the equity curve reconstruction function."""

    def _make_data(self, n_days=10, initial_price=100.0):
        """Create a simple price DataFrame."""
        dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
        prices = [initial_price + i for i in range(n_days)]
        return pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "Close": prices})

    def test_empty_data(self):
        """Empty data returns empty list."""
        from llmwikify.reproduction.backtest_pkg.run_backtest import (
            _reconstruct_equity_curve,
        )

        result = _reconstruct_equity_curve([], pd.DataFrame(), 100000.0)
        assert result == []

    def test_no_trades(self):
        """No trades: equity stays at initial_cash."""
        from llmwikify.reproduction.backtest_pkg.run_backtest import (
            _reconstruct_equity_curve,
        )

        data = self._make_data(n_days=5)
        result = _reconstruct_equity_curve([], data, 100000.0)
        assert len(result) == 5
        # All values should be initial_cash (no position)
        for entry in result:
            assert entry["value"] == 100000.0

    def test_buy_and_hold(self):
        """Buy on day 1, hold: equity = cash - cost + position * close."""
        from llmwikify.reproduction.backtest_pkg.run_backtest import (
            _reconstruct_equity_curve,
        )

        data = self._make_data(n_days=5, initial_price=100.0)
        trades = [
            {"date": "2024-01-02", "action": "buy", "quantity": 100, "price": 101.0},
        ]
        result = _reconstruct_equity_curve(trades, data, 100000.0)
        assert len(result) == 5
        # Day 1 (2024-01-01): no trade yet, equity = 100000
        assert result[0]["value"] == 100000.0
        # Day 2 (2024-01-02): buy 100 @ 101, cash = 100000 - 10100 = 89900, position = 100
        # equity = 89900 + 100 * 101 = 89900 + 10100 = 100000
        assert result[1]["value"] == 100000.0
        # Day 3 (2024-01-03): price = 102, equity = 89900 + 100 * 102 = 89900 + 10200 = 100100
        assert result[2]["value"] == 100100.0

    def test_buy_and_sell(self):
        """Buy then sell: track cash through full cycle."""
        from llmwikify.reproduction.backtest_pkg.run_backtest import (
            _reconstruct_equity_curve,
        )

        data = self._make_data(n_days=5, initial_price=100.0)
        trades = [
            {"date": "2024-01-02", "action": "buy", "quantity": 100, "price": 101.0},
            {"date": "2024-01-04", "action": "sell", "quantity": 100, "price": 103.0},
        ]
        result = _reconstruct_equity_curve(trades, data, 100000.0)
        # Day 4 (2024-01-04): sell 100 @ 103, cash = 89900 + 10300 = 100200, position = 0
        assert result[3]["value"] == 100200.0
        # Day 5 (2024-01-05): no position, cash = 100200
        assert result[4]["value"] == 100200.0

    def test_dict_trades(self):
        """Trades as dicts with 'side' key (alternative format)."""
        from llmwikify.reproduction.backtest_pkg.run_backtest import (
            _reconstruct_equity_curve,
        )

        data = self._make_data(n_days=3, initial_price=100.0)
        trades = [
            {"date": "2024-01-01", "side": "buy", "qty": 50, "price": 100.0},
        ]
        result = _reconstruct_equity_curve(trades, data, 100000.0)
        # Day 1: buy 50 @ 100, cash = 100000 - 5000 = 95000, position = 50
        # equity = 95000 + 50 * 100 = 100000
        assert result[0]["value"] == 100000.0


# ─── DuckDB pipeline ───────────────────────────────────────────────────


class TestDuckDBPipeline:
    """End-to-end test for factor value storage."""

    def test_store_and_query(self):
        """Store factor values and query them back."""
        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            compute_and_store_factor,
            list_stored_factors,
            query_factor_values,
        )

        # Create test close_wide data
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        stocks = ["000001.SZ", "000002.SZ", "000003.SZ"]
        import numpy as np

        np.random.seed(42)
        data = np.random.randn(60, 3).cumsum(axis=0) + 100
        close_wide = pd.DataFrame(data, index=dates, columns=stocks)
        close_wide.index.name = "date"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"

            # Store
            rows = compute_and_store_factor(
                close_wide=close_wide,
                factor_name="test_momentum_20d",
                factor_class="momentum",
                factor_params={"period": 20},
                db_path=db_path,
            )
            assert rows > 0

            # Query
            result = query_factor_values("test_momentum_20d", db_path=db_path)
            assert len(result) == rows
            assert "date" in result.columns
            assert "stock" in result.columns
            assert "factor_name" in result.columns
            assert "value" in result.columns

            # List
            factors = list_stored_factors(db_path=db_path)
            assert len(factors) == 1
            assert factors[0]["factor_name"] == "test_momentum_20d"
            assert factors[0]["row_count"] == rows

    def test_empty_close_wide(self):
        """Empty close_wide returns 0 rows stored."""
        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            compute_and_store_factor,
        )

        close_wide = pd.DataFrame()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            rows = compute_and_store_factor(
                close_wide=close_wide,
                factor_name="test_empty",
                factor_class="momentum",
                factor_params={"period": 20},
                db_path=db_path,
            )
            assert rows == 0

    def test_upsert_no_duplicates(self):
        """Storing same factor twice does not create duplicates."""
        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            compute_and_store_factor,
            query_factor_values,
        )

        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        stocks = ["000001.SZ"]
        import numpy as np

        np.random.seed(42)
        data = np.random.randn(30, 1).cumsum(axis=0) + 100
        close_wide = pd.DataFrame(data, index=dates, columns=stocks)
        close_wide.index.name = "date"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            kwargs = dict(
                factor_name="test_upsert",
                factor_class="momentum",
                factor_params={"period": 10},
                db_path=db_path,
            )
            rows1 = compute_and_store_factor(close_wide=close_wide, **kwargs)
            rows2 = compute_and_store_factor(close_wide=close_wide, **kwargs)
            result = query_factor_values("test_upsert", db_path=db_path)
            # Should not double the rows (upsert behavior)
            assert len(result) == rows1
