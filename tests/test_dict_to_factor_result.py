"""Tests for dict → FactorResult conversion (PR8 L2 → PR9a ResultFactory).

PR8 originally tested `FactorStage._dict_to_factor_result`. After PR9a that
method moved to `ResultFactory.from_cached_dict`. The tests here now cover
the canonical location (factor/result_factory.py) — same behavior, new home.

Covers:
  - All 14 fields preserved
  - alpha_index extracted from signal.metadata
  - Missing fields default to None/0/empty
  - h5_path Path conversion
  - backtest ic_mean/icir/win_rate
  - stage / error preserved
  - Real cached file (v1 output) round-trips correctly
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.reproduction.backtest.base import FactorResult
from llmwikify.reproduction.factor import ResultFactory


@pytest.fixture
def factory() -> ResultFactory:
    return ResultFactory()


class TestDictToFactorResult:
    def test_full_dict_all_fields(self, factory: ResultFactory) -> None:
        """All dict fields map to FactorResult fields."""
        d = {
            "status": "success",
            "alpha_index": 42,
            "factor_name": "板块轮动周期表",
            "formula_brief": "f(t) = ...",
            "code": "def f(): return 1",
            "code_chars": 100,
            "ic_mean": 0.05,
            "icir": 0.3,
            "ic_winrate": 0.55,
            "h5_path": "/tmp/alpha_042.h5",
            "stage": None,
            "error": None,
            "elapsed_sec": 12.5,
        }
        fr = factory.from_cached_dict(d, 42)
        assert fr.status == "success"
        assert fr.signal.id == "042"  # byte-equal: "{idx:03d}"
        assert fr.signal.name == "板块轮动周期表"
        assert fr.signal.formula_brief == "f(t) = ..."
        assert fr.signal.metadata["alpha_index"] == 42
        assert fr.signal.metadata["index"] == 42
        assert fr.code == "def f(): return 1"
        assert fr.code_chars == 100
        assert fr.h5_path == Path("/tmp/alpha_042.h5")
        assert fr.backtest == {
            "ic_mean": 0.05, "icir": 0.3, "win_rate": 0.55,
        }
        assert fr.elapsed_sec == 12.5

    def test_missing_optional_fields(self, factory: ResultFactory) -> None:
        """Fields not in dict default to None / 0 / empty."""
        d = {"status": "success", "alpha_index": 1}
        fr = factory.from_cached_dict(d, 1)
        assert fr.code is None
        assert fr.code_chars == 0
        assert fr.h5_path is None
        assert fr.backtest == {
            "ic_mean": None, "icir": None, "win_rate": None,
        }
        assert fr.stage is None
        assert fr.error is None
        assert fr.elapsed_sec == 0.0

    def test_failed_status(self, factory: ResultFactory) -> None:
        d = {
            "status": "failed",
            "alpha_index": 7,
            "stage": "codegen",
            "error": "LLM timeout",
            "code": "partial code",
            "code_chars": 12,
        }
        fr = factory.from_cached_dict(d, 7)
        assert fr.status == "failed"
        assert fr.stage == "codegen"
        assert fr.error == "LLM timeout"
        assert fr.code == "partial code"
        assert fr.code_chars == 12

    def test_signal_id_byte_equal(self, factory: ResultFactory) -> None:
        """signal.id must be '{idx:03d}' (e.g. '001', '042') for byte-equal."""
        d = {"status": "success", "alpha_index": 1}
        fr = factory.from_cached_dict(d, 1)
        assert fr.signal.id == "001"  # not "alpha-001"

        d = {"status": "success", "alpha_index": 42}
        fr = factory.from_cached_dict(d, 42)
        assert fr.signal.id == "042"

    def test_h5_path_is_path_object(self, factory: ResultFactory) -> None:
        d = {"status": "success", "alpha_index": 1, "h5_path": "/tmp/foo.h5"}
        fr = factory.from_cached_dict(d, 1)
        assert isinstance(fr.h5_path, Path)
        assert str(fr.h5_path) == "/tmp/foo.h5"

    def test_h5_path_none_when_missing(self, factory: ResultFactory) -> None:
        d = {"status": "success", "alpha_index": 1}
        fr = factory.from_cached_dict(d, 1)
        assert fr.h5_path is None

    def test_to_dict_round_trip(self, factory: ResultFactory) -> None:
        """After conversion, to_dict() should preserve key fields for byte-equal."""
        d = {
            "status": "success",
            "alpha_index": 1,
            "factor_name": "Alpha#1",
            "formula_brief": "rank(close, 5)",
            "code": "x = 1",
            "code_chars": 5,
            "ic_mean": 0.02,
            "icir": 0.1,
            "ic_winrate": 0.51,
            "h5_path": "/tmp/a.h5",
            "stage": "",  # v2 outputs empty string for success
            "error": "",
            "elapsed_sec": 12.0,
        }
        fr = factory.from_cached_dict(d, 1)
        out = fr.to_dict()
        # Key fields preserved
        assert out["status"] == "success"
        assert out["alpha_index"] == 1
        assert out["ic_mean"] == 0.02
        assert out["icir"] == 0.1
        assert out["ic_winrate"] == 0.51
        assert out["stage"] == ""  # L2: coerced None → ""

    def test_real_cached_file_round_trip(self, factory: ResultFactory, tmp_path: Path) -> None:
        """Real cached v1/v2 single_factor_001.json should round-trip to same JSON shape.

        Note: factor_series_len / factor_series_dtype are NOT preserved by
        from_cached_dict (we have no pl.Series in the JSON). This is
        intentional — L2 doesn't need the actual series, just the metrics.
        """
        # Use an actual v1 output
        real = Path("scripts/output/single_factor_001.json")
        if not real.exists():
            pytest.skip("Real cached file not available")
        d = json.loads(real.read_text())
        fr = factory.from_cached_dict(d, idx=d.get("alpha_index", 1))
        out = fr.to_dict()
        # Check key fields (skip factor_series_len / dtype — not preserved)
        SKIP = {"factor_series_len", "factor_series_dtype"}
        for k in out:
            if k in SKIP:
                continue
            if k in d:
                assert out[k] == d[k], f"Mismatch for {k}: {out[k]!r} vs {d[k]!r}"
