"""Tests for multi-factor paper extraction."""

from __future__ import annotations

import pytest


class TestExtractFactorsFromList:
    def _make_extraction(self, n_factors: int = 3) -> dict:
        """Create a mock extraction dict with factor_list."""
        factors = []
        for i in range(n_factors):
            factors.append({
                "name": f"alpha_{i+1:03d}",
                "formula": f"rank(close / delay(close, {5*(i+1)}))",
                "description": f"Alpha {i+1}: {5*(i+1)}日收益率排名",
                "asset_type": "stock",
                "category": "price",
                "subcategory": "momentum",
                "input_columns": ["close"],
                "frequency": "日频",
                "default_params": {"window": 5*(i+1)},
                "financial_intuition": f"捕捉{5*(i+1)}日动量",
                "market_behavior": "短期反转",
                "theoretical_basis": "行为金融学",
                "hypotheses": [
                    {
                        "id": "H1",
                        "name": f"Alpha {i+1} IC显著",
                        "description": f"Alpha {i+1} 的IC均值显著不为0",
                        "expected_ic_sign": "正",
                        "source": "理论推导",
                        "priority": "主假设",
                    }
                ],
                "calculation_steps": [
                    {"step": 1, "description": f"计算{5*(i+1)}日收益率"},
                    {"step": 2, "description": "截面排名"},
                ],
            })
        return {"factor_list": factors, "suggested_signal": {"signal_type": "unknown"}}

    def test_basic_extraction(self):
        """_extract_factors_from_list produces correct number of factors."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=5)
        results = _extract_factors_from_list(extraction, "test_paper")
        assert len(results) == 5

    def test_factor_name_format(self):
        """Factor names follow asset/category/slug format."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=1)
        results = _extract_factors_from_list(extraction, "test_paper")
        assert results[0]["name"] == "stock/price/alpha-001"

    def test_six_layer_structure(self):
        """Each factor has l1-l5 + metadata keys."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=1)
        results = _extract_factors_from_list(extraction, "test_paper")
        factor = results[0]["factor"]
        assert "l1" in factor
        assert "l2" in factor
        assert "l3" in factor
        assert "l4" in factor
        assert "l5" in factor
        assert "metadata" in factor

    def test_l1_fields(self):
        """L1 contains definition, formula, input_columns, etc."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=1)
        results = _extract_factors_from_list(extraction, "test_paper")
        l1 = results[0]["factor"]["l1"]
        assert l1["formula"] == "rank(close / delay(close, 5))"
        assert l1["input_columns"] == ["close"]
        assert l1["frequency"] == "日频"
        assert l1["default_params"] == {"window": 5}

    def test_l4_hypotheses_unverified(self):
        """L4 hypotheses are marked as 未验证."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=1)
        results = _extract_factors_from_list(extraction, "test_paper")
        hypotheses = results[0]["factor"]["l4"]["hypotheses"]
        assert len(hypotheses) == 1
        assert hypotheses[0]["status"] == "未验证"

    def test_empty_factor_list(self):
        """Empty factor_list returns empty list."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = {"factor_list": []}
        results = _extract_factors_from_list(extraction, "test_paper")
        assert results == []

    def test_missing_factor_list(self):
        """Missing factor_list returns empty list."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = {}
        results = _extract_factors_from_list(extraction, "test_paper")
        assert results == []

    def test_metadata_source_paper(self):
        """Metadata includes source_paper."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = self._make_extraction(n_factors=1)
        results = _extract_factors_from_list(extraction, "my_paper")
        assert results[0]["factor"]["metadata"]["source_paper"] == "my_paper"

    def test_defaults_for_missing_fields(self):
        """Missing fields get sensible defaults."""
        from llmwikify.reproduction.paper_understanding.extract_paper import (
            _extract_factors_from_list,
        )
        extraction = {"factor_list": [{"name": "minimal_factor"}]}
        results = _extract_factors_from_list(extraction, "test")
        factor = results[0]["factor"]
        assert factor["l1"]["input_columns"] == ["close"]
        assert factor["l1"]["frequency"] == "日频"
        assert factor["l2"]["data_alignment"] == "T+1"
        assert factor["l4"]["hypothesis_limit"] == 5
