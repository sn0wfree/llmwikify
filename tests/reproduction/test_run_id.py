"""Tests for run_id: 唯一 ID 生成 + sanitize."""

from __future__ import annotations

import re

import pytest

from llmwikify.reproduction import run_id as rid


class TestGenerateRunId:
    """Test generate_run_id (4 测试)."""

    def test_returns_string(self) -> None:
        """generate_run_id() 返回非空字符串."""
        result = rid.generate_run_id()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_includes_uuid(self) -> None:
        """默认生成的 ID 包含 UUID 部分 (避免冲突)."""
        result = rid.generate_run_id()
        # 至少包含 hex 字符
        assert re.search(r"[0-9a-f]{6,}", result), f"No hex in: {result}"

    def test_unique_per_call(self) -> None:
        """每次调用生成不同 ID (UUID 后缀)."""
        ids = {rid.generate_run_id() for _ in range(10)}
        assert len(ids) == 10

    def test_with_start_end(self) -> None:
        """传 start/end 时, ID 包含日期片段."""
        result = rid.generate_run_id(start="20240101", end="20241231")
        # 可能用 - 分隔
        assert "20240101" in result or "2024-01-01" in result


class TestSanitizeRunId:
    """Test sanitize_run_id (1 测试)."""

    def test_sanitize_removes_unsafe(self) -> None:
        """sanitize_run_id 去除不安全字符."""
        dirty = "run/with\\bad:chars*?<>|"
        clean = rid.sanitize_run_id(dirty)
        # 替换为安全字符 (通常 _ 或 -)
        assert "/" not in clean
        assert "\\" not in clean
        assert ":" not in clean
        assert "*" not in clean
        assert "?" not in clean
