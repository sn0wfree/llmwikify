"""Tests for PR4 Sink abstraction + 3 implementations.

Covers:
  - Sink Protocol (2 tests): structural typing
  - SingleJsonSink (8 tests): write_one, id sanitization, success/failed
  - YamlDuckdbSink (6 tests): skip failed, calls persist_code_to_yaml
  - BatchSummarySink (10 tests): aggregate JSON/MD, NaN handling, empty results

Total: ~26 tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from llmwikify.reproduction.backtest.base import FactorResult
from llmwikify.reproduction.signal_source.base import Signal
from llmwikify.reproduction.sink import (
    BatchSummarySink,
    SingleJsonSink,
    Sink,
    YamlDuckdbSink,
)

# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def success_result() -> FactorResult:
    sig = Signal(id="alpha-001", name="Alpha#1", formula_brief="rank(close, 5)",
                 metadata={"index": 1, "alpha_index": 1})
    return FactorResult(
        signal=sig,
        status="success",
        code="def f(df): return df['close'].rank()",
        code_chars=35,
        factor_series=pl.Series("s", [1.0, 2.0, 3.0]),
        h5_path=Path("/tmp/alpha_001.h5"),
        backtest={"ic_mean": 0.01, "icir": 0.1, "win_rate": 0.51},
        elapsed_sec=12.5,
    )


@pytest.fixture
def failed_result() -> FactorResult:
    sig = Signal(id="alpha-002", name="Alpha#2", formula_brief="x")
    return FactorResult(
        signal=sig,
        status="failed",
        stage="codegen",
        error="LLM timeout",
        elapsed_sec=5.0,
    )


# ─── Sink Protocol ─────────────────────────────────────────────────────


class TestSinkProtocol:
    def test_all_sinks_satisfy_protocol(self) -> None:
        """All 3 concrete sinks have write_one / write_batch / flush methods."""
        sinks = [
            SingleJsonSink(output_dir=Path("/tmp")),
            YamlDuckdbSink(factors_dir=Path("/tmp")),
            BatchSummarySink(output_dir=Path("/tmp")),
        ]
        for sink in sinks:
            assert hasattr(sink, "write_one")
            assert hasattr(sink, "write_batch")
            assert hasattr(sink, "flush")

    def test_default_write_batch_returns_empty(self) -> None:
        """Sink with explicit empty write_batch returns []."""

        class MinimalSink:
            def write_one(self, result):
                return Path("/dev/null")

            def write_batch(self, results):
                return []

        s = MinimalSink()
        assert s.write_batch([]) == []


# ─── SingleJsonSink ────────────────────────────────────────────────────


class TestSingleJsonSink:
    def test_write_one_creates_file(self, tmp_path: Path, success_result: FactorResult) -> None:
        sink = SingleJsonSink(output_dir=tmp_path)
        out = sink.write_one(success_result)
        assert out.exists()
        assert out.name == "single_factor_alpha-001.json"

    def test_write_one_creates_parent_dir(self, tmp_path: Path, success_result: FactorResult) -> None:
        nested = tmp_path / "deep" / "nested"
        sink = SingleJsonSink(output_dir=nested)
        out = sink.write_one(success_result)
        assert out.exists()

    def test_write_one_json_content(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        sink = SingleJsonSink(output_dir=tmp_path)
        out = sink.write_one(success_result)
        data = json.loads(out.read_text())
        assert data["status"] == "success"
        assert data["code_chars"] == 35
        assert data["ic_mean"] == 0.01
        assert data["alpha_index"] == 1  # from metadata

    def test_write_one_sanitizes_slashes(
        self, tmp_path: Path,
    ) -> None:
        """signal.id with slashes should be sanitized in filename."""
        sig = Signal(id="1601/path/alpha-001", name="x", formula_brief="x")
        result = FactorResult(signal=sig, status="success", code="x", code_chars=1)
        sink = SingleJsonSink(output_dir=tmp_path)
        out = sink.write_one(result)
        # No nested dirs created — slashes replaced with _
        assert out.exists()
        assert "/" not in out.name
        assert "\\" not in out.name

    def test_write_one_unicode_name(
        self, tmp_path: Path,
    ) -> None:
        """Chinese name should serialize correctly (ensure_ascii=False)."""
        sig = Signal(id="signal-001", name="板块轮动周期表", formula_brief="x")
        result = FactorResult(
            signal=sig, status="success", code="x", code_chars=1,
            backtest={"ic_mean": 0.01},
        )
        sink = SingleJsonSink(output_dir=tmp_path)
        out = sink.write_one(result)
        text = out.read_text()
        assert "板块轮动周期表" in text  # ensure_ascii=False

    def test_write_one_failed_status(
        self, tmp_path: Path, failed_result: FactorResult,
    ) -> None:
        """Failed signals should still write JSON (mirrors v2 behavior)."""
        sink = SingleJsonSink(output_dir=tmp_path)
        out = sink.write_one(failed_result)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["status"] == "failed"
        assert data["stage"] == "codegen"

    def test_write_batch_returns_empty(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        sink = SingleJsonSink(output_dir=tmp_path)
        assert sink.write_batch([success_result]) == []

    def test_flush_is_noop(self, tmp_path: Path) -> None:
        sink = SingleJsonSink(output_dir=tmp_path)
        assert sink.flush() is None


# ─── YamlDuckdbSink ────────────────────────────────────────────────────


class TestYamlDuckdbSink:
    def test_instantiation(self, tmp_path: Path) -> None:
        sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
        assert sink.factors_dir == tmp_path

    def test_skip_failed_signal(
        self, tmp_path: Path, failed_result: FactorResult,
    ) -> None:
        """Failed signals don't get persisted to library (mirrors v2)."""
        sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
        out = sink.write_one(failed_result)
        assert out == Path("/dev/null")

    def test_write_one_calls_persist_code_to_yaml(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        """Verify persist_code_to_yaml is called with correct args."""
        factor_dir = tmp_path / "stk_alpha_001_abc123"
        with patch(
            "llmwikify.reproduction.pipeline.persist.persist_code_to_yaml",
            return_value=("created", factor_dir),
        ) as mock_persist, patch(
            "llmwikify.reproduction.persist.factor_library.save_backtest_duckdb",
            return_value=factor_dir / "factor.duckdb",
        ):
            sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
            sink.write_one(success_result)

        mock_persist.assert_called_once()
        kwargs = mock_persist.call_args.kwargs
        assert kwargs["factor_name"] == "alpha-001"
        assert kwargs["alpha_index"] == 1  # from signal.metadata
        assert kwargs["strategy_dir"] == "test"
        assert kwargs["factors_dir"] == tmp_path

    def test_write_one_passes_alpha_index_from_metadata(
        self, tmp_path: Path,
    ) -> None:
        """alpha_index from metadata (not just 'index')."""
        sig = Signal(id="1601_alpha-046", name="Alpha#46", formula_brief="x",
                     metadata={"index": 2, "alpha_index": 46})  # different
        result = FactorResult(signal=sig, status="success", code="x", code_chars=1)
        factor_dir = tmp_path / "stk_alpha_046_abc"
        with patch(
            "llmwikify.reproduction.pipeline.persist.persist_code_to_yaml",
            return_value=("created", factor_dir),
        ) as mock_persist, patch(
            "llmwikify.reproduction.persist.factor_library.save_backtest_duckdb",
        ):
            sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
            sink.write_one(result)
        kwargs = mock_persist.call_args.kwargs
        assert kwargs["alpha_index"] == 46  # alpha_index wins

    def test_write_one_handles_persist_exception(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        """YAML persist failure returns /dev/null, doesn't raise."""
        with patch(
            "llmwikify.reproduction.pipeline.persist.persist_code_to_yaml",
            side_effect=RuntimeError("disk full"),
        ):
            sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
            out = sink.write_one(success_result)
        assert out == Path("/dev/null")

    def test_write_batch_returns_empty(self, tmp_path: Path) -> None:
        sink = YamlDuckdbSink(factors_dir=tmp_path, strategy_dir="test")
        assert sink.write_batch([]) == []


# ─── BatchSummarySink ──────────────────────────────────────────────────


class TestBatchSummarySink:
    def test_write_one_is_noop(self, tmp_path: Path, success_result: FactorResult) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test")
        out = sink.write_one(success_result)
        assert out == Path("/dev/null")
        # No file written
        assert list(tmp_path.iterdir()) == []

    def test_write_batch_creates_json_and_md(
        self, tmp_path: Path, success_result: FactorResult, failed_result: FactorResult,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="my_paper")
        paths = sink.write_batch([success_result, failed_result])
        assert len(paths) == 2
        names = {p.name for p in paths}
        assert "multi_alpha_my_paper.json" in names
        assert "multi_alpha_my_paper.md" in names

    def test_aggregate_metrics_basic(
        self, tmp_path: Path,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="x")
        results = []
        for i in range(1, 4):
            sig = Signal(id=f"alpha-{i:03d}", name=f"A{i}", formula_brief="x")
            results.append(FactorResult(
                signal=sig, status="success", code="x", code_chars=1,
                backtest={"ic_mean": 0.01 * i, "icir": 0.1 * i, "win_rate": 0.5 + 0.01 * i},
            ))
        agg = sink._aggregate_metrics(results)
        assert agg["total"] == 3
        assert agg["success_count"] == 3
        assert agg["failed_count"] == 0
        assert agg["ic_mean"] == pytest.approx(0.02, abs=1e-4)
        assert agg["icir"] == pytest.approx(0.2, abs=1e-4)
        assert agg["winrate"] == pytest.approx(0.52, abs=1e-4)

    def test_aggregate_metrics_handles_nan(
        self, tmp_path: Path,
    ) -> None:
        """NaN values should be filtered, not crash."""
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="x")
        sig = Signal(id="x", name="X", formula_brief="x")
        nan = float("nan")
        results = [
            FactorResult(signal=sig, status="success", code="x", code_chars=1,
                        backtest={"ic_mean": nan, "icir": nan, "win_rate": nan}),
            FactorResult(signal=sig, status="success", code="x", code_chars=1,
                        backtest={"ic_mean": nan, "icir": nan, "win_rate": nan}),
        ]
        agg = sink._aggregate_metrics(results)
        # All NaN filtered → None for each metric
        assert agg["ic_mean"] is None
        assert agg["icir"] is None
        assert agg["winrate"] is None

    def test_aggregate_metrics_partial_nan(
        self, tmp_path: Path,
    ) -> None:
        """Mixed NaN/finite: average over finite only."""
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="x")
        sig = Signal(id="x", name="X", formula_brief="x")
        nan = float("nan")
        results = [
            FactorResult(signal=sig, status="success", code="x", code_chars=1,
                        backtest={"ic_mean": nan, "icir": 0.2, "win_rate": 0.6}),
            FactorResult(signal=sig, status="success", code="x", code_chars=1,
                        backtest={"ic_mean": 0.02, "icir": nan, "win_rate": 0.4}),
        ]
        agg = sink._aggregate_metrics(results)
        # ic_mean: only one finite (0.02) → 0.02
        # icir: only one finite (0.2) → 0.2
        # winrate: average of 0.6 + 0.4 = 0.5
        assert agg["ic_mean"] == pytest.approx(0.02)
        assert agg["icir"] == pytest.approx(0.2)
        assert agg["winrate"] == pytest.approx(0.5)

    def test_aggregate_metrics_empty(
        self, tmp_path: Path,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="x")
        agg = sink._aggregate_metrics([])
        assert agg["total"] == 0
        assert agg["success_count"] == 0
        assert agg["ic_mean"] is None

    def test_aggregate_metrics_all_failed(
        self, tmp_path: Path, failed_result: FactorResult,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="x")
        agg = sink._aggregate_metrics([failed_result])
        assert agg["total"] == 1
        assert agg["success_count"] == 0
        assert agg["failed_count"] == 1
        assert agg["ic_mean"] is None

    def test_aggregate_json_includes_per_alpha(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test")
        paths = sink.write_batch([success_result])
        json_path = [p for p in paths if p.suffix == ".json"][0]
        data = json.loads(json_path.read_text())
        assert data["paper_id"] == "test"
        assert data["total"] == 1
        assert data["success_count"] == 1
        assert data["alphas"][0]["id"] == "alpha-001"
        assert data["alphas"][0]["ic_mean"] == 0.01

    def test_aggregate_markdown_format(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test")
        paths = sink.write_batch([success_result])
        md_path = [p for p in paths if p.suffix == ".md"][0]
        text = md_path.read_text()
        assert "# test — Batch Results" in text
        assert "Total: 1" in text
        assert "| alpha-001 | Alpha#1 | success |" in text

    def test_aggregate_markdown_failed_section(
        self, tmp_path: Path, success_result: FactorResult, failed_result: FactorResult,
    ) -> None:
        sink = BatchSummarySink(output_dir=tmp_path, paper_id="test")
        paths = sink.write_batch([success_result, failed_result])
        md_path = [p for p in paths if p.suffix == ".md"][0]
        text = md_path.read_text()
        assert "## Failed" in text
        assert "alpha-002" in text
        assert "codegen" in text

    def test_write_batch_creates_parent_dir(
        self, tmp_path: Path, success_result: FactorResult,
    ) -> None:
        nested = tmp_path / "deep" / "nested"
        sink = BatchSummarySink(output_dir=nested, paper_id="x")
        paths = sink.write_batch([success_result])
        assert all(p.exists() for p in paths)
