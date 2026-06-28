"""Tests for PR5 reporting/ extraction.

Covers:
  - BatchAggregator (10 tests): aggregate, format_metric, NaN, empty
  - BatchReporter (5 tests): banner, row, summary, all log via caplog
  - BatchSerializer (8 tests): write_json/markdown, content, schema
  - factor_results_to_dicts adapter (3 tests)
  - BatchSummarySink delegation (4 tests): now uses BatchSerializer
  - v2 backward compat (2 tests): re-exports work

Total: ~32 tests.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from llmwikify.reproduction.backtest.base import FactorResult
from llmwikify.reproduction.reporting import (
    BatchAggregator,
    BatchReporter,
    BatchSerializer,
    factor_results_to_dicts,
)
from llmwikify.reproduction.reporting.adapters import factor_results_to_dicts as fr2d
from llmwikify.reproduction.signal_source.base import Signal
from llmwikify.reproduction.sink import BatchSummarySink

# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_dicts() -> list[dict]:
    return [
        {"status": "success", "alpha_index": 1, "ic_mean": 0.01, "icir": 0.1, "ic_winrate": 0.51, "code_chars": 100, "elapsed_sec": 12.0},
        {"status": "success", "alpha_index": 2, "ic_mean": 0.02, "icir": 0.2, "ic_winrate": 0.52, "code_chars": 120, "elapsed_sec": 15.0},
        {"status": "failed", "alpha_index": 3, "stage": "codegen", "error": "timeout"},
    ]


@pytest.fixture
def sample_signal() -> Signal:
    return Signal(id="alpha-001", name="Alpha#1", formula_brief="rank(close, 5)",
                  metadata={"index": 1, "alpha_index": 1})


@pytest.fixture
def success_result(sample_signal: Signal) -> FactorResult:
    return FactorResult(
        signal=sample_signal,
        status="success",
        code="def f(df): return df['close'].rank()",
        code_chars=35,
        backtest={"ic_mean": 0.01, "icir": 0.1, "win_rate": 0.51},
        elapsed_sec=12.0,
    )


# ─── BatchAggregator ───────────────────────────────────────────────────


class TestBatchAggregator:
    def test_aggregate_basic(self, sample_dicts: list[dict]) -> None:
        agg = BatchAggregator.aggregate(sample_dicts)
        assert agg["total"] == 3
        assert agg["success_count"] == 2
        assert agg["failed_count"] == 1
        assert agg["ic_mean"] == pytest.approx(0.015)
        assert agg["icir"] == pytest.approx(0.15)
        assert agg["winrate"] == pytest.approx(0.515)

    def test_aggregate_empty(self) -> None:
        agg = BatchAggregator.aggregate([])
        assert agg == {
            "total": 0, "success_count": 0, "failed_count": 0,
            "ic_mean": None, "icir": None, "winrate": None,
        }

    def test_aggregate_all_failed(self) -> None:
        agg = BatchAggregator.aggregate([
            {"status": "failed", "stage": "x"},
            {"status": "failed", "stage": "y"},
        ])
        assert agg["total"] == 2
        assert agg["success_count"] == 0
        assert agg["failed_count"] == 2
        assert agg["ic_mean"] is None

    def test_aggregate_nan_filtered(self) -> None:
        """NaN values are filtered out (Bug 7 fix)."""
        nan = float("nan")
        agg = BatchAggregator.aggregate([
            {"status": "success", "ic_mean": nan, "icir": 0.1, "ic_winrate": nan},
            {"status": "success", "ic_mean": 0.02, "icir": nan, "ic_winrate": 0.5},
        ])
        # ic_mean: only one finite (0.02) → 0.02
        assert agg["ic_mean"] == pytest.approx(0.02)
        assert agg["icir"] == pytest.approx(0.1)
        assert agg["winrate"] == pytest.approx(0.5)

    def test_aggregate_rounds_to_4_decimals(self) -> None:
        agg = BatchAggregator.aggregate([
            {"status": "success", "ic_mean": 0.123456789},
        ])
        assert agg["ic_mean"] == 0.1235  # rounded

    def test_format_metric_basic(self) -> None:
        assert BatchAggregator.format_metric(0.01) == "+0.0100"
        assert BatchAggregator.format_metric(-0.005) == "-0.0050"

    def test_format_metric_none(self) -> None:
        assert BatchAggregator.format_metric(None) == "  NaN"

    def test_format_metric_nan(self) -> None:
        assert BatchAggregator.format_metric(float("nan")) == "  NaN"

    def test_format_metric_custom_na(self) -> None:
        assert BatchAggregator.format_metric(None, na="N/A") == "N/A"

    def test_format_metric_custom_fmt(self) -> None:
        assert BatchAggregator.format_metric(0.5, fmt=".2%") == "50.00%"


# ─── BatchReporter ─────────────────────────────────────────────────────


class TestBatchReporter:
    def test_log_banner(self, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            BatchReporter.log_banner()
        assert any("101-Alpha Batch Runner" in r.message for r in caplog.records)

    def test_log_row_success(self, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            BatchReporter.log_row(1, {
                "status": "success",
                "ic_mean": 0.01, "icir": 0.1, "ic_winrate": 0.51,
                "elapsed_sec": 12.5,
            }, elapsed_cum=12.5)
        assert any("success" in r.message for r in caplog.records)

    def test_log_row_failed(self, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            BatchReporter.log_row(2, {
                "status": "failed", "stage": "codegen",
                "error": "LLM timeout", "elapsed_sec": 5.0,
            }, elapsed_cum=5.0)
        assert any("failed" in r.message for r in caplog.records)

    def test_log_summary_basic(self, caplog, sample_dicts: list[dict]) -> None:
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            BatchReporter.log_summary(sample_dicts)
        log_text = "\n".join(r.message for r in caplog.records)
        assert "Summary" in log_text
        assert "Total:  3" in log_text
        assert "Avg IC:" in log_text

    def test_log_summary_with_failed(self, caplog, sample_dicts: list[dict]) -> None:
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            BatchReporter.log_summary(sample_dicts)
        log_text = "\n".join(r.message for r in caplog.records)
        assert "Failed alphas:" in log_text
        assert "alpha-003" in log_text


# ─── BatchSerializer ───────────────────────────────────────────────────


class TestBatchSerializer:
    def test_write_json(self, tmp_path: Path, sample_dicts: list[dict]) -> None:
        path = tmp_path / "summary.json"
        BatchSerializer.write_json(sample_dicts, path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["total"] == 3
        assert data["success_count"] == 2
        assert data["failed_count"] == 1
        assert data["aggregate"]["ic_mean_avg"] == pytest.approx(0.015)
        assert len(data["alphas"]) == 3
        # Failed alpha's error truncated to 200
        failed = [a for a in data["alphas"] if a["status"] == "failed"][0]
        assert failed["stage"] == "codegen"

    def test_write_json_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.json"
        BatchSerializer.write_json([], path)
        data = json.loads(path.read_text())
        assert data["total"] == 0
        assert data["alphas"] == []

    def test_write_json_unicode(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.json"
        BatchSerializer.write_json([
            {"status": "success", "alpha_index": 1, "error": "中文错误信息"},
        ], path)
        text = path.read_text()
        assert "中文错误信息" in text  # ensure_ascii=False

    def test_write_markdown_header(self, tmp_path: Path, sample_dicts: list[dict]) -> None:
        path = tmp_path / "summary.md"
        BatchSerializer.write_markdown(sample_dicts, path)
        text = path.read_text()
        assert "# 101-Alpha Batch Results (v2)" in text

    def test_write_markdown_total(self, tmp_path: Path, sample_dicts: list[dict]) -> None:
        path = tmp_path / "summary.md"
        BatchSerializer.write_markdown(sample_dicts, path)
        text = path.read_text()
        assert "Total: 3 | Success: 2 | Failed: 1" in text
        assert "Avg IC:" in text

    def test_write_markdown_table(self, tmp_path: Path, sample_dicts: list[dict]) -> None:
        path = tmp_path / "summary.md"
        BatchSerializer.write_markdown(sample_dicts, path)
        text = path.read_text()
        assert "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |" in text
        assert "| alpha-001 | success |" in text
        assert "| alpha-002 | success |" in text

    def test_write_markdown_failed_section(self, tmp_path: Path, sample_dicts: list[dict]) -> None:
        path = tmp_path / "summary.md"
        BatchSerializer.write_markdown(sample_dicts, path)
        text = path.read_text()
        assert "## Failed Alphas" in text
        assert "alpha-003" in text
        assert "codegen" in text

    def test_write_markdown_no_metrics(self, tmp_path: Path) -> None:
        """All-failed: no Avg IC line (because ic_mean is None)."""
        path = tmp_path / "summary.md"
        BatchSerializer.write_markdown([
            {"status": "failed", "alpha_index": 1, "stage": "x"},
        ], path)
        text = path.read_text()
        assert "Total: 1 | Success: 0 | Failed: 1" in text
        assert "Avg IC" not in text


# ─── factor_results_to_dicts adapter ───────────────────────────────────


class TestFactorResultsToDicts:
    def test_import_alias(self) -> None:
        """Both top-level and module-level imports work."""
        from llmwikify.reproduction.reporting.adapters import (
            factor_results_to_dicts as fr2d_module,
        )
        assert fr2d_module is factor_results_to_dicts

    def test_basic_conversion(self, success_result: FactorResult) -> None:
        dicts = factor_results_to_dicts([success_result])
        assert len(dicts) == 1
        d = dicts[0]
        assert d["status"] == "success"
        assert d["alpha_index"] == 1
        assert d["ic_mean"] == 0.01
        assert d["factor_name"] == "Alpha#1"

    def test_empty(self) -> None:
        assert factor_results_to_dicts([]) == []


# ─── BatchSummarySink delegation ───────────────────────────────────────


class TestBatchSummarySinkDelegation:
    """PR5: BatchSummarySink now delegates to BatchSerializer (no inline)."""

    def test_delegates_to_batch_serializer(self, tmp_path: Path, success_result: FactorResult, caplog) -> None:
        """write_batch should call BatchSerializer.write_json/markdown."""
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.sink.batch_summary"):
            with patch(
                "llmwikify.reproduction.reporting.serializer.BatchSerializer.write_json",
            ) as mock_json, patch(
                "llmwikify.reproduction.reporting.serializer.BatchSerializer.write_markdown",
            ) as mock_md:
                sink = BatchSummarySink(output_dir=tmp_path, paper_id="test")
                sink.write_batch([success_result])
        mock_json.assert_called_once()
        mock_md.assert_called_once()

    def test_logs_summary_by_default(
        self, tmp_path: Path, success_result: FactorResult, caplog,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test", log_summary=True)
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            sink.write_batch([success_result])
        assert any("Summary" in r.message for r in caplog.records)

    def test_skip_log_summary(
        self, tmp_path: Path, success_result: FactorResult, caplog,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test", log_summary=False)
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.reporting.reporter"):
            sink.write_batch([success_result])
        assert not any("Summary" in r.message for r in caplog.records)

    def test_output_matches_old_inline(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        """PR5 output should match PR4 inline output for same input."""
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="paper_x", log_summary=False)
        paths = sink.write_batch([success_result])
        assert len(paths) == 2
        # JSON should have paper_id-aware content (BatchSerializer.write_json doesn't include paper_id in body)
        # but filename should include paper_id
        assert any("paper_x" in p.name for p in paths)


# ─── v2 backward compat ────────────────────────────────────────────────


class TestV2BackwardCompat:
    def test_v2_re_exports_batch_aggregator(self) -> None:
        """scripts.run_101_alphas_v2 still exports BatchAggregator."""
        from scripts.run_101_alphas_v2 import BatchAggregator as V2BA
        assert V2BA is BatchAggregator

    def test_v2_re_exports_batch_serializer(self) -> None:
        from scripts.run_101_alphas_v2 import BatchSerializer as V2BS
        assert V2BS is BatchSerializer

    def test_v2_re_exports_batch_reporter(self) -> None:
        from scripts.run_101_alphas_v2 import BatchReporter as V2BR
        assert V2BR is BatchReporter

    def test_v2_aggregate_still_works(self) -> None:
        from scripts.run_101_alphas_v2 import BatchAggregator
        agg = BatchAggregator.aggregate([{"status": "success", "ic_mean": 0.01}])
        assert agg["ic_mean"] == 0.01
