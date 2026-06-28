"""Tests for BatchSerializer (P1 refactor).

Covers:
  - write_json: writes valid JSON with correct schema (total/aggregate/alphas)
  - write_markdown: writes table with header + rows
  - write_markdown: failed alphas section appears when failures exist
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_101_alphas_v2 import BatchSerializer


class TestWriteJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01,
             "icir": 0.1, "ic_winrate": 0.5, "code_chars": 100, "elapsed_sec": 1.0},
            {"status": "failed", "alpha_index": 2, "stage": "TimeoutError",
             "error": "future boom", "code_chars": 0, "elapsed_sec": 0.0},
        ]
        out = tmp_path / "summary.json"
        BatchSerializer.write_json(results, out)
        assert out.exists()

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total"] == 2
        assert data["success_count"] == 1
        assert data["failed_count"] == 1
        assert data["aggregate"]["ic_mean_avg"] == 0.01
        assert data["aggregate"]["icir_avg"] == 0.1
        assert data["aggregate"]["winrate_avg"] == 0.5
        assert len(data["alphas"]) == 2

    def test_alpha_entry_schema(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.05,
             "icir": 0.5, "ic_winrate": 0.6, "code_chars": 200, "elapsed_sec": 12.3,
             "stage": "", "error": ""},
        ]
        out = tmp_path / "summary.json"
        BatchSerializer.write_json(results, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        entry = data["alphas"][0]
        assert entry == {
            "index": 1,
            "status": "success",
            "ic_mean": 0.05,
            "icir": 0.5,
            "ic_winrate": 0.6,
            "code_chars": 200,
            "elapsed_sec": 12.3,
            "stage": "",
            "error": "",
        }

    def test_error_truncated_to_200(self, tmp_path: Path) -> None:
        long_error = "x" * 1000
        results = [{"status": "failed", "alpha_index": 1, "error": long_error}]
        out = tmp_path / "summary.json"
        BatchSerializer.write_json(results, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["alphas"][0]["error"]) == 200


class TestWriteMarkdown:
    def test_basic_table(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.05,
             "icir": 0.5, "ic_winrate": 0.6, "code_chars": 100, "elapsed_sec": 12.3},
        ]
        out = tmp_path / "summary.md"
        BatchSerializer.write_markdown(results, out)
        content = out.read_text(encoding="utf-8")

        assert "# 101-Alpha Batch Results (v2)" in content
        assert "- Total: 1 | Success: 1 | Failed: 0" in content
        assert "- Avg IC: +0.0500 | Avg ICIR: +0.5000 | Avg Winrate: 60.0%" in content
        assert "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |" in content
        assert "| alpha-001 | success | +0.0500 | +0.5000 | 60.0% | 100 | 12.3s |" in content

    def test_failed_alphas_section(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01,
             "icir": 0.1, "ic_winrate": 0.5, "code_chars": 100, "elapsed_sec": 1.0},
            {"status": "failed", "alpha_index": 2, "stage": "TimeoutError",
             "error": "future boom"},
        ]
        out = tmp_path / "summary.md"
        BatchSerializer.write_markdown(results, out)
        content = out.read_text(encoding="utf-8")

        assert "## Failed Alphas" in content
        assert "alpha-002" in content
        assert "TimeoutError" in content
        assert "future boom" in content

    def test_no_failed_section_when_all_success(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01,
             "icir": 0.1, "ic_winrate": 0.5, "code_chars": 100, "elapsed_sec": 1.0},
        ]
        out = tmp_path / "summary.md"
        BatchSerializer.write_markdown(results, out)
        content = out.read_text(encoding="utf-8")
        assert "## Failed Alphas" not in content

    def test_empty_results(self, tmp_path: Path) -> None:
        out = tmp_path / "summary.md"
        BatchSerializer.write_markdown([], out)
        content = out.read_text(encoding="utf-8")
        assert "# 101-Alpha Batch Results (v2)" in content
        assert "- Total: 0 | Success: 0 | Failed: 0" in content
        assert "Avg IC:" not in content  # no metrics for empty

    def test_nan_metrics_show_na(self, tmp_path: Path) -> None:
        results = [
            {"status": "success", "alpha_index": 1,
             "ic_mean": float("nan"), "icir": float("nan"),
             "ic_winrate": float("nan"), "code_chars": 100, "elapsed_sec": 1.0},
        ]
        out = tmp_path / "summary.md"
        BatchSerializer.write_markdown(results, out)
        content = out.read_text(encoding="utf-8")
        assert "NaN" in content
        # Avg IC not shown for all-NaN
        assert "Avg IC:" not in content
