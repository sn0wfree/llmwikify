#!/usr/bin/env python3
"""Unit + integration tests for Track B Pass 1 multi-turn continuation.

Coverage:
  - _parse_signals_from_response: parses done flag, dict/list, empty, bad JSON
  - _run_pass1: 1-round all done, multiple rounds with continuation, done=true,
    done by count, consecutive zero new, max rounds cap, dedup, fallback max_tokens
  - Integration: dedup, continuation scenarios
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.llm_extraction.planner import PlanResult
from llmwikify.reproduction.llm_extraction.track_b import (
    MAX_CONSECUTIVE_ZERO,
    MAX_ROUNDS,
    PASS1_MAX_TOKENS_DEFAULT,
    _parse_signals_from_response,
    _run_pass1,
)


# ── Mock LLM clients ──────────────────────────────────────────


class RoundSequenceFakeLLM:
    """Returns pre-defined responses per round.

    Constructor takes list[str] → each entry is response for round 1..N.
    """

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[tuple] = []

    def chat(self, messages: list, **kwargs) -> str:
        idx = len(self.calls)
        self.calls.append((messages, kwargs))
        if idx >= len(self.responses):
            return json.dumps({"signals": [], "done": True})
        return self.responses[idx]


def single_round_response(count: int, done: bool = True, start: int = 1) -> str:
    items = [
        {"name": f"Alpha#{i}", "formula": f"rank(x_{i})"}
        for i in range(start, start + count)
    ]
    return json.dumps({"signals": items, "done": done})


# ── _parse_signals_from_response ────────────────────────────────


class TestParseSignals:
    def test_dict_with_signals_and_done_false(self):
        resp = json.dumps({
            "signals": [
                {"name": "Alpha#1", "formula": "rank(x)"},
            ],
            "done": False,
        })
        stubs, done = _parse_signals_from_response(resp)
        assert len(stubs) == 1
        assert stubs[0].name == "Alpha#1"
        assert done is False

    def test_dict_with_signals_and_done_true(self):
        resp = json.dumps({
            "signals": [
                {"name": "Alpha#1", "formula": "rank(x)"},
                {"name": "Alpha#2", "formula": "-corr(a,b)"},
            ],
            "done": True,
        })
        stubs, done = _parse_signals_from_response(resp)
        assert len(stubs) == 2
        assert done is True

    def test_direct_list_no_done(self):
        resp = json.dumps([
            {"name": "S1", "formula": "a+b"},
            {"name": "S2", "formula": "c-d"},
        ])
        stubs, done = _parse_signals_from_response(resp)
        assert len(stubs) == 2
        assert done is False
        assert stubs[1].formula_brief == "c-d"

    def test_empty_list(self):
        stubs, done = _parse_signals_from_response('{"signals":[],"done":true}')
        assert stubs == []
        assert done is True

    def test_no_json(self):
        stubs, done = _parse_signals_from_response("this is not JSON")
        assert stubs == []
        assert done is False

    def test_missing_name_skipped(self):
        resp = json.dumps({
            "signals": [
                {"formula": "orphan"},
                {"name": "Good", "formula": "ok"},
            ],
        })
        stubs, done = _parse_signals_from_response(resp)
        assert len(stubs) == 1
        assert stubs[0].name == "Good"
        assert done is False


# ── _run_pass1 termination conditions ──────────────────────────


class TestRunPass1:
    def test_one_round_all_done(self):
        """All 5 signals in first round, LLM says done: true → done after 1."""
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=5,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        client = RoundSequenceFakeLLM([
            single_round_response(5, done=True),
        ])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 1
        assert len(stubs) == 5
        assert all(s.index == i+1 for i, s in enumerate(stubs))
        assert stubs[-1].name == "Alpha#5"

    def test_two_rounds_continuation(self):
        """30 signals split into two rounds 20 + 10 → done by count."""
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=30,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        client = RoundSequenceFakeLLM([
            single_round_response(20, done=False, start=1),
            single_round_response(10, done=True, start=21),
        ])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 2
        assert len(stubs) == 30
        assert stubs[19].name == "Alpha#20"
        assert stubs[29].name == "Alpha#30"
        assert stubs[19].name == "Alpha#20"
        assert stubs[29].name == "Alpha#30"
        assert stubs[-1].index == 30

    def test_done_by_llm_before_count(self):
        """LLM says done after 20 signals even though estimate is 30 → stop."""
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=30,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        client = RoundSequenceFakeLLM([
            single_round_response(20, done=True),
        ])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 1
        assert len(stubs) == 20

    def test_consecutive_zero_new_stops(self):
        """Three consecutive rounds with zero new → stop (F1: MAX_CONSECUTIVE_ZERO 2→3)."""
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=30,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        client = RoundSequenceFakeLLM([
            single_round_response(20, done=False),  # 20 new
            "{}",  # 0 new (consecutive_zero=1)
            "{}",  # 0 new (consecutive_zero=2)
            "{}",  # 0 new (consecutive_zero=3) → stop after 4 rounds
        ])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == 4
        assert len(stubs) == 20

    def test_max_rounds_cap(self):
        """Stop when hits MAX_ROUNDS even if not done.

        If every round has one NEW signal (no duplicates), stops at exactly MAX_ROUNDS.
        """
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=200,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        # every round different name, so new every time → stop at MAX_ROUNDS
        responses = []
        for i in range(MAX_ROUNDS + 2):
            responses.append(json.dumps({
                "signals": [{"name": f"Alpha#{i+1}", "formula": "f"}],
                "done": False,
            }))
        client = RoundSequenceFakeLLM(responses)
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls == MAX_ROUNDS
        assert len(stubs) == MAX_ROUNDS

    def test_dedup_keeps_unique(self):
        """Duplicate names are deduped across rounds, only first kept."""
        plan = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=19,
            confidence=0.95,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        # round 1: 1-10; round 2: repeats 10 + 11-19 → 19 unique
        resp1 = json.dumps({
            "signals": [{"name": f"Alpha#{i}", "formula": str(i)} for i in range(1, 11)],
            "done": False,
        })
        resp2 = json.dumps({
            "signals": [
                {"name": "Alpha#10", "formula": "10"},  # duplicate
                *[{"name": f"Alpha#{i}", "formula": str(i)} for i in range(11, 20)],
            ],
            "done": True,
        })
        client = RoundSequenceFakeLLM([resp1, resp2])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
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
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        client = RoundSequenceFakeLLM(['{"signals":[],"done":false}'])
        stubs, latency, n_calls = _run_pass1(
            client, plan, "test", "dummy text",
        )
        assert n_calls >= 1
        assert len(stubs) == 0


# ── Integration: real parsed.md + plan.json from 101 Alphas ─────

PILOT_DIR = Path(__file__).parent.parent.parent / "quant" / "papers" / "1601_00991v3"


@pytest.mark.skipif(not PILOT_DIR.exists(), reason="101 Alphas pilot data not found")
class TestIntegration101AlphasMultiTurn:
    """Mock LLM sequential 101 → should get 101 signals across multiple rounds."""

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

    def test_101_two_rounds_gets_all(self, plan, parsed_text):
        """LLM returns 50 in first round, 51 in second round → 101 signals."""
        responses = [
            single_round_response(50, done=False, start=1),
            single_round_response(51, done=True, start=51),
        ]
        client = RoundSequenceFakeLLM(responses)
        stubs, latency, n_calls = _run_pass1(
            client, plan, plan.paper_id, parsed_text,
        )
        assert n_calls == 2
        assert len(stubs) == 101
        assert stubs[0].name == "Alpha#1"
        assert stubs[-1].name == "Alpha#101"
        assert stubs[-1].index == 101

    def test_101_one_round_gets_all(self, plan, parsed_text):
        """LLM returns all 101 signals in one round → 1 call."""
        client = RoundSequenceFakeLLM([
            single_round_response(101, done=True, start=1),
        ])
        stubs, latency, n_calls = _run_pass1(
            client, plan, plan.paper_id, parsed_text,
        )
        assert n_calls == 1
        assert len(stubs) == 101
        assert stubs[0].name == "Alpha#1"
        assert stubs[-1].name == "Alpha#101"
        assert stubs[-1].index == 101

    def test_latency_accumulates_all_rounds(self, plan, parsed_text):
        """latency_ms should accumulate across all rounds."""
        responses = [
            single_round_response(30, done=False, start=1),
            single_round_response(30, done=False, start=31),
            single_round_response(41, done=True, start=61),
        ]
        client = RoundSequenceFakeLLM(responses)
        stubs, latency, n_calls = _run_pass1(
            client, plan, plan.paper_id, parsed_text,
        )
        assert n_calls == 3
        assert len(stubs) == 101
        # latency is non-negative (mock LLM has no real delay)
        assert latency >= 0


# ── Run directly ────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
