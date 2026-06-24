"""Tests for extract_paper.py — paper structure extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.extract_paper import (
    build_paper_pages,
    extract_paper_structure,
)


class FakeLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response: str = ""):
        self._response = response or json.dumps({
            "strategy_logic": {
                "core_hypothesis": "Momentum works",
                "market_logic": "Trends persist",
                "alpha_source": "Price momentum",
                "applicable_conditions": "Trending markets",
            },
            "data_requirements": {
                "fields": ["close", "volume"],
                "frequency": "daily",
                "universe": "A-shares",
                "data_source": "Wind",
            },
            "operation_steps": {
                "signal_generation": "MA crossover",
                "position_sizing": "Full position",
                "rebalance_frequency": "Daily",
                "stop_loss": "None",
                "transaction_cost": "0.1%",
            },
            "model_framework": {
                "model_type": "technical",
                "framework": "MA crossover",
                "validation": "Backtest",
                "evaluation_metrics": ["sharpe", "max_dd"],
            },
            "strengths_weaknesses": {
                "strengths": ["Simple", "Robust"],
                "weaknesses": ["Lagging"],
                "improvement_directions": ["Add volume filter"],
            },
            "datasets": {
                "name": "CSI300",
                "source": "Wind",
                "time_range": "2020-2024",
                "processing": "None",
            },
            "risks": {
                "known_limitations": ["Lagging signal"],
                "assumption_risks": ["Trend persistence"],
                "implementation_gaps": ["Slippage"],
            },
            "references": {
                "original_paper": "Jegadeesh & Titman 1993",
                "related_papers": [],
                "code_repositories": [],
            },
            "suggested_signal": {
                "signal_type": "ma_cross",
                "signal_params": {"fast": 5, "slow": 20},
                "confidence": "medium",
                "reasoning": "Simple MA crossover matches paper description",
            },
        })

    def chat(self, messages, **kwargs):
        return self._response


def test_extract_paper_structure_with_llm():
    extraction = extract_paper_structure(
        paper_content="Test paper content about momentum",
        paper_id="test-001",
        source_type="pdf",
        source_ref="/tmp/test.pdf",
        llm_client=FakeLLMClient(),
    )
    assert extraction is not None
    assert extraction.get("strategy_logic") is not None
    assert extraction["strategy_logic"]["core_hypothesis"] == "Momentum works"


def test_extract_paper_structure_without_llm():
    extraction = extract_paper_structure(
        paper_content="Test paper content",
        paper_id="test-002",
        llm_client=None,
    )
    assert extraction == {}


def test_extract_paper_structure_empty_content():
    extraction = extract_paper_structure(
        paper_content="",
        paper_id="test-003",
        llm_client=FakeLLMClient(),
    )
    assert extraction == {}


def test_build_paper_pages_logic():
    extraction = {
        "strategy_logic": {
            "core_hypothesis": "Momentum works",
            "market_logic": "Trends persist",
            "alpha_source": "Price momentum",
            "applicable_conditions": "Trending markets",
        }
    }
    pages = build_paper_pages(extraction, "test-001")
    assert len(pages) >= 1
    logic_page = next(p for p in pages if "logic" in p["page_name"])
    assert "Momentum works" in logic_page["content"]
    assert logic_page["page_type"] == "Source"


def test_build_paper_pages_factor():
    extraction = {
        "suggested_signal": {
            "signal_type": "ma_cross",
            "signal_params": {"fast": 5, "slow": 20},
            "confidence": "medium",
            "reasoning": "Test",
        }
    }
    pages = build_paper_pages(extraction, "test-002")
    factor_page = next((p for p in pages if p["page_type"] == "Factor"), None)
    assert factor_page is not None
    assert "ma_cross" in factor_page["content"]
    assert "Factor" in factor_page["page_type"]


def test_build_paper_pages_strategy():
    extraction = {
        "suggested_signal": {
            "signal_type": "momentum",
            "signal_params": {"period": 60},
            "confidence": "high",
            "reasoning": "Test",
        }
    }
    pages = build_paper_pages(extraction, "test-003")
    strategy_page = next((p for p in pages if p["page_type"] == "Strategy"), None)
    assert strategy_page is not None
    assert "momentum" in strategy_page["content"]


def test_build_paper_pages_unknown_signal():
    extraction = {
        "suggested_signal": {
            "signal_type": "unknown",
            "signal_params": {},
            "confidence": "low",
            "reasoning": "Cannot determine",
        }
    }
    pages = build_paper_pages(extraction, "test-004")
    # Should NOT create Factor/Strategy pages for unknown signal
    factor_pages = [p for p in pages if p["page_type"] == "Factor"]
    strategy_pages = [p for p in pages if p["page_type"] == "Strategy"]
    assert len(factor_pages) == 0
    assert len(strategy_pages) == 0


def test_build_paper_pages_full():
    extraction = {
        "strategy_logic": {"core_hypothesis": "Test"},
        "data_requirements": {"fields": ["close"]},
        "risks": {"known_limitations": ["Lag"]},
        "suggested_signal": {
            "signal_type": "rsi",
            "signal_params": {"period": 14},
            "confidence": "high",
            "reasoning": "Test",
        },
    }
    pages = build_paper_pages(extraction, "test-005")
    assert len(pages) >= 4  # logic + data + risks + factor + strategy
    types = [p["page_type"] for p in pages]
    assert "Source" in types
    assert "Factor" in types
    assert "Strategy" in types


def test_build_paper_pages_operations():
    extraction = {
        "operation_steps": {
            "signal_generation": "MA cross",
            "position_sizing": "Equal weight",
            "rebalance_frequency": "Daily",
            "stop_loss": "5%",
            "transaction_cost": "0.1%",
        }
    }
    pages = build_paper_pages(extraction, "test-ops")
    ops_page = next((p for p in pages if p["page_name"].endswith("-operations")), None)
    assert ops_page is not None
    assert ops_page["page_type"] == "Source"
    assert "MA cross" in ops_page["content"]
    assert "Position Sizing" in ops_page["content"]
    assert "Stop Loss" in ops_page["content"]


def test_build_paper_pages_model():
    extraction = {
        "model_framework": {
            "model_type": "deep learning",
            "framework": "Transformer",
            "validation": "Walk-forward",
            "evaluation_metrics": ["sharpe", "ic", "rank_ic"],
        }
    }
    pages = build_paper_pages(extraction, "test-mdl")
    model_page = next((p for p in pages if p["page_name"].endswith("-model")), None)
    assert model_page is not None
    assert "Transformer" in model_page["content"]
    assert "sharpe" in model_page["content"]
    assert "ic" in model_page["content"]


def test_build_paper_pages_sw_three_columns():
    extraction = {
        "strengths_weaknesses": {
            "strengths": ["Simple", "Interpretable"],
            "weaknesses": ["Lagging"],
            "improvement_directions": ["Add regime filter"],
        }
    }
    pages = build_paper_pages(extraction, "test-sw")
    sw_page = next((p for p in pages if p["page_name"].endswith("-sw")), None)
    assert sw_page is not None
    assert "## Strengths" in sw_page["content"]
    assert "## Weaknesses" in sw_page["content"]
    assert "## Improvement Directions" in sw_page["content"]
    assert "Simple" in sw_page["content"]
    assert "Lagging" in sw_page["content"]
    assert "regime filter" in sw_page["content"]


def test_build_paper_pages_datasets():
    extraction = {
        "datasets": {
            "name": "CSI300",
            "source": "Wind",
            "time_range": "2010-2024",
            "processing": "Forward-adjusted prices",
        }
    }
    pages = build_paper_pages(extraction, "test-ds")
    ds_page = next((p for p in pages if p["page_name"].endswith("-datasets")), None)
    assert ds_page is not None
    assert "CSI300" in ds_page["content"]
    assert "2010-2024" in ds_page["content"]
    assert "Forward-adjusted" in ds_page["content"]


def test_build_paper_pages_references():
    extraction = {
        "references": {
            "original_paper": "Jegadeesh & Titman (1993)",
            "related_papers": ["Carhart (1997)", "Fama-French (1993)"],
            "code_repositories": ["https://github.com/example/momentum"],
        }
    }
    pages = build_paper_pages(extraction, "test-ref")
    ref_page = next((p for p in pages if p["page_name"].endswith("-references")), None)
    assert ref_page is not None
    assert "Jegadeesh & Titman (1993)" in ref_page["content"]
    assert "## Related Papers" in ref_page["content"]
    assert "Carhart (1997)" in ref_page["content"]
    assert "## Code Repositories" in ref_page["content"]
    assert "```" in ref_page["content"]
    assert "github.com/example/momentum" in ref_page["content"]


def test_build_paper_pages_all_eight_categories():
    """With all 8 categories, build 8 Source pages + Factor + Strategy = 10."""
    extraction = {
        "strategy_logic": {"core_hypothesis": "h"},
        "data_requirements": {"fields": ["close"]},
        "risks": {"known_limitations": ["x"]},
        "operation_steps": {"signal_generation": "sg"},
        "model_framework": {"model_type": "mt"},
        "strengths_weaknesses": {"strengths": ["a"]},
        "datasets": {"name": "n"},
        "references": {"original_paper": "op"},
        "suggested_signal": {
            "signal_type": "ma_cross",
            "signal_params": {"fast": 5},
            "reasoning": "r",
        },
    }
    pages = build_paper_pages(extraction, "test-all")
    source_pages = [p for p in pages if p["page_type"] == "Source"]
    assert len(source_pages) == 8
    suffixes = [
        "logic", "data", "risks", "operations", "model", "sw", "datasets", "references"
    ]
    for sfx in suffixes:
        assert any(p["page_name"].endswith(f"-{sfx}") for p in source_pages), \
            f"missing page suffix: {sfx}"
