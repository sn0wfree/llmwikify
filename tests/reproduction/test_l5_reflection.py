"""Tests for L5 reflection feature."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.reproduction.l5_orchestrator import (
    _build_reflection_prompt,
    _parse_reflection,
    run_l5_pipeline,
)


def _mock_factor_data():
    """Return a minimal factor data dict."""
    return {
        "factor": {
            "name": "stock/price/test_factor",
            "l1": {
                "definition": "20-day momentum",
                "formula": "f_t = close_t / close_{t-20} - 1",
                "default_params": {"period": 20},
            },
            "l4": {
                "hypotheses": [
                    {
                        "id": "H1",
                        "name": "Momentum persists",
                        "expected_ic_sign": "正",
                        "status": "未验证",
                    }
                ],
            },
            "version": 1,
        }
    }


def _mock_l5_data(score=55):
    """Return mock L5 data."""
    return {
        "factor_analysis": {
            "ic_analysis": {"ic_mean": 0.02, "icir": 0.5, "rank_ic_mean": 0.025, "win_rate": 0.55},
            "group_analysis": {"group_monotonicity": "G1>G2>G3>G4>G5", "ls_ann_return": 0.1, "ls_sharpe": 1.2, "ls_max_drawdown": 0.15},
            "return_analysis": {"ann_return": 0.08, "sharpe": 0.8, "calmar": 0.5, "sortino": 1.0},
            "turnover_analysis": {"avg_turnover": 0.3},
            "stability_analysis": {"yearly": {"2023": {"rank_ic": 0.02}, "2024": {"rank_ic": 0.015}}},
            "oos_analysis": {"oos_rank_ic": 0.015, "oos_sharpe": 0.8},
            "cost_analysis": {"net_ann_return": 0.06},
        },
        "hypothesis_testing": [{"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"}],
        "overall_assessment": {"score": score, "status": "失败" if score < 60 else "通过", "final_meaning": None},
    }


def _mock_backtest_result():
    """Return a mock FactorBacktestResult."""
    import datetime
    base = datetime.datetime(2023, 1, 1)
    ic_series = [
        {"date": (base + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), "ic": 0.02}
        for i in range(100)
    ]
    return SimpleNamespace(
        ic_series=ic_series,
        longshort_curve=[],
        longshort_sharpe=1.0,
        longshort_mdd=0.1,
        ic_mean=0.02,
        ic_std=0.01,
        icir=2.0,
        t_stat=3.0,
        win_rate=0.6,
        annual_return=0.1,
        max_drawdown=0.15,
        turnover=0.3,
        quantile_returns={"G1": 0.1, "G5": -0.05},
        group_metrics={},
        n_stocks_per_date=[],
        total_rebalances=100,
        valid_rebalances=100,
    )


# ─── _build_reflection_prompt ──────────────────────────────────────────


class TestBuildReflectionPrompt:
    def test_includes_factor_info(self):
        """Prompt includes factor name, definition, formula."""
        factor = _mock_factor_data()["factor"]
        l5_data = _mock_l5_data()
        prompt = _build_reflection_prompt(factor, l5_data)
        assert "test_factor" in prompt
        assert "20-day momentum" in prompt
        assert "close_t / close_{t-20}" in prompt

    def test_includes_l5_metrics(self):
        """Prompt includes key L5 metrics."""
        factor = _mock_factor_data()["factor"]
        l5_data = _mock_l5_data(score=55)
        prompt = _build_reflection_prompt(factor, l5_data)
        assert "55" in prompt
        assert "0.02" in prompt  # ic_mean
        assert "1.2" in prompt   # ls_sharpe

    def test_includes_hypothesis_testing(self):
        """Prompt includes hypothesis testing results."""
        factor = _mock_factor_data()["factor"]
        l5_data = _mock_l5_data()
        prompt = _build_reflection_prompt(factor, l5_data)
        assert "H1" in prompt
        assert "支持" in prompt

    def test_includes_params(self):
        """Prompt includes factor params."""
        factor = _mock_factor_data()["factor"]
        l5_data = _mock_l5_data()
        prompt = _build_reflection_prompt(factor, l5_data)
        assert "period" in prompt


# ─── _parse_reflection ─────────────────────────────────────────────────


class TestParseReflection:
    def test_valid_json(self):
        """Parse valid JSON response."""
        response = json.dumps({
            "suggestions": [
                {
                    "type": "parameter_adjustment",
                    "path": "l1.default_params.period",
                    "current_value": 20,
                    "proposed_value": 10,
                    "reasoning": "IC decays fast",
                    "expected_impact": "IC +30%",
                    "confidence": "medium",
                }
            ],
            "reflection_notes": "Main issue is period too long.",
        })
        result = _parse_reflection(response)
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["type"] == "parameter_adjustment"
        assert result["reflection_notes"] == "Main issue is period too long."

    def test_think_block_stripped(self):
        """Think blocks are stripped before parsing."""
        response = "<think>Analyzing...</think>" + json.dumps({
            "suggestions": [],
            "reflection_notes": "Factor is good.",
        })
        result = _parse_reflection(response)
        assert result["reflection_notes"] == "Factor is good."

    def test_code_fence_stripped(self):
        """Code fences are stripped before parsing."""
        response = "```json\n" + json.dumps({
            "suggestions": [{"type": "new_hypothesis", "path": "l4.hypotheses", "current_value": None, "proposed_value": "H2", "reasoning": "New insight", "expected_impact": "Better understanding", "confidence": "low"}],
            "reflection_notes": "...",
        }) + "\n```"
        result = _parse_reflection(response)
        assert len(result["suggestions"]) == 1

    def test_invalid_json(self):
        """Invalid JSON returns empty suggestions."""
        result = _parse_reflection("not json at all")
        assert result["suggestions"] == []
        assert result["reflection_notes"] == ""

    def test_empty_suggestions(self):
        """Empty suggestions list is valid."""
        response = json.dumps({"suggestions": [], "reflection_notes": "All good."})
        result = _parse_reflection(response)
        assert result["suggestions"] == []
        assert result["reflection_notes"] == "All good."

    def test_multiple_suggestions(self):
        """Multiple suggestions are parsed correctly."""
        response = json.dumps({
            "suggestions": [
                {"type": "parameter_adjustment", "path": "l1.default_params.period", "current_value": 20, "proposed_value": 10, "reasoning": "...", "expected_impact": "...", "confidence": "high"},
                {"type": "formula_improvement", "path": "l1.formula", "current_value": "old", "proposed_value": "new", "reasoning": "...", "expected_impact": "...", "confidence": "medium"},
            ],
            "reflection_notes": "...",
        })
        result = _parse_reflection(response)
        assert len(result["suggestions"]) == 2
        assert result["suggestions"][0]["type"] == "parameter_adjustment"
        assert result["suggestions"][1]["type"] == "formula_improvement"


# ─── run_l5_pipeline integration ───────────────────────────────────────


class TestReflectionInPipeline:
    def test_reflection_stored_in_l5(self):
        """Reflection results are stored in l5.reflections."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        mock_llm = MagicMock()
        # First call: hypothesis testing, second call: reflection
        mock_llm.chat.side_effect = [
            json.dumps({"hypothesis_testing": [{"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"}], "final_meaning": "Momentum factor."}),
            json.dumps({"suggestions": [{"type": "parameter_adjustment", "path": "l1.default_params.period", "current_value": 20, "proposed_value": 10, "reasoning": "IC decays", "expected_impact": "IC +30%", "confidence": "medium"}], "reflection_notes": "Period too long."}),
        ]

        written = {}
        def capture_write(name, data):
            written["data"] = data

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml", side_effect=capture_write):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)

            assert result["success"] is True
            # LLM was called twice (hypothesis + reflection)
            assert mock_llm.chat.call_count == 2
            # Reflection is in l5_data
            l5_data = result["l5_data"]
            assert "reflections" in l5_data
            assert len(l5_data["reflections"]) == 1
            reflection = l5_data["reflections"][0]
            assert reflection["iteration"] == 1
            assert len(reflection["suggestions"]) == 1
            assert reflection["suggestions"][0]["type"] == "parameter_adjustment"
            assert reflection["applied"] is False
            # Reflection is written to YAML
            assert "reflections" in written["data"]["factor"]["l5"]

    def test_reflection_failure_doesnt_block(self):
        """Reflection failure doesn't block the pipeline."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        mock_llm = MagicMock()
        # First call succeeds (hypothesis), second call fails (reflection)
        mock_llm.chat.side_effect = [
            json.dumps({"hypothesis_testing": [], "final_meaning": "..."}),
            Exception("LLM error"),
        ]

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)
            # Pipeline still succeeds
            assert result["success"] is True

    def test_no_llm_no_reflection(self):
        """Without LLM client, no reflection is generated."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=None)
            l5_data = result["l5_data"]
            assert "reflections" not in l5_data or l5_data.get("reflections") == []

    def test_empty_suggestions_not_stored(self):
        """Empty suggestions list is not stored."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"hypothesis_testing": [], "final_meaning": "..."}),
            json.dumps({"suggestions": [], "reflection_notes": "All good."}),
        ]

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)
            l5_data = result["l5_data"]
            # Empty suggestions should not create a reflection entry
            reflections = l5_data.get("reflections", [])
            assert len(reflections) == 0

    def test_reflection_iteration_increments(self):
        """Reflection iteration number increments correctly."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        # Pre-existing reflection
        mock_factor["factor"]["l5"] = {
            "reflections": [
                {"iteration": 1, "date": "2024-01-01", "suggestions": [], "applied": True}
            ]
        }

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"hypothesis_testing": [], "final_meaning": "..."}),
            json.dumps({"suggestions": [{"type": "parameter_adjustment", "path": "l1.default_params.period", "current_value": 20, "proposed_value": 10, "reasoning": "...", "expected_impact": "...", "confidence": "high"}], "reflection_notes": "..."}),
        ]

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)
            reflections = result["l5_data"]["reflections"]
            assert len(reflections) == 2
            assert reflections[0]["iteration"] == 1
            assert reflections[1]["iteration"] == 2
