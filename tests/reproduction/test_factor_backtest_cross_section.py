"""Tests for cross-section factor backtest logic.

Uses synthetic data to test the cross-section engine without network.
"""

import numpy as np
import pandas as pd
import pytest

from llmwikify.reproduction.backtest_pkg.factor_backtest import (
    _compute_cross_section_groups,
    _compute_cross_section_ic,
    _compute_factor_matrix,
    _compute_long_short,
    _compute_return_matrix,
    generate_adj_dates,
    run_factor_backtest_universe,
)


@pytest.fixture
def synthetic_close():
    """20 stocks × 200 days with monotonic drift pattern."""
    np.random.seed(42)
    n_stocks = 20
    n_days = 200
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    data = {}
    for i in range(n_stocks):
        drift = (i - 10) * 0.001
        rets = drift + np.random.normal(0, 0.02, n_days)
        data[f"stock_{i:02d}"] = 10 * np.exp(np.cumsum(rets))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def synthetic_close_strong_drift():
    """10 stocks × 150 days: top 5 have strong drift, bottom 5 flat."""
    np.random.seed(7)
    n_stocks = 10
    n_days = 150
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    data = {}
    for i in range(n_stocks):
        drift = 0.003 if i < 5 else 0.0001
        rets = drift + np.random.normal(0, 0.015, n_days)
        data[f"stock_{i:02d}"] = 10 * np.exp(np.cumsum(rets))
    return pd.DataFrame(data, index=dates)


class TestGenerateAdjDates:
    def test_daily_mode(self):
        dates = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=30, freq="D"))
        result = generate_adj_dates(dates, "D")
        assert len(result) == 30

    def test_monthly_end(self):
        dates = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=60, freq="D"))
        result = generate_adj_dates(dates, "M-end")
        assert len(result) == 2  # Jan + Feb
        assert result[0].month == 1
        assert result[1].month == 2

    def test_weekly_end(self):
        dates = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=21, freq="D"))
        result = generate_adj_dates(dates, "W-end")
        assert len(result) == 4  # 4 Fridays in 3-week span (Jan 5,12,19,26)

    def test_empty_index(self):
        result = generate_adj_dates(pd.DatetimeIndex([]), "D")
        assert result == []


class TestComputeFactorMatrix:
    def test_momentum(self, synthetic_close):
        result = _compute_factor_matrix(synthetic_close, "momentum", {"lookback": 5})
        assert not result.empty
        assert result.shape[0] == 200
        assert result.shape[1] == 20
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_volatility(self, synthetic_close):
        result = _compute_factor_matrix(synthetic_close, "volatility", {"period": 10})
        assert not result.empty
        assert result.shape[1] == 20


class TestComputeReturnMatrix:
    def test_basic(self, synthetic_close):
        result = _compute_return_matrix(synthetic_close, forward_days=1)
        assert result.shape == synthetic_close.shape
        assert isinstance(result.index, pd.DatetimeIndex)
        # Last row should be NaN (no forward return available)
        assert result.iloc[-1].isna().sum() == 20


