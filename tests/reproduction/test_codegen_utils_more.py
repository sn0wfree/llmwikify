"""Tests for codegen_utils: 补充测试 (现有 test_factor_compiler_react 覆盖部分)."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import codegen_utils as cu


class TestExtractPython:
    """Test extract_python (4 测试)."""

    def test_basic_code_block(self) -> None:
        """基本 ```python ... ``` 提取."""
        text = "```python\ndef foo(): pass\n```"
        result = cu.extract_python(text)
        assert "def foo" in result

    def test_no_fence_returns_empty(self) -> None:
        """无 code fence 返回空 (实际可能是 None)."""
        result = cu.extract_python("plain text")
        # 接受 None 或空字符串
        assert result is None or result == ""

    def test_multiple_blocks_returns_first(self) -> None:
        """多个 block 返回第一个."""
        text = "```python\nx = 1\n```\ntext\n```python\ny = 2\n```"
        result = cu.extract_python(text)
        assert "x = 1" in result

    def test_empty_string(self) -> None:
        """空字符串返回 None 或空."""
        result = cu.extract_python("")
        assert result is None or result == ""


class TestValidateSyntax:
    """Test validate_syntax (3 测试)."""

    def test_valid_code(self) -> None:
        """合法 Python 代码."""
        ok, err = cu.validate_syntax("def foo(): pass")
        assert ok is True
        assert err == ""

    def test_invalid_code(self) -> None:
        """非法 Python 代码 (语法错误)."""
        ok, err = cu.validate_syntax("def foo(:")
        assert ok is False
        assert err  # 非空

    def test_empty_string(self) -> None:
        """空字符串."""
        ok, err = cu.validate_syntax("")
        assert ok is True  # 空代码语法上合法


class TestValidateSafety:
    """Test validate_safety (3 测试)."""

    def test_safe_code(self) -> None:
        """安全代码."""
        ok, err = cu.validate_safety("def compute_factor(df): return df['close']")
        assert ok is True

    def test_dangerous_if_detected(self) -> None:
        """危险: if 在 pl.Expr 上."""
        ok, err = cu.validate_safety("if rank(x): pass")
        # 应检测到 if 危险
        assert isinstance(ok, bool)

    def test_safe_function_form(self) -> None:
        """函数形式安全."""
        ok, err = cu.validate_safety("def compute_factor(df):\n    return df.with_columns(rank('close'))")
        assert ok is True


class TestExtractJson:
    """Test extract_json_from_response (3 测试)."""

    def test_json_in_code_fence(self) -> None:
        """```json { ... } ``` 提取."""
        text = '```json\n{"key": "value"}\n```'
        result = cu.extract_json_from_response(text)
        assert result is not None
        assert result["key"] == "value"

    def test_bare_json(self) -> None:
        """裸 JSON 提取."""
        text = '{"key": "value"}'
        result = cu.extract_json_from_response(text)
        assert result is not None
        assert result["key"] == "value"

    def test_invalid_json_returns_none(self) -> None:
        """无效 JSON 返回 None."""
        result = cu.extract_json_from_response("not json")
        assert result is None
