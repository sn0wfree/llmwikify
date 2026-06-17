#!/usr/bin/env python3
"""Unit + integration tests for Track B Pass 1 batching changes.

Coverage:
  - _build_batch_spec: round 0, continuation, small remaining
  - _parse_signals_from_response: dict, list, empty, bad JSON, no-name skip
  - _run_pass1: batching (101), single call (<=10), low-confidence fallback, dedup
  - Integration: real parsed.md + plan.json → 11 batches → 101 signals
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.llm_extraction.planner import PlanResult
from llmwikify.reproduction.llm_extraction.track_b import (
    BATCH_MAX_TOKENS,
    BATCH_SIZE,
    _build_batch_spec,
    _parse_signals_from_response,
    _run_pass1,
)

# ── Mock LLM clients ────────────────────────────────────────


class BatchFakeLLM:
    """Returns sequential items (10 per batch, then remainder)."""

    def __init__(self, total: int = 101, batch_size: int = BATCH_SIZE):
        self.calls: list[tuple] = []
        self.total = total
        self.batch_size = batch_size

    def chat(self, messages: list, **kwargs) -> str:
        batch_idx = len(self.calls)
        start = batch_idx * self.batch_size + 1
        count = max(0, min(self.batch_size, self.total - start + 1))
        if count <= 0:
            return json.dumps({"signals": [], "n_signals": 0})
        items = [
            {"name": f"Alpha#{i}", "formula": f"rank(x_{i})"}
            for i in range(start, start + count)
        ]
        self.calls.append((messages, kwargs))
        return json.dumps({"signals": items, "n_signals": len(items)})


class SingleFakeLLM:
    """Returns all items in one call."""

    def __init__(self, count: int = 5):
        self.count = count
        self.calls = 0

    def chat(self, messages: list, **kwargs) -> str:
        self.calls += 1
        items = [
            {"name": f"Signal#{i}", "formula": f"expr_{i}"}
            for i in range(1, self.count + 1)
        ]
        return json.dumps({"signals": items, "n_signals": len(items)})


class DedupFakeLLM:
    """First round 10 items, second round 10 items with 1 overlap."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages: list, **kwargs) -> str:
        self.calls += 1
        if self.calls == 1:
            items = [
                {"name": f"Alpha#{i}", "formula": str(i)}
                for i in range(1, 11)
            ]
        elif self.calls == 2:
            items = [
                {"name": "Alpha#10", "formula": "10"},  # duplicate
                *[{"name": f"Alpha#{i}", "formula": str(i)}
                  for i in range(11, 20)],
            ]
        else:
            items = []
        return json.dumps({"signals": items, "n_signals": len(items)})


# ── _build_batch_spec ────────────────────────────────────────


class TestBuildBatchSpec:
    def test_first_batch(self):
        spec = _build_batch_spec(0, BATCH_SIZE, set(), 101)
        assert "first 10" in spec
        assert "101 total" in spec
        assert "strict JSON" in spec

    def test_continuation_batch(self):
        seen = {f"Alpha#{i}" for i in range(11, 21)}
        spec = _build_batch_spec(2, BATCH_SIZE, seen, 101)
        assert "Already captured" in spec
        assert "Alpha#" in spec
        assert "DO NOT output these again" in spec
        assert "strict JSON" in spec

    def test_last_batch_small_remaining(self):
        seen = {f"Alpha#{i}" for i in range(1, 101)}
        spec = _build_batch_spec(10, BATCH_SIZE, seen, 101)
        # at most 1 remaining (or 0 if total already reached)
        assert "at most 1" in spec or "at most 0" in spec

    def test_small_paper_first_batch(self):
        spec = _build_batch_spec(0, BATCH_SIZE, set(), 5)
        assert "first 5" in spec
        assert "5 total" in spec


# ── _parse_signals_from_response ──────────────────────────────


class TestParseSignals:
    def test_dict_with_signals(self):
        resp = json.dumps({
            "signals": [
                {"name": "Alpha#1", "formula": "rank(x)"},
            ],
        })
        stubs = _parse_signals_from_response(resp)
        assert len(stubs) == 1
        assert stubs[0].name == "Alpha#1"

    def test_direct_list(self):
        resp = json.dumps([
            {"name": "S1", "formula": "a+b"},
            {"name": "S2", "formula": "c-d"},
        ])
        stubs = _parse_signals_from_response(resp)
        assert len(stubs) == 2
        assert stubs[1].formula_brief == "c-d"

    def test_empty_list(self):
        stubs = _parse_signals_from_response('{"signals":[]}')
        assert stubs == []

    def test_no_json(self):
        stubs = _parse_signals_from_response("this is not JSON")
        assert stubs == []

    def test_missing_name_skipped(self):
        resp = json.dumps({
            "signals": [
                {"formula": "orphan"},
                {"name": "Good", "formula": "ok"},
            ],
        })
        stubs = _parse_signals_from_response(resp)
        assert len(stubs) == 1
        assert stubs[0].name == "Good"


