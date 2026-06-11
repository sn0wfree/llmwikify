"""Tests for universe resolution module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from llmwikify.reproduction.universe import (
    HEDGE_INDEX_CODE,
    INDEX_ALIASES,
    get_index_constituents,
    resolve_universe,
)


class TestIndexAliases:
    """Test INDEX_ALIASES dictionary coverage."""

    def test_hs300_variants(self):
        assert INDEX_ALIASES["HS300"] == "000300"
        assert INDEX_ALIASES["沪深300"] == "000300"
        assert INDEX_ALIASES["000300"] == "000300"
        assert INDEX_ALIASES["000300.SH"] == "000300"
        assert INDEX_ALIASES["CSI300"] == "000300"

    def test_zz500_variants(self):
        assert INDEX_ALIASES["ZZ500"] == "000905"
        assert INDEX_ALIASES["中证500"] == "000905"

    def test_sz50_variants(self):
        assert INDEX_ALIASES["SZ50"] == "000016"
        assert INDEX_ALIASES["上证50"] == "000016"

    def test_zz1000_variants(self):
        assert INDEX_ALIASES["ZZ1000"] == "000852"
        assert INDEX_ALIASES["中证1000"] == "000852"

    def test_all_42_aliases(self):
        assert len(INDEX_ALIASES) == 42


class TestResolveUniverse:
    """Test resolve_universe with different input types."""

    def test_none_returns_empty(self):
        assert resolve_universe(None) == []

    def test_empty_string_returns_empty(self):
        assert resolve_universe("") == []

    def test_single_returns_empty(self):
        assert resolve_universe("single") == []

    def test_all_returns_empty(self):
        assert resolve_universe("all") == []

    def test_custom_returns_empty(self):
        assert resolve_universe("custom") == []

    def test_list_dedupes(self):
        result = resolve_universe(["000001", "600519", "000001"])
        assert result == ["000001", "600519"]

    def test_list_strips_suffix(self):
        result = resolve_universe(["000001.SZ", "600519.SH"])
        assert result == ["000001", "600519"]

    def test_list_filters_invalid(self):
        result = resolve_universe(["000001", "abc", "", "1234", "600519"])
        assert result == ["000001", "600519"]

    def test_index_code_calls_akshare(self):
        """resolve_universe('HS300') should call get_index_constituents."""
        mock_ak = MagicMock()
        mock_ak.index_stock_cons.return_value = pd.DataFrame({"品种代码": ["000001", "600519", "000858"]})
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            # Clear cache so fresh call happens
            from llmwikify.reproduction import universe
            universe._CACHE.clear()
            result = resolve_universe("HS300")
            assert result == ["000001", "600519", "000858"]


class TestGetIndexConstituents:
    """Test get_index_constituents with mocked AKShare."""

    def test_sina_source(self):
        mock_ak = MagicMock()
        mock_ak.index_stock_cons.return_value = pd.DataFrame({"品种代码": ["000001", "600519"]})
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            from llmwikify.reproduction import universe
            universe._CACHE.clear()
            result = get_index_constituents("HS300")
            assert result == ["000001", "600519"]

    def test_csindex_fallback(self):
        mock_ak = MagicMock()
        mock_ak.index_stock_cons.return_value = pd.DataFrame()
        mock_ak.index_stock_cons_csindex.return_value = pd.DataFrame({"成分券代码": ["000001", "600519"]})
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            from llmwikify.reproduction import universe
            universe._CACHE.clear()
            result = get_index_constituents("HS300")
            assert result == ["000001", "600519"]

    def test_both_fail_returns_empty(self):
        mock_ak = MagicMock()
        mock_ak.index_stock_cons.side_effect = Exception("network error")
        mock_ak.index_stock_cons_csindex.side_effect = Exception("network error")
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            from llmwikify.reproduction import universe
            universe._CACHE.clear()
            result = get_index_constituents("HS300")
            assert result == []

    def test_empty_code_returns_empty(self):
        result = get_index_constituents("")
        assert result == []

    def test_cache_hit(self):
        """Second call should use cache."""
        mock_ak = MagicMock()
        mock_ak.index_stock_cons.return_value = pd.DataFrame({"品种代码": ["000001"]})
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            from llmwikify.reproduction import universe
            universe._CACHE.clear()
            r1 = get_index_constituents("HS300")
            r2 = get_index_constituents("HS300")
            assert r1 == r2 == ["000001"]
            # AKShare called only once due to cache
            assert mock_ak.index_stock_cons.call_count == 1


class TestHedgeIndexCode:
    """Test HEDGE_INDEX_CODE mapping."""

    def test_hs300(self):
        assert HEDGE_INDEX_CODE["HS300"] == "000300.SH"

    def test_zz500(self):
        assert HEDGE_INDEX_CODE["ZZ500"] == "000905.SH"

    def test_sz50(self):
        assert HEDGE_INDEX_CODE["SZ50"] == "000016.SH"

    def test_passthrough(self):
        assert HEDGE_INDEX_CODE.get("000300.SH", "000300.SH") == "000300.SH"
