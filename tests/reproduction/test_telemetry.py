"""Tests for telemetry: 进程内指标收集."""

from __future__ import annotations

import pytest

from llmwikify.reproduction.common import telemetry as t


class TestTelemetry:
    """Test Telemetry class (5 测试)."""

    def test_record_and_count(self) -> None:
        """record() 增加 count."""
        tm = t.Telemetry()
        tm.record("compile.success")
        tm.record("compile.success")
        tm.record("compile.failure")
        assert tm.count("compile.success") == 2
        assert tm.count("compile.failure") == 1
        assert tm.count("unknown_event") == 0

    def test_record_with_kwargs(self) -> None:
        """record 接受额外 kwargs (存为最近事件 context)."""
        tm = t.Telemetry()
        tm.record("compile.failure", error_kind="TimeoutError", factor="momentum")
        # count 不应含 kwargs, 仅 event
        assert tm.count("compile.failure") == 1
        # summary 应含 counts (含 'compile.failure' 键)
        summary = tm.summary()
        assert "compile.failure" in summary["counts"]
        # recent 列表应含完整事件 (含 kwargs)
        assert summary["recent"][0]["error_kind"] == "TimeoutError"
        assert summary["recent"][0]["factor"] == "momentum"

    def test_summary_returns_counts(self) -> None:
        """summary() 返回事件计数快照."""
        tm = t.Telemetry()
        tm.record("a")
        tm.record("a")
        tm.record("b")
        summary = tm.summary()
        assert "counts" in summary or "a" in summary
        # 至少 2 个事件
        assert tm.count("a") == 2
        assert tm.count("b") == 1

    def test_recent_events_truncated(self) -> None:
        """recent events 列表最多保留 _recent_max 个."""
        tm = t.Telemetry()
        # 写入 200 个事件
        for i in range(200):
            tm.record("e", idx=i)
        summary = tm.summary()
        # recent 列表应 ≤ _recent_max (100)
        recent = summary.get("recent", [])
        assert len(recent) <= tm._recent_max

    def test_get_telemetry_singleton(self) -> None:
        """get_telemetry() 返回同一实例."""
        a = t.get_telemetry()
        b = t.get_telemetry()
        assert a is b
        assert isinstance(a, t.Telemetry)
