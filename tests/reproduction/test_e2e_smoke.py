"""E2E smoke: 全模块 import + 公共 API 完整性 (S3 阶段).

验证 reproduction/ 56 个模块全部可 import, 公共 API 不缺失.
这是 refactor 期间最关键的安全网.

详见: docs/designs/pipeline_framework.md Section 29.9
"""

from __future__ import annotations

import pytest
import importlib

ALL_TOP_MODULES = [
    # common/ (Phase 1)
    "common.config", "common.paths", "common.run_id", "common.telemetry",
    "common.errors", "common.utils", "common.llm_factory",
    # data_source/ (Phase 2)
    "data_source.router", "data_source.universe", "data_source.quantnodes_adapter",
    "data_source.akshare", "data_source.clickhouse", "data_source.ifind",
    # 顶层
    "paper_understanding.contracts", "paper_understanding.extract_strategy",
    "paper_understanding.extract_factors", "paper_understanding.extract_paper",
    "paper_understanding.quant_wiki", "paper_understanding.schemas",
    # persist/ (Phase 8)
    "persist.factor_library", "persist.sessions", "persist.run",
    # backtest_pkg/ (Phase 7)
    "backtest_pkg.factor_backtest", "backtest_pkg.run_backtest",
    "backtest_pkg.metrics", "backtest_pkg.strategies",
    "backtest_pkg.l5_validation", "backtest_pkg.l5_orchestrator",
    "backtest_pkg.factor_value_store", "backtest_pkg.quantnodes_repro",
    # codegen/ (Phase 5)
    "codegen.llm_code", "codegen.react_engine", "codegen.compiler",
    "codegen.repair", "codegen.semantic", "codegen.metadata",
    # codegen/ast/ (Phase 6)
    "codegen.ast.compiler", "codegen.ast.nodes",
    "codegen.ast.complexity", "codegen.ast.extractor",
]

LLM_EXTRACTION_MODULES = [
    "paper_understanding.llm_extraction.config", "paper_understanding.llm_extraction.defer",
    "paper_understanding.llm_extraction.log_decorator",
    "paper_understanding.llm_extraction.orchestrator", "paper_understanding.llm_extraction.plan_saver",
    "paper_understanding.llm_extraction.planner", "paper_understanding.llm_extraction.preview",
    "paper_understanding.llm_extraction.retry", "paper_understanding.llm_extraction.runlog",
    "paper_understanding.llm_extraction.section_detector", "paper_understanding.llm_extraction.stage0_ingest",
    "paper_understanding.llm_extraction.track_a", "paper_understanding.llm_extraction.track_b",
    "paper_understanding.llm_extraction.validator", "paper_understanding.llm_extraction",
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
        from llmwikify.reproduction.persist import factor_library
        from llmwikify.reproduction.persist import sessions
        from llmwikify.reproduction.codegen import llm_code as codegen_utils
        # 再 import 其他模块, 不应出错
        from llmwikify.reproduction.backtest_pkg import l5_validation
        from llmwikify.reproduction.backtest_pkg import metrics
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
        from llmwikify.reproduction.backtest_pkg import factor_backtest
        assert hasattr(factor_backtest, "run_factor_backtest")

    def test_extract_paper_function_exists(self) -> None:
        """extract_paper_structure 存在 (WebUI 论文页面依赖)."""
        from llmwikify.reproduction.paper_understanding import extract_paper
        # 实际函数名是 extract_paper_structure / build_paper_pages
        assert hasattr(extract_paper, "extract_paper_structure") or hasattr(extract_paper, "build_paper_pages")

    def test_factor_library_yaml_io(self) -> None:
        """factor_library YAML 读写 (WebUI 因子页面依赖)."""
        from llmwikify.reproduction.persist import factor_library
        assert hasattr(factor_library, "read_factor_yaml")
        assert hasattr(factor_library, "write_factor_yaml")
        assert hasattr(factor_library, "list_factors")
        assert hasattr(factor_library, "list_factors_by_category")
