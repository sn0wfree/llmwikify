#!/usr/bin/env python3
"""Unit tests for DeferredQueue (P6 Layer 2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.defer import DeferredItem, DeferredQueue


# ── Basic add / len ───────────────────────────────────


class TestBasicAdd:
    def test_empty_queue(self, tmp_path):
        q = DeferredQueue(tmp_path)
        assert len(q) == 0
        assert not q

    def test_add_one(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None, (), {}, reason="boom")
        assert len(q) == 1
        assert q

    def test_add_multiple(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None)
        q.add("s2", lambda: None)
        q.add("s3", lambda: None)
        assert len(q) == 3

    def test_item_preserves_stage_and_reason(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("stage1_call1", lambda: None, reason="timeout")
        item = q.items[0]
        assert item.stage == "stage1_call1"
        assert item.reason == "timeout"
        assert item.added_at > 0

    def test_item_preserves_args_kwargs(self, tmp_path):
        q = DeferredQueue(tmp_path)
        fn = lambda *a, **k: None
        q.add("s", fn, ("a", "b"), {"k": 1})
        item = q.items[0]
        assert item.args == ("a", "b")
        assert item.kwargs == {"k": 1}
        assert item.fn is fn


# ── Flush ────────────────────────────────────────────


class TestFlush:
    def test_flush_resolves_succeeding_items(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None)
        q.add("s2", lambda: None)
        resolved, errors = q.flush()
        assert resolved == 2
        assert errors == []
        assert len(q) == 0

    def test_flush_returns_errors_for_failing_items(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None)  # succeeds
        q.add("s2", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        resolved, errors = q.flush()
        assert resolved == 1
        assert len(errors) == 1
        assert "boom" in str(errors[0])

    def test_flush_does_not_requeue_failures(self, tmp_path):
        """After flush, items that failed are removed (no infinite loop)."""
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: (_ for _ in ()).throw(RuntimeError("persistent")))
        resolved, errors = q.flush()
        assert resolved == 0
        assert len(errors) == 1
        # Queue is empty (no re-queue)
        assert len(q) == 0

    def test_flush_skips_items_without_fn(self, tmp_path):
        """Items loaded from disk metadata have no fn; skip them."""
        q = DeferredQueue(tmp_path)
        # Manually create an item with no fn (as if loaded from disk)
        q.items.append(DeferredItem(
            stage="s1", reason="x", added_at=0.0, fn=None,
        ))
        resolved, errors = q.flush()
        assert resolved == 0
        assert errors == []

    def test_flush_empty_queue(self, tmp_path):
        q = DeferredQueue(tmp_path)
        resolved, errors = q.flush()
        assert resolved == 0
        assert errors == []
        assert len(q) == 0


# ── Persistence ─────────────────────────────────────


class TestPersistence:
    def test_save_metadata_writes_json(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None, reason="timeout")
        q.add("s2", lambda: None, reason="rate_limit")
        q.save_metadata()
        assert q.path.exists()
        data = json.loads(q.path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["stage"] == "s1"
        assert data[0]["reason"] == "timeout"
        assert "fn" not in data[0]
        assert "args" not in data[0]

    def test_save_metadata_creates_workdir(self, tmp_path):
        work = tmp_path / "subdir" / "paper1"
        q = DeferredQueue(work)
        q.save_metadata()
        assert q.path.exists()

    def test_save_metadata_empty(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.save_metadata()
        assert q.path.exists()
        data = json.loads(q.path.read_text(encoding="utf-8"))
        assert data == []

    def test_save_metadata_unicode_safe(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None, reason="中文 αβγ")
        q.save_metadata()
        data = json.loads(q.path.read_text(encoding="utf-8"))
        assert data[0]["reason"] == "中文 αβγ"


# ── Clear / iter ────────────────────────────────────


class TestClearIter:
    def test_clear(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None)
        q.add("s2", lambda: None)
        assert len(q) == 2
        q.clear()
        assert len(q) == 0

    def test_iter(self, tmp_path):
        q = DeferredQueue(tmp_path)
        q.add("s1", lambda: None)
        q.add("s2", lambda: None)
        items = list(q)
        assert len(items) == 2
        assert [i.stage for i in items] == ["s1", "s2"]


# ── Integration: deferred-then-flush pattern ──────


class TestDeferredThenFlush:
    def test_defer_then_flush_orchestrator_pattern(self, tmp_path):
        """Simulate orchestrator pattern: defer, then flush at end."""
        q = DeferredQueue(tmp_path)
        calls = {"fn_a": 0, "fn_b": 0}

        def fn_a():
            calls["fn_a"] += 1

        def fn_b():
            calls["fn_b"] += 1

        # Defer both
        q.add("stage_a", fn_a, reason="first attempt failed")
        q.add("stage_b", fn_b, reason="second attempt failed")
        assert len(q) == 2

        # Flush (1 retry pass)
        resolved, errors = q.flush()
        assert resolved == 2
        assert calls == {"fn_a": 1, "fn_b": 1}
        assert len(q) == 0

        # Persist metadata
        q.save_metadata()
        assert q.path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
