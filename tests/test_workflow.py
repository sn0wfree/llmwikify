"""Tests for UnifiedWorkflow and _track_b_to_factor adapter.

Migrated from test_extract_factor_metadata.py (which tested the deleted
_extract_factor_from_page function from paper.py). The same 6-layer
structure logic is now in _track_b_to_factor() in pipeline/workflow.py.
"""
from __future__ import annotations


def test_track_b_to_factor_with_classification():
    """When SignalDetail has classification, all 6 layers populated from it."""
    from llmwikify.reproduction.pipeline.workflow import _track_b_to_factor

    detail = {
        "name": "Alpha#1",
        "description": "动量因子",
        "classification": {
            "asset_type": "stock",
            "category": "price",
            "subcategory": "momentum",
        },
        "l1": {
            "definition": "过去20个交易日的涨跌幅",
            "formula": "f_t = close_t / close_{t-20} - 1",
            "input_columns": ["close"],
            "frequency": "日频",
            "default_params": {"period": 20},
            "param_constraints": {"period": "≥5"},
            "business_constraints": "上市不足20日不可算",
        },
        "l2": {
            "calculation_steps": [
                {"step": 1, "description": "取close序列", "formula": "close"},
                {"step": 2, "description": "计算20日收益", "formula": "f = pct_change(20)"},
            ],
            "edge_case_handling": "前20个日期输出NaN",
            "missing_value_handling": "保持NaN",
            "complexity": "O(T × N)",
        },
        "l3": {
            "financial_intuition": "市场对股票的近期认可程度",
            "market_behavior": "价格偏离近期均值",
            "theoretical_basis": "行为金融学动量效应",
            "historical_effectiveness": "A股2010-2020有效",
            "related_factors": "与反转因子方向相反",
        },
        "l4": {
            "hypotheses": [
                {
                    "id": "H1",
                    "name": "动量延续",
                    "description": "高动量→未来继续涨",
                    "expected_ic_sign": "正",
                    "source": "动量效应理论",
                    "priority": "主假设",
                },
            ],
        },
        "success": True,
    }

    result = _track_b_to_factor(detail, "test_paper")
    factor = result["factor"]

    # Verify name and classification
    assert result["name"] == "alpha1"
    assert factor["name"] == "alpha1"
    assert factor["asset_type"] == "stock"
    assert factor["category"] == "price"
    assert factor["subcategory"] == "momentum"
    assert factor["source_paper"] == "test_paper"
    assert factor["version"] == 1
    assert factor["status"] == "draft"

    # Verify L1
    l1 = factor["l1"]
    assert l1["definition"] == "过去20个交易日的涨跌幅"
    assert l1["formula"] == "f_t = close_t / close_{t-20} - 1"
    assert l1["input_columns"] == ["close"]
    assert l1["frequency"] == "日频"
    assert l1["default_params"] == {"period": 20}

    # Verify L2
    l2 = factor["l2"]
    assert len(l2["calculation_steps"]) == 2
    assert l2["calculation_steps"][0]["description"] == "取close序列"
    assert l2["edge_case_handling"] == "前20个日期输出NaN"
    assert l2["complexity"] == "O(T × N)"

    # Verify L3
    l3 = factor["l3"]
    assert l3["financial_intuition"] == "市场对股票的近期认可程度"
    assert l3["theoretical_basis"] == "行为金融学动量效应"
    assert l3["related_factors"] == "与反转因子方向相反"

    # Verify L4
    l4 = factor["l4"]
    assert len(l4["hypotheses"]) == 1
    assert l4["hypotheses"][0]["id"] == "H1"


def test_track_b_to_factor_fallback_defaults():
    """When SignalDetail lacks classification, fallback to defaults."""
    from llmwikify.reproduction.pipeline.workflow import _track_b_to_factor

    detail = {
        "name": "Alpha#2",
        "description": "value factor",
        "l1": {"formula": "ep_ratio"},
        "l2": {},
        "l3": {},
        "l4": {},
        "success": True,
    }

    result = _track_b_to_factor(detail, "test_paper")
    factor = result["factor"]

    # Default classification
    assert factor["asset_type"] == "stock"
    assert factor["category"] == "price"
    assert factor["subcategory"] == "alpha"

    # L1 from SignalDetail
    assert factor["l1"]["formula"] == "ep_ratio"


def test_track_b_to_factor_empty_layers():
    """When SignalDetail has empty layers, factor dict is still valid."""
    from llmwikify.reproduction.pipeline.workflow import _track_b_to_factor

    detail = {
        "name": "Alpha#3",
        "classification": {"asset_type": "stock", "category": "price", "subcategory": "volatility"},
        "l1": {},
        "l2": {},
        "l3": {},
        "l4": {},
        "success": True,
    }

    result = _track_b_to_factor(detail, "test_paper")
    factor = result["factor"]

    assert factor["subcategory"] == "volatility"
    assert factor["l1"] == {}
    assert factor["l2"] == {}
    assert factor["l3"] == {}
    assert factor["l4"] == {}


def test_track_b_to_factor_partial_classification():
    """When classification has only some fields, use defaults for missing."""
    from llmwikify.reproduction.pipeline.workflow import _track_b_to_factor

    detail = {
        "name": "Alpha#4",
        "classification": {"subcategory": "reversal"},  # only subcategory
        "l1": {},
        "l2": {},
        "l3": {},
        "l4": {},
        "success": True,
    }

    result = _track_b_to_factor(detail, "test_paper")
    factor = result["factor"]

    assert factor["asset_type"] == "stock"  # default
    assert factor["category"] == "price"  # default
    assert factor["subcategory"] == "reversal"  # from classification


def test_workflow_config_defaults():
    """WorkflowConfig has sensible defaults."""
    from llmwikify.reproduction.pipeline.workflow import WorkflowConfig

    config = WorkflowConfig(paper_id="test", source_type="pdf", source_ref="test.pdf")
    assert config.paper_id == "test"
    assert config.symbol == "000300.SH"
    assert config.start_date == "2023-01-01"
    assert config.end_date == "2025-12-31"
    assert config.use_react is True
    assert config.skip_codegen is False
    assert config.skip_backtest is False


def test_workflow_result_defaults():
    """WorkflowResult has sensible defaults."""
    from llmwikify.reproduction.pipeline.workflow import WorkflowResult

    result = WorkflowResult(paper_id="test")
    assert result.success is False
    assert result.n_signals == 0
    assert result.n_coded == 0
    assert result.pass2_details == []
    assert result.code_results == []
    assert result.written_factors == []
    assert result.backtest_results == []
    assert result.error is None
