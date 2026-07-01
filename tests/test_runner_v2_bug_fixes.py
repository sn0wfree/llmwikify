"""Tests for P3 bug fixes (Bug 9 + Bug 5 + Bug 6 regression).

Covers:
  - MetaStage._find_available: scandir-based (Bug 9)
    - empty dir → []
    - partial dir → correct indices
    - missing dir → [] (FileNotFoundError handled)
    - ignores subdirectories
    - ignores non-matching files
  - FactorRunner._fail_result: synthetic result has all fields (Bug 5)
  - FactorStage SkipLoader integration: corrupt JSON skipped (Bug 6)
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_101_alphas_v2 import (
    FactorRunner,
    MetaStage,
    RunConfig,
)


class _StubRunner(FactorRunner):
    """Concrete stub for instantiating FactorRunner.run (abstract)."""

    def run(self):  # type: ignore[override]
        return None


def _make_meta(tmp_path: Path, alpha_start: int = 1, alpha_end: int = 5) -> MetaStage:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = RunConfig(
        track_b_path=tmp_path / "track_b.json",
        output_dir=output_dir,
        alpha_start=alpha_start,
        alpha_end=alpha_end,
    )
    return MetaStage(config)


class TestFindAvailable:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        meta = _make_meta(tmp_path)
        assert meta._find_available() == []

    def test_partial_dir_returns_correct_indices(self, tmp_path: Path) -> None:
        """Bug 9 fix: scandir should find exact matches in expected range."""
        meta = _make_meta(tmp_path, alpha_start=1, alpha_end=10)
        # Write only 1, 3, 5 (out of 10 expected)
        for idx in (1, 3, 5):
            (tmp_path / "output" / f"single_factor_{idx:03d}.json").write_text("{}")
        result = meta._find_available()
        assert result == [1, 3, 5]

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        """Output dir doesn't exist → [] instead of crash."""
        config = RunConfig(
            track_b_path=tmp_path / "track_b.json",
            output_dir=tmp_path / "nonexistent",  # doesn't exist
            alpha_start=1,
            alpha_end=5,
        )
        meta = MetaStage(config)
        assert meta._find_available() == []

    def test_ignores_subdirectories(self, tmp_path: Path) -> None:
        """Subdirectories named like single_factor_NNN.json should be ignored."""
        meta = _make_meta(tmp_path, alpha_start=1, alpha_end=5)
        # Create a subdir with matching name
        (tmp_path / "output" / "single_factor_001.json").mkdir()  # directory, not file
        (tmp_path / "output" / "single_factor_002.json").write_text("{}")  # file
        result = meta._find_available()
        assert result == [2]  # subdir not counted

    def test_ignores_non_matching_files(self, tmp_path: Path) -> None:
        meta = _make_meta(tmp_path, alpha_start=1, alpha_end=5)
        (tmp_path / "output" / "single_factor_001.json").write_text("{}")
        (tmp_path / "output" / "other_file.txt").write_text("x")
        (tmp_path / "output" / "single_factor_001.json.bak").write_text("{}")  # different ext
        (tmp_path / "output" / "random_alpha_001.json").write_text("{}")
        result = meta._find_available()
        assert result == [1]

    def test_full_range(self, tmp_path: Path) -> None:
        meta = _make_meta(tmp_path, alpha_start=1, alpha_end=10)
        for idx in range(1, 11):
            (tmp_path / "output" / f"single_factor_{idx:03d}.json").write_text("{}")
        result = meta._find_available()
        assert result == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


# ─── Bug 5 regression (synthetic result full fields) ────────────────


class TestFailResultBug5:
    def test_synthetic_result_has_all_fields(self) -> None:
        """Bug 5: synthetic result from _handle_parallel_failure must include
        all result fields (code_chars=0, ic_*=None) for downstream JSON/MD.
        """
        config = RunConfig(track_b_path=Path("/tmp/track_b.json"))
        runner = _StubRunner(config)
        result = runner._fail_result(
            alpha_index=99, stage="TimeoutError", error="future boom", t0=0.0,
        )
        assert result["status"] == "failed"
        assert result["alpha_index"] == 99
        assert result["stage"] == "TimeoutError"
        assert result["error"] == "future boom"
        assert result["code"] is None
        assert result["code_chars"] == 0  # ← Bug 5 fix
        assert result["ic_mean"] is None
        assert result["icir"] is None
        assert result["ic_winrate"] is None
        assert "elapsed_sec" in result


# ─── Bug 6 regression (corrupt JSON skipped) ────────────────────────


class TestLoadSkippedResultsBug6:
    def test_corrupt_json_skipped_not_crashed(self, tmp_path: Path, caplog) -> None:
        """Bug 6: corrupt JSON in single_factor_NNN.json should be skipped."""
        import logging
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        config = RunConfig(
            track_b_path=tmp_path / "track_b.json",
            output_dir=output_dir,
            alpha_start=1,
            alpha_end=3,
            no_delay=True,
        )
        from scripts.run_101_alphas_v2 import FactorStage
        stage = FactorStage(config)

        (output_dir / "single_factor_001.json").write_text(
            json.dumps({"status": "success", "alpha_index": 1, "ic_mean": 0.01})
        )
        (output_dir / "single_factor_002.json").write_text(
            "{{{ not json"
        )

        caplog.set_level(logging.WARNING, logger="llmwikify.reproduction.factor.skip_loader")
        from llmwikify.reproduction.factor import SkipLoader
        loader = SkipLoader(
            output_dir=output_dir,
            alpha_start=1,
            alpha_end=3,
        )
        results = loader.load([1, 2], stage._factory)
        stage.results.extend(results)

        # Only valid appended (L2: FactorResult, idx in signal.metadata)
        assert len(stage.results) == 1
        assert stage.results[0].signal.metadata["alpha_index"] == 1
        # Warning for corrupt
        assert any("skip-corrupt" in r.message or "002" in r.message
                   for r in caplog.records)
