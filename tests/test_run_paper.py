"""Tests for PR7 scripts/run_paper.py generic entry point.

Covers:
  - PAPER_REGISTRY contains expected built-ins
  - get_paper_defaults() resolves built-in + auto-detect
  - build_signal_source() returns correct type per source_type
  - build_sinks() returns 3 sinks
  - build_recipe() creates valid PaperRecipe
  - run_smoke() returns 0 for working papers, 1 for missing
  - CLI: --help / --paper-id / --smoke / invalid paper_id
  - get_paper_defaults raises ValueError for unknown paper_id

Total: ~15 tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from llmwikify.reproduction.signal_source import (
    AcademicPdfSignalSource,
    TrackBPass2SignalSource,
    TrackBSignalSource,
)
from llmwikify.reproduction.sink import (
    BatchSummarySink,
    SingleJsonSink,
    YamlDuckdbSink,
)
from scripts.run_paper import (
    PAPER_REGISTRY,
    PaperDefaults,
    build_recipe,
    build_signal_source,
    build_sinks,
    get_paper_defaults,
    run_smoke,
)

# ─── Paper registry ────────────────────────────────────────────────────


class TestPaperRegistry:
    def test_contains_101_alphas(self) -> None:
        assert "101_alphas_minimal" in PAPER_REGISTRY
        d = PAPER_REGISTRY["101_alphas_minimal"]
        assert d.signal_source_type == "track_b"

    def test_contains_1601(self) -> None:
        assert "1601_00991v3" in PAPER_REGISTRY
        d = PAPER_REGISTRY["1601_00991v3"]
        assert d.signal_source_type == "academic_pdf"
        assert d.is_academic is True

    def test_101_paper_yaml_exists(self) -> None:
        yaml = Path("quant/papers/101_alphas_minimal/paper.yaml")
        assert yaml.exists()

    def test_1601_paper_yaml_exists(self) -> None:
        yaml = Path("quant/papers/1601_00991v3/paper.yaml")
        assert yaml.exists()

    def test_broker_paper_yaml_exists(self) -> None:
        yaml = Path(
            "quant/papers/20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论/paper.yaml"
        )
        assert yaml.exists()


# ─── get_paper_defaults ────────────────────────────────────────────────


class TestGetPaperDefaults:
    def test_builtin_101(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        assert isinstance(d, PaperDefaults)
        assert d.paper_id == "101_alphas_minimal"
        assert d.signal_source_type == "track_b"

    def test_builtin_1601(self) -> None:
        d = get_paper_defaults("1601_00991v3")
        assert d.signal_source_type == "academic_pdf"
        assert d.is_academic is True

    def test_auto_detect_broker(self) -> None:
        d = get_paper_defaults(
            "20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论"
        )
        assert d.signal_source_type == "track_b_pass2"
        assert d.signal_source_path.exists()

    def test_unknown_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Unknown paper_id"):
            get_paper_defaults("nonexistent_paper_xyz")


# ─── build_signal_source ──────────────────────────────────────────────


class TestBuildSignalSource:
    def test_track_b(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        src = build_signal_source(d)
        assert isinstance(src, TrackBSignalSource)

    def test_academic_pdf(self) -> None:
        d = get_paper_defaults("1601_00991v3")
        src = build_signal_source(d)
        assert isinstance(src, AcademicPdfSignalSource)

    def test_track_b_pass2(self) -> None:
        d = get_paper_defaults(
            "20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论"
        )
        src = build_signal_source(d)
        assert isinstance(src, TrackBPass2SignalSource)


# ─── build_sinks ───────────────────────────────────────────────────────


class TestBuildSinks:
    def test_returns_three_sinks(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        sinks = build_sinks(d)
        assert len(sinks) == 3
        assert isinstance(sinks[0], SingleJsonSink)
        assert isinstance(sinks[1], YamlDuckdbSink)
        assert isinstance(sinks[2], BatchSummarySink)


# ─── build_recipe ─────────────────────────────────────────────────────


class TestBuildRecipe:
    def test_recipe_construction(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        recipe = build_recipe(d, workers=2, no_delay=True)
        assert recipe.paper_id == "101_alphas_minimal"
        assert recipe.workers == 2  # workers=2 < 3, no cap
        assert recipe.delay == 0.0

    def test_recipe_workers_capped(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        recipe = build_recipe(d, workers=10)
        assert recipe.workers == 3  # capped to 3


# ─── run_smoke ─────────────────────────────────────────────────────────


class TestRunSmoke:
    def test_smoke_101_returns_zero(self) -> None:
        d = get_paper_defaults("101_alphas_minimal")
        assert run_smoke(d) == 0

    def test_smoke_1601_returns_zero(self) -> None:
        d = get_paper_defaults("1601_00991v3")
        assert run_smoke(d) == 0

    def test_smoke_招商_returns_zero(self) -> None:
        d = get_paper_defaults(
            "20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论"
        )
        assert run_smoke(d) == 0

    def test_smoke_missing_path_returns_one(self, tmp_path: Path) -> None:
        d = PaperDefaults(
            paper_id="missing",
            paper_dir=tmp_path,
            signal_source_type="track_b",
            signal_source_path=tmp_path / "nonexistent.json",
            output_dir=tmp_path / "out",
            factors_dir=tmp_path / "factors",
            strategy_dir="x",
            json_filename="x.json",
            md_filename="x.md",
        )
        assert run_smoke(d) == 1


# ─── CLI integration ──────────────────────────────────────────────────


class TestCLI:
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/run_paper.py", "--help"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
        )
        assert result.returncode == 0
        assert "paper-id" in result.stdout

    def test_no_args_exits_error(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/run_paper.py"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
        )
        assert result.returncode != 0
        assert "paper-id" in result.stderr or "recipe" in result.stderr

    def test_unknown_paper_exits_one(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/run_paper.py", "--paper-id", "nonexistent_xyz"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
        )
        assert result.returncode == 1
        assert "Unknown paper_id" in result.stderr

    def test_smoke_101_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/run_paper.py",
             "--paper-id", "101_alphas_minimal", "--smoke"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
        )
        assert result.returncode == 0
        # Logs go to stderr (setup_logging config), so check there
        assert "SMOKE TEST PASSED" in result.stderr
