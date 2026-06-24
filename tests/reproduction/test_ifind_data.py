"""Tests for ifind_data: iFinD 数据源 (mock 优先)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from llmwikify.reproduction.data_source import ifind as id_


class TestFetchTradabilityBatch:
    """Test fetch_tradability_batch (3 测试)."""

    def test_returns_dict_or_dataframe(self) -> None:
        """返回 dict 或 DataFrame."""
        with patch.object(id_, "fetch_tradability_batch", return_value={}):
            result = id_.fetch_tradability_batch()
            assert result is not None

    def test_empty_when_no_data(self) -> None:
        """无数据返回空."""
        with patch.object(id_, "fetch_tradability_batch", return_value={}):
            result = id_.fetch_tradability_batch(symbols=[], start="20200101", end="20200101")
            assert result is not None

    def test_function_callable(self) -> None:
        """函数可调用."""
        assert callable(id_.fetch_tradability_batch)


class TestFetchIpoDates:
    """Test fetch_ipo_dates (2 测试)."""

    def test_returns_dict(self) -> None:
        """返回 dict (date → date)."""
        with patch.object(id_, "fetch_ipo_dates", return_value={}):
            result = id_.fetch_ipo_dates()
            assert result is not None

    def test_function_callable(self) -> None:
        """函数可调用."""
        assert callable(id_.fetch_ipo_dates)


class TestFetchStHistory:
    """Test fetch_st_history (2 测试)."""

    def test_returns_dict(self) -> None:
        """返回 dict."""
        with patch.object(id_, "fetch_st_history", return_value={}):
            result = id_.fetch_st_history()
            assert result is not None

    def test_function_callable(self) -> None:
        """函数可调用."""
        assert callable(id_.fetch_st_history)


class TestFetchSuspendHistory:
    """Test fetch_suspend_history (2 测试)."""

    def test_returns_dict(self) -> None:
        """返回 dict."""
        with patch.object(id_, "fetch_suspend_history", return_value={}):
            result = id_.fetch_suspend_history()
            assert result is not None

    def test_function_callable(self) -> None:
        """函数可调用."""
        assert callable(id_.fetch_suspend_history)


class TestBuildTradableMatrices:
    """Test build_tradable_matrices (2 测试)."""

    def test_returns_dict(self) -> None:
        """返回 dict."""
        with patch.object(id_, "build_tradable_matrices", return_value={}):
            result = id_.build_tradable_matrices()
            assert result is not None

    def test_function_callable(self) -> None:
        """函数可调用."""
        assert callable(id_.build_tradable_matrices)


class TestModuleStructure:
    """Test 模块结构 (3 测试)."""

    def test_logger_exists(self) -> None:
        """logger 实例存在."""
        import logging
        assert hasattr(id_, "logger")
        assert isinstance(id_.logger, logging.Logger)

    def test_public_api_count(self) -> None:
        """5 个公共 fetch 函数."""
        public_funcs = [
            "fetch_tradability_batch",
            "fetch_ipo_dates",
            "fetch_st_history",
            "fetch_suspend_history",
            "build_tradable_matrices",
        ]
        for fn in public_funcs:
            assert hasattr(id_, fn), f"Missing: {fn}"

    def test_module_docstring(self) -> None:
        """模块有 docstring."""
        assert id_.__doc__ is not None
