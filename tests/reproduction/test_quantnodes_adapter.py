"""Tests for quantnodes_adapter: QuantNodes 上下文构建."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from llmwikify.reproduction.data_source import quantnodes_adapter as qa


class TestDateAndCode:
    """Test 日期和代码映射函数 (3 测试)."""

    def test_dates_to_int(self) -> None:
        """dates_to_int 返回 int array."""
        idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02"])
        result = qa.dates_to_int(idx)
        assert isinstance(result, np.ndarray)
        assert result.dtype in (np.int32, np.int64)

    def test_build_code_map(self) -> None:
        """build_code_map 返回 dict[str, int]."""
        cols = pd.Index(["000001.SZ", "000002.SZ"])
        result = qa.build_code_map(cols)
        assert isinstance(result, dict)
        assert "000001.SZ" in result

    def test_extract_ic_result_callable(self) -> None:
        """extract_ic_result 可调用."""
        assert callable(qa.extract_ic_result)


class TestQNContext:
    """Test build_qn_context (3 测试)."""

    def test_callable(self) -> None:
        """build_qn_context 可调用."""
        assert callable(qa.build_qn_context)

    def test_convert_wide_to_qn_callable(self) -> None:
        """convert_wide_to_qn 可调用."""
        assert callable(qa.convert_wide_to_qn)

    def test_module_imports(self) -> None:
        """模块可导入 + 公共 API 数量."""
        public_funcs = [
            "dates_to_int", "build_code_map", "convert_wide_to_qn",
            "build_qn_context", "extract_ic_result",
            "extract_group_result", "extract_longshort_result",
        ]
        for fn in public_funcs:
            assert hasattr(qa, fn), f"Missing: {fn}"


class TestExtractResults:
    """Test 3 个 extract 函数 (2 测试)."""

    def test_extract_group_result_callable(self) -> None:
        """extract_group_result 可调用."""
        assert callable(qa.extract_group_result)

    def test_extract_longshort_result_callable(self) -> None:
        """extract_longshort_result 可调用."""
        assert callable(qa.extract_longshort_result)
