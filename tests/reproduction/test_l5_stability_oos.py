"""Tests for L5 stability and OOS improvements."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llmwikify.reproduction.backtest_pkg.l5_validation import (
    analyze_oos,
    analyze_stability,
    compute_score,
    run_l5_validation,
    _score_stability,
    _score_oos,
)


def _make_ic_series(n=100, ic_values=None, start_date="2023-01-01"):
    """Create a mock IC series for testing."""
    import datetime
    if ic_values is None:
        ic_values = [0.02] * n
    base = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    series = []
    for i, ic in enumerate(ic_values):
        d = base + datetime.timedelta(days=i)
        series.append({"date": d.strftime("%Y-%m-%d"), "ic": ic})
    return series


def _make_longshort_curve(n=100, start_value=1.0, daily_return=0.001):
    """Create a mock long-short equity curve."""
    import datetime
    base = datetime.datetime.strptime("2023-01-01", "%Y-%m-%d")
    curve = []
    value = start_value
    for i in range(n):
        d = base + datetime.timedelta(days=i)
        curve.append({"date": d.strftime("%Y-%m-%d"), "value": round(value, 4)})
        value *= (1 + daily_return)
    return curve


def _make_result(ic_series=None, longshort_curve=None, **kwargs):
    """Create a mock FactorBacktestResult."""
    if ic_series is None:
        ic_series = _make_ic_series()
    return SimpleNamespace(
        ic_series=ic_series,
        longshort_curve=longshort_curve or [],
        longshort_sharpe=kwargs.get("longshort_sharpe", 1.0),
        longshort_mdd=kwargs.get("longshort_mdd", 0.1),
        ic_mean=kwargs.get("ic_mean", 0.02),
        ic_std=kwargs.get("ic_std", 0.01),
        icir=kwargs.get("icir", 2.0),
        t_stat=kwargs.get("t_stat", 3.0),
        win_rate=kwargs.get("win_rate", 0.6),
        annual_return=kwargs.get("annual_return", 0.1),
        max_drawdown=kwargs.get("max_drawdown", 0.15),
        turnover=kwargs.get("turnover", 0.3),
        quantile_returns=kwargs.get("quantile_returns", {}),
        group_metrics=kwargs.get("group_metrics", {}),
        n_stocks_per_date=kwargs.get("n_stocks_per_date", []),
        total_rebalances=kwargs.get("total_rebalances", 100),
        valid_rebalances=kwargs.get("valid_rebalances", 100),
    )


# ─── analyze_stability ─────────────────────────────────────────────────


class TestAnalyzeStability:
    def test_empty_ic_series(self):
        result = _make_result(ic_series=[])
        stability = analyze_stability(result)
        assert stability["yearly"] == {}
        assert stability["rolling_ic"] == {}
        assert stability["ic_decay"] == {}

    def test_yearly_breakdown(self):
        """IC series spanning 2 years produces yearly breakdown."""
        ic_values = [0.02] * 250 + [-0.01] * 250  # 2 years
        result = _make_result(ic_series=_make_ic_series(n=500, ic_values=ic_values))
        stability = analyze_stability(result)
        assert len(stability["yearly"]) == 2
        assert "2023" in stability["yearly"]
        assert "2024" in stability["yearly"]

    def test_rolling_ic_20d(self):
        """Rolling 20d IC computed when enough data."""
        result = _make_result(ic_series=_make_ic_series(n=60))
        stability = analyze_stability(result)
        assert "rolling_20d" in stability["rolling_ic"]
        r20 = stability["rolling_ic"]["rolling_20d"]
        assert "mean" in r20
        assert "std" in r20
        assert "positive_ratio" in r20

    def test_rolling_ic_insufficient_data(self):
        """Rolling IC not computed when insufficient data."""
        result = _make_result(ic_series=_make_ic_series(n=15))
        stability = analyze_stability(result)
        assert "rolling_20d" not in stability["rolling_ic"]

    def test_ic_decay(self):
        """IC decay computed when enough data."""
        # First half: high IC, second half: low IC
        ic_values = [0.05] * 50 + [0.01] * 50
        result = _make_result(ic_series=_make_ic_series(n=100, ic_values=ic_values))
        stability = analyze_stability(result)
        assert "ic_decay" in stability
        decay = stability["ic_decay"]
        assert decay["first_half_ic"] > decay["second_half_ic"]
        assert decay["is_stable"] is False  # decay_ratio < 0.5

    def test_ic_decay_stable(self):
        """IC is stable when second half retains >50%."""
        ic_values = [0.03] * 50 + [0.02] * 50
        result = _make_result(ic_series=_make_ic_series(n=100, ic_values=ic_values))
        stability = analyze_stability(result)
        decay = stability["ic_decay"]
        assert decay["is_stable"] is True


class TestScoreStability:
    def test_high_score_stable_factor(self):
        """Stable factor gets high stability score."""
        stability = {
            "yearly": {
                "2022": {"rank_ic": 0.03, "n_obs": 250},
                "2023": {"rank_ic": 0.02, "n_obs": 250},
                "2024": {"rank_ic": 0.025, "n_obs": 250},
            },
            "rolling_ic": {
                "rolling_20d": {"mean": 0.025, "std": 0.01, "positive_ratio": 0.85},
            },
            "ic_decay": {
                "first_half_ic": 0.03,
                "second_half_ic": 0.025,
                "decay_ratio": 0.83,
                "is_stable": True,
            },
        }
        score = _score_stability(stability)
        assert score >= 8

    def test_low_score_unstable_factor(self):
        """Unstable factor gets low stability score."""
        stability = {
            "yearly": {
                "2022": {"rank_ic": 0.03, "n_obs": 250},
                "2023": {"rank_ic": -0.02, "n_obs": 250},
            },
            "rolling_ic": {
                "rolling_20d": {"mean": 0.005, "std": 0.1, "positive_ratio": 0.45},
            },
            "ic_decay": {
                "first_half_ic": 0.03,
                "second_half_ic": 0.005,
                "decay_ratio": 0.17,
                "is_stable": False,
            },
        }
        score = _score_stability(stability)
        assert score <= 5


# ─── analyze_oos ───────────────────────────────────────────────────────


class TestAnalyzeOos:
    def test_empty_ic_series(self):
        result = _make_result(ic_series=[])
        oos = analyze_oos(result)
        assert oos["oos_rank_ic"] == 0.0
        assert oos["kfold"] == {}

    def test_70_30_split_backward_compatible(self):
        """70/30 split still works."""
        result = _make_result(ic_series=_make_ic_series(n=100))
        oos = analyze_oos(result)
        assert "oos_rank_ic" in oos
        assert "oos_ls_return" in oos
        assert "oos_sharpe" in oos

    def test_kfold_produces_results(self):
        """K-fold cross-validation produces results."""
        ic_values = [0.02 + (i % 10) * 0.001 for i in range(100)]
        result = _make_result(
            ic_series=_make_ic_series(n=100, ic_values=ic_values),
            longshort_curve=_make_longshort_curve(n=100),
        )
        oos = analyze_oos(result, n_folds=5)
        assert "kfold" in oos
        kfold = oos["kfold"]
        assert kfold["n_folds"] == 5
        assert "oos_ic_mean" in kfold
        assert "oos_ic_std" in kfold
        assert "oos_ic_positive_ratio" in kfold
        assert "is_robust" in kfold

    def test_kfold_robust_when_all_positive(self):
        """K-fold is robust when all OOS ICs are positive."""
        ic_values = [0.02] * 100  # All positive
        result = _make_result(
            ic_series=_make_ic_series(n=100, ic_values=ic_values),
            longshort_curve=_make_longshort_curve(n=100),
        )
        oos = analyze_oos(result, n_folds=5)
        assert oos["kfold"]["is_robust"] is True
        assert oos["kfold"]["oos_ic_positive_ratio"] == 1.0

    def test_kfold_not_robust_when_mixed(self):
        """K-fold not robust when OOS ICs are mixed."""
        ic_values = [0.05] * 50 + [-0.05] * 50  # Mixed signs
        result = _make_result(
            ic_series=_make_ic_series(n=100, ic_values=ic_values),
            longshort_curve=_make_longshort_curve(n=100),
        )
        oos = analyze_oos(result, n_folds=5)
        assert oos["kfold"]["is_robust"] is False


class TestScoreOos:
    def test_high_score_robust_oos(self):
        """Robust OOS gets high score."""
        oos = {
            "oos_rank_ic": 0.035,
            "kfold": {
                "is_robust": True,
                "oos_ic_positive_ratio": 1.0,
                "oos_ic_mean": 0.03,
            },
        }
        score = _score_oos(oos)
        assert score >= 8

    def test_low_score_weak_oos(self):
        """Weak OOS gets low score."""
        oos = {
            "oos_rank_ic": 0.0,
            "kfold": {
                "is_robust": False,
                "oos_ic_positive_ratio": 0.3,
                "oos_ic_mean": 0.005,
            },
        }
        score = _score_oos(oos)
        assert score <= 4


# ─── run_l5_validation integration ─────────────────────────────────────


class TestRunL5Validation:
    def test_output_includes_new_fields(self):
        """L5 validation output includes rolling_ic, ic_decay, kfold."""
        ic_values = [0.02 + (i % 10) * 0.001 for i in range(100)]
        result = _make_result(
            ic_series=_make_ic_series(n=100, ic_values=ic_values),
            longshort_curve=_make_longshort_curve(n=100),
        )
        l5 = run_l5_validation(result, n_folds=5)
        stability = l5["factor_analysis"]["stability_analysis"]
        oos = l5["factor_analysis"]["oos_analysis"]

        # Stability has new fields
        assert "rolling_ic" in stability
        assert "ic_decay" in stability

        # OOS has kfold
        assert "kfold" in oos

    def test_score_computed(self):
        """Score is computed from new analysis results."""
        result = _make_result(ic_series=_make_ic_series(n=100))
        l5 = run_l5_validation(result)
        assert l5["overall_assessment"]["score"] > 0
        assert l5["overall_assessment"]["status"] in ("通过", "失败", "待更新")
