"""Tests for BatchAggregator (P1 refactor).

Covers:
  - aggregate: 3 mock results → correct metrics (success-only, NaN-filtered)
  - aggregate: empty list → ic_mean=None
  - aggregate: all-NaN → ic_mean=None (Bug 7 副作用解决：拆分后 import math 只 1 次)
  - aggregate: Total = Success + Failed invariant
  - format_metric: None / 0.05 / NaN / positive / negative
  - format_metric: custom fmt / na
"""
from __future__ import annotations

import math

from scripts.run_101_alphas_v2 import BatchAggregator


class TestAggregate:
    def test_three_mixed_results(self) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01, "icir": 0.1, "ic_winrate": 0.51},
            {"status": "success", "alpha_index": 2, "ic_mean": 0.02, "icir": 0.2, "ic_winrate": 0.52},
            {"status": "failed", "alpha_index": 3, "stage": "react", "error": "boom"},
        ]
        agg = BatchAggregator.aggregate(results)
        assert agg["total"] == 3
        assert agg["success_count"] == 2
        assert agg["failed_count"] == 1
        assert agg["ic_mean"] == 0.015  # avg(0.01, 0.02) = 0.015
        assert agg["icir"] == 0.15
        assert agg["winrate"] == 0.515

    def test_empty_list(self) -> None:
        agg = BatchAggregator.aggregate([])
        assert agg["total"] == 0
        assert agg["success_count"] == 0
        assert agg["failed_count"] == 0
        assert agg["ic_mean"] is None
        assert agg["icir"] is None
        assert agg["winrate"] is None

    def test_all_nan_returns_none(self) -> None:
        """Bug 7 验证: NaN-safe 过滤（math.isnan）正确处理 None / NaN。"""
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": float("nan"),
             "icir": float("nan"), "ic_winrate": float("nan")},
            {"status": "success", "alpha_index": 2, "ic_mean": None,
             "icir": None, "ic_winrate": None},
        ]
        agg = BatchAggregator.aggregate(results)
        assert agg["success_count"] == 2
        assert agg["ic_mean"] is None
        assert agg["icir"] is None
        assert agg["winrate"] is None

    def test_partial_nan_filtered(self) -> None:
        """混合 NaN + 有效值：只 avg 有效值。"""
        results = [
            {"status": "success", "ic_mean": float("nan"), "icir": 0.1, "ic_winrate": 0.5},
            {"status": "success", "ic_mean": 0.02, "icir": float("nan"), "ic_winrate": 0.5},
            {"status": "success", "ic_mean": 0.04, "icir": 0.3, "ic_winrate": float("nan")},
        ]
        agg = BatchAggregator.aggregate(results)
        assert agg["ic_mean"] == 0.03  # avg(0.02, 0.04) = 0.03
        assert agg["icir"] == 0.2  # avg(0.1, 0.3)
        assert agg["winrate"] == 0.5  # avg(0.5, 0.5)

    def test_total_equals_success_plus_failed(self) -> None:
        """Total invariant regression test."""
        results = [
            {"status": "success", "ic_mean": 0.01, "icir": 0.1, "ic_winrate": 0.5},
            {"status": "failed", "stage": "x", "error": "y"},
            {"status": "failed", "stage": "x", "error": "z"},
            {"status": "success", "ic_mean": 0.02, "icir": 0.2, "ic_winrate": 0.5},
        ]
        agg = BatchAggregator.aggregate(results)
        assert agg["total"] == agg["success_count"] + agg["failed_count"]

    def test_rounded_to_4_decimals(self) -> None:
        results = [
            {"status": "success", "ic_mean": 0.012345, "icir": 0.1, "ic_winrate": 0.5},
        ]
        agg = BatchAggregator.aggregate(results)
        assert agg["ic_mean"] == 0.0123  # 4-decimal rounding


class TestFormatMetric:
    def test_none_returns_na(self) -> None:
        assert BatchAggregator.format_metric(None) == "  NaN"

    def test_nan_returns_na(self) -> None:
        assert BatchAggregator.format_metric(float("nan")) == "  NaN"

    def test_positive(self) -> None:
        assert BatchAggregator.format_metric(0.05) == "+0.0500"

    def test_negative(self) -> None:
        assert BatchAggregator.format_metric(-0.03) == "-0.0300"

    def test_zero(self) -> None:
        assert BatchAggregator.format_metric(0.0) == "+0.0000"

    def test_custom_fmt(self) -> None:
        assert BatchAggregator.format_metric(0.5, fmt=".2f") == "0.50"

    def test_custom_na(self) -> None:
        assert BatchAggregator.format_metric(None, na="N/A") == "N/A"

    def test_non_float_int(self) -> None:
        """Integer values are also handled (isinstance check covers int)."""
        assert BatchAggregator.format_metric(2) == "+2.0000"
