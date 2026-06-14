"""L5 Orchestrator — chains the full L5 validation pipeline.

Flow:
  1. Read factor YAML (L1-L4)
  2. Run backtest (cross-section)
  3. Run L5 validation engine (7 modules + scoring)
  4. LLM hypothesis testing
  5. LLM final meaning generation
  6. Write results back to YAML
  7. Generate validation report

Trigger modes:
  - auto: on new factor registration
  - manual: user clicks "validate" button
  - scheduled: periodic check (future)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import yaml

from .factor_library import read_factor_yaml, write_factor_yaml
from .l5_validation import run_l5_validation

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# LLM Prompt for Hypothesis Testing
# ═══════════════════════════════════════════════════════════════

_HYPOTHESIS_TESTING_PROMPT = """你是一个量化因子分析专家。请根据以下因子分析数据，检验每个假设的结论。

## 因子信息
- 名称: {factor_name}
- 定义: {definition}
- 类别: {category}/{subcategory}

## L4 假设列表
{hypotheses_yaml}

## L5 分析结果

### IC 分析
- IC Mean: {ic_mean}
- ICIR: {icir}
- Rank IC Mean: {rank_ic_mean}
- Win Rate: {win_rate}

### 分组分析
- 分组年化收益: {group_returns}
- 分组单调性: {monotonicity}
- 多空年化收益: {ls_ann_return}
- 多空 Sharpe: {ls_sharpe}

### 收益分析
- 年化收益: {ann_return}
- Sharpe: {sharpe}
- Calmar: {calmar}
- Sortino: {sortino}

### 换手分析
- 平均换手率: {avg_turnover}

### OOS 分析
- OOS RankIC: {oos_rank_ic}
- OOS 多空 Sharpe: {oos_sharpe}

### 成本分析
- 扣费后年化: {net_ann_return}

### 综合评分: {score}/100

## 任务

对每个假设，判断其结论。结论必须是以下之一：
- **支持**: 数据强烈支持该假设
- **不支持**: 数据与该假设矛盾（包括"反向"情况）
- **部分支持**: 数据部分支持但不完全

请输出 JSON 格式：
```json
{{
  "hypothesis_testing": [
    {{"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC为正且ICIR>0.5..."}},
    ...
  ],
  "final_meaning": "根据分析结果，该因子是XXX因子，因为..."
}}
```

