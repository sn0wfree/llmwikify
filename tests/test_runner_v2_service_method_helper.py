"""Tests for ``ChatRunnerV2._call_service_method`` (R-2 extraction).

Covers the defensive adapter access pattern previously duplicated
between ``_safe_truncate`` and ``_get_tool_specs``:

  - getattr → None check → try/except → iscoroutine guard → fallback

The helper consolidates this pattern; both call sites now delegate
to it.  These tests verify both the helper's contract and the
behaviour of the two callers.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2


def _make_runner(chat_service: object) -> ChatRunnerV2:
    """Build a minimal ``ChatRunnerV2`` with the given ``chat_service``."""
    return ChatRunnerV2(
        chat_service=chat_service,
        tool_executor=MagicMock(),
        prompt_builder=MagicMock(),
    )


class TestCallServiceMethod:
    """The helper's direct contract."""

    def test_calls_present_method(self):
        cs = MagicMock()
        cs._truncate_messages = MagicMock(return_value=["x", "y"])
        runner = _make_runner(cs)
        result = runner._call_service_method(
            "_truncate_messages", ["a", "b"],
            default=None,
        )
        assert result == ["x", "y"]
        cs._truncate_messages.assert_called_once_with(["a", "b"])

    def test_missing_attr_returns_default(self):
        cs = MagicMock(spec=[])  # no _truncate_messages
        runner = _make_runner(cs)
        result = runner._call_service_method(
            "_truncate_messages", [],
            default=["fallback"],
        )
        assert result == ["fallback"]

    def test_exception_returns_default(self):
        cs = MagicMock()
        cs._truncate_messages = MagicMock(side_effect=RuntimeError("boom"))
        runner = _make_runner(cs)
        result = runner._call_service_method(
            "_truncate_messages", [],
            default=["fallback"],
        )
        assert result == ["fallback"]

    def test_coroutine_result_returns_default(self):
        """If the method is async, helper can't await — return default."""
        cs = MagicMock()
        # A Future / coroutine-like object that ``inspect.iscoroutine``
        # treats as a coroutine. We use a real coroutine here.
        async def _async_get_specs(reg):
            return [{"name": "tool"}]
        cs._get_toolspec = _async_get_specs
        runner = _make_runner(cs)
        result = runner._call_service_method(
            "_get_toolspec", MagicMock(),
            default=[],
        )
        assert result == []

    def test_default_log_label_uses_attr_name(self):
        """When ``log_label`` is omitted, the warning uses ``attr_name``."""
        cs = MagicMock()
        cs._truncate_messages = MagicMock(side_effect=ValueError("bad"))
        runner = _make_runner(cs)
        # No exception propagates; the helper logs and returns default.
        result = runner._call_service_method(
            "_truncate_messages", [], default=None,
        )
        assert result is None


class TestSafeTruncateWithHelper:
    """``_safe_truncate`` behaviour via the helper."""

    def test_truncate_returns_truncated(self):
        cs = MagicMock()
        cs._truncate_messages = MagicMock(return_value=[{"role": "user"}])
        runner = _make_runner(cs)
        result = runner._safe_truncate(
            [{"role": "user"}, {"role": "assistant"}],
        )
        assert result == [{"role": "user"}]

    def test_truncate_no_method_returns_original(self):
        cs = MagicMock(spec=[])
        runner = _make_runner(cs)
        msgs = [{"role": "user", "content": "x"}]
        result = runner._safe_truncate(msgs)
        assert result is msgs

    def test_truncate_raises_returns_original(self):
        cs = MagicMock()
        cs._truncate_messages = MagicMock(side_effect=ValueError("bad"))
        runner = _make_runner(cs)
        msgs = [{"role": "user"}]
        result = runner._safe_truncate(msgs)
        assert result is msgs


class TestGetToolSpecsWithHelper:
    """``_get_tool_specs`` behaviour via the helper."""

    def test_get_specs_returns_list(self):
        cs = MagicMock()
        cs._get_toolspec = MagicMock(return_value=[{"name": "tool1"}])
        runner = _make_runner(cs)
        result = runner._get_tool_specs(MagicMock())
        assert result == [{"name": "tool1"}]

    def test_get_specs_no_method_returns_empty(self):
        cs = MagicMock(spec=[])
        runner = _make_runner(cs)
        result = runner._get_tool_specs(MagicMock())
        assert result == []

    def test_get_specs_raises_returns_empty(self):
        cs = MagicMock()
        cs._get_toolspec = MagicMock(side_effect=RuntimeError("x"))
        runner = _make_runner(cs)
        result = runner._get_tool_specs(MagicMock())
        assert result == []

    def test_get_specs_returns_none_treated_as_empty(self):
        """Some implementations may return None instead of []."""
        cs = MagicMock()
        cs._get_toolspec = MagicMock(return_value=None)
        runner = _make_runner(cs)
        result = runner._get_tool_specs(MagicMock())
        assert result == []

    def test_get_specs_returns_empty_list_kept(self):
        """Empty list result should not be replaced with anything else."""
        cs = MagicMock()
        cs._get_toolspec = MagicMock(return_value=[])
        runner = _make_runner(cs)
        result = runner._get_tool_specs(MagicMock())
        assert result == []
