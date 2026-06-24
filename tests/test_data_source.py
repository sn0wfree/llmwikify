"""Phase 2 后置测试: 验证 data_source/ 子包搬迁后可用.

搬迁后改为新路径 (data_source.X), 仅改 import, 不改测试逻辑.
"""
from __future__ import annotations


def test_data_router_init():
    from llmwikify.reproduction.data_source.router import DataRouter
    r = DataRouter(use_cache=False)
    assert r is not None


def test_resolve_universe():
    from llmwikify.reproduction.data_source.universe import resolve_universe
    result = resolve_universe("all")
    assert result is not None


def test_quantnodes_adapter():
    from llmwikify.reproduction.data_source.quantnodes_adapter import build_qn_context
    import pandas as pd
    idx = pd.to_datetime(["2020-01-01"])
    factor_wide = pd.DataFrame({"1": [0.5]}, index=idx)
    close_wide = pd.DataFrame({"1": [10.0]}, index=idx)
    ctx = build_qn_context(factor_wide, close_wide)
    assert ctx is not None


def test_akshare_source_exists():
    from llmwikify.reproduction.data_source.router import AKShareDataSource
    assert AKShareDataSource is not None
