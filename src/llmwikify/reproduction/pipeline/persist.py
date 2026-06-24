"""Persistence: YAML + DB for backtest results."""
from __future__ import annotations

import math
import time


def _nan_to_none(v):  # noqa: ANN001
    return None if isinstance(v, float) and math.isnan(v) else v


def persist_code_to_yaml(
    factor_name: str,
    code: str,
    formula_brief: str,
    backtest: dict,
    h5_path: str,
    code_chars: int,
) -> str | None:
    """Persist code-path factor YAML (6-layer) to quant/factors/.

    Mirrors ``factor_compiler.persist_l5_to_yaml`` pattern:
      read_factor_yaml -> modify l5.* -> write_factor_yaml -> log.
    """
    from llmwikify.reproduction.factor_library import (
        read_factor_yaml,
        write_factor_yaml,
    )
    from llmwikify.reproduction.pipeline.score import compute_score, compute_status

    slug = factor_name.replace("-", "_")

    try:
        existing = read_factor_yaml(slug)
        if existing is None:
            data = {
                "factor": {
                    "name": slug,
                    "asset_type": "stock",
                    "category": "formulaic",
                    "status": "已验证",
                }
            }
        else:
            data = existing

        factor = data.setdefault("factor", {})
        factor["name"] = slug
        factor["asset_type"] = factor.get("asset_type", "stock")
        factor["category"] = factor.get("category", "formulaic")
        factor["status"] = "已验证"
        factor["updated_at"] = time.strftime("%Y-%m-%d")

        from llmwikify.reproduction.pipeline.data_loader import derive_input_columns

        l1 = factor.setdefault("l1", {})
        l1["definition"] = formula_brief[:200]
        l1["formula"] = formula_brief
        l1["frequency"] = "日频"
        l1["output_schema"] = "[date × Code]"
        l1["input_columns"] = derive_input_columns(formula_brief)
        l1["nan_meaning"] = "上市不足或窗口期数据不足"
        l1["default_params"] = {}
        l1["param_constraints"] = {}
        l1["business_constraints"] = "支持日频调仓, T+1 信号"

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
            "pass_threshold": 60,
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

        action = write_factor_yaml(slug, data)
        print(f"[yaml] {action} (slug={slug})")
        return action
    except Exception as exc:
        print(f"[yaml] persist_code_to_yaml failed for {factor_name}: {exc}")
        return None


def save_backtest_to_db(
    slug: str,
    alpha_index: int,
    backtest: dict,
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    universe: str = "all",
    adj_mode: str = "M-end",
) -> bool:
    """Persist backtest result to reproduction_results table.

    Reuses ReproductionDatabase.create_result (sessions.py:413).
    """
    try:
        from llmwikify.reproduction.sessions import ReproductionDatabase

        db = ReproductionDatabase()
        run_id = f"pipeline_a_{alpha_index:03d}"
        session_id = db.create_session(
            wiki_id="default",
            paper_id="101_alphas_minimal",
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
            hedge="equal",
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
        )
        print(f"[db] created result run_id={run_id} factor_ref={slug}")
        return True
    except Exception as exc:
        print(f"[db] save_backtest_to_db failed for {slug}: {exc}")
        return False
