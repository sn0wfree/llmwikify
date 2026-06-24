"""Tests for Phase 14C: pipeline/ business modules extracted from test_one_factor_llm_code.py."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from llmwikify.reproduction.pipeline.backtest_config import (
    LONG_DATE_BEG,
    LONG_DATE_END,
    PROJECT_ROOT,
    build_qn_config,
)
from llmwikify.reproduction.pipeline.backtest_extract import (
    extract_full_backtest_from_ctx,
    safe_float,
)
from llmwikify.reproduction.pipeline.data_loader import (
    derive_input_columns,
    wide_from_long,
    write_factor_h5,
)
from llmwikify.reproduction.pipeline.factor_fix import add_noise, detect_binary
from llmwikify.reproduction.pipeline.score import compute_score, compute_status


class TestWideFromLong:
    def test_basic_conversion(self):
        df = pl.DataFrame({
            "date": [20200101, 20200101, 20200102, 20200102],
            "code": ["A", "B", "A", "B"],
            "value": [1.0, 2.0, 3.0, 4.0],
        })
        factor = pl.Series("factor", [10.0, 20.0, 30.0, 40.0])
        wide = wide_from_long(df, factor)
        assert wide.shape == (2, 2)
        assert set(wide.columns) == {"A", "B"}

    def test_length_mismatch_raises(self):
        df = pl.DataFrame({"date": [1], "code": ["A"]})
        factor = pl.Series("f", [1.0, 2.0])
        try:
            wide_from_long(df, factor)
            assert False, "Should have raised"
        except AssertionError:
            pass


class TestWriteFactorH5:
    def test_creates_file(self, tmp_path: Path):
        wide = pd.DataFrame({"A": [1.0], "B": [2.0]}, index=[20200101])
        h5_path = write_factor_h5(wide, "test_factor", tmp_path)
        assert h5_path.exists()
        assert h5_path.name == "factor_test_factor.h5"
        with pd.HDFStore(h5_path, "r") as store:
            keys = store.keys()
            assert len(keys) == 1


class TestDeriveInputColumns:
    def test_basic_formula(self):
        result = derive_input_columns("rank(close / open)")
        assert "close" in result
        assert "open" in result
        assert "volume" in result  # auto-added base columns

    def test_no_price_tokens(self):
        result = derive_input_columns("rank(industry)")
        assert "industry" in result


class TestBuildQnConfig:
    def test_structure(self, tmp_path: Path):
        h5 = tmp_path / "factor_test.h5"
        cfg = build_qn_config("alpha-001", h5, "code here")
        assert cfg["factor"]["name"] == "alpha_001"
        assert cfg["factor"]["factor_dir"] == "factor_test.h5"
        assert isinstance(cfg["load_keys"], list)
        assert isinstance(cfg["output"]["format"], list)
        assert cfg["preprocess"]["adj_date_beg"] == LONG_DATE_BEG

    def test_constants(self):
        assert LONG_DATE_BEG == 20200101
        assert LONG_DATE_END == 20241231
        assert PROJECT_ROOT == Path("/home/ll/llmwikify")


class TestSafeFloat:
    def test_normal(self):
        assert safe_float(3.14) == 3.14

    def test_none(self):
        assert safe_float(None) is None
        assert safe_float(None, 0.0) == 0.0

    def test_nan(self):
        assert safe_float(float("nan")) is None
        assert safe_float(float("nan"), -1.0) == -1.0

    def test_string(self):
        assert safe_float("abc") is None
        assert safe_float("3.14") == 3.14


class TestExtractFullBacktestFromCtx:
    def test_empty_ctx(self):
        result = extract_full_backtest_from_ctx({})
        assert result["ic_mean"] is None
        assert result["ic_series"] == []
        assert result["group_metrics"] == {}

    def test_with_ic_data(self):
        import pandas as pd

        ic_result = {"IC均值": 0.05, "ICIR": 0.12, "IC为正比例": 0.55}
        ic = {20200101: 0.01, 20200102: 0.03}
        ctx = {"ICAnalyzer": {"ic_result": ic_result, "ic": ic}}
        result = extract_full_backtest_from_ctx(ctx)
        assert result["ic_mean"] == 0.05
        assert result["icir"] == 0.12
        assert len(result["ic_series"]) == 2


class TestComputeScore:
    def test_none_returns_50(self):
        assert compute_score(None, None) == 50

    def test_high_icir(self):
        score = compute_score(0.5, 0.6)
        assert 50 < score <= 100

    def test_negative_icir(self):
        score = compute_score(-0.5, 0.3)
        assert 0 <= score < 50


class TestComputeStatus:
    def test_none(self):
        assert compute_status(None) == "待验证"

    def test_positive(self):
        assert compute_status(0.15) == "通过"

    def test_negative(self):
        assert compute_status(-0.1) == "失败"

    def test_neutral(self):
        assert compute_status(0.05) == "待更新"


class TestFactorFix:
    def test_detect_binary(self):
        s = pl.Series([0.0, 0.0, 0.0])
        assert detect_binary(s) is True

    def test_detect_non_binary(self):
        s = pl.Series([1.0, 2.0, 3.0])
        assert detect_binary(s) is False

    def test_add_noise(self):
        s = pl.Series([0.0, 0.0, 0.0])
        result = add_noise(s)
        assert result.dtype == pl.Float64
        assert len(result) == 3
        assert not all(v == 0.0 for v in result.to_list())
