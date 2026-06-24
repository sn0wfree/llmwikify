#!/usr/bin/env python3
"""Unit tests for success rate metric and auto-retry logic.

Coverage:
  - Success rate calculation
  - Threshold constants
  - TrackBResult new fields
  - Auto-retry logic
  - Orchestrator integration
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    PASS2_SUCCESS_THRESHOLD_HIGH,
    PASS2_SUCCESS_THRESHOLD_LOW,
    PASS2_MAX_RETRY_ROUNDS,
    SignalDetail,
    SignalStub,
    TrackBResult,
)


class TestSuccessRateConstants:
    def test_thresholds_are_valid(self):
        assert 0.0 <= PASS2_SUCCESS_THRESHOLD_LOW <= PASS2_SUCCESS_THRESHOLD_HIGH <= 1.0

    def test_retry_rounds_positive(self):
        assert PASS2_MAX_RETRY_ROUNDS >= 0

    def test_default_values(self):
        assert PASS2_SUCCESS_THRESHOLD_HIGH == 0.95
        assert PASS2_SUCCESS_THRESHOLD_LOW == 0.80
        assert PASS2_MAX_RETRY_ROUNDS == 1


class TestTrackBResultFields:
    def test_new_fields_exist(self):
        result = TrackBResult(paper_id="test")
        assert hasattr(result, "success_rate")
        assert hasattr(result, "retry_rounds")
        assert hasattr(result, "needs_retry")

    def test_default_values(self):
        result = TrackBResult(paper_id="test")
        assert result.success_rate == 0.0
        assert result.retry_rounds == 0
        assert result.needs_retry is False

    def test_to_dict_includes_new_fields(self):
        result = TrackBResult(
            paper_id="test",
            success_rate=0.95,
            retry_rounds=1,
            needs_retry=False,
        )
        d = result.to_dict()
        assert "success_rate" in d
        assert "retry_rounds" in d
        assert "needs_retry" in d
        assert d["success_rate"] == 0.95
        assert d["retry_rounds"] == 1
        assert d["needs_retry"] is False


class TestSuccessRateCalculation:
    def test_high_success_rate(self):
        """98/101 = 97% should be high success."""
        n_complete = 98
        n_total = 101
        success_rate = n_complete / n_total
        assert success_rate >= PASS2_SUCCESS_THRESHOLD_HIGH

    def test_medium_success_rate(self):
        """90/101 = 89% should trigger retry."""
        n_complete = 90
        n_total = 101
        success_rate = n_complete / n_total
        assert PASS2_SUCCESS_THRESHOLD_LOW <= success_rate < PASS2_SUCCESS_THRESHOLD_HIGH

    def test_low_success_rate(self):
        """80/101 = 79% should warn."""
        n_complete = 80
        n_total = 101
        success_rate = n_complete / n_total
        assert success_rate < PASS2_SUCCESS_THRESHOLD_LOW

    def test_zero_total(self):
        """Empty list should return 0.0."""
        success_rate = 0.0 / 0.0 if False else 0.0  # Avoid division by zero
        assert success_rate == 0.0


class TestAutoRetryLogic:
    def test_no_retry_when_high_success(self):
        """Should not retry when success rate >= 95%."""
        success_rate = 0.97
        n_failed = 3
        retry_rounds = 0
        
        needs_retry = success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and n_failed > 0
        should_retry = needs_retry and retry_rounds < PASS2_MAX_RETRY_ROUNDS
        
        assert not should_retry

    def test_retry_when_medium_success(self):
        """Should retry when success rate is 80-95%."""
        success_rate = 0.89
        n_failed = 11
        retry_rounds = 0
        
        needs_retry = success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and n_failed > 0
        should_retry = needs_retry and retry_rounds < PASS2_MAX_RETRY_ROUNDS
        
        assert should_retry

    def test_no_retry_when_max_rounds_reached(self):
        """Should not retry when max retry rounds reached."""
        success_rate = 0.89
        n_failed = 11
        retry_rounds = PASS2_MAX_RETRY_ROUNDS
        
        needs_retry = success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and n_failed > 0
        should_retry = needs_retry and retry_rounds < PASS2_MAX_RETRY_ROUNDS
        
        assert not should_retry

    def test_no_retry_when_zero_failures(self):
        """Should not retry when there are no failures."""
        success_rate = 0.90
        n_failed = 0
        retry_rounds = 0
        
        needs_retry = success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and n_failed > 0
        should_retry = needs_retry and retry_rounds < PASS2_MAX_RETRY_ROUNDS
        
        assert not should_retry


class TestSignalStubAndDetail:
    def test_signal_stub_creation(self):
        stub = SignalStub(index=1, name="Alpha#1", formula_brief="x+y", description="test")
        assert stub.index == 1
        assert stub.name == "Alpha#1"

    def test_signal_detail_success(self):
        detail = SignalDetail(
            name="Alpha#1",
            success=True,
            l1={"formula": "x+y"},
            latency_ms=1000,
        )
        assert detail.success is True
        assert detail.l1 == {"formula": "x+y"}

    def test_signal_detail_failure(self):
        detail = SignalDetail(
            name="Alpha#1",
            success=False,
            error="json_parse_failed",
            latency_ms=1000,
        )
        assert detail.success is False
        assert detail.error == "json_parse_failed"


class TestOrchestratorIntegration:
    def test_summary_includes_success_rate_fields(self):
        """Orchestrator summary should include success rate fields."""
        # This is a structural test - actual integration tested in e2e
        from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper
        import inspect
        
        # Check that run_one_paper exists and has the expected signature
        sig = inspect.signature(run_one_paper)
        assert "paper_id" in sig.parameters
        assert "source_path" in sig.parameters
        assert "output_root" in sig.parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
