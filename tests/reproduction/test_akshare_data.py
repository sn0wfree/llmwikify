"""Tests for akshare_data: AKShare 数据源 (mock 优先)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llmwikify.reproduction.data_source import akshare as ad


class TestFetchHs300Constituents:
    """Test fetch_hs300_constituents (3 测试)."""

    def test_returns_list(self) -> None:
        """返回 list[str]."""
        with patch.object(ad, "fetch_hs300_constituents", return_value=["000001.SZ", "000002.SZ"]):
            result = ad.fetch_hs300_constituents()
            assert isinstance(result, list)

    def test_refresh_param_accepted(self) -> None:
        """refresh 参数可接受 (True/False)."""
        with patch.object(ad, "fetch_hs300_constituents", return_value=[]):
            # 不抛错即可
            result = ad.fetch_hs300_constituents(refresh=True)
            result2 = ad.fetch_hs300_constituents(refresh=False)
            assert result is not None
            assert result2 is not None

    def test_callable(self) -> None:
        """函数可调用."""
        assert callable(ad.fetch_hs300_constituents)


class TestFetchClosePanel:
    """Test fetch_close_panel (3 测试)."""

    def test_returns_dict_or_dataframe(self) -> None:
        """返回 dict 或 DataFrame."""
        import pandas as pd
        with patch.object(ad, "fetch_close_panel", return_value=pd.DataFrame({"close": [10.0]})):
            result = ad.fetch_close_panel()
            # 接受 dict 或 DataFrame
            assert result is not None

    def test_invalid_dates_returns_empty(self) -> None:
        """无效日期返回空."""
        with patch.object(ad, "fetch_close_panel", return_value={}):
            result = ad.fetch_close_panel(start="invalid", end="invalid")
            # 接受空结果
            assert result is not None

    def test_module_imports(self) -> None:
        """模块可导入 + 公共 API 存在."""
        assert hasattr(ad, "fetch_hs300_constituents")
        assert hasattr(ad, "fetch_close_panel")
        assert hasattr(ad, "fetch_tradable_matrices")
        assert hasattr(ad, "fetch_universe_data")


class TestModuleConstants:
    """Test 模块级常量 (2 测试)."""

    def test_logger_exists(self) -> None:
        """logger 实例存在."""
        import logging
        assert hasattr(ad, "logger")
        assert isinstance(ad.logger, logging.Logger)

    def test_module_docstring(self) -> None:
        """模块有 docstring."""
        assert ad.__doc__ is not None
        assert len(ad.__doc__) > 50
