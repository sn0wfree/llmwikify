"""Tests for PR3 BacktestEngine abstraction.

Covers:
  - FactorResult dataclass (10 tests): construction, to_dict, metadata
  - BacktestEngine Protocol (2 tests): structural typing check
  - QuantNodesBacktest adapter (10 tests): config, resolver, error path

Total: ~22 tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from llmwikify.reproduction.backtest import (
    BacktestEngine,
    FactorResult,
    QuantNodesBacktest,
)
from llmwikify.reproduction.signal_source.base import Signal

# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_signal() -> Signal:
    return Signal(
        id="alpha-001",
        name="Alpha#1",
        formula_brief="rank(close, 5)",
        metadata={"index": 1, "alpha_index": 1, "paper_id": "test"},
    )


@pytest.fixture
def chinese_signal() -> Signal:
    """Signal with Chinese name (招商/浙商 style)."""
    return Signal(
        id="signal-001",
        name="板块轮动周期表",
        formula_brief="Phase_State = f(credit_cycle)",
        metadata={"index": 1, "paper_id": "招商证券"},
    )


@pytest.fixture
def sample_series() -> pl.Series:
    return pl.Series("factor", [1.0, 2.0, 3.0, 4.0, 5.0])


# ─── FactorResult ───────────────────────────────────────────────────────


class TestFactorResult:
    def test_minimal_construction(self, sample_signal: Signal) -> None:
        result = FactorResult(signal=sample_signal, status="success")
        assert result.signal == sample_signal
        assert result.status == "success"
        assert result.code is None
        assert result.code_chars == 0
        assert result.factor_series is None
        assert result.backtest == {}
        assert result.stage is None
        assert result.error is None
        assert result.elapsed_sec == 0.0
        assert result.metadata == {}

    def test_full_construction(
        self, sample_signal: Signal, sample_series: pl.Series,
    ) -> None:
        result = FactorResult(
            signal=sample_signal,
            status="success",
            code="def compute_factor(df): return df['close'].rank()",
            code_chars=46,
            factor_series=sample_series,
            h5_path=Path("/tmp/alpha_001.h5"),
            backtest={"ic_mean": 0.01, "icir": 0.1, "win_rate": 0.51},
            elapsed_sec=12.5,
            metadata={"iterations": 1},
        )
        assert result.code_chars == 46
        assert result.factor_series is not None
        assert result.backtest["ic_mean"] == 0.01
        assert result.elapsed_sec == 12.5

    def test_to_dict_basic_keys(self, sample_signal: Signal) -> None:
        result = FactorResult(
            signal=sample_signal,
            status="success",
            code="x",
            code_chars=1,
            elapsed_sec=5.0,
        )
        d = result.to_dict()
        assert "status" in d
        assert "code" in d
        assert "code_chars" in d
        assert "ic_mean" in d
        assert "icir" in d
        assert "ic_winrate" in d
        assert "elapsed_sec" in d
        assert "h5_path" in d

    def test_to_dict_status_failed(self, sample_signal: Signal) -> None:
        result = FactorResult(
            signal=sample_signal,
            status="failed",
            stage="codegen",
            error="LLM timeout",
            elapsed_sec=5.0,
        )
        d = result.to_dict()
        assert d["status"] == "failed"
        assert d["stage"] == "codegen"
        assert d["error"] == "LLM timeout"
        assert d["code"] is None
        assert d["code_chars"] == 0

    def test_to_dict_alpha_index_from_metadata(
        self, sample_signal: Signal,
    ) -> None:
        """metadata.index → alpha_index in to_dict (v2 compat)."""
        result = FactorResult(
            signal=sample_signal,  # metadata has index=1
            status="success",
        )
        d = result.to_dict()
        assert d["alpha_index"] == 1

    def test_to_dict_alpha_index_from_explicit(
        self, sample_signal: Signal,
    ) -> None:
        """metadata.alpha_index takes precedence over index."""
        sig = Signal(id="x", name="X", formula_brief="x", metadata={"alpha_index": 42, "index": 1})
        result = FactorResult(signal=sig, status="success")
        d = result.to_dict()
        assert d["alpha_index"] == 42

    def test_to_dict_alpha_index_absent(self) -> None:
        sig = Signal(id="x", name="X", formula_brief="x", metadata={})
        result = FactorResult(signal=sig, status="success")
        d = result.to_dict()
        # No alpha_index key when metadata has no index
        assert "alpha_index" not in d

    def test_to_dict_factor_series_info(
        self, sample_signal: Signal, sample_series: pl.Series,
    ) -> None:
        result = FactorResult(
            signal=sample_signal,
            status="success",
            factor_series=sample_series,
        )
        d = result.to_dict()
        assert d["factor_series_len"] == 5
        # polars dtype returns full name (e.g. "Float64", "Int64")
        assert "Float" in d["factor_series_dtype"]

    def test_to_dict_no_factor_series(self, sample_signal: Signal) -> None:
        result = FactorResult(signal=sample_signal, status="failed")
        d = result.to_dict()
        assert d["factor_series_len"] == 0
        assert d["factor_series_dtype"] is None

    def test_to_dict_h5_path_stringified(
        self, sample_signal: Signal,
    ) -> None:
        result = FactorResult(
            signal=sample_signal,
            status="success",
            h5_path=Path("/tmp/alpha_001.h5"),
        )
        d = result.to_dict()
        assert d["h5_path"] == "/tmp/alpha_001.h5"

    def test_to_dict_no_h5_path(self, sample_signal: Signal) -> None:
        result = FactorResult(signal=sample_signal, status="success")
        d = result.to_dict()
        assert d["h5_path"] is None


# ─── BacktestEngine Protocol ────────────────────────────────────────────


class TestBacktestEngineProtocol:
    def test_quantnodes_satisfies_protocol(self) -> None:
        """QuantNodesBacktest should be structurally compatible."""
        engine = QuantNodesBacktest()
        # Protocol members are present
        assert hasattr(engine, "run")
        assert callable(engine.run)

    def test_stub_engine_satisfies_protocol(self) -> None:
        """Any class with run(code, h5_path, signal) → dict matches."""

        class StubEngine:
            def run(self, code: str, h5_path: Path, signal: Signal) -> dict[str, Any]:
                return {"ic_mean": 0.0, "icir": 0.0, "win_rate": 0.5}

        stub = StubEngine()
        sig = Signal(id="x", name="X", formula_brief="x")
        result = stub.run(code="x", h5_path=Path("/tmp/x.h5"), signal=sig)
        assert result["ic_mean"] == 0.0


# ─── QuantNodesBacktest ────────────────────────────────────────────────


class TestQuantNodesBacktest:
    def test_instantiation_no_config(self) -> None:
        engine = QuantNodesBacktest()
        assert engine._config is None

    def test_instantiation_with_config(self) -> None:
        cfg = {"date_beg": 20200101, "groups": 5}
        engine = QuantNodesBacktest(config=cfg)
        assert engine._config is cfg

    def test_default_resolver_uses_signal_id(self, sample_signal: Signal) -> None:
        """Default resolver returns signal.id (filesystem-safe)."""
        engine = QuantNodesBacktest()
        assert engine._default_resolver(sample_signal) == "alpha-001"

    def test_default_resolver_handles_chinese(self, chinese_signal: Signal) -> None:
        """signal.id for Chinese-name signal is 'signal-001' (not Chinese chars)."""
        engine = QuantNodesBacktest()
        resolved = engine._default_resolver(chinese_signal)
        assert resolved == "signal-001"
        assert resolved.isascii()  # No Chinese chars in id

    def test_custom_resolver(self, sample_signal: Signal) -> None:
        """Custom resolver overrides default."""

        def my_resolver(sig: Signal) -> str:
            return f"custom_{sig.name}"

        engine = QuantNodesBacktest(factor_name_resolver=my_resolver)
        assert engine._resolve(sample_signal) == "custom_Alpha#1"

    def test_run_extracts_metrics(self, sample_signal: Signal) -> None:
        """run() should call build_qn_config + PipelineRunner + extract."""
        fake_ctx = {
            "ICAnalyzer": {
                "ic_result": {"IC均值": 0.015, "ICIR": 0.12, "IC为正比例": 0.55},
                "rank_ic_result": {"Rank IC均值": 0.014, "Rank ICIR": 0.11},
            },
            "GroupAnalyzer": {},
        }
        with patch(
            "llmwikify.reproduction.pipeline.backtest_config.build_qn_config",
            return_value={"fake": "config"},
        ) as mock_build, patch(
            "QuantNodes.research.factor_test.pipeline_runner.PipelineRunner",
        ) as mock_runner_cls:
            mock_runner = mock_runner_cls.from_dict.return_value
            mock_runner.run.return_value = fake_ctx

            engine = QuantNodesBacktest()
            result = engine.run(
                code="def f(df): return df['close']",
                h5_path=Path("/tmp/alpha_001.h5"),
                signal=sample_signal,
            )

        # build_qn_config was called with the right args
        mock_build.assert_called_once()
        kwargs = mock_build.call_args.kwargs
        assert kwargs["factor_name"] == "alpha-001"
        assert kwargs["h5_path"] == Path("/tmp/alpha_001.h5")
        assert kwargs["expression"] == "def f(df): return df['close']"

        # Metrics extracted from fake ctx
        assert result["ic_mean"] == pytest.approx(0.015)
        assert result["icir"] == pytest.approx(0.12)
        assert result["win_rate"] == pytest.approx(0.55)

    def test_run_with_chinese_signal(self, chinese_signal: Signal) -> None:
        """run() should sanitize Chinese name via signal.id."""
        with patch(
            "llmwikify.reproduction.pipeline.backtest_config.build_qn_config",
            return_value={},
        ) as mock_build, patch(
            "QuantNodes.research.factor_test.pipeline_runner.PipelineRunner",
        ) as mock_runner_cls:
            mock_runner = mock_runner_cls.from_dict.return_value
            mock_runner.run.return_value = {}

            engine = QuantNodesBacktest()
            engine.run(
                code="x",
                h5_path=Path("/tmp/s.h5"),
                signal=chinese_signal,
            )

        # factor_name should be 'signal-001' (id, not Chinese name)
        kwargs = mock_build.call_args.kwargs
        assert kwargs["factor_name"] == "signal-001"

    def test_run_handles_pipeline_exception(self, sample_signal: Signal) -> None:
        """Pipeline failure should NOT raise — returns error dict."""
        with patch(
            "llmwikify.reproduction.pipeline.backtest_config.build_qn_config",
            side_effect=RuntimeError("QN connection lost"),
        ):
            engine = QuantNodesBacktest()
            result = engine.run(
                code="x",
                h5_path=Path("/tmp/x.h5"),
                signal=sample_signal,
            )

        assert "error" in result
        assert "QN connection lost" in result["error"]
        assert result["ic_mean"] is None
        assert result["icir"] is None

    def test_run_passes_config_to_build_qn_config(self, sample_signal: Signal) -> None:
        """config arg should be forwarded to build_qn_config."""
        cfg = {"date_beg": 20200101}
        with patch(
            "llmwikify.reproduction.pipeline.backtest_config.build_qn_config",
            return_value={},
        ) as mock_build, patch(
            "QuantNodes.research.factor_test.pipeline_runner.PipelineRunner",
        ):
            engine = QuantNodesBacktest(config=cfg)
            engine.run(code="x", h5_path=Path("/tmp/x.h5"), signal=sample_signal)

        kwargs = mock_build.call_args.kwargs
        assert kwargs["config"] is cfg
