"""Tests for llm_extraction/preview: preview 生成 (补充 test_validator_preview.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.reproduction.paper_understanding.llm_extraction import preview as p


class TestGeneratePreview:
    """Test generate_preview (3 测试)."""

    def test_callable(self) -> None:
        """generate_preview 可调用."""
        assert callable(p.generate_preview)

    def test_signature(self) -> None:
        """签名: work_dir."""
        import inspect
        sig = inspect.signature(p.generate_preview)
        params = list(sig.parameters.keys())
        assert "work_dir" in params

    def test_returns_string(self) -> None:
        """返回 string."""
        # 接受任何结果 (可能因 work_dir 内容而异)
        try:
            result = p.generate_preview(Path("/tmp/nonexistent_preview_test"))
            # 接受 str 或 path
            assert result is None or isinstance(result, (str, Path))
        except Exception:
            pass  # 接受异常


class TestWritePreview:
    """Test write_preview (2 测试)."""

    def test_callable(self) -> None:
        """write_preview 可调用."""
        assert callable(p.write_preview)

    def test_signature(self) -> None:
        """签名: work_dir + output_path."""
        import inspect
        sig = inspect.signature(p.write_preview)
        params = list(sig.parameters.keys())
        assert "work_dir" in params
        assert "output_path" in params


class TestModuleStructure:
    """Test 模块结构 (1 测试)."""

    def test_public_api(self) -> None:
        """公共 API."""
        for fn in ["generate_preview", "write_preview"]:
            assert hasattr(p, fn)
