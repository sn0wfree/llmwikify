"""锁定每个 reproduction/ 模块的公共 API.

防止 refactor 时意外删除/重命名公共函数/类, 破坏 WebUI/CLI/外部调用.

Phase 1+2 完成后, common/ 和 data_source/ 子包的模块路径已更新.

详见: docs/designs/pipeline_framework.md Section 29.5.2
"""
from __future__ import annotations

import importlib

import pytest

# 每个模块的关键公共 API (函数名 + 类名, 不含签名)
# Phase 3: 更新为新路径 (common.X / data_source.X)
EXPECTED_PUBLIC_API = {
    # ── common/ 子包 (Phase 1) ──
    "common.config": [
        "config",
        "Config",
    ],
    "common.paths": [
        "WIKI_DIR_FACTOR",
        "WIKI_DIR_REPRODUCTION",
        "WIKI_DIR_SOURCES",
        "WIKI_DIR_STRATEGY",
        "page_path",
        "result_path",
    ],
    "common.run_id": [
        "generate_run_id",
    ],
    "common.telemetry": [
        "get_telemetry",
    ],
    "common.errors": [
        "categorize_compile_error",
        "categorize_extract_error",
        "StructuredError",
    ],
    "common.utils": [
        "parse_frontmatter",
        "generate_slug",
    ],
    "common.llm_factory": [
        "build_default_client",
    ],
    # ── data_source/ 子包 (Phase 2) ──
    "data_source.router": [
        "DataRouter",
        "DataSource",
        "ParquetLocalDataSource",
        "SynthDataSource",
    ],
    "data_source.universe": [
        "resolve_universe",
        "get_index_constituents",
    ],
    "data_source.quantnodes_adapter": [
        "build_qn_context",
    ],
    "data_source.akshare": [
        "fetch_hs300_constituents",
    ],
    "data_source.clickhouse": [
        "fetch_hs300_constituents",
    ],
    "data_source.ifind": [
        "build_tradable_matrices",
    ],
    # ── codegen/ 子包 (Phase 5) ──
    "codegen.llm_code": [
        "generate_factor_code",
        "extract_python",
        "validate_syntax",
        "validate_safety",
        "execute_code",
        "build_llm_client",
        "extract_json_from_response",
    ],
    "codegen.react_engine": [
        "compile_to_code_react",
        "ReactState",
        "ReactStep",
        "ReactResult",
        "ReactErrorKind",
    ],
    "codegen.compiler": [
        "FactorCompiler",
    ],
    "codegen.semantic": [
        "SemanticOp",
        "get_op",
        "list_ops",
        "list_by_family",
        "get_doc_for_llm",
        "instantiate",
        "load_user_registry",
    ],
    "codegen.repair": [
    ],
    "codegen.metadata": [
        "extract_factor_metadata",
    ],
    # ── 顶层模块 ──
    "persist.factor_library": [
        "read_factor_yaml",
        "write_factor_yaml",
        "list_factors",
        "list_factors_by_category",
        "update_index",
    ],
    "persist.sessions": [
        "ReproductionDatabase",
        "Session",
        "Artifact",
        "Result",
    ],
    "paper_understanding.schemas": [
        "BacktestResult",
        "WikiFactor",
        "WikiStrategy",
        "FactorBacktestResult",
    ],
    "paper_understanding.extract_paper": [
        "extract_paper_structure",
        "_extract_factors_from_list",
        "build_paper_pages",
        "run_factor_compile_for_paper",
    ],
    "paper_understanding.quant_wiki": [
        "get_quant_wiki",
    ],
    # ── backtest_pkg/ 子包 (Phase 7) ──
    "backtest_pkg.factor_backtest": [
        "run_factor_backtest",
        "run_factor_backtest_universe",
    ],
    "backtest_pkg.run_backtest": [
        "run_backtest",
    ],
    "backtest_pkg.factor_value_store": [
        "store_factor_values",
        "query_factor_values",
        "compute_and_store_factor",
        "list_stored_factors",
    ],
    "backtest_pkg.l5_orchestrator": [
        "run_l5_pipeline",
    ],
    "backtest_pkg.l5_validation": [
        "run_l5_validation",
    ],
    "backtest_pkg.metrics": [
        "evaluation",
    ],
    "backtest_pkg.quantnodes_repro": [
        "run_factor_backtest",
    ],
    "paper_understanding.llm_extraction": [
        "run_one_paper",
    ],
    "persist.run": [
        "run_reproduction",
        "RunContext",
    ],
    # ── codegen/ast/ 子包 (Phase 6) ──
    "codegen.ast.compiler": [
        "compile_ast",
        "CompileError",
    ],
    "codegen.ast.nodes": [
        "ASTNode",
        "get_op_spec",
        "is_known_op",
    ],
    "codegen.ast.extractor": [
        "extract_ast",
    ],
    "codegen.ast.complexity": [
        "compute_complexity",
    ],
    "backtest_pkg.strategies": [
        "SIGNAL_NODE_REGISTRY",
    ],
    "paper_understanding.contracts": [
        "FactorPage",
    ],
    "paper_understanding.extract_strategy": [
        "extract_strategy_config",
    ],
    "paper_understanding.extract_factors": [
        "extract_factors",
    ],
    # ── llm_extraction/ ──
    "paper_understanding.llm_extraction.orchestrator": [
        "run_one_paper",
    ],
    "paper_understanding.llm_extraction.track_a": [
        "run_track_a",
    ],
    "paper_understanding.llm_extraction.track_b": [
        "run_track_b",
    ],
    "paper_understanding.llm_extraction.planner": [
        "plan_paper",
    ],
    "paper_understanding.llm_extraction.validator": [
        "validate_paper_outputs",
    ],
    "paper_understanding.llm_extraction.retry": [
        "with_retry",
    ],
    "paper_understanding.llm_extraction.defer": [
        "DeferredQueue",
    ],
    "paper_understanding.llm_extraction.runlog": [
        "RunLogger",
    ],
    "paper_understanding.llm_extraction.section_detector": [
        "detect_sections",
    ],
    "paper_understanding.llm_extraction.plan_saver": [
        "save_plan",
    ],
    "paper_understanding.llm_extraction.preview": [
        "generate_preview",
    ],
    "paper_understanding.llm_extraction.log_decorator": [
        "with_logging",
    ],
    "paper_understanding.llm_extraction.stage0_ingest": [
        "run_stage0_ingest",
    ],
}


