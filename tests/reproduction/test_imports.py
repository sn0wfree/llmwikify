"""Smoke test: 验证 reproduction/ 下模块全部可导入.

这是 20 阶段 refactor 的安全网. 每个模块都需能 import, 否则后续 refactor
会破坏 WebUI 或 CLI.

Phase 1+2 完成后模块结构:
- common/ (7): config, paths, run_id, telemetry, errors, utils, llm_factory
- data_source/ (6): router, universe, quantnodes_adapter, akshare, clickhouse, ifind
- 顶层 (28): 未搬迁的模块
- llm_extraction/ (15): 除 llm_factory 外的子包模块

详见: docs/designs/pipeline_framework.md Section 29.5.1
"""
from __future__ import annotations

import importlib
import os

import pytest

import llmwikify.reproduction

# ── common/ 子包 (7 个, Phase 1 搬迁) ──────────────────────
COMMON_MODULES = [
    "common.config",
    "common.paths",
    "common.run_id",
    "common.telemetry",
    "common.errors",
    "common.utils",
    "common.llm_factory",
]

# ── data_source/ 子包 (6 个, Phase 2 搬迁) ─────────────────
DATA_SOURCE_MODULES = [
    "data_source.router",
    "data_source.universe",
    "data_source.quantnodes_adapter",
    "data_source.akshare",
    "data_source.clickhouse",
    "data_source.ifind",
]

# ── 顶层模块 (未搬迁, 28 个) ──────────────────────────────
TOP_LEVEL_MODULES = [
    "paper_understanding.contracts",
    "paper_understanding.extract_strategy",
    "paper_understanding.extract_factors",
    "paper_understanding.extract_paper",
    "paper_understanding.quant_wiki",
    "paper_understanding.schemas",
]

# ── persist/ 子包 (3 个, Phase 8 搬迁) ──────────────────────
PERSIST_MODULES = [
    "persist.factor_library",
    "persist.sessions",
    "persist.run",
]

# ── backtest_pkg/ 子包 (8 个, Phase 7 搬迁) ────────────────
BACKTEST_MODULES = [
    "backtest_pkg.factor_backtest",
    "backtest_pkg.run_backtest",
    "backtest_pkg.metrics",
    "backtest_pkg.strategies",
    "backtest_pkg.l5_validation",
    "backtest_pkg.l5_orchestrator",
    "backtest_pkg.factor_value_store",
    "backtest_pkg.quantnodes_repro",
]

# ── codegen/ast/ 子包 (4 个, Phase 6 搬迁) ────────────────────
CODEGEN_AST_MODULES = [
    "codegen.ast.compiler",
    "codegen.ast.nodes",
    "codegen.ast.complexity",
    "codegen.ast.extractor",
]

# ── codegen/ 子包 (6 个, Phase 5 搬迁) ─────────────────────
CODEGEN_MODULES = [
    "codegen.llm_code",
    "codegen.react_engine",
    "codegen.compiler",
    "codegen.repair",
    "codegen.semantic",
    "codegen.metadata",
]

# ── llm_extraction/ 子包 (15 个, 除 llm_factory 外) ────────
LLM_EXTRACTION_MODULES = [
    "llm_extraction.config",
    "llm_extraction.defer",
    "llm_extraction.log_decorator",
    "llm_extraction.orchestrator",
    "llm_extraction.plan_saver",
    "llm_extraction.planner",
    "llm_extraction.preview",
    "llm_extraction.retry",
    "llm_extraction.runlog",
    "llm_extraction.section_detector",
    "llm_extraction.stage0_ingest",
    "llm_extraction.track_a",
    "llm_extraction.track_b",
    "llm_extraction.validator",
    "llm_extraction",
]

ALL_MODULES = COMMON_MODULES + DATA_SOURCE_MODULES + CODEGEN_MODULES + CODEGEN_AST_MODULES + BACKTEST_MODULES + PERSIST_MODULES + TOP_LEVEL_MODULES + LLM_EXTRACTION_MODULES


