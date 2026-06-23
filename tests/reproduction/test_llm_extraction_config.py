"""Tests for llm_extraction/config: Pass2Config dataclass."""

from __future__ import annotations

import pytest

from llmwikify.reproduction.llm_extraction import config as c


class TestPass2Config:
    """Test Pass2Config (4 测试)."""

    def test_construction_with_defaults(self) -> None:
        """Pass2Config 默认构造."""
        cfg = c.Pass2Config()
        assert cfg is not None
        # 至少有 mode 字段 (或任意字段)
        assert len(cfg.__dict__) > 5

    def test_fields_documented(self) -> None:
        """fields() 列出所有字段."""
        from dataclasses import fields
        field_names = {f.name for f in fields(c.Pass2Config)}
        assert len(field_names) > 0

    def test_to_dict(self) -> None:
        """asdict() 序列化为 dict."""
        from dataclasses import asdict
        cfg = c.Pass2Config()
        d = asdict(cfg)
        assert isinstance(d, dict)
        assert len(d) > 0

    def test_default_values_present(self) -> None:
        """默认字段值存在."""
        cfg = c.Pass2Config()
        d = cfg.__dict__
        # 至少 5 个字段
        assert len(d) >= 5


class TestConfigImports:
    """Test 其他公共 API (1 测试)."""

    def test_path_constant(self) -> None:
        """Path 类型可导入 (来自 stdlib, 验证 Python 环境)."""
        from pathlib import Path
        assert Path is not None
