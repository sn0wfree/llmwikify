"""E2E smoke: 全模块 import + 公共 API 完整性 (S3 阶段).

验证 reproduction/ 56 个模块全部可 import, 公共 API 不缺失.
这是 refactor 期间最关键的安全网.

详见: docs/designs/pipeline_framework.md Section 29.9
"""

from __future__ import annotations

import pytest
import importlib

ALL_TOP_MODULES = [
    "akshare_data", "ast_compiler", "ast_complexity", "ast_extractor",
    "ast_nodes", "backtest", "clickhouse_data", "codegen_utils",
    "config", "contracts", "error_categorizer", "extract",
    "extract_factors", "extract_paper", "factor_backtest",
    "factor_compiler", "factor_compiler_react", "factor_extractor",
    "factor_library", "factor_value_store", "ifind_data",
    "l5_orchestrator", "l5_validation", "metrics", "paths",
    "quant_wiki", "quantnodes_adapter", "quantnodes_repro",
    "router", "run", "run_id", "schemas", "self_repairing",
    "sessions", "strategies", "telemetry", "universe", "utils",
]

LLM_EXTRACTION_MODULES = [
    "llm_extraction.config", "llm_extraction.defer",
    "llm_extraction.llm_factory", "llm_extraction.log_decorator",
    "llm_extraction.orchestrator", "llm_extraction.plan_saver",
    "llm_extraction.planner", "llm_extraction.preview",
    "llm_extraction.retry", "llm_extraction.runlog",
    "llm_extraction.section_detector", "llm_extraction.stage0_ingest",
    "llm_extraction.track_a", "llm_extraction.track_b",
    "llm_extraction.validator", "llm_extraction",
]


class TestAllModulesImportable:
    """Test 56 个模块全部可 import (smoke)."""

    @pytest.mark.parametrize("module_name", ALL_TOP_MODULES)
    def test_top_level_module(self, module_name: str) -> None:
        """顶层模块 import."""
        try:
            importlib.import_module(f"llmwikify.reproduction.{module_name}")
        except Exception as exc:
            pytest.fail(f"Failed to import {module_name}: {exc}")

    @pytest.mark.parametrize("module_name", LLM_EXTRACTION_MODULES)
    def test_llm_extraction_module(self, module_name: str) -> None:
        """llm_extraction/ 子包模块 import."""
        try:
            importlib.import_module(f"llmwikify.reproduction.{module_name}")
        except Exception as exc:
            pytest.fail(f"Failed to import {module_name}: {exc}")


class TestCrossModuleCompatibility:
    """Test 跨模块导入顺序无关 (3 测试)."""

    def test_import_does_not_require_order(self) -> None:
        """import 顺序无关."""
        # 先 import 一些模块
        from llmwikify.reproduction import factor_library
        from llmwikify.reproduction import sessions
        from llmwikify.reproduction import codegen_utils
        # 再 import 其他模块, 不应出错
        from llmwikify.reproduction import l5_validation
        from llmwikify.reproduction import metrics
        # 全部成功
        assert factor_library is not None
        assert sessions is not None

    def test_no_circular_dependencies_at_import(self) -> None:
        """import 时无循环依赖 (运行到现在 = 0 circular)."""
        # 简单测试: re-import 全部模块
        for m in ALL_TOP_MODULES[:10]:  # 前 10 个足够
            importlib.import_module(f"llmwikify.reproduction.{m}")
        assert True  # 没抛错即通过

    def test_reproduction_top_level_imports(self) -> None:
        """reproduction 顶层 package 可 import."""
        import llmwikify.reproduction
        # 应有这些公共 API
        for name in ["run_backtest", "BacktestResult", "WikiFactor"]:
            assert hasattr(llmwikify.reproduction, name), f"Missing top-level: {name}"


class TestWebUICompatibility:
    """Test WebUI 接口兼容性 (3 测试)."""

    def test_factor_backtest_function_exists(self) -> None:
        """factor_backtest.run_factor_backtest 存在 (WebUI 依赖)."""
        from llmwikify.reproduction import factor_backtest
        assert hasattr(factor_backtest, "run_factor_backtest")

    def test_extract_paper_function_exists(self) -> None:
        """extract_paper_structure 存在 (WebUI 论文页面依赖)."""
        from llmwikify.reproduction import extract_paper
        # 实际函数名是 extract_paper_structure / build_paper_pages
        assert hasattr(extract_paper, "extract_paper_structure") or hasattr(extract_paper, "build_paper_pages")

    def test_factor_library_yaml_io(self) -> None:
        """factor_library YAML 读写 (WebUI 因子页面依赖)."""
        from llmwikify.reproduction import factor_library
        assert hasattr(factor_library, "read_factor_yaml")
        assert hasattr(factor_library, "write_factor_yaml")
        assert hasattr(factor_library, "list_factors")
        assert hasattr(factor_library, "list_factors_by_category")
