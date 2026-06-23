"""Tests for factor_value_store: H5/Parquet 存储."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from llmwikify.reproduction import factor_value_store as fvs


class TestFactorValueStore:
    """Test 公共 API (5 测试)."""

    def test_store_factor_values_callable(self) -> None:
        """store_factor_values 可调用."""
        assert callable(fvs.store_factor_values)

    def test_compute_and_store_factor_callable(self) -> None:
        """compute_and_store_factor 可调用."""
        assert callable(fvs.compute_and_store_factor)

    def test_query_factor_values_callable(self) -> None:
        """query_factor_values 可调用."""
        assert callable(fvs.query_factor_values)

    def test_list_stored_factors_callable(self) -> None:
        """list_stored_factors 可调用."""
        assert callable(fvs.list_stored_factors)

    def test_module_imports(self) -> None:
        """模块可导入 + 公共 API 数量."""
        public_funcs = [
            "store_factor_values",
            "query_factor_values",
            "compute_and_store_factor",
            "list_stored_factors",
        ]
        for fn in public_funcs:
            assert hasattr(fvs, fn), f"Missing: {fn}"
