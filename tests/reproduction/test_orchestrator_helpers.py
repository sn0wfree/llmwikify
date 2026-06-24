"""Tests for orchestrator helper functions: _slugify, _write_factor_yamls."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import (
    _slugify,
    _write_factor_yamls,
)


class TestSlugify:
    def test_alpha_1(self):
        assert _slugify("Alpha#1") == "alpha-001"

    def test_alpha_42(self):
        assert _slugify("Alpha#42") == "alpha-042"

    def test_alpha_101(self):
        assert _slugify("Alpha#101") == "alpha-101"

    def test_alpha_999(self):
        assert _slugify("Alpha#999") == "alpha-999"

    def test_no_number(self):
        result = _slugify("Momentum")
        assert result == "momentum"

    def test_mixed(self):
        result = _slugify("Signal_42_test")
        assert "42" in result

    def test_empty(self):
        result = _slugify("")
        assert isinstance(result, str)


def _make_detail(name, success=True, has_l1=True):
    """Create a mock SignalDetail-like object."""
    if success and has_l1:
        return SimpleNamespace(
            success=True,
            name=name,
            description=f"Description of {name}",
            l1={"definition": "def", "formula": "f(x)"},
            l2={"calculation_steps": []},
            l3={"financial_intuition": "intuition"},
            l4={"hypotheses": []},
        )
    else:
        return SimpleNamespace(
            success=success,
            name=name,
            description="",
            l1={},
            l2={},
            l3={},
            l4={},
        )


def _make_stub(name, formula="f(x)"):
    """Create a mock SignalStub-like object."""
    return SimpleNamespace(name=name, formula_brief=formula)


class TestWriteFactorYamls:
    def test_creates_factors_dir(self, tmp_path):
        n = _write_factor_yamls(
            tmp_path, "test_paper",
            [_make_detail("Alpha#1")],
            [_make_stub("Alpha#1")],
        )
        assert (tmp_path / "factors").exists()

    def test_writes_yaml_file(self, tmp_path):
        _write_factor_yamls(
            tmp_path, "test_paper",
            [_make_detail("Alpha#1")],
            [_make_stub("Alpha#1")],
        )
        assert (tmp_path / "factors" / "alpha-001.yaml").exists()

    def test_yaml_is_valid(self, tmp_path):
        _write_factor_yamls(
            tmp_path, "test_paper",
            [_make_detail("Alpha#1")],
            [_make_stub("Alpha#1")],
        )
        data = yaml.safe_load(
            (tmp_path / "factors" / "alpha-001.yaml").read_text()
        )
        assert "factor" in data
        assert data["factor"]["name"] == "alpha-001"

    def test_returns_correct_count(self, tmp_path):
        details = [_make_detail(f"Alpha#{i}") for i in range(1, 6)]
        stubs = [_make_stub(f"Alpha#{i}") for i in range(1, 6)]
        n = _write_factor_yamls(tmp_path, "test", details, stubs)
        assert n == 5

    def test_skips_failed_details(self, tmp_path):
        details = [
            _make_detail("Alpha#1"),
            _make_detail("Alpha#2", success=False),
            _make_detail("Alpha#3"),
        ]
        stubs = [_make_stub(f"Alpha#{i}") for i in range(1, 4)]
        n = _write_factor_yamls(tmp_path, "test", details, stubs)
        assert n == 2
        assert not (tmp_path / "factors" / "alpha-002.yaml").exists()

    def test_skips_empty_l1(self, tmp_path):
        details = [
            _make_detail("Alpha#1"),
            _make_detail("Alpha#2", has_l1=False),
        ]
        stubs = [_make_stub("Alpha#1"), _make_stub("Alpha#2")]
        n = _write_factor_yamls(tmp_path, "test", details, stubs)
        assert n == 1

    def test_yaml_has_l1_l4_layers(self, tmp_path):
        _write_factor_yamls(
            tmp_path, "test_paper",
            [_make_detail("Alpha#1")],
            [_make_stub("Alpha#1")],
        )
        data = yaml.safe_load(
            (tmp_path / "factors" / "alpha-001.yaml").read_text()
        )
        f = data["factor"]
        assert "l1" in f
        assert "l2" in f
        assert "l3" in f
        assert "l4" in f

    def test_yaml_metadata_fields(self, tmp_path):
        _write_factor_yamls(
            tmp_path, "test_paper",
            [_make_detail("Alpha#1")],
            [_make_stub("Alpha#1")],
        )
        data = yaml.safe_load(
            (tmp_path / "factors" / "alpha-001.yaml").read_text()
        )
        f = data["factor"]
        assert f["source_paper"] == "test_paper"
        assert f["status"] == "draft"
        assert f["asset_type"] == "stock"
        assert f["category"] == "alpha"

    def test_empty_details(self, tmp_path):
        n = _write_factor_yamls(tmp_path, "test", [], [])
        assert n == 0
        # Directory is created but empty
        assert (tmp_path / "factors").exists()
        assert list((tmp_path / "factors").glob("*.yaml")) == []

    def test_multiple_files(self, tmp_path):
        details = [_make_detail(f"Alpha#{i}") for i in range(1, 11)]
        stubs = [_make_stub(f"Alpha#{i}") for i in range(1, 11)]
        n = _write_factor_yamls(tmp_path, "test", details, stubs)
        assert n == 10
        files = list((tmp_path / "factors").glob("*.yaml"))
        assert len(files) == 10
