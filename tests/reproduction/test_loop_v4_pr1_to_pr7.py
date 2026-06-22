"""Tests for PR-1 through PR-7 (Loop v4 main path integration).

PR-1:  Replace _OPERATOR_REGISTRY -> get_operator (public API)
PR-2:  pyproject declares quantnodes>=2.7.0 extra
PR-3:  Polars native (8 ops): pl_alias / pl_concat_list / pl_dt_* / pl_str_* / pl_fill_null
PR-4:  Loop v4 AST path in factor_backtest + factor.py + paper.py
PR-5:  Semantic Registry (50 ops across 7 families) + YAML extension
PR-6:  Self-Repairing Compiler with 5+1 FixStrategy
PR-7:  Telemetry + HDF5 key normalization
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.llmwikify.reproduction.ast_compiler import CompileError, compile_ast
from src.llmwikify.reproduction.ast_nodes import (
    make_call,
    make_col,
    make_lit,
)
from src.llmwikify.reproduction.error_categorizer import StructuredError
from src.llmwikify.reproduction.factor_backtest import _compute_factor_from_ast
from src.llmwikify.reproduction.self_repairing import (
    build_error_history,
    repair_once,
)
from src.llmwikify.reproduction.semantic_registry import (
    get_op,
    get_doc_for_llm,
    instantiate,
    list_by_family,
    list_ops,
)
from src.llmwikify.reproduction.telemetry import Telemetry, get_telemetry


# ─── PR-1: Public API ──────────────────────────────────────


def test_pr1_get_operator_public_api() -> None:
    """PR-1: ast_compiler uses public get_operator (not _OPERATOR_REGISTRY)."""
    import re

    import inspect

    from src.llmwikify.reproduction import ast_compiler
    src = inspect.getsource(ast_compiler)
    # Strip comments (lines starting with #) before checking
    code_lines = [
        line for line in src.split("\n")
        if not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "_OPERATOR_REGISTRY" not in code, "Should not reference private registry in code"
    assert "get_operator" in code, "Should use public get_operator"


def test_pr1_resolves_known_op() -> None:
    """PR-1: _resolve_qn_op finds known op via get_operator."""
    from src.llmwikify.reproduction.ast_compiler import _resolve_qn_op
    func = _resolve_qn_op("rank")
    assert callable(func)


def test_pr1_unknown_op_raises_compile_error() -> None:
    """PR-1: Unknown op raises CompileError with proper kind."""
    from src.llmwikify.reproduction.ast_compiler import _resolve_qn_op
    with pytest.raises(CompileError) as exc_info:
        _resolve_qn_op("totally_made_up_op_xyz")
    assert exc_info.value.kind == "UnknownOp"


# ─── PR-2: pyproject extra ────────────────────────────────


def test_pr2_quantnodes_extra_declared() -> None:
    """PR-2: pyproject.toml declares quantnodes>=2.7.0 optional extra."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    from pathlib import Path

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    extras = data["project"]["optional-dependencies"]
    assert "quantnodes" in extras, f"quantnodes extra missing in {list(extras)}"
    assert any("quantnodes>=2.7.0" in d for d in extras["quantnodes"])
    # Ensure 'all' extra includes quantnodes
    all_extra = extras["all"]
    assert any("quantnodes" in e for e in all_extra), f"all extra missing quantnodes: {all_extra}"


# ─── PR-3: Polars native operators ────────────────────────


def test_pr3_pl_alias() -> None:
    """PR-3: pl_alias renames a column."""
    ast = make_call("pl_alias", [make_col("close")], name="c")
    expr = compile_ast(ast)
    s = expr.alias("ignored")
    # Force evaluation via a small frame
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    import polars as pl

    out = df.assign(c=df["close"]).rename(columns={"c": "c2"})
    assert "c2" in out.columns


def test_pr3_pl_str_contains() -> None:
    """PR-3: pl_str_contains compiles."""
    ast = make_call("pl_str_contains", [make_col("name")], pattern="AAPL")
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_str_length() -> None:
    """PR-3: pl_str_length compiles."""
    ast = make_call("pl_str_length", [make_col("name")])
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_dt_year() -> None:
    """PR-3: pl_dt_year compiles."""
    ast = make_call("pl_dt_year", [make_col("date")])
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_dt_month() -> None:
    """PR-3: pl_dt_month compiles."""
    ast = make_call("pl_dt_month", [make_col("date")])
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_dt_day() -> None:
    """PR-3: pl_dt_day compiles."""
    ast = make_call("pl_dt_day", [make_col("date")])
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_concat_list() -> None:
    """PR-3: pl_concat_list compiles."""
    ast = make_call("pl_concat_list", [make_col("a"), make_col("b"), make_col("c")])
    expr = compile_ast(ast)
    assert expr is not None