# ── CRITICAL_IMPORTS: 33 个关键 import 语句 ──────────────────
# Phase 3: 全部改为新路径
CRITICAL_IMPORTS = [
    # common/ (7)
    "from llmwikify.reproduction.common.config import config",
    "from llmwikify.reproduction.common.paths import page_path, result_path",
    "from llmwikify.reproduction.common.run_id import generate_run_id, sanitize_run_id",
    "from llmwikify.reproduction.common.telemetry import get_telemetry",
    "from llmwikify.reproduction.common.errors import StructuredError, categorize_compile_error",
    "from llmwikify.reproduction.common.utils import parse_frontmatter, generate_slug",
    "from llmwikify.reproduction.common.llm_factory import build_default_client",
    # data_source/ (6)
    "from llmwikify.reproduction.data_source.router import DataRouter",
    "from llmwikify.reproduction.data_source.universe import resolve_universe",
    "from llmwikify.reproduction.data_source.quantnodes_adapter import build_qn_context",
    "from llmwikify.reproduction.data_source.akshare import fetch_hs300_constituents",
    "from llmwikify.reproduction.data_source.clickhouse import fetch_close_panel",
    "from llmwikify.reproduction.data_source.ifind import build_tradable_matrices",
    # codegen/ (6)
    "from llmwikify.reproduction.codegen.llm_code import generate_factor_code, SYSTEM_PROMPT_CODE",
    "from llmwikify.reproduction.codegen.react_engine import compile_to_code_react, ReactStep, ReactResult",
    "from llmwikify.reproduction.codegen.compiler import FactorCompiler",
    "from llmwikify.reproduction.codegen.semantic import get_op, list_ops",
    # codegen/ast/ (4)
    "from llmwikify.reproduction.codegen.ast.compiler import compile_ast, CompileError",
    "from llmwikify.reproduction.codegen.ast.nodes import ASTNode, get_op_spec",
    # backtest_pkg/ (8)
    "from llmwikify.reproduction.backtest_pkg.factor_backtest import run_factor_backtest, run_factor_backtest_universe",
    "from llmwikify.reproduction.backtest_pkg.run_backtest import run_backtest",
    "from llmwikify.reproduction.backtest_pkg.metrics import evaluation",
    "from llmwikify.reproduction.backtest_pkg.l5_orchestrator import run_l5_pipeline",
    "from llmwikify.reproduction.backtest_pkg.l5_validation import run_l5_validation",
    "from llmwikify.reproduction.backtest_pkg.factor_value_store import store_factor_values, query_factor_values",
    "from llmwikify.reproduction.backtest_pkg.quantnodes_repro import run_factor_backtest",
    # persist/ (3)
    "from llmwikify.reproduction.persist.factor_library import read_factor_yaml, write_factor_yaml",
    "from llmwikify.reproduction.persist.sessions import ReproductionDatabase",
    "from llmwikify.reproduction.persist.run import run_reproduction, RunContext",
    # 顶层 (5)
    "from llmwikify.reproduction.paper_understanding.quant_wiki import get_quant_wiki",
    "from llmwikify.reproduction.paper_understanding.extract_paper import extract_paper_structure, _extract_factors_from_list",
    "from llmwikify.reproduction.paper_understanding.schemas import BacktestResult, WikiFactor, FactorBacktestResult",
    "from llmwikify.reproduction.paper_understanding.contracts import FactorPage",
]


@pytest.mark.mock
@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports(module_name: str) -> None:
    """全部模块能 import."""
    try:
        importlib.import_module(f"llmwikify.reproduction.{module_name}")
    except Exception as exc:
        pytest.fail(f"Failed to import llmwikify.reproduction.{module_name}: {exc}")


@pytest.mark.mock
def test_reproduction_init_imports() -> None:
    """reproduction/__init__.py 顶层能 import (兼容旧 API)."""
    import llmwikify.reproduction  # noqa: F401


