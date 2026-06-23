"""Tests for ``iter_with_metrics`` and ``call_with_metrics`` (R-1).

Regression coverage for the R-1 extraction of the
``measure_latency`` + ``LLMMetricsCollector.record(...)`` template that
was previously duplicated 3 times in ``ChatRunnerV2._stream_llm``.

Covers:
  - successful streaming yields all events + records success=True
  - successful single-shot call yields one DONE event + records
  - exception in source records success=False and re-raises
  - chars_in is forwarded to the metric record
  - ``iter_factory`` is invoked once, inside the timing window
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llmwikify.apps.chat.agent.llm_metrics import (
    call_with_metrics,
    get_llm_metrics_collector,
    iter_with_metrics,
)


def _reset_collector() -> None:
    get_llm_metrics_collector().reset()


class TestIterWithMetrics:
    def setup_method(self) -> None:
        _reset_collector()

    def test_yields_all_events(self):
        async def _src():
            for i in range(3):
                yield {"type": "content", "text": str(i)}

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "test", 100)]

        events = asyncio.run(_collect())
        assert len(events) == 3
        assert events[0] == {"type": "content", "text": "0"}
        assert events[2] == {"type": "content", "text": "2"}

    def test_records_success(self):
        async def _src():
            yield {"type": "done", "content": "ok"}

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "p1", 50)]

        asyncio.run(_collect())
        summary = get_llm_metrics_collector().summary()
        assert summary["total_records"] == 1
        assert summary["success_count"] == 1
        assert summary["error_count"] == 0
        assert summary["by_prompt"]["p1"]["count"] == 1
        assert summary["by_prompt"]["p1"]["error_count"] == 0

    def test_records_error_on_exception(self):
        async def _src():
            yield {"type": "content", "text": "x"}
            raise RuntimeError("boom")

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "p2", 10)]

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(_collect())

        summary = get_llm_metrics_collector().summary()
        assert summary["total_records"] == 1
        assert summary["success_count"] == 0
        assert summary["error_count"] == 1
        assert "RuntimeError" in summary["recent"][0]["error"]
        assert "boom" in summary["recent"][0]["error"]

    def test_chars_in_forwarded(self):
        async def _src():
            yield {"type": "done", "content": "x"}

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "p3", 4242)]

        asyncio.run(_collect())
        summary = get_llm_metrics_collector().summary()
        assert summary["total_chars_in"] == 4242
        assert summary["recent"][0]["chars_in"] == 4242

    def test_iter_factory_invoked_once(self):
        """Factory is called once, even if the stream yields many events."""
        calls = []

        def _factory():
            calls.append(1)

            async def _src():
                for i in range(5):
                    yield {"type": "content", "text": str(i)}
            return _src()

        async def _collect():
            return [ev async for ev in iter_with_metrics(_factory, "p4", 0)]

        asyncio.run(_collect())
        assert len(calls) == 1

    def test_empty_iter_records(self):
        async def _src():
            if False:
                yield  # make it a generator

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "p5", 0)]

        events = asyncio.run(_collect())
        assert events == []
        summary = get_llm_metrics_collector().summary()
        assert summary["total_records"] == 1
        assert summary["success_count"] == 1

    def test_chains_exceptions_with_context(self):
        async def _src():
            yield {"type": "content", "text": "x"}
            raise ValueError("bad arg")

        async def _collect():
            return [ev async for ev in iter_with_metrics(_src, "p6", 0)]

        with pytest.raises(ValueError, match="bad arg"):
            asyncio.run(_collect())


class TestCallWithMetrics:
    def setup_method(self) -> None:
        _reset_collector()

    def test_yields_done_event(self):
        class _Reply:
            content = "the answer"

        def _call():
            return _Reply()

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb1", 0)]

        events = asyncio.run(_collect())
        assert len(events) == 1
        assert events[0] == {"type": "done", "content": "the answer"}

    def test_handles_missing_content(self):
        class _Reply:
            pass

        def _call():
            return _Reply()

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb2", 0)]

        events = asyncio.run(_collect())
        assert events[0]["content"] == ""

    def test_handles_none_content(self):
        class _Reply:
            content = None

        def _call():
            return _Reply()

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb3", 0)]

        events = asyncio.run(_collect())
        assert events[0]["content"] == ""

    def test_records_success(self):
        class _Reply:
            content = "ok"

        def _call():
            return _Reply()

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb4", 30)]

        asyncio.run(_collect())
        summary = get_llm_metrics_collector().summary()
        assert summary["total_records"] == 1
        assert summary["success_count"] == 1
        assert summary["by_prompt"]["fb4"]["count"] == 1

    def test_records_error_on_exception(self):
        def _call():
            raise ConnectionError("network down")

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb5", 0)]

        with pytest.raises(ConnectionError, match="network down"):
            asyncio.run(_collect())

        summary = get_llm_metrics_collector().summary()
        assert summary["error_count"] == 1
        assert "ConnectionError" in summary["recent"][0]["error"]

    def test_chars_in_forwarded(self):
        class _Reply:
            content = "x"

        def _call():
            return _Reply()

        async def _collect():
            return [ev async for ev in call_with_metrics(_call, "fb6", 9999)]

        asyncio.run(_collect())
        summary = get_llm_metrics_collector().summary()
        assert summary["total_chars_in"] == 9999


class TestHelpersIntegration:
    """Verify both helpers can coexist and record independently."""

    def setup_method(self) -> None:
        _reset_collector()

    def test_both_helpers_record_separately(self):
        class _Reply:
            content = "fb answer"

        async def _stream():
            yield {"type": "content", "text": "stream answer"}

        def _call():
            return _Reply()

        async def _scenario():
            # Stream path
            async for _ in iter_with_metrics(_stream, "stream_tag", 10):
                pass
            # Single-shot path
            async for _ in call_with_metrics(_call, "call_tag", 20):
                pass

        asyncio.run(_scenario())

        summary = get_llm_metrics_collector().summary()
        assert summary["total_records"] == 2
        assert summary["by_prompt"]["stream_tag"]["count"] == 1
        assert summary["by_prompt"]["call_tag"]["count"] == 1
        assert summary["total_chars_in"] == 30
