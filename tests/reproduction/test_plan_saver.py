"""Tests for plan_saver.save_plan."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwikify.reproduction.llm_extraction.plan_saver import save_plan


def _make_stage0(**overrides):
    defaults = dict(
        paper_id="test_001",
        title="Test Paper",
        source_type="pdf",
        char_count=12345,
        content_hash="abc123",
        source_path=Path("/raw/test.pdf"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_sections(**overrides):
    defaults = dict(
        paper_id="test_001",
        sections=[],
        n_sections=0,
        latency_ms=100,
        success=True,
        error=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_plan(**overrides):
    defaults = dict(
        paper_id="test_001",
        schema_choice="factor",
        paper_type="quant",
        n_signals_estimate=50,
        extraction_strategy="track_b",
        token_budget={"track_b_pass1": 4096},
        confidence=0.9,
        latency_ms=200,
        success=True,
        error=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestSavePlanBasic:
    def test_creates_plan_json(self, tmp_path):
        path = save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        assert path.exists()
        assert path.name == "plan.json"

    def test_returns_path(self, tmp_path):
        path = save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        assert isinstance(path, Path)

    def test_creates_work_dir_if_missing(self, tmp_path):
        work_dir = tmp_path / "new" / "dir"
        path = save_plan(_make_stage0(), None, _make_plan(), work_dir)
        assert path.exists()
        assert work_dir.exists()


class TestSavePlanStructure:
    def test_top_level_keys(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        assert "paper_id" in data
        assert "title" in data
        assert "source_type" in data
        assert "char_count" in data
        assert "content_hash" in data
        assert "source_path" in data
        assert "stage1_call1_sections" in data
        assert "stage1_call2_plan" in data

    def test_stage0_fields(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        assert data["paper_id"] == "test_001"
        assert data["title"] == "Test Paper"
        assert data["source_type"] == "pdf"
        assert data["char_count"] == 12345
        assert data["content_hash"] == "abc123"

    def test_sections_none_fallback(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        sec = data["stage1_call1_sections"]
        assert sec["success"] is False
        assert sec["n_sections"] == 0
        assert sec["error"] == "no_call"
        assert sec["sections"] == []

    def test_sections_present(self, tmp_path):
        sections = _make_sections(n_sections=5, success=True)
        save_plan(_make_stage0(), sections, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        sec = data["stage1_call1_sections"]
        assert sec["success"] is True
        assert sec["n_sections"] == 5

    def test_plan_fields(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        p = data["stage1_call2_plan"]
        assert p["schema_choice"] == "factor"
        assert p["n_signals_estimate"] == 50
        assert p["confidence"] == 0.9
        assert p["token_budget"] == {"track_b_pass1": 4096}


class TestSavePlanEdgeCases:
    def test_empty_sections_list(self, tmp_path):
        sections = _make_sections(sections=[], n_sections=0)
        save_plan(_make_stage0(), sections, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        assert data["stage1_call1_sections"]["sections"] == []

    def test_plan_error_state(self, tmp_path):
        plan = _make_plan(success=False, error="llm_timeout", confidence=0.0)
        save_plan(_make_stage0(), None, plan, tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        p = data["stage1_call2_plan"]
        assert p["success"] is False
        assert p["error"] == "llm_timeout"
        assert p["confidence"] == 0.0

    def test_json_is_valid(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        content = (tmp_path / "plan.json").read_text()
        data = json.loads(content)  # Should not raise
        assert isinstance(data, dict)

    def test_unicode_in_title(self, tmp_path):
        stage0 = _make_stage0(title="量化因子研究报告")
        save_plan(stage0, None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        assert data["title"] == "量化因子研究报告"

    def test_overwrites_existing(self, tmp_path):
        save_plan(_make_stage0(), None, _make_plan(), tmp_path)
        save_plan(_make_stage0(title="Updated"), None, _make_plan(), tmp_path)
        data = json.loads((tmp_path / "plan.json").read_text())
        assert data["title"] == "Updated"