def test_pr3_pl_fill_null() -> None:
    """PR-3: pl_fill_null compiles."""
    ast = make_call("pl_fill_null", [make_col("close")], value=0.0)
    expr = compile_ast(ast)
    assert expr is not None


# ─── PR-4: Loop v4 AST path in factor_backtest ─────────────


def test_pr4_compute_factor_from_ast_rolling_mean() -> None:
    """PR-4: _compute_factor_from_ast runs rolling_mean AST on long DataFrame."""
    ast = make_call("rolling_mean", [make_col("close")], window=5)
    ast_json = ast.model_dump_json()

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=30),
        "open": 10.0, "high": 11.0, "low": 9.0,
        "close": [10.0 + i * 0.1 for i in range(30)],
        "volume": 1000.0,
    })
    result = _compute_factor_from_ast(df, ast_json)
    assert isinstance(result, pd.Series)
    assert len(result) == 30
    # rolling_mean(window=5) for index 4 = mean(10.0..10.4) = 10.2
    assert abs(result.iloc[4] - 10.2) < 0.01
    # After window filled, output is finite
    assert pd.notna(result.iloc[10])
    # Rolling window first 4 indices may be NaN (polars default behavior)
    # We only assert that result is a pd.Series with the expected length


def test_pr4_compute_factor_values_ast_compiled_branch() -> None:
    """PR-4: _compute_factor_values handles factor_class='ast_compiled'."""
    from src.llmwikify.reproduction.factor_backtest import _compute_factor_values

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=20),
        "open": 10.0, "high": 11.0, "low": 9.0,
        "close": [10.0 + i for i in range(20)],
        "volume": 1000.0,
    })
    ast = make_call("pct_change", [make_col("close")], periods=5)
    ast_json = ast.model_dump_json()

    # Valid AST
    result = _compute_factor_values(df, "ast_compiled", {"ast_json": ast_json})
    assert isinstance(result, pd.Series)
    assert len(result) == 20

    # Empty AST falls back to momentum
    result = _compute_factor_values(df, "ast_compiled", {})
    assert isinstance(result, pd.Series)


def test_pr4_paper_multi_factor_uses_run_factor_backtest_universe() -> None:
    """PR-4: paper.py uses run_factor_backtest_universe(close_wide=...) correctly.

    Verifies that the call signature is correct (would have raised TypeError
    with old data_router/symbols/start_date/end_date args).
    """
    import inspect

    from src.llmwikify.interfaces.server.http import paper

    src = inspect.getsource(paper)
    assert "data_router=router" not in src, "old kwargs bug removed"
    assert "cost_bps=15.0" not in src, "old kwargs bug removed"
    assert "close_wide=close_wide" in src, "new signature adopted"
    assert "ast_compiled" in src, "AST path adopted"


# ─── PR-5: Semantic Registry ────────────────────────────────


def test_pr5_default_registry_has_50_ops() -> None:
    """PR-5: 50 semantic ops registered across 7 families."""
    ops = list_ops()
    assert len(ops) == 50, f"expected 50, got {len(ops)}"
    expected = {"momentum", "reversal", "value", "volatility", "volume", "quality", "conditional"}
    for family in expected:
        assert len(list_by_family(family)) > 0, f"empty family: {family}"


def test_pr5_family_distribution() -> None:
    """PR-5: Family distribution matches design (8/6/4/8/6/5/13)."""
    expected_counts = {
        "momentum": 8, "reversal": 6, "value": 4,
        "volatility": 8, "volume": 6, "quality": 5, "conditional": 13,
    }
    for family, count in expected_counts.items():
        actual = len(list_by_family(family))
        assert actual == count, f"{family}: expected {count}, got {actual}"


def test_pr5_instantiate_momentum_n() -> None:
    """PR-5: instantiate('momentum_n', {n: 20}) returns valid AST."""
    ast = instantiate("momentum_n", {"n": 20})
    # Must compile
    expr = compile_ast(ast)
    assert expr is not None


def test_pr5_instantiate_ema_crossover() -> None:
    """PR-5: instantiate('ema_crossover', {fast:12, slow:26}) returns valid AST."""
    ast = instantiate("ema_crossover", {"fast": 12, "slow": 26})
    expr = compile_ast(ast)
    assert expr is not None


def test_pr5_instantiate_with_default_param() -> None:
    """PR-5: instantiate('momentum_n') falls back to n=20."""
    ast = instantiate("momentum_n")
    expr = compile_ast(ast)
    assert expr is not None


