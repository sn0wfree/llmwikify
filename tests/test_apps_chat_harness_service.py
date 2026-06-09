"""Tests for HarnessService (apps/chat/harness/service.py)."""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.harness.quality_gate import QualityGate
from llmwikify.apps.chat.harness.review import (
    ResearchReviewer,
    ResearchRevisor,
)
from llmwikify.apps.chat.harness.service import HarnessService
from llmwikify.apps.chat.harness.source_analyzer import SourceAnalyzer
from llmwikify.apps.chat.harness.source_filter import SourceFilter
from llmwikify.apps.chat.harness.structure_validator import (
    StructureValidator,
)


@pytest.fixture
def harness():
    return HarnessService(config={})


class TestHarnessServicePrimitives:
    def test_quality_gate(self, harness):
        assert isinstance(harness.quality_gate, QualityGate)

    def test_source_filter(self, harness):
        assert isinstance(harness.source_filter, SourceFilter)

    def test_structure_validator(self, harness):
        assert isinstance(harness.structure_validator, StructureValidator)

    def test_research_reviewer(self, harness):
        assert isinstance(harness.research_reviewer, ResearchReviewer)

    def test_research_revisor(self, harness):
        assert isinstance(harness.research_revisor, ResearchRevisor)

    def test_source_analyzer(self, harness):
        assert isinstance(harness.source_analyzer, SourceAnalyzer)


class TestHarnessServiceLazyInit:
    def test_quality_gate_cached(self, harness):
        qg1 = harness.quality_gate
        qg2 = harness.quality_gate
        assert qg1 is qg2

    def test_source_filter_cached(self, harness):
        sf1 = harness.source_filter
        sf2 = harness.source_filter
        assert sf1 is sf2

    def test_research_reviewer_uses_separate_llm(self, harness):
        harness.llm = "default-llm"
        harness.report_llm = "report-llm"
        rr = harness.research_reviewer
        rv = harness.research_revisor
        assert rr.llm_client == "default-llm"
        assert rv.llm_client == "report-llm"

    def test_research_revisor_falls_back_to_default_llm(self, harness):
        harness.llm = "default-llm"
        rv = harness.research_revisor
        assert rv.llm_client == "default-llm"


class TestHarnessServiceReset:
    def test_reset_clears_cache(self, harness):
        _ = harness.quality_gate
        assert harness._quality_gate is not None
        harness.reset()
        assert harness._quality_gate is None
