"""Tests for error_categorizer: 异常分类 + StructuredError."""

from __future__ import annotations

import pytest

from llmwikify.reproduction.common import errors as ec


class TestStructuredError:
    """Test StructuredError dataclass (3 测试)."""

    def test_construction(self) -> None:
        """基本构造."""
        e = ec.StructuredError(kind="TestKind", message="test message")
        assert e.kind == "TestKind"
        assert e.message == "test message"
        assert e.suggestion == ""
        assert e.context == {}

    def test_to_prompt_with_suggestion(self) -> None:
        """to_prompt() 包含 kind + message + suggestion."""
        e = ec.StructuredError(
            kind="UnknownOp",
            message="Op 'foo' not in 157",
            suggestion="Use rolling_mean instead",
        )
        prompt = e.to_prompt()
        assert "[UnknownOp]" in prompt
        assert "Op 'foo' not in 157" in prompt
        assert "Suggestion: Use rolling_mean instead" in prompt

    def test_to_prompt_without_suggestion(self) -> None:
        """无 suggestion 时只输出 kind + message."""
        e = ec.StructuredError(kind="Test", message="msg")
        prompt = e.to_prompt()
        assert "[Test]" in prompt
        assert "Suggestion" not in prompt


class TestCategorizeCompileError:
    """Test categorize_compile_error (5 测试)."""

    def test_unknown_op(self) -> None:
        """UnknownOp 错误模式."""
        err = Exception("UnknownOp 'foo_bar' is not in 157 known operators")
        result = ec.categorize_compile_error(err)
        assert result.kind == "UnknownOp"
        assert "foo_bar" in result.context.get("op", "")

    def test_wrong_arg_count(self) -> None:
        """WrongArgCount 错误模式."""
        err = Exception("Operator rank expects 1 args, got 2")
        result = ec.categorize_compile_error(err)
        assert result.kind == "WrongArgCount"

    def test_missing_kwarg(self) -> None:
        """MissingKwarg 错误模式."""
        err = Exception("rolling_mean requires kwargs={'window': N}")
        result = ec.categorize_compile_error(err)
        assert result.kind == "MissingKwarg"

    def test_unknown_column(self) -> None:
        """UnknownColumn 错误模式 + available_columns."""
        err = Exception("UnknownColumn 'bad_col' could not find column")
        result = ec.categorize_compile_error(err, available_columns=["close", "open"])
        assert result.kind == "UnknownColumn"
        assert result.context["column"] == "bad_col"
        assert "close" in result.suggestion

    def test_unknown_error_returns_generic(self) -> None:
        """无法识别的错误返回 kind='Other' (实现细节, 实际是 Other)."""
        err = Exception("something completely weird happened")
        result = ec.categorize_compile_error(err)
        assert result.kind in ("Unknown", "Other")


class TestCategorizeExtractError:
    """Test categorize_extract_error (2 测试)."""

    def test_json_parse_error(self) -> None:
        """JSON 解析错误."""
        err = Exception("Failed to parse JSON: invalid syntax")
        result = ec.categorize_extract_error(err)
        # 应该有某种 kind
        assert isinstance(result.kind, str)
        assert len(result.kind) > 0

    def test_returns_structured(self) -> None:
        """返回 StructuredError 类型."""
        err = Exception("test")
        result = ec.categorize_extract_error(err)
        assert isinstance(result, ec.StructuredError)
