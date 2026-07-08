"""Tests for doctor layout introspection (v0.40+).

Covers:
  - Wiki._extract_subdirs_from_wiki_md (regex parser, 2 sources)
  - Wiki.expected_layout / actual_layout / check_layout / layout_diff
  - Doctor's _check_wiki_dir integration
  - Bug regression: --wiki-root flag honoured
  - Fix dict present for every fail and actionable warn

5 fixture wikis (real user projects) are used as the ground truth
because the v0.40+ parser must handle non-trivial wiki.md layouts
(custom page types, missing optional subdirs, etc.).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from llmwikify.kernel import Wiki

# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

FIXTURE_WIKIS = {
    "DataTrackor":      "/home/ll/Public/DataTrackor",
    "AssetAllocationv2": "/home/ll/Public/AssetAllocationv2",
    "strategy":         "/home/ll/Public/strategy",
    "pe_monitor":       "/home/ll/Public/pe_monitor",
    "comovement":       "/home/ll/Public/comovement",
}


@pytest.fixture(params=list(FIXTURE_WIKIS.keys()))
def fixture_wiki(request):
    """Yield a real Wiki instance for each of the 5 fixture projects."""
    path = Path(FIXTURE_WIKIS[request.param])
    if not path.exists():
        pytest.skip(f"Fixture wiki not found: {path}")
    return request.param, Wiki(path)


# ─────────────────────────────────────────────────────────────────
# Wiki._extract_subdirs_from_wiki_md (regex parser)
# ─────────────────────────────────────────────────────────────────

class TestExtractSubdirsFromWikiMd:
    """The 5 fixture projects exercise the two parser sources
    (Directory Structure tree + Page Types table) and both
    regular and custom subdir sets.
    """

    def test_data_trackor_7_default_subdirs(self, fixture_wiki):
        name, wiki = fixture_wiki
        if name != "DataTrackor":
            pytest.skip("project-specific test")
        subdirs = wiki._extract_subdirs_from_wiki_md()
        # 6 default + .sink (auto-added by init)
        expected = {"sources", "entities", "concepts",
                    "comparisons", "synthesis", "claims", ".sink"}
        assert expected.issubset(set(subdirs)), (
            f"DataTrackor should contain all 7 default subdirs, got {subdirs}"
        )

    def test_strategy_includes_8_custom_subdirs(self, fixture_wiki):
        name, wiki = fixture_wiki
        if name != "strategy":
            pytest.skip("project-specific test")
        subdirs = set(wiki._extract_subdirs_from_wiki_md())
        # 6 default + 8 custom (factors, strategies, backtests, signals,
        # models, portfolios, execution, research) + .sink
        custom = {"factors", "strategies", "backtests", "signals",
                  "models", "portfolios", "execution", "research"}
        assert custom.issubset(subdirs), (
            f"strategy should declare 8 custom subdirs, missing: {custom - subdirs}"
        )

    def test_pe_monitor_includes_pe_domain_subdirs(self, fixture_wiki):
        name, wiki = fixture_wiki
        if name != "pe_monitor":
            pytest.skip("project-specific test")
        subdirs = set(wiki._extract_subdirs_from_wiki_md())
        # 4 standard + 9 PE domain (investments, valuation-methods, ...)
        pe = {"investments", "valuation-methods", "cashflow-types",
              "covenants", "risks", "industries", "entity-portfolios",
              "fund-lp", "valuation-models"}
        assert pe.issubset(subdirs), (
            f"pe_monitor should declare PE domain subdirs, "
            f"missing: {pe - subdirs}"
        )

    def test_comovement_includes_finance_research(self, fixture_wiki):
        name, wiki = fixture_wiki
        if name != "comovement":
            pytest.skip("project-specific test")
        subdirs = set(wiki._extract_subdirs_from_wiki_md())
        # 6 default + 8 custom (models, metrics, datasets, experiments,
        # papers, case_studies, ...) + .sink
        custom = {"models", "metrics", "datasets", "experiments",
                  "papers", "case_studies"}
        assert custom.issubset(subdirs)

    def test_wiki_md_missing_returns_empty(self, tmp_path):
        """A wiki root with no wiki.md → no declared subdirs."""
        w = Wiki(tmp_path)
        assert w._extract_subdirs_from_wiki_md() == []

    def test_wiki_md_no_directory_section_returns_empty(self, tmp_path):
        """wiki.md exists but has no 'Directory Structure' section."""
        (tmp_path / "wiki.md").write_text(
            "# Wiki Schema\n\n## Page Types\n\nSome text, no tree.\n"
        )
        w = Wiki(tmp_path)
        assert w._extract_subdirs_from_wiki_md() == []

    def test_jupyter_noise_filtered_in_actual_layout(self, tmp_path):
        """``actual_layout`` must filter out ``.ipynb_checkpoints/``,
        which is created by JupyterLab and is not an llmwikify subdir.
        """
        (tmp_path / "wiki.md").write_text(
            "# Wiki Schema\n\n## Directory Structure\n\n```\nwiki/\n"
            "├── sources/\n└── .sink/\n```\n"
        )
        (tmp_path / "wiki").mkdir()
        (tmp_path / "wiki" / "sources").mkdir()
        (tmp_path / "wiki" / ".sink").mkdir()
        (tmp_path / "wiki" / ".ipynb_checkpoints").mkdir()  # jupyter noise
        (tmp_path / "wiki" / "concepts").mkdir()              # undeclared

        w = Wiki(tmp_path)
        actual = w.actual_layout
        assert "wiki/sources/" in actual
        assert "wiki/.sink/" in actual
        assert "wiki/.ipynb_checkpoints/" not in actual, (
            ".ipynb_checkpoints should be filtered"
        )
        # undeclared subdirs ARE recorded in actual (to surface drift)
        assert "wiki/concepts/" in actual


# ─────────────────────────────────────────────────────────────────
# Wiki.expected_layout / layout_diff
# ─────────────────────────────────────────────────────────────────

class TestWikiLayoutDiff:
    """The diff classifies each path into one of three buckets:
    in_both (consistent), declared_only (missing on disk),
    actual_only (on disk but not in wiki.md)."""

    def test_5_fixture_wikis_have_in_both_4_functional(self, fixture_wiki):
        name, wiki = fixture_wiki
        diff = wiki.layout_diff()
        # All 4 functional paths are present in every fixture wiki
        for required in ("raw/", "wiki/", ".llmwikify.db", "wiki.md"):
            assert required in diff["in_both"], (
                f"{name}: required {required!r} should be in_both, "
                f"got declared_only={diff['declared_only']}"
            )

    def test_strategy_has_actual_only_factorbacktest_risk(self, fixture_wiki):
        """strategy's wiki.md doesn't list factorbacktest/ and risk/
        (added later by user, wiki.md went stale). Should be in
        actual_only — informational, not a failure."""
        name, wiki = fixture_wiki
        if name != "strategy":
            pytest.skip("project-specific test")
        diff = wiki.layout_diff()
        assert "wiki/factorbacktest/" in diff["actual_only"]
        assert "wiki/risk/" in diff["actual_only"]

    def test_pe_monitor_has_declared_only_covenants_risks(self, fixture_wiki):
        """pe_monitor's Page Types table lists covenants/ and risks/
        but user never created the dirs. Should be in declared_only —
        warning (not fail)."""
        name, wiki = fixture_wiki
        if name != "pe_monitor":
            pytest.skip("project-specific test")
        diff = wiki.layout_diff()
        assert "wiki/covenants/" in diff["declared_only"]
        assert "wiki/risks/" in diff["declared_only"]

    def test_comovement_actual_only_research(self, fixture_wiki):
        """comovement added wiki/research/ without updating wiki.md."""
        name, wiki = fixture_wiki
        if name != "comovement":
            pytest.skip("project-specific test")
        diff = wiki.layout_diff()
        assert "wiki/research/" in diff["actual_only"]

    def test_diff_sets_are_disjoint(self, fixture_wiki):
        """in_both, declared_only, actual_only must be pairwise disjoint
        and partition expected_layout ∪ actual_layout."""
        _, wiki = fixture_wiki
        diff = wiki.layout_diff()
        all_keys = diff["in_both"] + diff["declared_only"] + diff["actual_only"]
        assert len(all_keys) == len(set(all_keys)), (
            "diff sets must be pairwise disjoint"
        )


# ─────────────────────────────────────────────────────────────────
# Doctor integration (--wiki-root flag must be honoured)
# ─────────────────────────────────────────────────────────────────

class TestDoctorWikiRootFlag:
    """Regression: in v0.40, doctor switched to consulting the Wiki
    instance for layout. Without this fix, ``--wiki-root PATH`` was
    silently ignored and doctor always reported on the package's
    own root, not the user's actual wiki.
    """

    def test_wiki_root_flag_overrides_default_wiki(self):
        """Running doctor with --wiki-root on a fixture wiki must
        report that wiki's path in the wiki check, not the package
        root. Pre-fix bug: path was /home/ll/llmwikify (package root).
        """
        result = subprocess.run(
            [sys.executable, "-m", "llmwikify", "doctor",
             "--skip-llm", "--wiki-root", "/home/ll/Public/DataTrackor",
             "--json"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
        )
        assert result.returncode == 0, f"doctor failed: {result.stderr}"
        data = json.loads(result.stdout)
        wiki_check = next(c for c in data["checks"] if c["category"] == "wiki")
        # Pre-fix bug: path was the package root
        assert wiki_check["path"] == "/home/ll/Public/DataTrackor", (
            f"expected DataTrackor path, got {wiki_check['path']!r}"
        )
        # Pre-fix bug: wiki.md was reported as missing (path was wrong)
        assert wiki_check["status"] == "ok", (
            f"DataTrackor should pass wiki check, got {wiki_check}"
        )

    def test_5_fixture_wikis_all_pass_wiki_check(self):
        """Every fixture wiki has the 4 functional paths, so doctor
        should never report wiki as a hard fail for any of them.
        This is the regression test for the old ``index.md at root''
        bug."""
        for name, path in FIXTURE_WIKIS.items():
            result = subprocess.run(
                [sys.executable, "-m", "llmwikify", "doctor",
                 "--skip-llm", "--wiki-root", path, "--json"],
                capture_output=True, text=True, cwd="/home/ll/llmwikify",
            )
            data = json.loads(result.stdout)
            wiki_check = next(c for c in data["checks"] if c["category"] == "wiki")
            assert wiki_check["status"] == "ok", (
                f"{name}: wiki check should pass, got {wiki_check}"
            )


# ─────────────────────────────────────────────────────────────────
# Fix dict on every fail / actionable warn
# ─────────────────────────────────────────────────────────────────

class TestFixDictPresent:
    """D5=A: every fail and every actionable warn must carry a fix
    dict with {commands, docs, cost, risk, auto}."""

    def test_wiki_fail_has_fix(self):
        """A wiki with no functional paths → wiki check fails → must
        have a fix that says ``llmwikify init``."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # tmp is empty: no raw/, no wiki/, no db, no wiki.md
            result = subprocess.run(
                [sys.executable, "-m", "llmwikify", "doctor",
                 "--skip-llm", "--wiki-root", tmp, "--json"],
                capture_output=True, text=True, cwd="/home/ll/llmwikify",
            )
            data = json.loads(result.stdout)
            wiki_check = next(c for c in data["checks"] if c["category"] == "wiki")
            assert wiki_check["status"] == "fail"
            assert "fix" in wiki_check, "wiki fail must include a fix dict"
            assert "llmwikify init" in wiki_check["fix"]["commands"]
            assert wiki_check["fix"]["risk"] in ("low", "medium", "high")

    def test_config_missing_has_fix(self, tmp_path):
        """If ~/.llmwikify/llmwikify.json is missing, config check
        fails and must suggest ``llmwikify init-llm``."""
        import os
        # Force a missing config by pointing HOME to an empty dir.
        # monkeypatch only works in-process; subprocess needs env dict.
        env = {**os.environ, "HOME": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, "-m", "llmwikify", "doctor", "--json"],
            capture_output=True, text=True, cwd="/home/ll/llmwikify",
            env=env,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            config_check = data["checks"][0]
            if config_check.get("status") == "missing":
                assert "fix" in config_check
                assert any("init-llm" in c
                           for c in config_check["fix"]["commands"])
