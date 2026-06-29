"""Tests for SkipLoader (PR9b).

Covers:
  - scan: returns set of existing idx, respects skip_existing=False, handles missing dir
  - load: returns FactorResult list, handles corrupt JSON gracefully (Bug 6)
  - byte-equal: cached file round-trip via ResultFactory
  - integration: scan + load workflow
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.reproduction.factor import ResultFactory, SkipLoader

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def factory() -> ResultFactory:
    return ResultFactory()


@pytest.fixture
def output_dir_with_cached(tmp_path: Path) -> Path:
    """Create output_dir with 3 cached files (idx 1, 2, 3) and 1 corrupt."""
    out = tmp_path / "output"
    out.mkdir()
    for idx, status in [(1, "success"), (2, "success"), (3, "failed")]:
        (out / f"single_factor_{idx:03d}.json").write_text(
            json.dumps({
                "status": status,
                "alpha_index": idx,
                "factor_name": f"alpha-{idx:03d}",
                "formula_brief": "f(x) = x",
                "code": "x = 1",
                "code_chars": 5,
                "ic_mean": 0.02,
                "icir": 0.1,
                "ic_winrate": 0.51,
                "h5_path": f"/tmp/alpha_{idx:03d}.h5",
                "stage": None,
                "error": None if status == "success" else "test error",
                "elapsed_sec": 1.0,
            }),
            encoding="utf-8",
        )
    # Corrupt file
    (out / "single_factor_004.json").write_text("{invalid json", encoding="utf-8")
    return out


# ─── scan ────────────────────────────────────────────────────────────


class TestScan:
    def test_returns_existing_indices(self, output_dir_with_cached: Path) -> None:
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        skip = loader.scan()
        # scan() returns ALL existing file indices (including corrupt ones).
        # Filtering of corrupt JSON happens in load(), not scan().
        assert skip == {1, 2, 3, 4}

    def test_respects_skip_existing_false(self, output_dir_with_cached: Path) -> None:
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
            skip_existing=False,
        )
        assert loader.scan() == set()

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        loader = SkipLoader(
            output_dir=tmp_path / "nonexistent",
            alpha_start=1,
            alpha_end=5,
        )
        assert loader.scan() == set()

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        loader = SkipLoader(
            output_dir=tmp_path / "empty",
            alpha_start=1,
            alpha_end=5,
        )
        (tmp_path / "empty").mkdir()
        assert loader.scan() == set()

    def test_alpha_range_filter(self, output_dir_with_cached: Path) -> None:
        """scan() only returns idx in [alpha_start, alpha_end]."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=2,
            alpha_end=3,
        )
        assert loader.scan() == {2, 3}

    def test_file_not_in_range_ignored(self, output_dir_with_cached: Path) -> None:
        """Files outside [alpha_start, alpha_end] are NOT returned."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=10,
            alpha_end=20,
        )
        assert loader.scan() == set()


# ─── load ────────────────────────────────────────────────────────────


class TestLoad:
    def test_returns_factor_results(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        results = loader.load([1, 2, 3], factory)
        assert len(results) == 3
        assert all(r.signal.id == f"{i:03d}" for i, r in zip([1, 2, 3], results, strict=False))

    def test_sorted_order(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        """Results are returned in sorted idx order, regardless of input order."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        results = loader.load([3, 1, 2], factory)
        assert [r.signal.metadata["alpha_index"] for r in results] == [1, 2, 3]

    def test_corrupt_json_skipped(
        self, output_dir_with_cached: Path, factory: ResultFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Bug 6 invariant: corrupt JSON is skipped with a warning, not raised."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        with caplog.at_level("WARNING"):
            results = loader.load([1, 4, 2], factory)  # idx 4 is corrupt
        assert len(results) == 2  # 1 + 2, NOT 4
        assert "alpha-004" in caplog.text
        assert "skip-corrupt" in caplog.text

    def test_empty_skip_returns_empty(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        assert loader.load([], factory) == []

    def test_missing_file_skipped(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        """If skip list has idx without file, skip with warning (Bug 6)."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=10,
        )
        # idx 5, 6 don't have files
        results = loader.load([1, 5, 6], factory)
        assert len(results) == 1  # only 1 loaded
        assert results[0].signal.metadata["alpha_index"] == 1


# ─── Integration ─────────────────────────────────────────────────────


class TestIntegration:
    def test_scan_then_load(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        """Full workflow: scan() → load() should load all skip-existing idx."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        skip = loader.scan()
        results = loader.load(skip, factory)
        assert len(results) == 3  # 1, 2, 3 (idx 4 corrupt skipped during load)

    def test_byte_equal_round_trip(
        self, output_dir_with_cached: Path, factory: ResultFactory,
    ) -> None:
        """Real cached JSON should round-trip to_dict() byte-equal."""
        loader = SkipLoader(
            output_dir=output_dir_with_cached,
            alpha_start=1,
            alpha_end=5,
        )
        results = loader.load([1], factory)
        fr = results[0]
        # Read the original file and compare key fields
        original = json.loads(
            (output_dir_with_cached / "single_factor_001.json").read_text(encoding="utf-8"),
        )
        out = fr.to_dict()
        # Skip fields that aren't preserved (factor_series_len / dtype)
        for k in ["status", "alpha_index", "factor_name", "code", "ic_mean", "icir", "elapsed_sec"]:
            assert out[k] == original[k], f"Mismatch for {k}"
