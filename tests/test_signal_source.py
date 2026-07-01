"""Tests for PR2 SignalSource implementations.

Covers:
  - TrackBSignalSource: 101 alphas pass1_signals (15 tests)
  - TrackBPass2SignalSource: broker reports (招商/浙商) (10 tests)
  - AcademicPdfSignalSource: academic papers (1601) (10 tests)
  - Signal dataclass basics (2 tests)

Total: ~37 tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.reproduction.signal_source import (
    AcademicPdfSignalSource,
    Signal,
    SignalSource,
    TrackBPass2SignalSource,
    TrackBSignalSource,
)

# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def track_b_path(tmp_path: Path) -> Path:
    """track_b_checkpoint.json with 3 pass1_signals."""
    data = {
        "paper_id": "test_paper",
        "pass1_signals": [
            {"index": 1, "name": "Alpha#1", "formula_brief": "rank(close, 5)", "description": "rank by close"},
            {"index": 2, "name": "Alpha#2", "formula_brief": "-1 * close", "description": "neg close"},
            {"index": 3, "name": "Alpha#3", "formula_brief": "delay(close, 1)", "description": ""},
        ],
        "pass2_done_names": [],
        "pass2_details": [],
    }
    p = tmp_path / "track_b_checkpoint.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


@pytest.fixture
def track_b_pass2_broker_path(tmp_path: Path) -> Path:
    """track_b_pass2.json for broker report (招商 style)."""
    data = {
        "paper_id": "test_broker_paper",
        "pass2_details": [
            {
                "name": "板块轮动周期表",
                "description": "基于信贷周期...",
                "l1": {
                    "definition": "基于信贷周期的股票板块轮动规律",
                    "formula": "Phase_State = f(credit_cycle)",
                },
                "success": True,
                "error": None,
            },
            {
                "name": "技术面择时信号",
                "description": "技术指标综合",
                "l1": {
                    "definition": "MACD+RSI 综合",
                    "formula": "signal = 0.6 * macd + 0.4 * rsi",
                },
                "success": True,
                "error": None,
            },
            {
                "name": "失败信号",  # should be skipped
                "description": "x",
                "l1": {},
                "success": False,
                "error": "LLM timeout",
            },
        ],
        "n_pass1": 3,
        "n_pass2_complete": 2,
        "n_pass2_failed": 1,
    }
    p = tmp_path / "track_b_pass2.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


@pytest.fixture
def track_b_pass2_academic_path(tmp_path: Path) -> Path:
    """track_b_pass2.json for academic paper (1601 style)."""
    data = {
        "paper_id": "1601_00991v3",
        "pass2_details": [
            {
                "name": "Alpha#1",
                "description": "test description 1",
                "l1": {"definition": "def 1", "formula": "(rank(A) - 0.5)"},
                "success": True,
            },
            {
                "name": "Alpha#46",
                "description": "test description 46",
                "l1": {"definition": "def 46", "formula": "delay(close, 20)"},
                "success": True,
            },
            {
                "name": "Alpha#101",
                "description": "test description 101",
                "l1": {"definition": "def 101", "formula": "ts_rank(volume, 10)"},
                "success": False,  # should be skipped
            },
        ],
    }
    p = tmp_path / "track_b_pass2.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


# ─── Signal dataclass ──────────────────────────────────────────────────


class TestSignalDataclass:
    def test_minimal_construction(self) -> None:
        s = Signal(id="x", name="X", formula_brief="f(x) = x")
        assert s.id == "x"
        assert s.name == "X"
        assert s.formula_brief == "f(x) = x"
        assert s.metadata == {}

    def test_metadata_default_factory(self) -> None:
        """metadata should not be shared across instances."""
        s1 = Signal(id="a", name="A", formula_brief="x")
        s2 = Signal(id="b", name="B", formula_brief="y")
        s1.metadata["k"] = "v"
        assert "k" not in s2.metadata


# ─── TrackBSignalSource (101 alphas) ───────────────────────────────────


class TestTrackBSignalSource:
    def test_paper_id_from_json(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        assert src.paper_id == "test_paper"

    def test_paper_id_from_dir_when_missing(self, tmp_path: Path) -> None:
        """When paper_id field absent in JSON, fallback to dir name."""
        data = {"pass1_signals": [{"index": 1, "name": "A", "formula_brief": "x"}]}
        p = tmp_path / "101_alphas_minimal" / "track_b_checkpoint.json"
        p.parent.mkdir()
        p.write_text(json.dumps(data))
        src = TrackBSignalSource(p)
        assert src.paper_id == "101_alphas_minimal"

    def test_iter_signals_count(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        signals = list(src.iter_signals())
        assert len(signals) == 3

    def test_iter_signals_id_format(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        signals = list(src.iter_signals())
        assert [s.id for s in signals] == ["alpha-001", "alpha-002", "alpha-003"]

    def test_iter_signals_name(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        signals = list(src.iter_signals())
        assert signals[0].name == "Alpha#1"

    def test_iter_signals_formula_brief(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        signals = list(src.iter_signals())
        assert signals[0].formula_brief == "rank(close, 5)"
        assert signals[2].formula_brief == "delay(close, 1)"

    def test_iter_signals_metadata(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path)
        signals = list(src.iter_signals())
        meta = signals[0].metadata
        assert meta["index"] == 1
        assert meta["source"] == "track_b_pass1"
        assert meta["paper_id"] == "test_paper"
        assert meta["description"] == "rank by close"

    def test_iter_signals_is_generator(self, track_b_path: Path) -> None:
        """iter_signals should return iterable (can be re-iterated)."""
        src = TrackBSignalSource(track_b_path)
        signals1 = list(src.iter_signals())
        signals2 = list(src.iter_signals())
        assert len(signals1) == len(signals2) == 3

    def test_empty_pass1_signals(self, tmp_path: Path) -> None:
        data = {"paper_id": "empty", "pass1_signals": []}
        p = tmp_path / "track_b_checkpoint.json"
        p.write_text(json.dumps(data))
        src = TrackBSignalSource(p)
        assert list(src.iter_signals()) == []

    def test_real_101_alphas_paper(self) -> None:
        """Smoke test: real 101_alphas_minimal produces 101 signals."""
        from pathlib import Path as _P
        real = _P("quant/papers/101_alphas_minimal/track_b_checkpoint.json")
        if not real.exists():
            pytest.skip("real 101_alphas paper not available")
        src = TrackBSignalSource(real)
        signals = list(src.iter_signals())
        assert len(signals) == 101
        assert signals[0].id == "alpha-001"
        assert signals[0].name == "Alpha#1"
        assert signals[100].id == "alpha-101"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        src = TrackBSignalSource(tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError, match="track_b_checkpoint.json not found"):
            _ = src.paper_id

    def test_explicit_paper_id_overrides(self, track_b_path: Path) -> None:
        src = TrackBSignalSource(track_b_path, paper_id="override")
        assert src.paper_id == "override"


# ─── TrackBPass2SignalSource (broker reports) ──────────────────────────


class TestTrackBPass2SignalSource:
    def test_paper_id_from_json(self, track_b_pass2_broker_path: Path) -> None:
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        assert src.paper_id == "test_broker_paper"

    def test_iter_signals_count(self, track_b_pass2_broker_path: Path) -> None:
        """Failed signals are skipped → 2 of 3."""
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        assert len(signals) == 2

    def test_iter_signals_id_format(self, track_b_pass2_broker_path: Path) -> None:
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        assert [s.id for s in signals] == ["signal-001", "signal-002"]

    def test_iter_signals_chinese_name(self, track_b_pass2_broker_path: Path) -> None:
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        assert signals[0].name == "板块轮动周期表"

    def test_iter_signals_formula_from_l1(self, track_b_pass2_broker_path: Path) -> None:
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        assert signals[0].formula_brief == "Phase_State = f(credit_cycle)"
        assert signals[1].formula_brief == "signal = 0.6 * macd + 0.4 * rsi"

    def test_iter_signals_metadata(self, track_b_pass2_broker_path: Path) -> None:
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        meta = signals[0].metadata
        assert meta["index"] == 1
        assert meta["source"] == "track_b_pass2"
        assert meta["definition"] == "基于信贷周期的股票板块轮动规律"
        assert meta["l1"]["formula"] == "Phase_State = f(credit_cycle)"

    def test_iter_signals_skips_failed(self, track_b_pass2_broker_path: Path) -> None:
        """The failed signal (idx 3) should NOT be in the output."""
        src = TrackBPass2SignalSource(track_b_pass2_broker_path)
        signals = list(src.iter_signals())
        assert "失败信号" not in [s.name for s in signals]

    def test_empty_pass2_details(self, tmp_path: Path) -> None:
        data = {"paper_id": "empty", "pass2_details": []}
        p = tmp_path / "track_b_pass2.json"
        p.write_text(json.dumps(data))
        src = TrackBPass2SignalSource(p)
        assert list(src.iter_signals()) == []

    def test_missing_l1_defaults_to_empty_formula(self, tmp_path: Path) -> None:
        """If l1 is null, formula_brief should be empty string (not crash)."""
        data = {
            "paper_id": "x",
            "pass2_details": [
                {"name": "no_l1", "description": "", "l1": None, "success": True},
            ],
        }
        p = tmp_path / "track_b_pass2.json"
        p.write_text(json.dumps(data))
        src = TrackBPass2SignalSource(p)
        signals = list(src.iter_signals())
        assert len(signals) == 1
        assert signals[0].formula_brief == ""

    def test_real_broker_paper(self) -> None:
        """Smoke test: real 招商证券 paper produces signals."""
        from pathlib import Path as _P
        real = _P("quant/papers/20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论/track_b_pass2.json")
        if not real.exists():
            pytest.skip("real 招商证券 paper not available")
        src = TrackBPass2SignalSource(real)
        signals = list(src.iter_signals())
        assert len(signals) >= 5
        assert all(s.id.startswith("signal-") for s in signals)
        # Real data may have empty l1.formula for some signals (idx 2, 8 in 招商)
        # — just verify formula_brief is a string, not necessarily non-empty.
        assert all(isinstance(s.formula_brief, str) for s in signals)


# ─── AcademicPdfSignalSource (1601) ─────────────────────────────────────


class TestAcademicPdfSignalSource:
    def test_paper_id_from_json(self, track_b_pass2_academic_path: Path) -> None:
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        assert src.paper_id == "1601_00991v3"

    def test_iter_signals_count(self, track_b_pass2_academic_path: Path) -> None:
        """Failed signals are skipped → 2 of 3."""
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert len(signals) == 2

    def test_iter_signals_id_has_paper_prefix(self, track_b_pass2_academic_path: Path) -> None:
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert signals[0].id == "1601_00991v3_alpha-001"
        assert signals[1].id == "1601_00991v3_alpha-002"

    def test_iter_signals_preserves_name(self, track_b_pass2_academic_path: Path) -> None:
        """Name preserves 'Alpha#N' original convention."""
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert signals[0].name == "Alpha#1"
        assert signals[1].name == "Alpha#46"

    def test_iter_signals_formula_from_l1(self, track_b_pass2_academic_path: Path) -> None:
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert signals[1].formula_brief == "delay(close, 20)"

    def test_iter_signals_alpha_index_parsed(self, track_b_pass2_academic_path: Path) -> None:
        """metadata.alpha_index should parse from 'Alpha#N'."""
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert signals[0].metadata["alpha_index"] == 1
        assert signals[1].metadata["alpha_index"] == 46

    def test_iter_signals_alpha_index_none_for_non_alpha(self, tmp_path: Path) -> None:
        """Name without 'Alpha#N' pattern → alpha_index = None."""
        data = {
            "paper_id": "p",
            "pass2_details": [
                {"name": "板块轮动", "l1": {"formula": "x"}, "success": True},
            ],
        }
        p = tmp_path / "track_b_pass2.json"
        p.write_text(json.dumps(data, ensure_ascii=False))
        src = AcademicPdfSignalSource(p)
        signals = list(src.iter_signals())
        assert signals[0].metadata["alpha_index"] is None

    def test_iter_signals_metadata_source(self, track_b_pass2_academic_path: Path) -> None:
        src = AcademicPdfSignalSource(track_b_pass2_academic_path)
        signals = list(src.iter_signals())
        assert signals[0].metadata["source"] == "academic_pdf_pass2"

    def test_real_academic_paper(self) -> None:
        """Smoke test: real 1601_00991v3 paper."""
        from pathlib import Path as _P
        real = _P("quant/papers/1601_00991v3/track_b_pass2.json")
        if not real.exists():
            pytest.skip("real 1601 paper not available")
        src = AcademicPdfSignalSource(real)
        signals = list(src.iter_signals())
        assert len(signals) >= 50
        assert all(s.id.startswith("1601_00991v3_alpha-") for s in signals)
        assert all(s.formula_brief for s in signals)

    def test_explicit_paper_id_overrides(self, track_b_pass2_academic_path: Path) -> None:
        src = AcademicPdfSignalSource(
            track_b_pass2_academic_path, paper_id="custom_paper",
        )
        signals = list(src.iter_signals())
        assert signals[0].id == "custom_paper_alpha-001"
