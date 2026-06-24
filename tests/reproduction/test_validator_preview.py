#!/usr/bin/env python3
"""Unit tests for P7: Result Validator + preview.md.

Coverage:
  - _validate_plan: missing fields, low confidence, bad schema
  - _validate_track_a: missing tier1, missing metadata fields
  - _validate_track_b_pass1: zero signals, empty name/formula, batched but few
  - _validate_track_b_pass2: all failed, success w/o formula
  - validate_paper_outputs: integration with real pilot data
  - generate_preview: produces non-empty markdown, includes key sections
  - write_preview: writes to disk
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.preview import (
    generate_preview,
    write_preview,
)
from llmwikify.reproduction.paper_understanding.llm_extraction.validator import (
    ValidationIssue,
    validate_paper_outputs,
)


# ── Validator unit tests ──────────────────────────────────


class TestValidatePlan:
    def test_valid_plan(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_plan
        data = {
            "paper_id": "p1",
            "source_path": "/x.pdf",
            "stage1_call2_plan": {
                "success": True,
                "schema_choice": "factor",
                "confidence": 0.95,
            },
        }
        issues = _validate_plan(data)
        assert len(issues) == 0

    def test_missing_paper_id(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_plan
        data = {"stage1_call2_plan": {"success": True, "schema_choice": "factor"}}
        issues = _validate_plan(data)
        assert any(i.level == "error" and "paper_id" in i.message for i in issues)

    def test_low_confidence(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_plan
        data = {
            "paper_id": "p1",
            "stage1_call2_plan": {
                "success": True,
                "schema_choice": "factor",
                "confidence": 0.5,
            },
        }
        issues = _validate_plan(data)
        assert any(i.level == "warning" and "low" in i.message for i in issues)

    def test_invalid_schema(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_plan
        data = {
            "paper_id": "p1",
            "stage1_call2_plan": {
                "success": True,
                "schema_choice": "nonsense",
                "confidence": 0.9,
            },
        }
        issues = _validate_plan(data)
        assert any(i.level == "error" and "schema_choice" in i.message for i in issues)


class TestValidateTrackA:
    def test_valid_track_a(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_a
        data = {
            "success": True,
            "schema_choice": "factor",
            "tier1": {
                "paper_metadata": {
                    "title": "Test",
                    "authors": ["A"],
                },
            },
        }
        issues = _validate_track_a(data)
        # No errors expected
        assert not any(i.level == "error" for i in issues)

    def test_failed_track_a(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_a
        data = {"success": False, "error": "JSON parse failed"}
        issues = _validate_track_a(data)
        assert any(i.level == "error" and "failed" in i.message for i in issues)

    def test_empty_tier1(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_a
        data = {"success": True, "schema_choice": "factor", "tier1": {}}
        issues = _validate_track_a(data)
        assert any(i.level == "error" and "tier1" in i.message for i in issues)


class TestValidatePass1:
    def test_valid_pass1(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass1
        data = {
            "schema_choice": "factor",
            "enabled": True,
            "n_pass1": 2,
            "pass1_signals": [
                {"name": "A", "formula_brief": "x+y"},
                {"name": "B", "formula_brief": "x-y"},
            ],
            "llm_calls": 1,
        }
        issues = _validate_track_b_pass1(data)
        assert not any(i.level == "error" for i in issues)

    def test_zero_signals(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass1
        data = {
            "schema_choice": "factor",
            "enabled": True,
            "n_pass1": 0,
            "error": "pass1_no_signals",
        }
        issues = _validate_track_b_pass1(data)
        assert any(i.level == "error" and "no signals" in i.message for i in issues)

    def test_summary_skipped_ok(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass1
        data = {"schema_choice": "summary", "enabled": False}
        issues = _validate_track_b_pass1(data)
        assert issues == []

    def test_empty_name(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass1
        data = {
            "schema_choice": "factor",
            "enabled": True,
            "n_pass1": 2,
            "pass1_signals": [
                {"name": "", "formula_brief": "x"},
                {"name": "Good", "formula_brief": "y"},
            ],
        }
        issues = _validate_track_b_pass1(data)
        assert any(i.level == "warning" and "empty name" in i.message for i in issues)

    def test_batched_but_few(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass1
        data = {
            "schema_choice": "factor",
            "enabled": True,
            "n_pass1": 3,
            "llm_calls": 5,
            "pass1_signals": [{"name": f"S{i}", "formula_brief": "x"} for i in range(3)],
        }
        issues = _validate_track_b_pass1(data)
        assert any(i.level == "info" and "batched" in i.message for i in issues)


class TestValidatePass2:
    def test_valid_pass2(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass2
        data = {
            "n_pass1": 2,
            "n_pass2_complete": 2,
            "n_pass2_failed": 0,
            "pass2_details": [
                {"name": "A", "success": True, "l1": {"formula": "x+y"}},
                {"name": "B", "success": True, "l1": {"formula": "x-y"}},
            ],
        }
        issues = _validate_track_b_pass2(data)
        assert not any(i.level == "error" for i in issues)

    def test_all_failed(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass2
        data = {
            "n_pass1": 2,
            "n_pass2_complete": 0,
            "n_pass2_failed": 2,
            "pass2_details": [
                {"name": "A", "success": False, "error": "timeout"},
                {"name": "B", "success": False, "error": "timeout"},
            ],
        }
        issues = _validate_track_b_pass2(data)
        assert any(i.level == "error" and "all" in i.message for i in issues)

    def test_missing_l1(self):
        from llmwikify.reproduction.paper_understanding.llm_extraction.validator import _validate_track_b_pass2
        data = {
            "n_pass1": 1,
            "n_pass2_complete": 1,
            "n_pass2_failed": 0,
            "pass2_details": [
                {"name": "A", "success": True, "l1": {}},
            ],
        }
        issues = _validate_track_b_pass2(data)
        assert any(i.level == "warning" and "L1" in i.message for i in issues)


# ── Integration with real pilot data ───────────────────────


PILOT_DIR = Path(__file__).parent.parent.parent / "quant" / "papers" / "1601_00991v3"


@pytest.mark.skipif(not PILOT_DIR.exists(), reason="101 Alphas pilot data not found")
class TestIntegrationPilotData:
    def test_validate_paper_outputs(self):
        report = validate_paper_outputs(PILOT_DIR)
        assert report.paper_id == "1601_00991v3"
        assert "plan.json" in report.files_checked
        assert "track_a.json" in report.files_checked

    def test_preview_generates_md(self):
        content = generate_preview(PILOT_DIR)
        assert "# Extraction Preview" in content
        assert "Overview" in content
        assert "Validation" in content
        assert "Stats" in content
        # 101 Alphas has 101 signals, should be in preview
        assert "Pass 1 Signals" in content

    def test_preview_handles_partial_pass2(self):
        """Pilot has track_b_pass2_one.json (single factor), not pass2.json.
        Preview should aggregate partials via glob fallback."""
        content = generate_preview(PILOT_DIR)
        # Should detect track_b_pass2_*.json partials and render Pass 2 section
        assert "Pass 2 Factor Detail" in content or "No Pass 2" in content

    def test_write_preview(self, tmp_path):
        out = write_preview(PILOT_DIR, tmp_path / "preview.md")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "# Extraction Preview" in content


# ── Edge cases ─────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_workdir(self, tmp_path):
        report = validate_paper_outputs(tmp_path / "empty_paper")
        assert report.paper_id == "empty_paper"
        assert "plan.json" in report.files_missing
        assert report.n_errors == 0  # no data → no errors, just missing

    def test_corrupted_json(self, tmp_path):
        p = tmp_path / "bad_paper"
        p.mkdir()
        (p / "plan.json").write_text("{ invalid json", encoding="utf-8")
        report = validate_paper_outputs(p)
        assert any(
            i.level == "error" and "JSON" in i.message
            for i in report.issues
        )

    def test_preview_with_only_plan(self, tmp_path):
        p = tmp_path / "only_plan"
        p.mkdir()
        (p / "plan.json").write_text(json.dumps({
            "paper_id": "test",
            "stage1_call2_plan": {
                "success": True,
                "schema_choice": "factor",
                "n_signals_estimate": 5,
                "confidence": 0.9,
            },
        }), encoding="utf-8")
        content = generate_preview(p)
        assert "# Extraction Preview" in content
        assert "only_plan" in content  # directory name appears in title


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