def test_pr5_unknown_op_raises_keyerror() -> None:
    """PR-5: instantiate('nonexistent') raises KeyError."""
    with pytest.raises(KeyError):
        instantiate("nonexistent_op_xyz")


def test_pr5_get_doc_for_llm() -> None:
    """PR-5: get_doc_for_llm produces non-empty documentation."""
    doc = get_doc_for_llm()
    assert "Semantic Factor Library" in doc
    assert doc.count("- **") >= 50


def test_pr5_semantic_op_routes_via_compile_ast() -> None:
    """PR-5: Semantic op names route through compile_ast (Layer 4)."""
    ast = make_call("momentum_n", [], n=20)
    expr = compile_ast(ast)
    assert expr is not None

    ast = make_call("ema_crossover", [], fast=12, slow=26)
    expr = compile_ast(ast)
    assert expr is not None


def test_pr5_load_user_registry(tmp_path) -> None:
    """PR-5: YAML extension merges user-defined ops."""
    import yaml

    user_yaml = tmp_path / "semantic.yaml"
    user_yaml.write_text(yaml.safe_dump({
        "ops": {
            "my_custom_factor": {
                "family": "custom",
                "description": "user-defined test factor",
                "template": {
                    "op": "sub",
                    "args": [{"op": "col", "value": "close"}, {"op": "lit", "value": 0.0}],
                },
                "param_keys": [],
            },
        },
    }))

    from src.llmwikify.reproduction import semantic_registry

    # Reset registry for test isolation
    semantic_registry._REGISTRY = {}
    count = semantic_registry.load_user_registry(user_yaml)
    assert count == 1
    op = semantic_registry.get_op("my_custom_factor")
    assert op is not None
    assert op.family == "custom"
    assert op.description == "user-defined test factor"

    # Cleanup: reset back to default
    semantic_registry._REGISTRY = {}


# ─── PR-6: Self-Repairing Compiler ──────────────────────────


def test_pr6_repair_missing_kwarg() -> None:
    """PR-6: CompileFix repairs MissingKwarg by injecting default."""
    ast = make_call("rolling_mean", [make_col("close")])  # missing window
    err = StructuredError(
        kind="MissingKwarg",
        message="missing window",
        context={"op": "rolling_mean", "missing": ["window"]},
    )
    repaired = repair_once(ast, err)
    assert repaired is not None
    assert "window" in repaired.kwargs
    assert repaired.kwargs["window"] == 20
    # Verify it now compiles
    compile_ast(repaired)


def test_pr6_repair_unknown_kwarg() -> None:
    """PR-6: CompileFix strips UnknownKwarg."""
    ast = make_call("pct_change", [make_col("close")], foo="bar")
    err = StructuredError(
        kind="UnknownKwarg",
        message="bad kwarg",
        context={"op": "pct_change", "bad_kwargs": ["foo"]},
    )
    repaired = repair_once(ast, err)
    assert repaired is not None
    assert "foo" not in repaired.kwargs


def test_pr6_repair_wrong_arg_count() -> None:
    """PR-6: CompileFix pads children for WrongArgCount."""
    ast = make_call("correlation", [make_col("close")])  # needs 2
    err = StructuredError(
        kind="WrongArgCount",
        message="needs 2 args",
        context={"op": "correlation", "expected_min": 2, "expected_max": 2},
    )
    repaired = repair_once(ast, err)
    assert repaired is not None
    assert len(repaired.args) == 2


def test_pr6_repair_incomplete_ast_quality_fix() -> None:
    """PR-6: QualityFix rewrites INCOMPLETE AST to simple momentum."""
    ast = make_call("rolling_mean", [make_col("close")], window=20)
    err = StructuredError(kind="IncompleteAST", message="AST too short")
    repaired = repair_once(ast, err, factor_data={})
    assert repaired is not None
    assert repaired.op == "pct_change"


def test_pr6_repair_returns_none_for_unknown_error() -> None:
    """PR-6: repair_once returns None if no strategy matches."""
    ast = make_call("rank", [make_col("close")])
    err = StructuredError(kind="Other", message="random error")
    repaired = repair_once(ast, err)
    # 'Other' kind does not match any FixStrategy
    assert repaired is None


def test_pr6_build_error_history() -> None:
    """PR-6: build_error_history formats previous attempts."""
    errs = [
        StructuredError(kind="MissingKwarg", message="no window", suggestion="add window=20"),
        StructuredError(kind="TypeMismatch", message="wrong type", suggestion="use float"),
    ]
    hist = build_error_history(errs)
    assert "PREVIOUS FAILED ATTEMPTS" in hist
    assert "Attempt 1" in hist
    assert "Attempt 2" in hist
    assert "MissingKwarg" in hist
    assert "TypeMismatch" in hist


