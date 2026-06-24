"""Tests for track_b checkpoint functions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    SignalDetail,
    SignalStub,
    _delete_checkpoint,
    _load_checkpoint,
    _save_checkpoint,
)


def _make_stub(name, index=1, formula="f(x)"):
    return SignalStub(index=index, name=name, formula_brief=formula)


def _make_detail(name, success=True, has_l1=True):
    if success and has_l1:
        return SignalDetail(
            name=name,
            description=f"desc of {name}",
            l1={"definition": "def", "formula": "f(x)"},
            l2={"calculation_steps": []},
            l3={"financial_intuition": "intuition"},
            l4={"hypotheses": []},
            success=True,
            latency_ms=100,
        )
    return SignalDetail(
        name=name,
        success=success,
        error="json_parse_failed" if not success else None,
    )


class TestSaveCheckpoint:
    def test_creates_file(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [_make_stub("A#1")], [])
        assert (tmp_path / "track_b_checkpoint.json").exists()

    def test_json_valid(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [_make_stub("A#1")], [])
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert isinstance(data, dict)

    def test_contains_pass1(self, tmp_path):
        stubs = [_make_stub("A#1"), _make_stub("A#2")]
        _save_checkpoint(tmp_path, "test", stubs, [])
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert len(data["pass1_signals"]) == 2

    def test_contains_pass2(self, tmp_path):
        details = [_make_detail("A#1"), _make_detail("A#2")]
        _save_checkpoint(tmp_path, "test", [_make_stub("A#1")], details)
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert len(data["pass2_details"]) == 2

    def test_has_updated_at(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [], [])
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert "updated_at" in data
        assert isinstance(data["updated_at"], float)

    def test_overwrites(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [_make_stub("A#1")], [])
        _save_checkpoint(tmp_path, "test", [_make_stub("A#1"), _make_stub("A#2")], [])
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert len(data["pass1_signals"]) == 2


class TestLoadCheckpoint:
    def test_returns_none_if_missing(self, tmp_path):
        result = _load_checkpoint(tmp_path)
        assert result is None

    def test_loads_stubs_and_details(self, tmp_path):
        stubs = [_make_stub("A#1"), _make_stub("A#2")]
        details = [_make_detail("A#1")]
        _save_checkpoint(tmp_path, "test", stubs, details)
        result = _load_checkpoint(tmp_path)
        assert result is not None
        loaded_stubs, loaded_details = result
        assert len(loaded_stubs) == 2
        assert len(loaded_details) == 1

    def test_roundtrip_stub_fields(self, tmp_path):
        stub = _make_stub("A#42", index=42, formula="rank(x)")
        _save_checkpoint(tmp_path, "test", [stub], [])
        result = _load_checkpoint(tmp_path)
        loaded_stub = result[0][0]
        assert loaded_stub.name == "A#42"
        assert loaded_stub.index == 42
        assert loaded_stub.formula_brief == "rank(x)"

    def test_roundtrip_detail_fields(self, tmp_path):
        detail = _make_detail("A#1")
        _save_checkpoint(tmp_path, "test", [], [detail])
        result = _load_checkpoint(tmp_path)
        loaded_detail = result[1][0]
        assert loaded_detail.name == "A#1"
        assert loaded_detail.success is True
        assert loaded_detail.l1 == {"definition": "def", "formula": "f(x)"}

    def test_corrupted_file_returns_none(self, tmp_path):
        cp_path = tmp_path / "track_b_checkpoint.json"
        cp_path.write_text("not valid json {{{")
        result = _load_checkpoint(tmp_path)
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        cp_path = tmp_path / "track_b_checkpoint.json"
        cp_path.write_text("")
        result = _load_checkpoint(tmp_path)
        assert result is None


class TestDeleteCheckpoint:
    def test_deletes_file(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [], [])
        assert (tmp_path / "track_b_checkpoint.json").exists()
        _delete_checkpoint(tmp_path)
        assert not (tmp_path / "track_b_checkpoint.json").exists()

    def test_no_error_if_missing(self, tmp_path):
        # Should not raise
        _delete_checkpoint(tmp_path)

    def test_only_deletes_checkpoint(self, tmp_path):
        _save_checkpoint(tmp_path, "test", [], [])
        (tmp_path / "other.txt").write_text("keep")
        _delete_checkpoint(tmp_path)
        assert not (tmp_path / "track_b_checkpoint.json").exists()
        assert (tmp_path / "other.txt").exists()


class TestCheckpointInterval:
    def test_checkpoint_file_grows(self, tmp_path):
        for i in range(1, 25):
            details = [_make_detail(f"A#{j}") for j in range(1, i + 1)]
            _save_checkpoint(tmp_path, "test", [_make_stub(f"A#{j}") for j in range(1, i + 1)], details)
        data = json.loads((tmp_path / "track_b_checkpoint.json").read_text())
        assert len(data["pass2_details"]) == 24
