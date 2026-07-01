"""Tests for ResultFactory (PR9a).

Covers:
  - build_signal: id format, name fallback, metadata
  - success: all fields populated, elapsed_sec is positive
  - fail_codegen: stage / error / code preserved, code_chars=0 when code=None
  - fail_pipeline: traceback[-1500:] in metadata, stage="pipeline"
  - from_cached_dict: full 11-field mapping + missing-field tolerance
  - byte-equal: signal.id format matches v2 convention
"""
from __future__ import annotations

import time
from pathlib import Path

import polars as pl
import pytest

from llmwikify.reproduction.factor import ResultFactory

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def factory() -> ResultFactory:
    return ResultFactory()


@pytest.fixture
def sample_series() -> pl.Series:
    return pl.Series("alpha_001", [0.1, 0.2, 0.3, 0.4])


@pytest.fixture
def backtest_metrics() -> dict:
    return {
        "ic_mean": 0.025,
        "icir": 0.5,
        "win_rate": 0.52,
        "ic_std": 0.05,
    }


# ─── build_signal ────────────────────────────────────────────────────


class TestBuildSignal:
    def test_id_format_3_digit_padded(self, factory: ResultFactory) -> None:
        """Byte-equal: signal.id = f'{idx:03d}' for 1-based indices."""
        for idx, expected in [(1, "001"), (10, "010"), (100, "100"), (101, "101")]:
            sig = factory.build_signal(idx)
            assert sig.id == expected, f"idx={idx} got {sig.id!r}"

    def test_name_fallback(self, factory: ResultFactory) -> None:
        """Empty name → f'alpha-{idx:03d}'."""
        assert factory.build_signal(1).name == "alpha-001"
        assert factory.build_signal(99).name == "alpha-099"

    def test_name_explicit(self, factory: ResultFactory) -> None:
        sig = factory.build_signal(1, name="custom_name")
        assert sig.name == "custom_name"

    def test_formula_brief_preserved(self, factory: ResultFactory) -> None:
        sig = factory.build_signal(1, formula_brief="rank(close)")
        assert sig.formula_brief == "rank(close)"

    def test_metadata_has_alpha_index_and_index(self, factory: ResultFactory) -> None:
        """v2 compat: metadata has both 'alpha_index' and 'index' keys."""
        sig = factory.build_signal(7)
        assert sig.metadata["alpha_index"] == 7
        assert sig.metadata["index"] == 7


# ─── success ─────────────────────────────────────────────────────────


class TestSuccess:
    def test_all_fields_populated(
        self,
        factory: ResultFactory,
        sample_series: pl.Series,
        backtest_metrics: dict,
        tmp_path: Path,
    ) -> None:
        h5_path = tmp_path / "alpha_001.h5"
        t0 = time.monotonic()
        fr = factory.success(
            alpha_index=1,
            factor_name="alpha_001",
            formula_brief="rank(close)",
            code="def compute_factor(df): return df['close'].rank()",
            factor_series=sample_series,
            h5_path=h5_path,
            backtest=backtest_metrics,
            t0=t0,
        )
        assert fr.status == "success"
        assert fr.signal.id == "001"
        assert fr.signal.name == "alpha_001"
        assert fr.signal.formula_brief == "rank(close)"
        assert fr.code == "def compute_factor(df): return df['close'].rank()"
        assert fr.code_chars == len(fr.code)
        assert fr.factor_series is sample_series
        assert fr.h5_path == h5_path
        assert fr.backtest == backtest_metrics
        assert fr.stage is None
        assert fr.error is None
        assert fr.elapsed_sec >= 0

    def test_code_chars_uses_len(
        self,
        factory: ResultFactory,
        sample_series: pl.Series,
        backtest_metrics: dict,
        tmp_path: Path,
    ) -> None:
        h5_path = tmp_path / "alpha_001.h5"
        code = "x = 1"
        fr = factory.success(
            alpha_index=1, factor_name="x", formula_brief="x",
            code=code, factor_series=sample_series,
            h5_path=h5_path, backtest=backtest_metrics, t0=time.monotonic(),
        )
        assert fr.code_chars == 5

    def test_elapsed_sec_is_monotonic(
        self,
        factory: ResultFactory,
        sample_series: pl.Series,
        backtest_metrics: dict,
        tmp_path: Path,
    ) -> None:
        """elapsed_sec = time.monotonic() - t0 (always >= 0)."""
        h5_path = tmp_path / "alpha_001.h5"
        t0 = time.monotonic()
        time.sleep(0.01)  # 10ms
        fr = factory.success(
            alpha_index=1, factor_name="x", formula_brief="",
            code="", factor_series=sample_series,
            h5_path=h5_path, backtest=backtest_metrics, t0=t0,
        )
        assert fr.elapsed_sec >= 0.01
        assert fr.elapsed_sec < 0.5  # generous upper bound


