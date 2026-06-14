"""Tests for the upgraded _extract_factor_from_page function.

Verifies that factor wiki pages can be converted to 6-layer YAML using
the new factor_metadata field from LLM extraction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_extract_factor_uses_factor_metadata():
    """When extraction has factor_metadata, all 6 layers should be populated from it."""
    from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

    # Simulate a Factor wiki page (output of build_paper_pages)
    page = {
        "page_name": "factor-test-paper-momentum",
        "content": """---
title: 动量因子
type: Factor
factor_class: momentum
signal_type: momentum
signal_params: {"period": 20}
status: draft
---

# Factor — test-paper

**Signal Type:** momentum
**Parameters:** {"period": 20}
**Reasoning:** momentum works
""",
    }

    # Simulate LLM extraction output (with new factor_metadata field)
    extraction = {
        "suggested_signal": {
            "signal_type": "momentum",
            "signal_params": {"period": 20},
        },
        "factor_metadata": {
            "asset_type": "stock",
            "category": "price",
            "subcategory": "momentum",
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
                "meaning_summary": "捕捉20日价格趋势",
                "key_insights": ["A股可能表现为反转"],
                "uncertainty": "需L5验证",
            },
        },
    }

    result = _extract_factor_from_page(page, "test-paper", extraction=extraction)
    factor = result["factor"]

    # Verify name and metadata
    assert "name" in result
    assert "stock/price/" in result["name"]
    assert factor["name_cn"] == "动量因子"
    assert factor["asset_type"] == "stock"
    assert factor["category"] == "price"
    assert factor["subcategory"] == "momentum"
    assert factor["version"] == 1
    assert factor["status"] == "已注册"

    # Verify L1 from metadata
    l1 = factor["l1"]
    assert l1["definition"] == "过去20个交易日的涨跌幅"
    assert l1["formula"] == "f_t = close_t / close_{t-20} - 1"
    assert l1["input_columns"] == ["close"]
    assert l1["frequency"] == "日频"
    assert l1["default_params"] == {"period": 20}
    assert l1["param_constraints"] == {"period": "≥5"}
    assert l1["business_constraints"] == "上市不足20日不可算"
    # Verify code_location NOT in l1 (was a bug)
    assert "code_location" not in l1

    # Verify L2 from metadata (multi-step)
    l2 = factor["l2"]
    assert len(l2["calculation_steps"]) == 2
    assert l2["calculation_steps"][0]["description"] == "取close序列"
    assert l2["edge_case_handling"] == "前20个日期输出NaN"
    assert l2["missing_value_handling"] == "保持NaN"
    assert l2["complexity"] == "O(T × N)"
    assert l2["data_alignment"] == "T+1"
    # Verify code_location NOT in l2 (LLM shouldn't fill this in)
    assert "code_location" not in l2

    # Verify L3 from metadata
    l3 = factor["l3"]
    assert l3["financial_intuition"] == "市场对股票的近期认可程度"
    assert l3["market_behavior"] == "价格偏离近期均值"
    assert l3["theoretical_basis"] == "行为金融学动量效应"
    assert l3["historical_effectiveness"] == "A股2010-2020有效"
    assert l3["related_factors"] == "与反转因子方向相反"

    # Verify L4 from metadata (with status set)
    l4 = factor["l4"]
    assert len(l4["hypotheses"]) == 1
    assert l4["hypotheses"][0]["id"] == "H1"
    assert l4["hypotheses"][0]["name"] == "动量延续"
    assert l4["hypotheses"][0]["status"] == "未验证"  # auto-set
    assert l4["hypothesis_limit"] == 5
    assert l4["archived_hypotheses"] == []
    assert l4["meaning_summary"] == "捕捉20日价格趋势"
    assert "A股可能表现为反转" in l4["key_insights"]
    assert l4["uncertainty"] == "需L5验证"
    assert l4["final_meaning"] is None

    # L5/L6 should be empty
    assert factor["l5"] == {}
    assert factor["l6"] == {}


def test_extract_factor_falls_back_when_no_metadata():
    """When extraction has no factor_metadata, fall back to wiki frontmatter + defaults."""
    from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

    page = {
        "page_name": "factor-test-paper-momentum",
        "content": """---
title: 动量因子
type: Factor
factor_class: momentum
signal_type: momentum
signal_params: {"period": 20}
status: draft
reasoning: momentum works
---
""",
    }

    # No extraction provided
    result = _extract_factor_from_page(page, "test-paper", extraction=None)
    factor = result["factor"]

    # L1 should fall back to defaults (no formula in wiki frontmatter)
    l1 = factor["l1"]
    assert l1["input_columns"] == ["close"]  # default
    assert l1["frequency"] == "日频"  # default
    assert "code_location" not in l1

    # L2 should have a single generic step
    l2 = factor["l2"]
    assert len(l2["calculation_steps"]) == 1

    # L3 should use reasoning
    l3 = factor["l3"]
    assert "momentum works" in l3["financial_intuition"]

    # L4 should have no hypotheses
    l4 = factor["l4"]
    assert l4["hypotheses"] == []


def test_extract_factor_l4_hypotheses_get_unverified_status():
    """Hypotheses from LLM should be marked 未验证 (just registered)."""
    from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

    page = {
        "page_name": "factor-x-y",
        "content": "---\ntitle: X Factor\nfactor_class: value\n---\n",
    }

    extraction = {
        "factor_metadata": {
            "subcategory": "value",
            "l4": {
                "hypotheses": [
                    {"id": "H1", "name": "value premium"},
                    {"id": "H2", "name": "reversal", "status": "支持"},  # already verified
                ],
            },
        }
    }

    result = _extract_factor_from_page(page, "test", extraction=extraction)
    factor = result["factor"]
    hypotheses = factor["l4"]["hypotheses"]

    # H1 had no status, should get 未验证
    assert hypotheses[0]["status"] == "未验证"
    # H2 had explicit status, should be preserved
    assert hypotheses[1]["status"] == "支持"


def test_extract_factor_code_location_not_in_any_layer():
    """Verify code_location is NEVER injected into any layer (L1 or L2)."""
    from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

    page = {
        "page_name": "factor-x",
        "content": "---\ntitle: X\n---\n",
    }

    # Both with and without metadata
    for extraction in [None, {"factor_metadata": {}}]:
        result = _extract_factor_from_page(page, "test", extraction=extraction)
        factor = result["factor"]
        assert "code_location" not in factor["l1"], f"code_location leaked into l1: {factor['l1']}"
        assert "code_location" not in factor["l2"], f"code_location leaked into l2: {factor['l2']}"
