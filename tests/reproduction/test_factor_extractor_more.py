"""Tests for factor_extractor: 补充测试 (现有 test_extract_factor_metadata 覆盖)."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from llmwikify.reproduction import factor_extractor as fe


class TestExtractFactorMetadata:
    """Test extract_factor_metadata 签名 (3 测试)."""

    def test_function_exists(self) -> None:
        """函数存在."""
        assert hasattr(fe, "extract_factor_metadata")
        assert callable(fe.extract_factor_metadata)

    def test_signature(self) -> None:
        """签名: llm + formula_brief + code."""
        import inspect
        sig = inspect.signature(fe.extract_factor_metadata)
        params = list(sig.parameters.keys())
        assert "llm" in params
        assert "formula_brief" in params
        assert "code" in params

    def test_with_existing_metadata(self) -> None:
        """支持 existing_metadata 参数."""
        import inspect
        sig = inspect.signature(fe.extract_factor_metadata)
        # Phase 3 加入了 existing_metadata
        assert "existing_metadata" in sig.parameters or "prompts" in sig.parameters


class TestSystemPromptConstants:
    """Test 模块级 prompt 常量 (2 测试)."""

    def test_system_prompt_metadata_exists(self) -> None:
        """SYSTEM_PROMPT_METADATA 存在."""
        assert hasattr(fe, "SYSTEM_PROMPT_METADATA")
        assert len(fe.SYSTEM_PROMPT_METADATA) > 100

    def test_system_prompt_metadata_v2_exists(self) -> None:
        """SYSTEM_PROMPT_METADATA_V2 存在 (Phase 3 加入)."""
        assert hasattr(fe, "SYSTEM_PROMPT_METADATA_V2")
        assert len(fe.SYSTEM_PROMPT_METADATA_V2) > 100
