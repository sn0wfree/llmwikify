#!/usr/bin/env python3
"""Unit tests for P8: RunLogger + Checkpoint.

Coverage:
  - RunLogger: append events, start/llm_call/success/fail/skip
  - RunLogger.read_all: reads back events
  - Checkpoint: mark, is_done, is_complete, pending_stages
  - load_checkpoint: from disk, fresh, corrupted
  - save_checkpoint: round-trip
  - Integration: simulate paper run with multi-stage progress
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.runlog import (
    Checkpoint,
    RunEvent,
    RunLogger,
    STAGES,
    load_checkpoint,
    make_run_logger,
    save_checkpoint,
)


# ── RunLogger ────────────────────────────────────────────


class TestRunLogger:
    def test_log_writes_jsonl(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        rl.log("stage0", "start")
        rl.log("stage0", "success", latency_ms=100, detail={"chars": 5000})
        content = (tmp_path / "run_log.jsonl").read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 2
        ev0 = json.loads(lines[0])
        assert ev0["paper_id"] == "p1"
        assert ev0["stage"] == "stage0"
        assert ev0["event"] == "start"
        ev1 = json.loads(lines[1])
        assert ev1["event"] == "success"
        assert ev1["latency_ms"] == 100
        assert ev1["detail"] == {"chars": 5000}

    def test_convenience_methods(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        rl.start_stage("stage0")
        rl.llm_call("stage0", latency_ms=50, model="m2.7")
        rl.success("stage0", latency_ms=100, n_signals=10)
        rl.fail("stage1_call1", error="timeout", latency_ms=30000)
        rl.skip("track_a", reason="summary schema")
        events = rl.read_all()
        assert len(events) == 5
        assert [e["event"] for e in events] == [
            "start", "llm_call", "success", "fail", "skip",
        ]
        assert events[3]["error"] == "timeout"
        assert events[4]["detail"]["reason"] == "summary schema"

    def test_mkdir_creates_workdir(self, tmp_path):
        work = tmp_path / "subdir" / "paper1"
        rl = RunLogger(work, "paper1")
        rl.log("stage0", "start")
        assert (work / "run_log.jsonl").exists()

    def test_read_all_empty(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        assert rl.read_all() == []

    def test_read_all_skips_blank_lines(self, tmp_path):
        log_path = tmp_path / "run_log.jsonl"
        log_path.write_text(
            '{"timestamp":1,"paper_id":"p1","stage":"s","event":"e"}\n\n'
            '{"timestamp":2,"paper_id":"p1","stage":"s","event":"e"}\n',
            encoding="utf-8",
        )
        rl = RunLogger(tmp_path, "p1")
        events = rl.read_all()
        assert len(events) == 2

    def test_unicode_in_detail(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        rl.success("stage0", latency_ms=100, note="中文测试 αβγ")
        events = rl.read_all()
        assert events[0]["detail"]["note"] == "中文测试 αβγ"


# ── Checkpoint ──────────────────────────────────────────


class TestCheckpoint:
    def test_fresh_has_all_stages_false(self):
        cp = Checkpoint(paper_id="p1")
        assert cp.status == "pending"
        for s in STAGES:
            assert cp.is_done(s) is False
        assert cp.is_complete() is False

    def test_mark_and_check(self):
        cp = Checkpoint(paper_id="p1")
        cp.mark("stage0")
        assert cp.is_done("stage0")
        assert not cp.is_done("stage1_call1")
        assert cp.last_updated > 0

    def test_mark_all_completes(self):
        cp = Checkpoint(paper_id="p1")
        for s in STAGES:
            cp.mark(s)
        assert cp.is_complete()
        assert cp.pending_stages() == []

    def test_pending_stages(self):
        cp = Checkpoint(paper_id="p1")
        cp.mark("stage0")
        assert cp.pending_stages() == [
            "stage1_call1", "stage1_call2", "track_a",
            "track_b_pass1", "track_b_pass2",
        ]

    def test_mark_unknown_raises(self):
        cp = Checkpoint(paper_id="p1")
        with pytest.raises(ValueError, match="unknown stage"):
            cp.mark("nonsense")

    def test_to_dict_roundtrip(self):
        cp = Checkpoint(paper_id="p1")
        cp.mark("stage0")
        d = cp.to_dict()
        restored = Checkpoint(
            paper_id=d["paper_id"],
            status=d["status"],
            last_updated=d["last_updated"],
            stages=d["stages"],
        )
        assert restored.is_done("stage0")
        assert not restored.is_done("stage1_call1")


# ── I/O ────────────────────────────────────────────────


class TestCheckpointIO:
    def test_load_fresh(self, tmp_path):
        cp = load_checkpoint(tmp_path / "new_paper")
        assert cp.paper_id == "new_paper"
        assert cp.status == "pending"
        for s in STAGES:
            assert cp.is_done(s) is False

    def test_save_and_load(self, tmp_path):
        work = tmp_path / "paper1"
        work.mkdir()
        cp = Checkpoint(paper_id="paper1")
        cp.mark("stage0")
        cp.mark("stage1_call1")
        save_checkpoint(cp, work)
        cp2 = load_checkpoint(work)
        assert cp2.is_done("stage0")
        assert cp2.is_done("stage1_call1")
        assert not cp2.is_done("stage1_call2")
        assert cp2.last_updated > 0

    def test_load_corrupted_returns_fresh(self, tmp_path):
        work = tmp_path / "paper1"
        work.mkdir()
        (work / "checkpoint.json").write_text("{ corrupted", encoding="utf-8")
        cp = load_checkpoint(work)
        assert cp.paper_id == "paper1"
        for s in STAGES:
            assert cp.is_done(s) is False

    def test_load_backfills_missing_stages(self, tmp_path):
        """If checkpoint has fewer stages (older format), backfill new ones."""
        work = tmp_path / "paper1"
        work.mkdir()
        (work / "checkpoint.json").write_text(
            json.dumps({
                "paper_id": "paper1",
                "status": "running",
                "stages": {"stage0": True},  # only one stage
            }),
            encoding="utf-8",
        )
        cp = load_checkpoint(work)
        assert cp.is_done("stage0")
        assert "track_b_pass2" in cp.stages
        assert cp.is_done("track_b_pass2") is False

    def test_make_run_logger(self, tmp_path):
        work = tmp_path / "paper1"
        work.mkdir()
        rl = make_run_logger(work)
        assert rl.paper_id == "paper1"
        assert rl.work_dir == work
        rl.log("stage0", "start")
        assert (work / "run_log.jsonl").exists()


# ── Integration: full paper run ────────────────────────


class TestFullRun:
    def test_simulate_full_extraction(self, tmp_path):
        """Simulate running all stages and verify resume behavior."""
        work = tmp_path / "paper1"
        work.mkdir()
        rl = make_run_logger(work)
        cp = load_checkpoint(work)
        assert cp.is_complete() is False

        # Run stage0
        if not cp.is_done("stage0"):
            rl.start_stage("stage0")
            rl.llm_call("stage0", latency_ms=5000, chars=10000)
            rl.success("stage0", latency_ms=5000, chars=10000)
            cp.mark("stage0")
            save_checkpoint(cp, work)

        # Simulate crash: don't run remaining stages
        # New run: should pick up from stage1_call1
        cp2 = load_checkpoint(work)
        assert cp2.is_done("stage0")
        assert cp2.pending_stages() == [
            "stage1_call1", "stage1_call2", "track_a",
            "track_b_pass1", "track_b_pass2",
        ]

        # Run remaining stages (each: start + success = 2 events)
        for stage in cp2.pending_stages():
            rl.start_stage(stage)
            rl.success(stage, latency_ms=100)
            cp2.mark(stage)
            save_checkpoint(cp2, work)

        # Verify all done
        cp3 = load_checkpoint(work)
        assert cp3.is_complete()
        # 3 events for stage0 (start + llm_call + success)
        # 2 events per remaining stage (start + success) × 5 stages
        events = rl.read_all()
        assert len(events) == 3 + 5 * 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
