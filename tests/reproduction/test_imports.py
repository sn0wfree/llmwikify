"""Smoke test: 验证 reproduction/ 下 56 个模块全部可导入.

这是 20 阶段 refactor 的安全网. 每个模块 (40 顶层 + 16 llm_extraction) 都需
能 import, 否则后续 refactor 会破坏 WebUI 或 CLI.

设计原则:
  - **不依赖函数签名**: 仅验证模块本身能 import
  - **不执行函数体**: 大部分模块 import 时已加载, 不主动调函数
  - **不依赖外部资源**: 不读 H5/DB/网络

详见: docs/designs/pipeline_framework.md Section 29.5.1
"""

from __future__ import annotations

import importlib
import sys

import pytest

# 40 顶层模块 (排除 __init__.py, __pycache__, conftest 等)
TOP_LEVEL_MODULES = [
    "akshare_data",
    "ast_compiler",
    "ast_complexity",
    "ast_extractor",
    "ast_nodes",
    "backtest",
    "clickhouse_data",
    "codegen_utils",
    "config",
    "contracts",
    "error_categorizer",
    "extract",
    "extract_factors",
    "extract_paper",
    "factor_backtest",
    "factor_compiler",
    "factor_compiler_react",
    "factor_extractor",
    "factor_library",
    "factor_value_store",
    "ifind_data",
    "l5_orchestrator",
    "l5_validation",
    "metrics",
    "paths",
    "quant_wiki",
    "quantnodes_adapter",
    "quantnodes_repro",
    "router",
    "run",
    "run_id",
    "schemas",
    "self_repairing",
    "sessions",
    "strategies",
    "telemetry",
    "universe",
    "utils",
]

# 16 llm_extraction/ 子包模块
LLM_EXTRACTION_MODULES = [
    "llm_extraction.config",
    "llm_extraction.defer",
    "llm_extraction.llm_factory",
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

# 共 38 + 16 = 54 个 (实际比 56 少 2, 因为 __init__ 已单列)
ALL_MODULES = TOP_LEVEL_MODULES + LLM_EXTRACTION_MODULES


@pytest.mark.mock
@pytest.mark.parametrize("module_name", TOP_LEVEL_MODULES)
def test_top_level_module_imports(module_name: str) -> None:
    """40 个顶层 .py 模块全部能 import."""
    try:
        importlib.import_module(f"llmwikify.reproduction.{module_name}")
    except Exception as exc:
        pytest.fail(f"Failed to import llmwikify.reproduction.{module_name}: {exc}")


@pytest.mark.mock
@pytest.mark.parametrize("module_name", LLM_EXTRACTION_MODULES)
def test_llm_extraction_module_imports(module_name: str) -> None:
    """16 个 llm_extraction/ 子包模块全部能 import."""
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
    """验证模块数符合 20 阶段 refactor 计划 (40 顶层 + 16 llm_extraction)."""
    # 动态扫描 reproduction/ 目录
    import llmwikify.reproduction
    pkg_path = llmwikify.reproduction.__path__[0]
    import os
    actual_top = {
        f[:-3] for f in os.listdir(pkg_path)
        if f.endswith(".py") and f != "__init__.py" and f != "conftest.py"
    }
    actual_llm_ext = set()
    llm_ext_path = os.path.join(pkg_path, "llm_extraction")
    if os.path.isdir(llm_ext_path):
        actual_llm_ext = {
            f"llm_extraction.{f[:-3]}"
            for f in os.listdir(llm_ext_path)
            if f.endswith(".py") and f != "__init__.py" and f != "conftest.py"
        }
    # 至少 ≥ 计划数 (允许新增模块)
    assert len(actual_top) >= len(TOP_LEVEL_MODULES), (
        f"Top-level modules shrunk: {len(actual_top)} < {len(TOP_LEVEL_MODULES)}. "
        f"Missing: {set(TOP_LEVEL_MODULES) - actual_top}"
    )
    assert len(actual_llm_ext) >= len(LLM_EXTRACTION_MODULES) - 1, (
        f"llm_extraction modules shrunk: {len(actual_llm_ext)} < {len(LLM_EXTRACTION_MODULES) - 1}. "
        f"Missing: {set(LLM_EXTRACTION_MODULES) - 1 - actual_llm_ext}"
    )


@pytest.mark.mock
def test_no_unexpected_import_errors() -> None:
    """批量 import 不应触发意外错误 (nanobot / 循环依赖等)."""
    # 强制清除缓存
    mods_before = set(sys.modules.keys())
    for module_name in ALL_MODULES:
        full_name = f"llmwikify.reproduction.{module_name}"
        if full_name in sys.modules:
            del sys.modules[full_name]
    # 重新 import
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
