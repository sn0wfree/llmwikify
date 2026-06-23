"""Tests for paths: Wiki 路径管理 (constants + helpers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llmwikify.reproduction import paths as p


class FakeWiki:
    """Minimal wiki mock for path tests."""

    def __init__(self, wiki_dir: Path):
        self.wiki_dir = wiki_dir


class TestWikiDirConstants:
    """Test 4 个 WIKI_DIR_* 常量 (4 测试)."""

    def test_factor_dir_loaded(self) -> None:
        assert isinstance(p.WIKI_DIR_FACTOR, str)
        assert len(p.WIKI_DIR_FACTOR) > 0

    def test_strategy_dir_loaded(self) -> None:
        assert isinstance(p.WIKI_DIR_STRATEGY, str)
        assert len(p.WIKI_DIR_STRATEGY) > 0

    def test_sources_dir_loaded(self) -> None:
        assert isinstance(p.WIKI_DIR_SOURCES, str)
        assert len(p.WIKI_DIR_SOURCES) > 0

    def test_reproduction_dir_loaded(self) -> None:
        assert isinstance(p.WIKI_DIR_REPRODUCTION, str)
        assert len(p.WIKI_DIR_REPRODUCTION) > 0


class TestPathHelpers:
    """Test path helper functions (5 测试)."""

    def test_page_path(self, tmp_path: Path) -> None:
        """page_path returns wiki/dir/slug.md."""
        wiki = FakeWiki(tmp_path)
        result = p.page_path(wiki, "factor", "momentum_20d")
        assert result == tmp_path / "factor" / "momentum_20d.md"

    def test_result_path(self, tmp_path: Path) -> None:
        """result_path returns wiki/dir/slug/results/run_id.md."""
        wiki = FakeWiki(tmp_path)
        result = p.result_path(wiki, "factor", "momentum_20d", "20240101-20241231")
        assert result == tmp_path / "factor" / "momentum_20d" / "results" / "20240101-20241231.md"

    def test_result_dir(self, tmp_path: Path) -> None:
        """result_dir returns wiki/dir/slug/results/."""
        wiki = FakeWiki(tmp_path)
        result = p.result_dir(wiki, "strategy", "my_strat")
        assert result == tmp_path / "strategy" / "my_strat" / "results"

    def test_list_pages_empty(self, tmp_path: Path) -> None:
        """list_pages on non-existent dir returns []."""
        wiki = FakeWiki(tmp_path)
        assert p.list_pages(wiki, "factor") == []

    def test_list_pages_with_files(self, tmp_path: Path) -> None:
        """list_pages reads frontmatter from .md files."""
        import tempfile
        wiki = FakeWiki(tmp_path)
        factor_dir = tmp_path / "factor"
        factor_dir.mkdir()
        (factor_dir / "momentum.md").write_text(
            "---\nname: momentum\ncategory: alpha\n---\nbody",
            encoding="utf-8",
        )
        (factor_dir / "value.md").write_text(
            "---\nname: value\ncategory: alpha\n---\nbody",
            encoding="utf-8",
        )

        result = p.list_pages(wiki, "factor")
        assert len(result) == 2
        slugs = {r["_slug"] for r in result}
        assert slugs == {"momentum", "value"}


class TestListResults:
    """Test list_results (2 测试)."""

    def test_list_results_empty(self, tmp_path: Path) -> None:
        """list_results on non-existent dir returns []."""
        wiki = FakeWiki(tmp_path)
        assert p.list_results(wiki, "factor", "momentum") == []

    def test_list_results_with_files(self, tmp_path: Path) -> None:
        """list_results returns run_id list."""
        wiki = FakeWiki(tmp_path)
        results_dir = tmp_path / "factor" / "momentum" / "results"
        results_dir.mkdir(parents=True)
        (results_dir / "20240101-20241231.md").write_text("result 1")
        (results_dir / "20250101-20251231.md").write_text("result 2")

        result = p.list_results(wiki, "factor", "momentum")
        assert len(result) == 2
        run_ids = {r["run_id"] for r in result}
        assert run_ids == {"20240101-20241231", "20250101-20251231"}


class TestModuleExports:
    """Test __all__ export list (1 测试)."""

    def test_all_exports(self) -> None:
        """__all__ 包含所有公共 API."""
        expected = {
            "WIKI_DIR_FACTOR",
            "WIKI_DIR_STRATEGY",
            "WIKI_DIR_SOURCES",
            "WIKI_DIR_REPRODUCTION",
            "page_path",
            "result_path",
            "result_dir",
            "list_pages",
            "list_results",
        }
        assert set(p.__all__) == expected
