"""Persistence: YAML + DB for backtest results."""
from __future__ import annotations

import math
import time
from typing import Any


def _nan_to_none(v):  # noqa: ANN001
    return None if isinstance(v, float) and math.isnan(v) else v


def persist_code_to_yaml(
    factor_name: str,
    code: str,
    formula_brief: str,
    backtest: dict,
    h5_path: str,
    code_chars: int,
    config: Any = None,
    *,
    alpha_index: int = 0,
    asset_type: str = "stock",
    category: str = "formulaic",
    frequency: str = "日频",
    nan_meaning: str = "上市不足或窗口期数据不足",
    business_constraints: str = "支持日频调仓, T+1 信号",
    pass_threshold: int = 60,
    strategy_dir: str = "",
    factors_dir: Any = None,
) -> tuple[str | None, Any]:
    """Persist code-path factor YAML (6-layer) to quant/factors/.

    If config is provided, reads business parameters from it.
    Otherwise uses explicit kwargs with defaults.

    Returns:
        (action, factor_dir_path) or (None, None) on failure.
    """
    from pathlib import Path

    from llmwikify.reproduction.persist.factor_library import (
        _get_factors_dir,
        read_factor_yaml,
        write_factor_yaml,
    )
    from llmwikify.reproduction.pipeline.data_loader import derive_input_columns
    from llmwikify.reproduction.pipeline.score import compute_score, compute_status

    # Apply config overrides
    if config is not None:
        asset_type = getattr(config, "asset_type", asset_type)
        category = getattr(config, "category", category)
        frequency = getattr(config, "frequency", frequency)
        nan_meaning = getattr(config, "nan_meaning", nan_meaning)
        business_constraints = getattr(config, "business_constraints", business_constraints)
        pass_threshold = getattr(config, "pass_threshold", pass_threshold)
        strategy_dir = getattr(config, "strategy_dir", strategy_dir)
        factors_dir = getattr(config, "factors_dir", factors_dir)

    slug = factor_name.replace("-", "_")

    # Directory naming: with hash if alpha_index > 0
    if alpha_index > 0:
        import hashlib
        code_hash = hashlib.md5(code.encode()).hexdigest()[:6]
        dir_name = f"stk_alpha_{alpha_index:03d}_{code_hash}"
        full_name = f"{strategy_dir}/{dir_name}" if strategy_dir else dir_name
    else:
        full_name = slug

    try:
        base_dir = Path(factors_dir) if factors_dir else _get_factors_dir()
        dir_path = base_dir / full_name
        dir_path.mkdir(parents=True, exist_ok=True)

        existing = read_factor_yaml(full_name)
        if existing is None:
            existing = read_factor_yaml(slug)
        if existing is None:
            data = {
                "factor": {
                    "name": slug,
                    "asset_type": asset_type,
                    "category": category,
                    "status": "已验证",
                }
            }
        else:
            data = existing

        factor = data.setdefault("factor", {})
        factor["name"] = slug
        factor["asset_type"] = factor.get("asset_type", asset_type)
        factor["category"] = factor.get("category", category)
        factor["status"] = "已验证"
        factor["updated_at"] = time.strftime("%Y-%m-%d")

        l1 = factor.setdefault("l1", {})
        if not l1.get("definition"):
            l1["definition"] = formula_brief[:200]
        l1["formula"] = formula_brief
        l1["frequency"] = frequency
        l1["output_schema"] = "[date × Code]"
        l1["input_columns"] = derive_input_columns(formula_brief)
        l1["nan_meaning"] = nan_meaning
        l1["default_params"] = {}
        l1["param_constraints"] = {}
        l1["business_constraints"] = business_constraints

        l5 = factor.setdefault("l5", {})
        l5["code"] = code
        l5["code_compile_status"] = "success"
        l5["code_chars"] = code_chars
        l5["h5_path"] = h5_path
        l5["ast"] = None
        l5["ast_compile_status"] = None
        l5["ast_compile_iterations"] = None
        l5["ast_compile_source"] = None
        l5["ast_compile_error"] = None

        icir = _nan_to_none(backtest.get("icir"))
        win_rate = _nan_to_none(backtest.get("win_rate"))
        l5["overall_assessment"] = {
            "score": compute_score(icir, win_rate),
            "status": compute_status(icir),
            "pass_threshold": pass_threshold,
            "final_meaning": "",
            "ic_mean": _nan_to_none(backtest.get("ic_mean")),
            "icir": icir,
            "winrate": win_rate,
            "rank_ic_mean": _nan_to_none(backtest.get("rank_ic_mean")),
            "rank_icir": _nan_to_none(backtest.get("rank_icir")),
            "annual_return": _nan_to_none(backtest.get("longshort_ann_return")),
            "longshort_sharpe": _nan_to_none(backtest.get("longshort_sharpe")),
            "longshort_max_dd": _nan_to_none(backtest.get("longshort_max_dd")),
            "validated_at": time.time(),
        }
        l5["validation_date"] = time.strftime("%Y-%m-%d")

        action = write_factor_yaml(full_name, data)
        print(f"[yaml] {action} (dir={dir_path})")
        return action, dir_path
    except Exception as exc:
        print(f"[yaml] persist_code_to_yaml failed for {factor_name}: {exc}")
        return None, None


