"""Tests for BatchReporter (P1 refactor).

Covers:
  - log_banner: 3 lines × 100-char "=" border
  - log_row: success / failed rows with correct format
  - log_summary: Total / Success / Failed / Avg IC + Failed list
"""
from __future__ import annotations

import logging

from scripts.run_101_alphas_v2 import BatchReporter


class TestLogBanner:
    def test_three_lines_with_borders(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        BatchReporter.log_banner()
        assert len(caplog.records) == 3
        assert caplog.records[0].message == "=" * 100
        assert caplog.records[1].message == "  101-Alpha Batch Runner (v2)"
        assert caplog.records[2].message == "=" * 100


class TestLogRow:
    def test_success_row(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        result = {"status": "success", "alpha_index": 1, "ic_mean": 0.025,
                  "icir": 0.18, "ic_winrate": 0.52, "elapsed_sec": 12.5}
        BatchReporter.log_row(1, result, 5.0)
        text = caplog.text
        assert "1" in text
        assert "success" in text
        assert "+0.0250" in text
        assert "+0.1800" in text
        assert "52.0%" in text
        assert "12.5" in text

    def test_failed_row_includes_stage_note(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        result = {"status": "failed", "alpha_index": 42, "stage": "TimeoutError",
                  "ic_mean": None, "icir": None, "ic_winrate": None,
                  "elapsed_sec": 0.0, "error": "boom"}
        BatchReporter.log_row(42, result, 100.0)
        text = caplog.text
        assert "failed" in text
        assert "42" in text
        assert "TimeoutError" in text  # stage as note

    def test_nan_metrics_show_na(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        result = {"status": "success", "alpha_index": 1,
                  "ic_mean": float("nan"), "icir": float("nan"),
                  "ic_winrate": float("nan"), "elapsed_sec": 1.0}
        BatchReporter.log_row(1, result, 0.0)
        text = caplog.text
        assert "NaN" in text


class TestLogSummary:
    def test_all_success(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01,
             "icir": 0.1, "ic_winrate": 0.5, "elapsed_sec": 1.0},
            {"status": "success", "alpha_index": 2, "ic_mean": 0.02,
             "icir": 0.2, "ic_winrate": 0.5, "elapsed_sec": 1.0},
        ]
        BatchReporter.log_summary(results)
        text = caplog.text
        assert "Total:  2" in text
        assert "Success: 2" in text
        assert "Failed: 0" in text
        assert "Avg IC: +0.0150" in text
        assert "Avg ICIR: +0.1500" in text

    def test_with_failed_list(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        results = [
            {"status": "success", "alpha_index": 1, "ic_mean": 0.01,
             "icir": 0.1, "ic_winrate": 0.5},
            {"status": "failed", "alpha_index": 2, "stage": "TimeoutError",
             "error": "future boom"},
        ]
        BatchReporter.log_summary(results)
        text = caplog.text
        assert "Total:  2" in text
        assert "Success: 1" in text
        assert "Failed: 1" in text
        assert "Failed alphas:" in text
        assert "alpha-002" in text
        assert "TimeoutError" in text

    def test_empty_results(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        BatchReporter.log_summary([])
        text = caplog.text
        assert "Total:  0" in text
        # No Avg IC line for empty
        assert "Avg IC:" not in text