# ─── fail_codegen ────────────────────────────────────────────────────


class TestFailCodegen:
    def test_with_code(self, factory: ResultFactory) -> None:
        t0 = time.monotonic()
        fr = factory.fail_codegen(
            alpha_index=5, stage="compile", error="SyntaxError: invalid syntax",
            code="def bad():", t0=t0,
        )
        assert fr.status == "failed"
        assert fr.stage == "compile"
        assert fr.error == "SyntaxError: invalid syntax"
        assert fr.code == "def bad():"
        assert fr.code_chars == len("def bad():")
        assert fr.backtest == {}
        assert fr.signal.id == "005"

    def test_with_none_code(self, factory: ResultFactory) -> None:
        """code=None → code_chars=0 (no AttributeError)."""
        fr = factory.fail_codegen(
            alpha_index=1, stage="react", error="LLM timeout",
            code=None, t0=time.monotonic(),
        )
        assert fr.code is None
        assert fr.code_chars == 0

    def test_empty_string_code(self, factory: ResultFactory) -> None:
        """code="" → code_chars=0 (distinguish from None)."""
        fr = factory.fail_codegen(
            alpha_index=1, stage="compile", error="empty code",
            code="", t0=time.monotonic(),
        )
        assert fr.code == ""
        assert fr.code_chars == 0


# ─── fail_pipeline ───────────────────────────────────────────────────


class TestFailPipeline:
    def test_stage_is_pipeline(
        self,
        factory: ResultFactory,
    ) -> None:
        fr = factory.fail_pipeline(
            alpha_index=10, code="def f(): pass",
            exc=RuntimeError("quantnodes crash"), t0=time.monotonic(),
        )
        assert fr.stage == "pipeline"

    def test_error_format(
        self,
        factory: ResultFactory,
    ) -> None:
        fr = factory.fail_pipeline(
            alpha_index=1, code="x",
            exc=ValueError("bad input"), t0=time.monotonic(),
        )
        assert fr.error == "ValueError: bad input"

    def test_traceback_in_metadata(
        self,
        factory: ResultFactory,
    ) -> None:
        """metadata['traceback'] = last 1500 chars of formatted traceback."""
        try:
            raise RuntimeError("test")
        except RuntimeError:
            fr = factory.fail_pipeline(
                alpha_index=1, code="x", exc=RuntimeError("test"),
                t0=time.monotonic(),
            )
        assert "traceback" in fr.metadata
        assert "RuntimeError: test" in fr.metadata["traceback"]
        assert len(fr.metadata["traceback"]) <= 1500

    def test_long_traceback_truncated(self, factory: ResultFactory) -> None:
        """traceback[-1500:] keeps last 1500 chars only."""
        # Force a deep stack to make traceback > 1500 chars
        def _deep(n: int) -> None:
            if n == 0:
                raise RuntimeError("deep")
            _deep(n - 1)
        try:
            _deep(100)
        except RuntimeError as exc:
            fr = factory.fail_pipeline(
                alpha_index=1, code="x", exc=exc, t0=time.monotonic(),
            )
        assert len(fr.metadata["traceback"]) <= 1500


# ─── from_cached_dict ────────────────────────────────────────────────