def save_backtest_to_db(
    slug: str,
    alpha_index: int,
    backtest: dict,
    config: Any = None,
    *,
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    universe: str = "all",
    adj_mode: str = "M-end",
    wiki_id: str = "default",
    paper_id: str = "101_alphas_minimal",
    hedge: str = "equal",
) -> bool:
    """Persist backtest result to reproduction_results table.

    If config is provided, reads wiki_id, paper_id, hedge, etc. from it.
    Otherwise uses explicit kwargs with defaults.
    """
    if config is not None:
        wiki_id = getattr(config, "wiki_id", wiki_id)
        paper_id = getattr(config, "paper_id", paper_id)
        start_date = getattr(config, "date_beg_iso", start_date)
        end_date = getattr(config, "date_end_iso", end_date)
        universe = getattr(config, "sample_index", universe)
        adj_mode = getattr(config, "adj_mode", adj_mode)
        hedge = getattr(config, "hedge", hedge)

    try:
        from llmwikify.reproduction.persist.sessions import ReproductionDatabase

        db = ReproductionDatabase()
        run_id = f"pipeline_a_{alpha_index:03d}"
        session_id = db.create_session(
            wiki_id=wiki_id,
            paper_id=paper_id,
            source_type="pipeline_a",
            source_ref=f"alpha_{alpha_index:03d}",
            symbol="universe:all",
            start_date=start_date,
            end_date=end_date,
        )
        db.create_result(
            run_id=run_id,
            session_id=session_id,
            result_type="factor_backtest",
            factor_ref=slug,
            strategy_ref=None,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            status="success",
            error=None,
            wiki_path=None,
            adj_mode=adj_mode,
            hedge=hedge,
            data_source="quantnodes_pipeline",
            ic_mean=_nan_to_none(backtest.get("ic_mean")),
            rank_ic_mean=_nan_to_none(backtest.get("rank_ic_mean")),
            icir=_nan_to_none(backtest.get("icir")),
            rank_icir=_nan_to_none(backtest.get("rank_icir")),
            win_rate=_nan_to_none(backtest.get("win_rate")),
            annual_return=_nan_to_none(backtest.get("longshort_ann_return")),
            longshort_ann_return=_nan_to_none(backtest.get("longshort_ann_return")),
            longshort_sharpe=_nan_to_none(backtest.get("longshort_sharpe")),
            longshort_max_dd=_nan_to_none(backtest.get("longshort_max_dd")),
            ic_series=backtest.get("ic_series", []),
            group_metrics=backtest.get("group_metrics", {}),
            equity_curve=backtest.get("equity_curve") or backtest.get("group_nav_series"),
        )
        print(f"[db] created result run_id={run_id} factor_ref={slug}")
        return True
    except Exception as exc:
        print(f"[db] save_backtest_to_db failed for {slug}: {exc}")
        return False
