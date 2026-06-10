"""Tests for extract_factors.py — factor extraction from paper understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.extract_factors import (
    build_factor_pages,
    extract_factors,
)


class FakeLLMClient:
    def __init__(self):
        self._response = json.dumps({
            "factors": [
                {
                    "name": "Momentum Factor",
                    "factor_class": "momentum",
                    "description": "60-day price momentum",
                    "formula": "Close.pct_change(60)",
                    "params": {"lookback": 60},
                    "signal_type": "momentum",
                    "signal_params": {"period": 60, "threshold": 0.05},
                    "confidence": "medium",
                },
                {
                    "name": "Volatility Factor",
                    "factor_class": "volatility",
                    "description": "20-day rolling volatility",
                    "formula": "Close.rolling(20).std()",
                    "params": {"period": 20},
                    "signal_type": "volatility",
                    "signal_params": {"period": 20, "entry_std": 1.0},
                    "confidence": "low",
                },
            ],
            "primary_factor": "Momentum Factor",
            "reasoning": "Paper describes momentum strategy",
        })

    def chat(self, user_msg: str, system: str = "") -> str:
        return self._response


def test_extract_factors_with_llm():
    understanding = {
        "strategy_logic": {"core_hypothesis": "Momentum works"},
        "suggested_signal": {"signal_type": "momentum"},
    }
    factors = extract_factors(understanding, "test-001", llm_client=FakeLLMClient())
    assert len(factors) == 2
    assert factors[0]["name"] == "Momentum Factor"
    assert factors[0]["signal_type"] == "momentum"


def test_extract_factors_without_llm():
    factors = extract_factors({"test": True}, "test-002", llm_client=None)
    assert factors == []


def test_extract_factors_empty():
    factors = extract_factors({}, "test-003", llm_client=FakeLLMClient())
    assert factors == []


def test_build_factor_pages():
    factors = [
        {
            "name": "Momentum Factor",
            "factor_class": "momentum",
            "description": "60-day momentum",
            "formula": "pct_change(60)",
            "signal_type": "momentum",
            "signal_params": {"period": 60},
            "confidence": "high",
        }
    ]
    pages = build_factor_pages(factors, "test-001")
    assert len(pages) == 1
    assert pages[0]["page_type"] == "Factor"
    assert "momentum" in pages[0]["content"]
    assert "factor" in pages[0]["page_name"]


def test_build_factor_pages_slug():
    factors = [
        {"name": "My Cool Factor!", "factor_class": "value", "signal_type": "rsi", "signal_params": {}}
    ]
    pages = build_factor_pages(factors, "test-002")
    assert "my-cool-factor" in pages[0]["page_name"]


def test_build_factor_pages_multiple():
    factors = [
        {"name": "Factor A", "factor_class": "momentum", "signal_type": "ma_cross", "signal_params": {}},
        {"name": "Factor B", "factor_class": "value", "signal_type": "rsi", "signal_params": {}},
    ]
    pages = build_factor_pages(factors, "test-003")
    assert len(pages) == 2
    names = [p["page_name"] for p in pages]
    assert len(set(names)) == 2  # unique slugs
