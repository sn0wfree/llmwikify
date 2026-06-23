"""Tests for ast_extractor: LLM 输出文本 → ASTNode."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import ast_extractor as ae
from llmwikify.reproduction.ast_nodes import ASTNode


class TestExtractAst:
    """Test extract_ast (5 测试).

    extract_ast 接受 LLM 输出文本, 解析为 ASTNode:
    - 接受 markdown ```json 包装
    - 接受 chatty prefix ("Here is the AST:")
    - 接受裸 JSON
    - 无效时返回 None
    """

    def test_markdown_json_fence(self) -> None:
        """```json { ... } ``` 包装格式."""
        text = '```json\n{"op": "rank", "args": []}\n```'
        result = ae.extract_ast(text)
        assert isinstance(result, ASTNode)
        assert result.op == "rank"

    def test_bare_json(self) -> None:
        """裸 JSON 格式."""
        text = '{"op": "ts_mean", "args": []}'
        result = ae.extract_ast(text)
        assert isinstance(result, ASTNode)
        assert result.op == "ts_mean"

    def test_chatty_prefix(self) -> None:
        """Chatty prefix ('Here is the AST:') 处理."""
        text = 'Here is the AST:\n{"op": "rank", "args": []}'
        result = ae.extract_ast(text)
        assert isinstance(result, ASTNode)
        assert result.op == "rank"

    def test_invalid_input_returns_none(self) -> None:
        """无效输入返回 None (不抛错)."""
        assert ae.extract_ast("not json at all") is None
        assert ae.extract_ast("") is None
        assert ae.extract_ast("{invalid json") is None

    def test_nested_ast(self) -> None:
        """嵌套 AST 解析."""
        text = '```json\n{"op": "rank", "args": [{"op": "ts_mean", "args": []}]}\n```'
        result = ae.extract_ast(text)
        assert isinstance(result, ASTNode)
        assert result.op == "rank"
        assert len(result.args) == 1
        assert result.args[0].op == "ts_mean"