@pytest.mark.mock
@pytest.mark.parametrize(
    "module_name,expected_names",
    list(EXPECTED_PUBLIC_API.items()),
    ids=list(EXPECTED_PUBLIC_API.keys()),
)
def test_module_public_api_exists(module_name: str, expected_names: list[str]) -> None:
    """验证模块的公共 API 仍存在 (锁定 refactor 不能改名/删除)."""
    mod = importlib.import_module(f"llmwikify.reproduction.{module_name}")
    actual_names = set(dir(mod))
    missing = [n for n in expected_names if n not in actual_names]
    assert not missing, (
        f"Module {module_name} missing public API: {missing}. "
        f"Cannot rename/delete these without updating WebUI/CLI callers."
    )


@pytest.mark.mock
def test_inventory_coverage() -> None:
    """验证 EXPECTED_PUBLIC_API 至少覆盖 30 个模块."""
    assert len(EXPECTED_PUBLIC_API) >= 30, (
        f"Inventory only covers {len(EXPECTED_PUBLIC_API)} modules. "
        f"Add more in EXPECTED_PUBLIC_API to reach 30+."
    )


@pytest.mark.mock
def test_inventory_includes_llm_extraction() -> None:
    """验证 paper_understanding/llm_extraction/ 子包有 API 锁定."""
    llm_ext_keys = [k for k in EXPECTED_PUBLIC_API if k.startswith("paper_understanding.llm_extraction.")]
    assert len(llm_ext_keys) >= 8, (
        f"paper_understanding/llm_extraction/ coverage: {len(llm_ext_keys)} modules. "
        f"Should be ≥ 8 (out of 16 total)."
    )
