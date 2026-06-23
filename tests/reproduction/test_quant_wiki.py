"""Tests for quant_wiki: QuantWiki 类 (补充 test_paper_api.py 覆盖)."""

from __future__ import annotations

import pytest
from pathlib import Path

from llmwikify.reproduction import quant_wiki as qw


class TestGetQuantRoot:
    """Test get_quant_root (2 测试)."""

    def test_returns_path(self) -> None:
        """get_quant_root 返回 Path."""
        result = qw.get_quant_root()
        assert isinstance(result, Path)

    def test_with_custom_root(self) -> None:
        """get_quant_root 接受 project_root."""
        result = qw.get_quant_root(project_root=Path("/tmp"))
        assert isinstance(result, Path)


class TestGetQuantWiki:
    """Test get_quant_wiki 工厂 (3 测试)."""

    def test_returns_quant_wiki(self) -> None:
        """返回 QuantWiki 实例."""
        result = qw.get_quant_wiki(project_root=Path("/tmp"))
        assert isinstance(result, qw.QuantWiki)

    def test_singleton_per_root(self) -> None:
        """同 root 多次调用应返回相同实例 (缓存)."""
        a = qw.get_quant_wiki(project_root=Path("/tmp/singleton_test"))
        b = qw.get_quant_wiki(project_root=Path("/tmp/singleton_test"))
        assert a is b

    def test_different_roots_different_instances(self) -> None:
        """不同 root 返回不同实例."""
        a = qw.get_quant_wiki(project_root=Path("/tmp/root_a"))
        b = qw.get_quant_wiki(project_root=Path("/tmp/root_b"))
        assert a is not b


class TestQuantWikiClass:
    """Test QuantWiki 类本身 (3 测试)."""

    def test_class_exists(self) -> None:
        """QuantWiki 类存在."""
        assert hasattr(qw, "QuantWiki")

    def test_has_required_attributes(self) -> None:
        """有 factors_dir 等属性."""
        wiki = qw.QuantWiki(factors_dir=Path("/tmp/factors"), project_root=Path("/tmp"))
        # 至少有 factors_dir
        assert hasattr(wiki, "factors_dir")

    def test_module_docstring(self) -> None:
        """模块有 docstring."""
        assert qw.__doc__ is not None
