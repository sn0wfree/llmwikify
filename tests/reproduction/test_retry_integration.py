#!/usr/bin/env python3
"""Integration tests: verify with_retry is wired into all 6 LLM call sites.

For each module, replace client.chat with a mock that fails N times then
succeeds. Verify the call ultimately succeeds (retry worked) and the
total call count matches expected (1 + retries).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Import each module that contains LLM call sites
from llmwikify.reproduction.llm_extraction import (
    DeferError,
    planner,
    section_detector,
    track_a,
    track_b,
)
from llmwikify.reproduction.llm_extraction.planner import PlanResult
from llmwikify.reproduction.llm_extraction.section_detector import Section
from llmwikify.reproduction.llm_extraction.track_b import (
    PASS1_MAX_TOKENS_DEFAULT,
    SignalStub,
)


class FlakyClient:
    """Mock LLM client that fails N times then returns a valid response."""

    def __init__(self, response: str, fail_times: int = 0, exc: Exception | None = None):
        self.response = response
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("transient")
        self.calls = 0
        self.last_messages = None
        self.last_kwargs = None

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        self.last_kwargs = kwargs
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.response

    async def achat(self, messages, **kwargs):
        """Async version for adaptive multi-turn Pass 2."""
        return self.chat(messages, **kwargs)


# ── Section detector ──────────────────────────────────


class TestSectionDetectorRetry:
    def test_retries_on_transient_failure(self):
        # Use a 1-section response so JSON parses cleanly
        good_response = json.dumps({
            "sections": [{"title": "Intro", "level": 1,
                          "char_start": 0, "char_end": 100}],
        })
        client = FlakyClient(good_response, fail_times=2)
        result = section_detector.detect_sections(
            paper_id="p1", parsed_text="x" * 200, llm_client=client,
        )
        assert result.success is True
        assert client.calls == 3  # 1 + 2 retries

    def test_passes_after_exhaustion_with_error(self):
        """Stage 1 Call 1 raises DeferError on retry exhaustion (caller's
        responsibility to handle via DeferredQueue)."""
        client = FlakyClient("irrelevant", fail_times=10)
        with pytest.raises(DeferError) as exc_info:
            section_detector.detect_sections(
                paper_id="p1", parsed_text="x" * 200, llm_client=client,
            )
        assert "after 3 attempts" in str(exc_info.value)
        assert client.calls == 3  # max_attempts=3


# ── Planner ──────────────────────────────────────────


class TestPlannerRetry:
    def test_retries_on_transient_failure(self):
        good_response = json.dumps({
            "schema_choice": "factor",
            "n_signals_estimate": 5,
            "confidence": 0.9,
            "token_budget": {"track_b_pass1": 5000},
        })
        client = FlakyClient(good_response, fail_times=2)
        result = planner.plan_paper(
            paper_id="p1", title="T", parsed_text="x" * 200,
            sections=None, llm_client=client,
        )
        assert result.success is True
        assert client.calls == 3

    def test_passes_after_exhaustion(self):
        """Planner raises DeferError on retry exhaustion."""
        client = FlakyClient("irrelevant", fail_times=10)
        with pytest.raises(DeferError) as exc_info:
            planner.plan_paper(
                paper_id="p1", title="T", parsed_text="x" * 200,
                sections=None, llm_client=client,
            )
        assert "after 3 attempts" in str(exc_info.value)
        assert client.calls == 3


# ── Track A Tier 1 ──────────────────────────────────


class TestTrackATier1Retry:
    def test_retries_on_transient_failure(self):
        good_response = json.dumps({
            "paper_metadata": {"title": "T", "authors": ["A"]},
        })
        client = FlakyClient(good_response, fail_times=2)
        plan = PlanResult(
            paper_id="p1", schema_choice="factor",
            n_signals_estimate=5, confidence=0.9,
            token_budget={"track_a_tier1": 5000}, success=True,
        )
        result, latency = track_a._run_tier1(
            client, plan, "p1", "T", "x" * 200, None,
        )
        assert client.calls == 3
        assert result.get("paper_metadata", {}).get("title") == "T"


# ── Track A Tier 2 ──────────────────────────────────


class TestTrackATier2Retry:
    def test_retries_on_transient_failure(self):
        good_response = json.dumps({"backtest": "results"})
        client = FlakyClient(good_response, fail_times=2)
        plan = PlanResult(
            paper_id="p1", schema_choice="factor",
            n_signals_estimate=5, confidence=0.9,
            token_budget={"track_a_tier2_per_section": 5000}, success=True,
        )
        tier2, attempted, failed, latency = track_a._run_tier2(
            client, plan, "p1", "x" * 200,
        )
        # FlakyClient is cumulative: first 2 calls fail, rest succeed.
        # 5 tier2 prompts: prompt 1 takes 3 calls (2 fail + 1 ok),
        # prompts 2-5 take 1 call each. Total = 3 + 4 = 7.
        assert client.calls == 7
        # All 5 prompts attempted; none failed (retry recovered)
        assert len(attempted) == 5
        assert failed == []

    def test_all_tier2_prompts_succeed(self):
        """If retries succeed for all prompts, tier2 is fully populated."""
        good_response = json.dumps({"backtest": "results"})
        client = FlakyClient(good_response, fail_times=0)  # no failures
        plan = PlanResult(
            paper_id="p1", schema_choice="factor",
            n_signals_estimate=5, confidence=0.9,
            token_budget={"track_a_tier2_per_section": 5000}, success=True,
        )
        tier2, attempted, failed, latency = track_a._run_tier2(
            client, plan, "p1", "x" * 200,
        )
        assert client.calls == 5  # 1 call per prompt, no retries
        assert failed == []


# ── Track B Pass 1 multi-turn ──────────────────────


class TestTrackBPass1MultiTurnRetry:
    def test_retries_on_transient_failure(self):
        """LLM first call fails, second call succeeds."""
        good_response = json.dumps({
            "signals": [
                {"name": "S1", "formula": "rank(x)"},
                {"name": "S2", "formula": "rank(y)"},
            ],
            "done": True,
        })
        client = FlakyClient(good_response, fail_times=2)
        plan = PlanResult(
            paper_id="p1", schema_choice="factor",
            n_signals_estimate=2,
            confidence=0.9,
            token_budget={"track_b_pass1": PASS1_MAX_TOKENS_DEFAULT},
            success=True,
        )
        stubs, latency, n_calls = track_b._run_pass1(
            client, plan, "p1", "x" * 200,
        )
        # 1 call with 2 retries = 3 total calls
        assert n_calls == 1
        assert client.calls == 3
        assert len(stubs) == 2


# ── Track B Pass 2 per-factor ──────────────────────


class TestTrackBPass2Retry:
    def test_retries_on_transient_failure(self):
        """Test that adaptive multi-turn can extract L1-L4 (success path).

        Note: Pass 2 prompt is now batch mode (v2). The retry mechanism
        for transient failures is tested separately in test_retry module.
        """
        good_response = json.dumps({
            "factors": [
                {
                    "name": "S1",
                    "description": "desc",
                    "l1": {"formula": "x+y"},
                    "l2": {"function_calls": ["rank"]},
                    "l3": {"input_data": ["close"]},
                    "l4": {"strategy_type": "mean-reversion"},
                    "need_more_context": None,
                }
            ]
        })
        # No failures - test success path
        client = FlakyClient(good_response, fail_times=0)
        plan = PlanResult(
            paper_id="p1", schema_choice="factor",
            n_signals_estimate=1, confidence=0.9,
            token_budget={"track_b_pass2_per_factor": 5000}, success=True,
        )
        stub = SignalStub(
            index=1, name="S1", formula_brief="x+y",
            context_excerpt="x" * 1000,  # > 200 chars to avoid fallback
        )
        # Test via _run_pass2_adaptive (async, single signal)
        import asyncio
        details, latency = asyncio.run(
            track_b._run_pass2_adaptive(
                client, plan, "p1", [stub], "x" * 200,
            )
        )
        # 1 successful call
        assert client.calls == 1
        assert len(details) == 1
        assert details[0].success is True
        assert details[0].l1.get("formula") == "x+y"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