# ── _run_pass1 ───────────────────────────────────────────────


class TestRunPass1:
    def test_batching_101_alphas(self):
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=101,
            confidence=0.95,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )
        client = BatchFakeLLM(total=101)
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 11, f"expected 11 calls, got {n_calls}"
        assert len(stubs) == 101, f"expected 101 stubs, got {len(stubs)}"
        assert stubs[0].name == "Alpha#1"
        assert stubs[-1].name == "Alpha#101"
        assert stubs[-1].index == 101

    def test_small_paper_single_call(self):
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=5,
            confidence=0.95,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )
        client = SingleFakeLLM(count=5)
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 1
        assert len(stubs) == 5

    def test_low_confidence_fallback(self):
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=101,
            confidence=0.5,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )
        client = SingleFakeLLM(count=3)
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 1
        assert len(stubs) == 3

    def test_dedup_keeps_unique(self):
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=11,  # > BATCH_SIZE to trigger batching
            confidence=0.95,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )
        client = DedupFakeLLM()
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        # DedupFakeLLM: call1=10 (1-10), call2=10 (Alpha#10 dup, 11-19)
        # After 2 rounds, len(new)=9 < 10 → break; 19 unique total
        assert n_calls == 2
        assert len(stubs) == 19
        assert stubs[0].name == "Alpha#1"
        assert stubs[-1].name == "Alpha#19"
        assert stubs[-1].index == 19

    def test_empty_response_does_not_crash(self):
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=101,
            confidence=0.95,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )

        class EmptyLLM:
            def chat(self, messages, **kwargs):
                return '{"signals":[],"n_signals":0}'

        client = EmptyLLM()
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls >= 1
        assert len(stubs) == 0


# ── Integration: real parsed.md + plan.json ───────────────────

PILOT_DIR = Path(__file__).parent.parent.parent / "quant" / "papers" / "1601_00991v3"


@pytest.mark.skipif(not PILOT_DIR.exists(), reason="101 Alphas pilot data not found")
class TestIntegration101Alphas:
    """Uses real parsed.md + plan.json from 101 Alphas pilot."""

    @pytest.fixture
    def plan(self):
        with open(PILOT_DIR / "plan.json") as f:
            data = json.load(f)
        p = data["stage1_call2_plan"]
        return PlanResult(
            paper_id=data["paper_id"],
            schema_choice=p.get("schema_choice", "summary"),
            n_signals_estimate=p.get("n_signals_estimate", 0),
            confidence=p.get("confidence", 0.0),
            token_budget=p.get("token_budget", {}),
            success=p.get("success", True),
        )

    @pytest.fixture
    def parsed_text(self):
        return (PILOT_DIR / "parsed.md").read_text(encoding="utf-8")

    def test_batching_returns_101_signals(self, plan, parsed_text):
        """With a perfect LLM (sequential), 11 batches → 101 signals."""
        client = BatchFakeLLM(total=101)
        stubs, latency, n_calls = _run_pass1(
            client, plan, plan.paper_id, parsed_text,
        )
        assert n_calls == 11
        assert len(stubs) == 101
        assert stubs[-1].name == "Alpha#101"
        assert stubs[-1].index == 101

    def test_batching_latency_includes_all_batches(self, plan, parsed_text):
        """latency_ms should accumulate across all batches."""
        class SlowFakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, **kwargs):
                import time
                self.calls += 1
                time.sleep(0.01)
                start = (self.calls - 1) * BATCH_SIZE + 1
                count = min(BATCH_SIZE, 101 - start + 1)
                items = [
                    {"name": f"Alpha#{i}", "formula": f"f({i})"}
                    for i in range(start, start + count)
                ]
                return json.dumps({"signals": items, "n_signals": len(items)})

        client = SlowFakeLLM()
        stubs, latency, n_calls = _run_pass1(
            client, plan, plan.paper_id, parsed_text,
        )
        assert n_calls == 11
        assert latency >= 100  # at least 10ms × 11 = 110ms
        assert len(stubs) == 101

    def test_single_call_path_for_small_estimate(self):
        """Even with real parsed.md, if n_signals_estimate <= SIZE, use single call."""
        small_plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=3,
            confidence=0.95,
            token_budget={"track_b_pass1": 12000},
            success=True,
        )
        client = SingleFakeLLM(count=3)
        stubs, latency, n_calls = _run_pass1(
            client, small_plan, "test", "dummy text",
        )
        assert n_calls == 1
        assert len(stubs) == 3


# ── Run directly ──────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