class TestFromCachedDict:
    def test_full_dict_mapping(self, factory: ResultFactory) -> None:
        """All 11 fields from legacy dict → FactorResult."""
        d = {
            "status": "success",
            "alpha_index": 1,
            "factor_name": "alpha_001",
            "formula_brief": "rank(close)",
            "code": "def f(): pass",
            "code_chars": 13,
            "h5_path": "/data/alpha_001.h5",
            "ic_mean": 0.025,
            "icir": 0.5,
            "ic_winrate": 0.52,
            "stage": None,
            "error": None,
            "elapsed_sec": 5.5,
        }
        fr = factory.from_cached_dict(d, idx=1)
        assert fr.status == "success"
        assert fr.signal.id == "001"
        assert fr.signal.name == "alpha_001"
        assert fr.signal.formula_brief == "rank(close)"
        assert fr.code == "def f(): pass"
        assert fr.code_chars == 13
        assert fr.h5_path == Path("/data/alpha_001.h5")
        assert fr.backtest["ic_mean"] == 0.025
        assert fr.backtest["icir"] == 0.5
        assert fr.backtest["win_rate"] == 0.52
        assert fr.stage is None
        assert fr.error is None
        assert fr.elapsed_sec == 5.5

    def test_missing_fields_use_defaults(self, factory: ResultFactory) -> None:
        """Empty dict → all defaults (no KeyError)."""
        fr = factory.from_cached_dict({}, idx=5)
        assert fr.status == "unknown"
        assert fr.code is None
        assert fr.code_chars == 0
        assert fr.h5_path is None
        assert fr.backtest == {"ic_mean": None, "icir": None, "win_rate": None}
        assert fr.stage is None
        assert fr.error is None
        assert fr.elapsed_sec == 0.0
        assert fr.signal.id == "005"
        assert fr.signal.name == "alpha-005"  # fallback

    def test_h5_path_coerced_to_path(self, factory: ResultFactory) -> None:
        """h5_path str → Path object."""
        fr = factory.from_cached_dict({"h5_path": "/x/y.h5"}, idx=1)
        assert isinstance(fr.h5_path, Path)
        assert str(fr.h5_path) == "/x/y.h5"

    def test_h5_path_none_when_missing(self, factory: ResultFactory) -> None:
        """Missing h5_path → None (not '' or Path(''))."""
        fr = factory.from_cached_dict({}, idx=1)
        assert fr.h5_path is None

    def test_ic_winrate_maps_to_win_rate(self, factory: ResultFactory) -> None:
        """Legacy 'ic_winrate' key → FactorResult.backtest['win_rate']."""
        fr = factory.from_cached_dict({"ic_winrate": 0.6}, idx=1)
        assert fr.backtest["win_rate"] == 0.6
        assert "ic_winrate" not in fr.backtest  # renamed

    def test_failed_status_preserved(self, factory: ResultFactory) -> None:
        d = {
            "status": "failed",
            "stage": "react",
            "error": "LLM error",
            "code": None,
            "code_chars": 0,
        }
        fr = factory.from_cached_dict(d, idx=1)
        assert fr.status == "failed"
        assert fr.stage == "react"
        assert fr.error == "LLM error"


# ─── Cross-cutting ───────────────────────────────────────────────────


class TestByteEqual:
    """Sanity: the `signal.id` convention matches v2 across the factory."""

    def test_id_format_consistent(self, factory: ResultFactory) -> None:
        """All 5 methods produce the same signal.id for the same idx."""
        idx = 7
        sig1 = factory.build_signal(idx)
        sig2 = factory.success(
            alpha_index=idx, factor_name="x", formula_brief="",
            code="", factor_series=pl.Series("x", [1.0]),
            h5_path=Path("/tmp/x.h5"), backtest={}, t0=time.monotonic(),
        ).signal
        sig3 = factory.fail_codegen(
            alpha_index=idx, stage="x", error="x", code=None, t0=time.monotonic(),
        ).signal
        sig4 = factory.fail_pipeline(
            alpha_index=idx, code="x", exc=RuntimeError("x"), t0=time.monotonic(),
        ).signal
        sig5 = factory.from_cached_dict({"alpha_index": idx}, idx=idx).signal
        for sig in [sig1, sig2, sig3, sig4, sig5]:
            assert sig.id == "007"
            assert sig.metadata["alpha_index"] == 7
            assert sig.metadata["index"] == 7