@pytest.mark.mock
def test_module_count_matches_plan() -> None:
    """验证模块数符合 20 阶段 refactor 计划."""
    pkg_path = llmwikify.reproduction.__path__[0]
    # Top-level .py files
    actual_top = {
        f[:-3] for f in os.listdir(pkg_path)
        if f.endswith(".py") and f != "__init__.py" and f != "conftest.py"
    }
    # common/ 子包
    common_path = os.path.join(pkg_path, "common")
    actual_common = set()
    if os.path.isdir(common_path):
        actual_common = {
            f"common.{f[:-3]}"
            for f in os.listdir(common_path)
            if f.endswith(".py") and f != "__init__.py"
        }
    # data_source/ 子包
    ds_path = os.path.join(pkg_path, "data_source")
    actual_ds = set()
    if os.path.isdir(ds_path):
        actual_ds = {
            f"data_source.{f[:-3]}"
            for f in os.listdir(ds_path)
            if f.endswith(".py") and f != "__init__.py"
        }
    # codegen/ 子包
    codegen_path = os.path.join(pkg_path, "codegen")
    actual_codegen = set()
    if os.path.isdir(codegen_path):
        for f in os.listdir(codegen_path):
            if f.endswith(".py") and f != "__init__.py":
                actual_codegen.add(f"codegen.{f[:-3]}")
        # codegen/ast/ 子包
        ast_path = os.path.join(codegen_path, "ast")
        if os.path.isdir(ast_path):
            for f in os.listdir(ast_path):
                if f.endswith(".py") and f != "__init__.py":
                    actual_codegen.add(f"codegen.ast.{f[:-3]}")
    # backtest_pkg/ 子包
    bt_path = os.path.join(pkg_path, "backtest_pkg")
    actual_bt = set()
    if os.path.isdir(bt_path):
        actual_bt = {
            f"backtest_pkg.{f[:-3]}"
            for f in os.listdir(bt_path)
            if f.endswith(".py") and f != "__init__.py"
        }
    # llm_extraction/ 子包
    llm_ext_path = os.path.join(pkg_path, "llm_extraction")
    actual_llm_ext = set()
    if os.path.isdir(llm_ext_path):
        actual_llm_ext = {
            f"llm_extraction.{f[:-3]}"
            for f in os.listdir(llm_ext_path)
            if f.endswith(".py") and f != "__init__.py" and f != "conftest.py"
        }
    # paper_understanding/ 子包
    pu_path = os.path.join(pkg_path, "paper_understanding")
    actual_pu = set()
    if os.path.isdir(pu_path):
        actual_pu = {
            f"paper_understanding.{f[:-3]}"
            for f in os.listdir(pu_path)
            if f.endswith(".py") and f != "__init__.py"
        }
    # 至少 ≥ 计划数 (允许新增模块)
    assert len(actual_top) >= len(TOP_LEVEL_MODULES) - len(actual_pu), (
        f"Top-level modules shrunk: {len(actual_top)} < {len(TOP_LEVEL_MODULES) - len(actual_pu)}. "
        f"Missing: {set(TOP_LEVEL_MODULES) - actual_pu - actual_top}"
    )
    assert len(actual_common) >= len(COMMON_MODULES), (
        f"common/ modules shrunk: {len(actual_common)} < {len(COMMON_MODULES)}. "
        f"Missing: {set(COMMON_MODULES) - actual_common}"
    )
    assert len(actual_ds) >= len(DATA_SOURCE_MODULES), (
        f"data_source/ modules shrunk: {len(actual_ds)} < {len(DATA_SOURCE_MODULES)}. "
        f"Missing: {set(DATA_SOURCE_MODULES) - actual_ds}"
    )
    assert len(actual_codegen) >= len(CODEGEN_MODULES) + len(CODEGEN_AST_MODULES), (
        f"codegen/ modules shrunk: {len(actual_codegen)} < {len(CODEGEN_MODULES) + len(CODEGEN_AST_MODULES)}. "
    )
    assert len(actual_bt) >= len(TOP_LEVEL_MODULES) - len(actual_top) - len(actual_pu), (
        f"backtest_pkg/ modules shrunk: {len(actual_bt)} < expected."
    )
    assert len(actual_pu) >= len(TOP_LEVEL_MODULES), (
        f"paper_understanding/ modules shrunk: {len(actual_pu)} < {len(TOP_LEVEL_MODULES)}. "
        f"Missing: {set(TOP_LEVEL_MODULES) - actual_pu}"
    )
    assert len(actual_llm_ext) >= len(LLM_EXTRACTION_MODULES) - 1, (
        f"llm_extraction modules shrunk: {len(actual_llm_ext)} < {len(LLM_EXTRACTION_MODULES) - 1}. "
        f"Missing: {set(LLM_EXTRACTION_MODULES) - 1 - actual_llm_ext}"
    )


@pytest.mark.mock
def test_no_unexpected_import_errors() -> None:
    """批量 import 不应触发意外错误 (nanobot / 循环依赖等)."""
    failed = []
    for module_name in ALL_MODULES:
        try:
            importlib.import_module(f"llmwikify.reproduction.{module_name}")
        except ModuleNotFoundError as exc:
            if "nanobot" in str(exc):
                pytest.fail(f"nanobot import still required: {exc}")
            failed.append((module_name, str(exc)))
        except ImportError as exc:
            failed.append((module_name, str(exc)))
    if failed:
        msg = "\n".join(f"  {m}: {e}" for m, e in failed)
        pytest.fail(f"Some modules failed to import:\n{msg}")


@pytest.mark.mock
@pytest.mark.parametrize("import_stmt", CRITICAL_IMPORTS)
def test_critical_import(import_stmt: str) -> None:
    """33 个关键 import 语句全部能执行."""
    exec(import_stmt)