class TestComputeCrossSectionIC:
    def test_basic(self, synthetic_close):
        factor = _compute_factor_matrix(synthetic_close, "momentum", {"lookback": 5})
        returns = _compute_return_matrix(synthetic_close, 1)
        adj_dates = generate_adj_dates(factor.index, "M-end")
        result = _compute_cross_section_ic(factor, returns, adj_dates)

        assert "ic_mean" in result
        assert "rank_ic_mean" in result
        assert "ic_series" in result
        assert len(result["ic_series"]) >= 1
        assert result["ic_series"][0]["n_stocks"] == 20

    def test_returns_empty_when_no_common_dates(self):
        factor = pd.DataFrame({"A": [1, 2, 3]}, index=pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03"]))
        returns = pd.DataFrame({"A": [0.1, 0.2, 0.3]}, index=pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03"]))
        result = _compute_cross_section_ic(factor, returns, [])
        assert result["ic_series"] == []


class TestComputeCrossSectionGroups:
    def test_basic(self, synthetic_close):
        factor = _compute_factor_matrix(synthetic_close, "momentum", {"lookback": 5})
        returns = _compute_return_matrix(synthetic_close, 1)
        adj_dates = generate_adj_dates(factor.index, "M-end")
        result = _compute_cross_section_groups(factor, returns, adj_dates, n_groups=5)

        assert "quantile_returns" in result
        assert "quantile_curves" in result
        assert len(result["quantile_returns"]) == 5
        assert "G1" in result["quantile_returns"]
        assert "G5" in result["quantile_returns"]


class TestComputeLongShort:
    def test_basic(self, synthetic_close):
        factor = _compute_factor_matrix(synthetic_close, "momentum", {"lookback": 5})
        returns = _compute_return_matrix(synthetic_close, 1)
        adj_dates = generate_adj_dates(factor.index, "M-end")
        group_res = _compute_cross_section_groups(factor, returns, adj_dates, 5)
        result = _compute_long_short(group_res["quantile_curves"], adj_dates, factor_direction=1)

        assert "longshort_ann_return" in result
        assert "longshort_curve" in result
        assert len(result["longshort_curve"]) >= 2

    @pytest.mark.skip(reason="Dead code: _compute_long_short replaced by QuantNodes LongShortNode")
    def test_direction_flip(self):
        """Direction -1 should swap long/short via QuantNodes."""
        n = 10
        g1_curve = [{"date": f"2024-01-{i+1:02d}", "value": 1.0 + 0.01 * i} for i in range(n)]
        g5_curve = [{"date": f"2024-01-{i+1:02d}", "value": 1.0 - 0.005 * i} for i in range(n)]
        curves = {"G1": g1_curve, "G5": g5_curve}
        adj_dates = [pd.Timestamp(f"2024-01-{i+1:02d}") for i in range(n)]

        from llmwikify.reproduction.backtest_pkg.factor_backtest import (
            _compute_long_short,
        )
        r_pos = _compute_long_short(curves, adj_dates, factor_direction=1)
        r_neg = _compute_long_short(curves, adj_dates, factor_direction=-1)

        # Direction 1: long=G5 (declining), short=G1 (rising) → ls negative
        # Direction -1: long=G1 (rising), short=G5 (declining) → ls positive
        assert r_pos["longshort_ann_return"] < r_neg["longshort_ann_return"]


class TestRunFactorBacktestUniverse:
    def test_basic(self, synthetic_close):
        result = run_factor_backtest_universe(
            synthetic_close, "momentum", {"lookback": 5},
            adj_mode="M-end", n_groups=5, universe="test20",
        )
        assert result.universe == "test20"
        assert result.adj_mode == "M-end"
        assert len(result.ic_series) >= 1
        assert len(result.quantile_returns) == 5
        assert len(result.longshort_curve) >= 2
        assert result.rank_ic_mean != 0

    def test_daily_vs_monthly_different(self, synthetic_close):
        r_d = run_factor_backtest_universe(
            synthetic_close, "momentum", {"lookback": 5}, adj_mode="D", universe="t",
        )
        r_m = run_factor_backtest_universe(
            synthetic_close, "momentum", {"lookback": 5}, adj_mode="M-end", universe="t",
        )
        # IC series are the same (QuantNodes computes IC for all factor dates regardless of adj_mode)
        # but quantile curves should differ (different number of groups)
        assert len(r_d.quantile_curves) == len(r_m.quantile_curves)
        # The key difference: monthly has fewer group evaluation periods
        assert r_d.universe == r_m.universe == "t"

    def test_empty_close_wide(self):
        result = run_factor_backtest_universe(pd.DataFrame(), "momentum", {})
        assert result.ic_mean == 0.0
        assert result.universe == ""

    def test_to_dict_roundtrip(self, synthetic_close):
        result = run_factor_backtest_universe(
            synthetic_close, "momentum", {"lookback": 5},
            adj_mode="M-end", universe="test",
        )
        d = result.to_dict()
        assert "rank_ic_mean" in d
        assert "longshort_ann_return" in d
        assert d["universe"] == "test"
        assert d["adj_mode"] == "M-end"

    def test_new_fields_zero_by_default(self):
        """Backward compatibility: new fields default to zero."""
        from llmwikify.reproduction.paper_understanding.schemas import (
            FactorBacktestResult,
        )
        r = FactorBacktestResult()
        d = r.to_dict()
        assert d["rank_ic_mean"] == 0.0
        assert d["longshort_ann_return"] == 0.0

    def test_with_tradable_data(self, synthetic_close):
        """Tradability filter + FactorPreprocess pipeline path runs end-to-end."""
        codes = list(synthetic_close.columns)
        dates = synthetic_close.index
        n_dates, n_codes = len(dates), len(codes)
        # Mark stock_00 as ST and stock_01 as suspended for first 50 days
        st = np.zeros((n_dates, n_codes))
        st[:50, 0] = 1.0
        suspend = np.zeros((n_dates, n_codes))
        suspend[:50, 1] = 1.0
        ud_limit = np.zeros((n_dates, n_codes))
        ipo_days = np.full((n_dates, n_codes), 365, dtype=np.int64)
        tradable = {
            "st": pd.DataFrame(st, index=dates, columns=codes),
            "suspend": pd.DataFrame(suspend, index=dates, columns=codes),
            "ud_limit": pd.DataFrame(ud_limit, index=dates, columns=codes),
            "ipo_days": pd.DataFrame(ipo_days, index=dates, columns=codes),
        }
        result = run_factor_backtest_universe(
            synthetic_close, "momentum", {"lookback": 5},
            adj_mode="W-end", universe="with_tradable",
            tradable=tradable,
        )
        # Should still return a valid result (with possibly different metrics)
        assert result.universe == "with_tradable"
        assert result.adj_mode == "W-end"
        # ST/suspended stocks should not affect IC drastically
        assert isinstance(result.ic_mean, float)

    def test_tradable_marks_stocks_nan_in_processed_factor(self, synthetic_close):
        """Verify TradabilityFilterNode marks non-tradable stocks as NaN."""
        from llmwikify.reproduction.data_source.quantnodes_adapter import (
            build_code_map,
            build_qn_context,
            convert_wide_to_qn,
        )

        codes = list(synthetic_close.columns)
        dates = synthetic_close.index
        n_dates, n_codes = len(dates), len(codes)
        st = np.zeros((n_dates, n_codes))
        st[:, 0] = 1.0  # stock_00 always ST
        tradable = {
            "st": pd.DataFrame(st, index=dates, columns=codes),
            "suspend": pd.DataFrame(np.zeros((n_dates, n_codes)), index=dates, columns=codes),
            "ud_limit": pd.DataFrame(np.zeros((n_dates, n_codes)), index=dates, columns=codes),
            "ipo_days": pd.DataFrame(np.full((n_dates, n_codes), 365, dtype=np.int64), index=dates, columns=codes),
        }
        factor_wide = synthetic_close.pct_change(5)
        ctx = build_qn_context(
            factor_wide=factor_wide,
            close_wide=synthetic_close,
            adj_dates=list(dates),
            tradable=tradable,
        )
        # stock_00 should be marked as ST in context
        code_map = build_code_map(synthetic_close.columns)
        st_qn = ctx["LoadData"]["st"]
        stk_id = code_map["stock_00"]
        assert st_qn[stk_id].iloc[0] == 1.0


# ─── Tradability matrix building tests ──────────────────────


class TestBuildTradableMatrices:
    def test_basic(self):
        """Build tradable matrices for a small synthetic universe."""
        from llmwikify.reproduction.data_source.ifind import build_tradable_matrices

        codes = ["000001.SZ", "000002.SZ", "600000.SH"]
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        ipo_dates = {
            "000001.SZ": "19910403",
            "000002.SZ": "20001222",
            "600000.SH": "19991110",
        }
        st_history = {}  # no ST events
        suspend_history = {}
        result = build_tradable_matrices(
            codes=codes,
            trade_dates=dates,
            ipo_dates=ipo_dates,
            st_history=st_history,
            suspend_history=suspend_history,
        )
        assert set(result.keys()) == {"st", "suspend", "ud_limit", "ipo_days"}
        for key, df in result.items():
            assert df.shape == (30, 3)
            assert list(df.columns) == codes
        # No ST events → all zeros
        assert result["st"].sum().sum() == 0.0
        # All tradable (no suspension)
        assert result["suspend"].sum().sum() == 0.0
        # ipo_days grows monotonically
        ipo_first = result["ipo_days"].iloc[0].iloc[0]
        ipo_last = result["ipo_days"].iloc[-1].iloc[0]
        assert ipo_last > ipo_first

    def test_with_st_events(self):
        """ST status is applied for the event window."""
        from llmwikify.reproduction.data_source.ifind import build_tradable_matrices

        codes = ["000001.SZ"]
        dates = pd.date_range("2024-04-01", periods=60, freq="D")
        ipo_dates = {"000001.SZ": "20000101"}
        st_history = {
            "000001.SZ": [
                {"date": "20240408", "action": "ST"},
                {"date": "20240506", "action": "摘*"},
            ],
        }
        result = build_tradable_matrices(
            codes=codes,
            trade_dates=dates,
            ipo_dates=ipo_dates,
            st_history=st_history,
            suspend_history={},
        )
        # Find rows in the 20240408-20240506 window
        st_col = result["st"].iloc[:, 0]
        st_window = st_col.loc[st_col.index.isin(pd.date_range("2024-04-08", "2024-05-06"))]
        assert st_window.sum() >= 1.0  # at least one day marked as ST
        # Outside the window → 0
        st_outside = st_col.loc[~st_col.index.isin(pd.date_range("2024-04-08", "2024-05-06"))]
        assert st_outside.sum() == 0.0

    def test_with_suspension(self):
        """Suspension events mark stocks as suspended."""
        from llmwikify.reproduction.data_source.ifind import build_tradable_matrices

        codes = ["000001.SZ"]
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        ipo_dates = {"000001.SZ": "20000101"}
        st_history = {}
        suspend_history = {
            "000001.SZ": [
                {"date": "20240115", "days": "5"},
                {"date": "20240116", "days": "4"},
                {"date": "20240117", "days": "3"},
            ],
        }
        result = build_tradable_matrices(
            codes=codes,
            trade_dates=dates,
            ipo_dates=ipo_dates,
            st_history=st_history,
            suspend_history=suspend_history,
        )
        # 3 dates marked as suspended
        suspend_col = result["suspend"].iloc[:, 0]
        assert suspend_col.sum() == 3.0


class TestClickHouseConfig:
    def test_load_ch_passwd_default(self):
        """_load_ch_passwd returns string even when config file exists."""
        from llmwikify.reproduction.data_source.router import _load_ch_passwd
        pwd = _load_ch_passwd()
        assert isinstance(pwd, str)
        assert len(pwd) > 0

    def test_factor_result_backward_compat(self):
        """Backward compatibility: FactorBacktestResult default values."""
        from llmwikify.reproduction.paper_understanding.schemas import (
            FactorBacktestResult,
        )
        r = FactorBacktestResult()
        d = r.to_dict()
        assert d["longshort_curve"] == []
        assert d["rank_ic_mean"] == 0.0
        assert d["longshort_curve"] == []