要求：
1. reasoning 简洁（50字以内）
2. final_meaning 一句话概括因子含义
3. 结论必须基于数据，不能凭空臆断
"""


def _build_hypothesis_prompt(
    factor: dict[str, Any],
    l5_data: dict[str, Any],
) -> str:
    """Build the hypothesis testing prompt from factor data + L5 analysis."""
    l4 = factor.get("l4", {})
    hypotheses = l4.get("hypotheses", [])
    fa = l5_data.get("factor_analysis", {})
    ic = fa.get("ic_analysis", {})
    ga = fa.get("group_analysis", {})
    ra = fa.get("return_analysis", {})
    ta = fa.get("turnover_analysis", {})
    oa = fa.get("oos_analysis", {})
    ca = fa.get("cost_analysis", {})
    score = l5_data.get("overall_assessment", {}).get("score", 0)

    hypotheses_yaml = yaml.dump(hypotheses, default_flow_style=False, allow_unicode=True)

    return _HYPOTHESIS_TESTING_PROMPT.format(
        factor_name=factor.get("name", "unknown"),
        definition=factor.get("l1", {}).get("definition", ""),
        category=factor.get("category", ""),
        subcategory=factor.get("subcategory", ""),
        hypotheses_yaml=hypotheses_yaml,
        ic_mean=ic.get("ic_mean", "N/A"),
        icir=ic.get("icir", "N/A"),
        rank_ic_mean=ic.get("rank_ic_mean", "N/A"),
        win_rate=ic.get("win_rate", "N/A"),
        group_returns=json.dumps(ga.get("group_returns", {}), ensure_ascii=False),
        monotonicity=ga.get("group_monotonicity", "N/A"),
        ls_ann_return=ga.get("ls_ann_return", "N/A"),
        ls_sharpe=ga.get("ls_sharpe", "N/A"),
        ann_return=ra.get("ann_return", "N/A"),
        sharpe=ra.get("sharpe", "N/A"),
        calmar=ra.get("calmar", "N/A"),
        sortino=ra.get("sortino", "N/A"),
        avg_turnover=ta.get("avg_turnover", "N/A"),
        oos_rank_ic=oa.get("oos_rank_ic", "N/A"),
        oos_sharpe=oa.get("oos_sharpe", "N/A"),
        net_ann_return=ca.get("net_ann_return", "N/A"),
        score=score,
    )


def _parse_llm_response(response: str) -> dict[str, Any]:
    """Parse LLM response JSON for hypothesis testing."""
    import re
    cleaned = re.sub(r"```(?:json)?\s*", "", response)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")
    return {}


# ═══════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════

def run_l5_pipeline(
    factor_name: str,
    llm_client: Any = None,
    cost_bps: float = 15.0,
    backtest_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full L5 validation pipeline for a factor.

    Steps:
      1. Read factor YAML
      2. Run backtest
      3. Run L5 validation engine
      4. LLM hypothesis testing (if llm_client provided)
      5. Write results back to YAML
      6. Return summary

    Args:
        factor_name: Factor path (e.g., 'stock/price/momentum_20d')
        llm_client: LLM client for hypothesis testing. If None, skip LLM step.
        cost_bps: Transaction cost in basis points
        backtest_params: Override backtest parameters (universe, dates, etc.)

    Returns:
        dict with keys: success, score, status, l5_data, error
    """
    # 1. Read factor YAML
    factor = read_factor_yaml(factor_name)
    if factor is None:
        return {"success": False, "error": f"Factor '{factor_name}' not found"}

    factor_data = factor.get("factor", factor)

    # 2. Run backtest
    bt_params = backtest_params or {}
    try:
        result = _run_backtest(factor_data, bt_params)
    except Exception as exc:
        logger.error("Backtest failed for %s: %s", factor_name, exc)
        return {"success": False, "error": f"Backtest failed: {exc}"}

    # 3. Run L5 validation engine
    l5_data = run_l5_validation(result, cost_bps=cost_bps)

    # 4. LLM hypothesis testing
    if llm_client is not None:
        try:
            prompt = _build_hypothesis_prompt(factor_data, l5_data)
            response = llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            )
            parsed = _parse_llm_response(response)
            if "hypothesis_testing" in parsed:
                l5_data["hypothesis_testing"] = parsed["hypothesis_testing"]
            if "final_meaning" in parsed:
                l5_data["overall_assessment"]["final_meaning"] = parsed["final_meaning"]
        except Exception as exc:
            logger.warning("LLM hypothesis testing failed: %s", exc)

    # 5. Write results back to YAML
    factor_data["l5"] = l5_data
    factor_data["status"] = l5_data["overall_assessment"]["status"]

    # Update L4 final_meaning if available
    final_meaning = l5_data["overall_assessment"].get("final_meaning")
    if final_meaning:
        factor_data.setdefault("l4", {})["final_meaning"] = final_meaning

    # 5b. Sync L4 hypothesis status from L5 hypothesis_testing results.
    # If LLM concluded H1=H2 as 支持/不支持/部分支持, update L4.
    l4 = factor_data.setdefault("l4", {})
    hypothesis_testing = l5_data.get("hypothesis_testing", [])
    if hypothesis_testing and l4.get("hypotheses"):
        for ht in hypothesis_testing:
            hyp_id = ht.get("hypothesis_id", "")
            conclusion = ht.get("conclusion", "")
            # Find matching L4 hypothesis and update status
            for h in l4["hypotheses"]:
                if h.get("id") == hyp_id:
                    # Map LLM conclusion to L4 status (order matters!)
                    # "不支持" must be checked before "支持" since "不" is a substring
                    if "部分" in conclusion:
                        h["status"] = "部分支持"
                    elif "不支持" in conclusion or "反向" in conclusion:
                        h["status"] = "不支持"
                    elif "支持" in conclusion:
                        h["status"] = "支持"
                    else:
                        h["status"] = "已验证"
                    h["conclusion"] = conclusion
                    h["reasoning"] = ht.get("reasoning", "")
                    break

    # 5c. Update validation_date as range (design requirement)
    start_date = bt_params.get("start_date", "")
    end_date = bt_params.get("end_date", "")
    if start_date and end_date:
        l5_data["validation_date"] = f"{start_date}~{end_date}"
    else:
        l5_data["validation_date"] = datetime.now().strftime("%Y-%m-%d")

    # Version bump (only if L5 data actually changed)
    if l5_data.get("score") is not None:
        factor_data["version"] = factor_data.get("version", 1) + 1
        factor_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    write_factor_yaml(factor_name, factor)

    return {
        "success": True,
        "score": l5_data["overall_assessment"]["score"],
        "status": l5_data["overall_assessment"]["status"],
        "breakdown": l5_data["overall_assessment"]["breakdown"],
        "l5_data": l5_data,
    }


def _run_backtest(factor_data: dict, bt_params: dict) -> Any:
    """Run backtest using existing infrastructure."""
    import asyncio
    from llmwikify.reproduction.config import config
    from llmwikify.reproduction.router import DataRouter

    factor_class = factor_data.get("subcategory", factor_data.get("factor_class", "momentum"))
    factor_params = factor_data.get("l1", {}).get("default_params", factor_data.get("factor_params", {}))
    if isinstance(factor_params, str):
        try:
            factor_params = json.loads(factor_params)
        except (json.JSONDecodeError, TypeError):
            factor_params = {}

    universe = bt_params.get("universe", config.get("universe.default", "synth"))
    start_date = bt_params.get("start_date", "2023-01-01")
    end_date = bt_params.get("end_date", "2024-12-31")
    adj_mode = bt_params.get("adj_mode", "D")
    n_groups = bt_params.get("n_groups", 5)
    factor_direction = bt_params.get("factor_direction", 1)

    data_router = DataRouter(use_cache=True)

    # Resolve universe
    from llmwikify.reproduction.universe import resolve_universe
    symbols = resolve_universe(universe)
    if not symbols:
        raise ValueError(f"Cannot resolve universe '{universe}'")

    # Fetch data
    merged_df, _ = data_router.get_universe(symbols, start_date, end_date)
    if merged_df is None or merged_df.empty:
        raise ValueError(f"No data for universe '{universe}'")

    close_wide = merged_df.pivot_table(
        index="date", columns="Code", values="close", aggfunc="last"
    )
    close_wide = close_wide.sort_index().dropna(how="all")

    from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe
    return run_factor_backtest_universe(
        close_wide=close_wide,
        factor_class=factor_class,
        factor_params=factor_params,
        adj_mode=adj_mode,
        n_groups=n_groups,
        factor_direction=factor_direction,
        universe=universe,
    )


__all__ = [
    "run_l5_pipeline",
    "_build_hypothesis_prompt",
    "_parse_llm_response",
]
