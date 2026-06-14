"""Tests for L4 hypothesis status sync from L5 hypothesis testing results.

Verifies that after L5 validation, L4 hypotheses have their status updated
to match LLM conclusions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _setup_factor_yaml(tmp_path: Path) -> Path:
    """Create a factor.yaml with L4 hypotheses for testing."""
    factors_dir = tmp_path / "quant" / "factors" / "stock" / "price"
    factors_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = factors_dir / "momentum_20d.yaml"
    yaml_path.write_text("""factor:
  name: stock_price_momentum_20d
  name_cn: 20日动量
  asset_type: stock
  category: price
  subcategory: momentum
  version: 1
  status: 已注册
  l1:
    definition: 动量
    formula: f_t = close_t / close_{t-20} - 1
  l2:
    calculation_steps: []
  l3: {}
  l4:
    hypotheses:
      - id: H1
        name: 动量延续
        description: 高动量未来继续涨
        expected_ic_sign: 正
        priority: 主假设
        status: 未验证
      - id: H2
        name: 反转回落
        description: 高动量反而跌
        expected_ic_sign: 负
        priority: 辅助假设
        status: 未验证
  l5: {}
  l6: {}
""", encoding="utf-8")
    return yaml_path


def test_l4_hypothesis_status_synced_from_l5(monkeypatch, tmp_path):
    """When L5 hypothesis_testing results are present, L4 hypothesis status should be updated."""
    import os
    os.chdir(tmp_path)
    _setup_factor_yaml(tmp_path)

    from llmwikify.reproduction import l5_orchestrator
    from llmwikify.reproduction import factor_library

    # Mock the backtest to return a known result
    class MockResult:
        ic_mean = 0.05
        ic_std = 0.1
        icir = 0.5
        rank_ic_mean = 0.05
        rank_ic_std = 0.1
        rank_icir = 0.5
        t_stat = 1.5
        win_rate = 0.6
        annual_return = 0.1
        max_drawdown = 0.1
        turnover = 0.3
        quantile_returns = {"G1": 0.1, "G2": 0.05, "G3": 0.0, "G4": -0.05, "G5": -0.1}
        ic_series = []
        quantile_curves = {}
        longshort_ann_return = 0.2
        longshort_sharpe = 1.5
        longshort_mdd = 0.1
        longshort_curve = []
        n_stocks_per_date = []
        group_metrics = {}
        total_rebalances = 0
        valid_rebalances = 0

    monkeypatch.setattr(l5_orchestrator, "_run_backtest", lambda *a, **kw: MockResult())

    # Mock LLM client to return hypothesis testing
    class MockLLM:
        def chat(self, messages, **kwargs):
            return json.dumps({
                "hypothesis_testing": [
                    {"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"},
                    {"hypothesis_id": "H2", "conclusion": "不支持（反向）", "reasoning": "IC positive means momentum continues"},
                ],
                "final_meaning": "20日动量因子是趋势跟随因子",
            })

    import json

    result = l5_orchestrator.run_l5_pipeline(
        factor_name="stock/price/momentum_20d",
        llm_client=MockLLM(),
        cost_bps=15.0,
        backtest_params={"start_date": "2024-01-01", "end_date": "2024-07-19"},
    )

    assert result["success"], f"Pipeline failed: {result.get('error')}"

    # Read back the YAML
    factor = factor_library.read_factor_yaml("stock/price/momentum_20d")
    assert factor is not None
    factor_data = factor["factor"]

    # Verify L4 hypotheses were updated
    hypotheses = factor_data["l4"]["hypotheses"]
    assert len(hypotheses) == 2

    h1 = next(h for h in hypotheses if h["id"] == "H1")
    assert h1["status"] == "支持", f"H1 should be 支持, got {h1.get('status')}"
    assert h1.get("conclusion") == "支持"

    h2 = next(h for h in hypotheses if h["id"] == "H2")
    assert h2["status"] == "不支持", f"H2 should be 不支持, got {h2.get('status')}"
    assert h2.get("conclusion") == "不支持（反向）"

    # Verify final_meaning was updated in L4
    assert factor_data["l4"]["final_meaning"] == "20日动量因子是趋势跟随因子"

    # Verify validation_date uses range format
    assert "~" in factor_data["l5"]["validation_date"]
    assert "2024-01-01" in factor_data["l5"]["validation_date"]
    assert "2024-07-19" in factor_data["l5"]["validation_date"]


def test_l4_partial_support_status(monkeypatch, tmp_path):
    """'部分支持' conclusion should map to '部分支持' status."""
    import os
    os.chdir(tmp_path)
    _setup_factor_yaml(tmp_path)

    from llmwikify.reproduction import l5_orchestrator
    from llmwikify.reproduction import factor_library

    class MockResult:
        ic_mean = 0.0
        ic_std = 0.0
        icir = 0.0
        rank_ic_mean = 0.0
        rank_ic_std = 0.0
        rank_icir = 0.0
        t_stat = 0.0
        win_rate = 0.0
        annual_return = 0.0
        max_drawdown = 0.0
        turnover = 0.0
        quantile_returns = {}
        ic_series = []
        quantile_curves = {}
        longshort_ann_return = 0.0
        longshort_sharpe = 0.0
        longshort_mdd = 0.0
        longshort_curve = []
        n_stocks_per_date = []
        group_metrics = {}
        total_rebalances = 0
        valid_rebalances = 0

    monkeypatch.setattr(l5_orchestrator, "_run_backtest", lambda *a, **kw: MockResult())

    class MockLLM:
        def chat(self, messages, **kwargs):
            return json.dumps({
                "hypothesis_testing": [
                    {"hypothesis_id": "H1", "conclusion": "部分支持", "reasoning": "mixed"},
                ],
            })

    import json

    result = l5_orchestrator.run_l5_pipeline(
        factor_name="stock/price/momentum_20d",
        llm_client=MockLLM(),
        cost_bps=15.0,
        backtest_params={"start_date": "2024-01-01", "end_date": "2024-07-19"},
    )

    assert result["success"]
    factor = factor_library.read_factor_yaml("stock/price/momentum_20d")
    h1 = factor["factor"]["l4"]["hypotheses"][0]
    assert h1["status"] == "部分支持"
