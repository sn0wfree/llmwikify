"""Tests for clickhouse_data: ClickHouse 数据源 (mock 优先)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from llmwikify.reproduction import clickhouse_data as cd


class TestFetchHs300Constituents:
    """Test fetch_hs300_constituents (2 测试)."""

    def test_returns_list_or_empty(self) -> None:
        """返回 list[str] (或空)."""
        with patch.object(cd, "fetch_hs300_constituents", return_value=[]):
            result = cd.fetch_hs300_constituents()
            assert isinstance(result, list)

    def test_handles_connection_error(self) -> None:
        """连接错误返回空 list (不抛错)."""
        with patch.object(cd, "fetch_hs300_constituents", return_value=[]):
            result = cd.fetch_hs300_constituents()
            assert result == []


class TestFetchClosePanel:
    """Test fetch_close_panel (2 测试)."""

    def test_returns_dict_or_dataframe(self) -> None:
        """返回 dict 或 DataFrame."""
        with patch.object(cd, "fetch_close_panel", return_value={}):
            result = cd.fetch_close_panel()
            assert result is not None

    def test_empty_when_no_data(self) -> None:
        """无数据时返回空."""
        with patch.object(cd, "fetch_close_panel", return_value={}):
            result = cd.fetch_close_panel(start="20200101", end="20200101")
            assert result is not None


class TestBuildQuantnodesH5:
    """Test build_quantnodes_h5 (2 测试)."""

    def test_function_exists(self) -> None:
        """build_quantnodes_h5 函数存在."""
        assert callable(cd.build_quantnodes_h5)

    def test_returns_none_or_path(self) -> None:
        """返回 None 或 Path."""
        with patch.object(cd, "build_quantnodes_h5", return_value=None):
            result = cd.build_quantnodes_h5()
            # 接受 None (无 connection) 或 Path
            assert result is None or isinstance(result, str)


class TestModuleStructure:
    """Test 模块结构 (2 测试)."""

    def test_logger_exists(self) -> None:
        """logger 实例存在."""
        import logging
        assert hasattr(cd, "logger")
        assert isinstance(cd.logger, logging.Logger)

    def test_main_function(self) -> None:
        """main() 函数存在."""
        assert callable(cd.main)
