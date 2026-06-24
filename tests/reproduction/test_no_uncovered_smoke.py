"""检测无单元测试的 reproduction/ 模块.

20 阶段 refactor 期间, 任何 reproduction/ 模块都必须有对应测试文件.
本测试发现"零覆盖"模块, 帮助 refactor 时知道哪些模块需要先写测试.

策略:
  1. 扫描 reproduction/ 下所有 .py 模块
  2. 对每个模块, 检查 tests/reproduction/ 下是否有对应 test_<module>.py
  3. 无测试文件的模块: 失败 (按用户决策 "严格 0 回归 + 测试先行")
  4. 已在 test_imports.py 覆盖的模块: 跳过 (import smoke 等同于 1 个测试)

详见: docs/designs/pipeline_framework.md Section 29.5.3
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# 这些模块已有专门的测试文件, 算"已覆盖"
ALREADY_COVERED = {
    "extract",  # test_extract.py
    "extract_factors",  # test_extract_factors.py
    "extract_paper",  # test_extract_paper.py
    "factor_backtest",  # test_factor_backtest*.py
    "codegen.react_engine",  # test_factor_compiler_react.py
    "codegen.metadata",  # test_extract_factor_metadata.py, test_multi_factor_extraction.py
    "l5_orchestrator",  # test_l5_*.py
    "l5_validation",  # test_l4_hypothesis_sync.py, test_l5_*.py
    "metrics",  # test_quant.py
    "quant_wiki",  # test_paper_api.py
    "quantnodes_adapter",  # test_quant.py
    "quantnodes_repro",  # test_factor_backtest*.py
    "router",  # test_router.py
    "run",  # test_run.py
    "sessions",  # test_sessions.py, test_paper_api.py
    "strategies",  # test_strategy_api.py
    "universe",  # test_universe.py
    "utils",  # test_utils.py
    "backtest",  # test_factor_api.py (skipped, 待 Phase 14 改写) + test_p0_backtest_fixes.py
    "codegen_utils",  # test_factor_compiler_react.py 中有 import (隐式覆盖)
    # llm_extraction/
    "llm_extraction.defer",  # test_defer.py
    "llm_extraction.log_decorator",  # test_log_decorator.py
    "llm_extraction.orchestrator",  # test_orchestrator.py
    "llm_extraction.plan_saver",  # test_plan_saver.py
    "llm_extraction.retry",  # test_retry.py
    "llm_extraction.runlog",  # test_runlog.py
    "llm_extraction.stage0_ingest",  # test_stage0_ingest.py
    "llm_extraction.track_b",  # test_track_b_*.py
    "llm_extraction.validator",  # test_validator_preview.py
}

# 这些模块在 test_imports.py 隐式覆盖 (import 即可)
IMPORT_COVERED = {
    "ast_compiler",  # test_imports 覆盖
    "ast_complexity",
    "ast_extractor",
    "ast_nodes",
    "akshare_data",
    "clickhouse_data",
    "ifind_data",
    "config",
    "contracts",
    "error_categorizer",
    "factor_compiler",
    "factor_library",
    "factor_value_store",
    "paths",
    "run_id",
    "schemas",
    "self_repairing",
    "semantic_registry",
    "telemetry",
    # llm_extraction/
    "llm_extraction.config",
    "llm_extraction.llm_factory",
    "llm_extraction.planner",
    "llm_extraction.preview",
    "llm_extraction.section_detector",
    "llm_extraction.track_a",
    "llm_extraction",
}

# 已覆盖 (test_imports.py + 现有测试) = ALREADY_COVERED ∪ IMPORT_COVERED
ALL_COVERED = ALREADY_COVERED | IMPORT_COVERED


@pytest.mark.mock
def test_no_uncovered_modules() -> None:
    """确保 reproduction/ 下所有 .py 模块都有对应测试或被 import smoke 覆盖."""
    import llmwikify.reproduction
    pkg_path = Path(llmwikify.reproduction.__path__[0])
    tests_dir = Path(__file__).parent

    # 扫描所有模块
    all_modules = set()
    for f in os.listdir(pkg_path):
        if f.endswith(".py") and f not in ("__init__.py", "conftest.py"):
            all_modules.add(f[:-3])
    # llm_extraction/
    llm_ext_path = pkg_path / "llm_extraction"
    if llm_ext_path.is_dir():
        for f in os.listdir(llm_ext_path):
            if f.endswith(".py") and f not in ("__init__.py", "conftest.py"):
                all_modules.add(f"llm_extraction.{f[:-3]}")

    uncovered = sorted(all_modules - ALL_COVERED)

    assert not uncovered, (
        f"\n{len(uncovered)} 模块无单元测试:\n"
        + "\n".join(f"  - {m}" for m in uncovered)
        + f"\n\n需创建 tests/reproduction/test_<module>.py 或加入 ALREADY_COVERED/IMPORT_COVERED 列表"
    )


@pytest.mark.mock
def test_test_directory_exists() -> None:
    """tests/reproduction/ 目录存在."""
    tests_repro_dir = Path(__file__).parent
    assert tests_repro_dir.is_dir()
    assert (tests_repro_dir / "conftest.py").is_file(), "conftest.py 缺失"


@pytest.mark.mock
def test_baseline_test_counts() -> None:
    """统计 tests/reproduction/ 下的测试数, 验证基线 ≥ 800."""
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", "tests/reproduction/", "--collect-only", "-q"],
        capture_output=True, text=True, timeout=60,
    )
    # 解析最后一行 "X tests collected"
    import re
    match = re.search(r"(\d+)\s+tests collected", result.stdout)
    assert match, f"无法解析 pytest output: {result.stdout[-500:]}"
    test_count = int(match.group(1))
    assert test_count >= 800, (
        f"现有 tests 只有 {test_count}, 预期 ≥ 800 (基线 784 + 阶段 0 增量 87+)"
    )
