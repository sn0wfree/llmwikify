"""Tests for run_l5_pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.reproduction.l5_orchestrator import (
    _build_hypothesis_prompt,
    _parse_llm_response,
    run_l5_pipeline,
)


def _mock_factor_data():
    """Return a minimal factor data dict."""
    return {
        "factor": {
            "name": "stock/price/test_factor",
            "l1": {
                "definition": "Test factor",
                "formula": "f_t = close_t / close_{t-20} - 1",
                "default_params": {"period": 20},
            },
            "l4": {
                "hypotheses": [
                    {
                        "id": "H1",
                        "name": "Test hypothesis",
                        "expected_ic_sign": "正",
                        "status": "未验证",
                    }
                ],
            },
            "version": 1,
        }
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


class TestRunL5Pipeline:
    def test_factor_not_found(self):
        """Returns error when factor not found."""
        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=None):
            result = run_l5_pipeline("nonexistent")
            assert result["success"] is False
            assert "not found" in result["error"]

    def test_backtest_failure(self):
        """Returns error when backtest fails."""
        mock_factor = _mock_factor_data()
        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", side_effect=Exception("backtest error")):
            result = run_l5_pipeline("stock/price/test_factor")
            assert result["success"] is False
            assert "backtest error" in result["error"]

    def test_success_without_llm(self):
        """Pipeline succeeds without LLM client."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()
        written = {}

        def capture_write(name, data):
            written["name"] = name
            written["data"] = data

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml", side_effect=capture_write):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=None)

            assert result["success"] is True
            assert "score" in result
            assert "status" in result
            assert result["status"] in ("通过", "失败", "待更新")

            # YAML was written
            assert written["name"] == "stock/price/test_factor"
            data = written["data"]
            assert "factor" in data
            assert "l5" in data["factor"]
            assert data["factor"]["version"] == 2  # Version bumped

    def test_success_with_mock_llm(self):
        """Pipeline succeeds with mock LLM client."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        mock_llm = MagicMock()
        mock_llm.chat.return_value = json.dumps({
            "hypothesis_testing": [
                {"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"}
            ],
            "final_meaning": "This is a momentum factor.",
        })

        written = {}
        def capture_write(name, data):
            written["data"] = data

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml", side_effect=capture_write):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)

            assert result["success"] is True
            # LLM was called
            mock_llm.chat.assert_called_once()
            # Hypothesis testing was populated
            l5_data = result["l5_data"]
            assert len(l5_data["hypothesis_testing"]) == 1
            assert l5_data["hypothesis_testing"][0]["conclusion"] == "支持"
            # Final meaning was set
            assert l5_data["overall_assessment"]["final_meaning"] == "This is a momentum factor."
            # L4 hypothesis status was synced
            l4 = written["data"]["factor"]["l4"]
            assert l4["hypotheses"][0]["status"] == "支持"

    def test_llm_failure_doesnt_block_pipeline(self):
        """LLM failure doesn't block the pipeline."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = Exception("LLM error")

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor", llm_client=mock_llm)
            # Pipeline still succeeds
            assert result["success"] is True

    def test_validation_date_set(self):
        """validation_date is set in the output."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml"):
            result = run_l5_pipeline("stock/price/test_factor")
            l5_data = result["l5_data"]
            assert "validation_date" in l5_data
            assert l5_data["validation_date"]  # Not empty

    def test_version_bumped(self):
        """Version is bumped after successful pipeline."""
        mock_factor = _mock_factor_data()
        mock_bt = _mock_backtest_result()
        written = {}

        def capture_write(name, data):
            written["data"] = data

        with patch("llmwikify.reproduction.l5_orchestrator.read_factor_yaml", return_value=mock_factor), \
             patch("llmwikify.reproduction.l5_orchestrator._run_backtest", return_value=mock_bt), \
             patch("llmwikify.reproduction.l5_orchestrator.write_factor_yaml", side_effect=capture_write):
            run_l5_pipeline("stock/price/test_factor")
            assert written["data"]["factor"]["version"] == 2


class TestBuildHypothesisPrompt:
    def test_includes_key_fields(self):
        """Prompt includes factor info and L5 data."""
        factor = _mock_factor_data()["factor"]
        l5_data = {
            "factor_analysis": {
                "ic_analysis": {"ic_mean": 0.02, "icir": 2.0, "rank_ic_mean": 0.025, "win_rate": 0.6},
                "group_analysis": {"group_returns": {}, "group_monotonicity": "G1>G5", "ls_ann_return": 0.1, "ls_sharpe": 1.5},
                "return_analysis": {"ann_return": 0.1, "sharpe": 1.0, "calmar": 0.8, "sortino": 1.2},
                "turnover_analysis": {"avg_turnover": 0.3},
                "oos_analysis": {"oos_rank_ic": 0.015, "oos_sharpe": 0.8},
                "cost_analysis": {"net_ann_return": 0.08},
            },
            "overall_assessment": {"score": 75},
        }
        prompt = _build_hypothesis_prompt(factor, l5_data)
        assert "test_factor" in prompt
        assert "0.02" in prompt
        assert "75" in prompt


class TestParseLlmResponse:
    def test_valid_json(self):
        response = '{"hypothesis_testing": [{"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"}], "final_meaning": "Momentum factor."}'
        parsed = _parse_llm_response(response)
        assert "hypothesis_testing" in parsed
        assert len(parsed["hypothesis_testing"]) == 1

    def test_think_block_stripped(self):
        response = '<think>分析中...</think>{"hypothesis_testing": [], "final_meaning": "..."}'
        parsed = _parse_llm_response(response)
        assert "hypothesis_testing" in parsed

    def test_invalid_json(self):
        parsed = _parse_llm_response("not json at all")
        assert parsed == {}
