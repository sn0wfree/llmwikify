"""Phase 5 TDD 前置测试: 验证 codegen/ 目标模块在搬迁前可用.

7 个测试, 定义 codegen/ 子包的公共 API 契约.
"""
from __future__ import annotations

import inspect


def test_extract_python():
    from llmwikify.reproduction.codegen.llm_code import extract_python
    text = "```python\ndef foo(): pass\n```"
    assert extract_python(text) == "def foo(): pass"


def test_validate_syntax():
    from llmwikify.reproduction.codegen.llm_code import validate_syntax
    ok, _ = validate_syntax("def foo(): pass")
    assert ok is True
    ok, _ = validate_syntax("def foo(:")
    assert ok is False


def test_validate_safety_delegates_to_sandbox():
    from llmwikify.reproduction.codegen.llm_code import validate_safety
    ok, _ = validate_safety("if rank(x): pass")
    assert ok is True  # no longer regex-filtered; caught at execution via ReAct


def test_execute_code():
    import polars as pl

    from llmwikify.reproduction.codegen.llm_code import execute_code
    df = pl.DataFrame({"x": [1, 2, 3]})
    code = "def compute_factor(df): return df['x'] * 2"
    series = execute_code(code, df)
    assert series.to_list() == [2, 4, 6]


def test_factor_compiler_init():
    from llmwikify.reproduction.codegen.compiler import FactorCompiler
    c = FactorCompiler()
    assert c is not None


def test_extract_factor_metadata_signature():
    from llmwikify.reproduction.codegen.metadata import extract_factor_metadata
    sig = inspect.signature(extract_factor_metadata)
    assert "llm" in sig.parameters
    assert "formula_brief" in sig.parameters
    assert "code" in sig.parameters


def test_system_prompt_code_exists():
    from llmwikify.reproduction.codegen.llm_code import SYSTEM_PROMPT_CODE
    assert "compute_factor" in SYSTEM_PROMPT_CODE
