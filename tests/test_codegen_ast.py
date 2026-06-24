"""Phase 6 TDD 前置测试: 验证 ast/ 目标模块在搬迁前可用.

5 个测试, 定义 ast/ 子包的公共 API 契约.
"""
from __future__ import annotations


def test_compile_ast():
    from llmwikify.reproduction.codegen.ast.compiler import compile_ast
    from llmwikify.reproduction.codegen.ast.nodes import make_col
    node = make_col("close")
    expr = compile_ast(node)
    assert expr is not None


def test_ast_node_construction():
    from llmwikify.reproduction.codegen.ast.nodes import make_col
    node = make_col("close")
    assert node.op == "col"
    assert node.value == "close"


def test_compute_complexity():
    from llmwikify.reproduction.codegen.ast.complexity import compute_complexity
    from llmwikify.reproduction.codegen.ast.nodes import make_col
    node = make_col("close")
    result = compute_complexity(node)
    assert isinstance(result, tuple)
    assert len(result) == 5


def test_extract_ast():
    from llmwikify.reproduction.codegen.ast.extractor import extract_ast
    json_str = '{"op": "col", "value": "close"}'
    result = extract_ast(json_str)
    assert result is not None
    assert result.op == "col"


def test_get_op_spec():
    from llmwikify.reproduction.codegen.ast.nodes import get_op_spec
    assert get_op_spec("rank") is not None