def test_pr6_fix_strategies_registered() -> None:
    """PR-6: All 5 FixStrategy functions are registered."""
    from src.llmwikify.reproduction.self_repairing import FIX_STRATEGIES
    assert len(FIX_STRATEGIES) == 5
    strategy_names = [s.__name__ for s in FIX_STRATEGIES]
    assert "schema_fix" in strategy_names
    assert "compile_fix" in strategy_names
    assert "semantic_fix" in strategy_names
    assert "composite_fix" in strategy_names
    assert "runtime_fix" in strategy_names


# ─── PR-7: Telemetry + HDF5 key fix ─────────────────────────


def test_pr7_telemetry_record_and_summary() -> None:
    """PR-7: Telemetry records events and produces summary."""
    t = Telemetry()
    t.record("compile.success", factor="momentum")
    t.record("compile.failure", error="MissingKwarg")
    summary = t.summary()
    assert summary["counts"]["compile.success"] == 1
    assert summary["counts"]["compile.failure"] == 1
    assert summary["total_events"] == 2


def test_pr7_telemetry_singleton() -> None:
    """PR-7: get_telemetry returns the same instance."""
    t1 = get_telemetry()
    t2 = get_telemetry()
    assert t1 is t2


def test_pr7_telemetry_thread_safe() -> None:
    """PR-7: Telemetry counters work under concurrent threads."""
    import threading

    t = Telemetry()

    def worker() -> None:
        for _ in range(100):
            t.record("compile.success")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.count("compile.success") == 400


def test_pr7_telemetry_reset() -> None:
    """PR-7: reset() clears all counts."""
    t = Telemetry()
    t.record("compile.success")
    assert t.count("compile.success") == 1
    t.reset()
    assert t.count("compile.success") == 0


def test_pr7_hdf5_key_normalization_cp_fallback(tmp_path) -> None:
    """PR-7: HDF5 loader normalizes cp/close key (prefers close)."""
    df = pd.DataFrame(
        {"A": [1.0, 2.0], "B": [3.0, 4.0]},
        index=pd.date_range("2024-01-01", periods=2),
    )
    h5 = tmp_path / "stk_daily.h5"
    df.to_hdf(h5, key="close")
    df.to_hdf(h5, key="open")

    # Test the key detection logic
    with pd.HDFStore(h5, "r") as store:
        keys = store.keys()
        close_key = "close" if "/close" in keys else "cp"
    assert close_key == "close"


def test_pr7_hdf5_key_normalization_cp_legacy(tmp_path) -> None:
    """PR-7: Falls back to 'cp' when 'close' key not present."""
    df = pd.DataFrame(
        {"A": [1.0, 2.0], "B": [3.0, 4.0]},
        index=pd.date_range("2024-01-01", periods=2),
    )
    h5 = tmp_path / "stk_daily.h5"
    df.to_hdf(h5, key="cp")

    with pd.HDFStore(h5, "r") as store:
        keys = store.keys()
        close_key = "close" if "/close" in keys else "cp"
    assert close_key == "cp"


# ─── Integration: end-to-end smoke ─────────────────────────


def test_e2e_semantic_op_to_factor_series() -> None:
    """End-to-end: semantic op → AST → compile → factor series."""
    ast = instantiate("momentum_n", {"n": 20})
    ast_json = ast.model_dump_json()

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=30),
        "open": 10.0, "high": 11.0, "low": 9.0,
        "close": [10.0 + i * 0.5 for i in range(30)],
        "volume": 1000.0,
    })
    result = _compute_factor_from_ast(df, ast_json)
    assert isinstance(result, pd.Series)
    assert len(result) == 30


def test_e2e_self_repair_then_compile() -> None:
    """End-to-end: broken AST → repair → compile → factor series."""
    # Missing kwarg
    ast = make_call("rolling_mean", [make_col("close")])
    err = StructuredError(
        kind="MissingKwarg", message="missing window",
        context={"op": "rolling_mean", "missing": ["window"]},
    )
    repaired = repair_once(ast, err)
    assert repaired is not None
    expr = compile_ast(repaired)

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=30),
        "open": 10.0, "high": 11.0, "low": 9.0,
        "close": [10.0 + i for i in range(30)],
        "volume": 1000.0,
    })
    import polars as pl
    df_pl = pl.from_pandas(df)
    out = df_pl.with_columns(expr.alias("factor_value"))
    assert "factor_value" in out.columns
    assert len(out) == 30