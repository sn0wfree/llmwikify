"""Regression: a non-UTF-8 wiki page must not break the lint path.

Before the fix a page holding an invalid byte (e.g. ``\\xff``) made
``wiki.lint()`` raise ``UnicodeDecodeError`` (HTTP 500), and made four
lint rules fail silently (swallowed by ``LintEngine.run_all``'s
``except Exception``), so lint reported "success" with half the rules
disabled.

Reading pages with ``errors="replace"`` keeps the readable part and
turns the invalid byte into U+FFFD, so the whole lint path survives.

Coverage — read before trusting the fix:

* These tests cover the pages under ``wiki/`` **and** the source summary
  pages under ``wiki/sources/``: the ``knowledge_gap`` rule reads those
  itself, so an invalid byte there used to kill that one rule (swallowed
  by ``LintEngine.run_all``).
* ``test_knowledge_gap_survives_non_utf8_source_page`` pins the fixed
  behaviour down: the source page read is lossy, so the rule runs to
  completion (the residual risk R1 of design §11, closed by P4-b-3a).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel import Wiki
from llmwikify.kernel.wiki.engines.analyzer import WikiAnalyzer
from llmwikify.kernel.wiki.lint import CrossPageRule, LintEngine
from llmwikify.kernel.wiki.lint.rules import (
    RULES,
    DataGapsRule,
    DatedClaimsRule,
    KnowledgeGapsRule,
    MissingCrossRefsRule,
    OutdatedPagesRule,
    PotentialContradictionsRule,
    QueryPageOverlapRule,
    RedundancyRule,
)

NORMAL_RULES = [
    DatedClaimsRule,
    QueryPageOverlapRule,
    DataGapsRule,
    OutdatedPagesRule,
    KnowledgeGapsRule,
    RedundancyRule,
]
CROSS_PAGE_RULES = [MissingCrossRefsRule, PotentialContradictionsRule]
ALL_RULE_NAMES = {rule.name for rule in RULES}

INVALID_BYTE_PAGE = b"# Broken Page\n\nReadable text \xff with an invalid byte.\n"
INVALID_BYTE_SOURCE_PAGE = (
    b"# Broken Source\n\nReadable source \xff with an invalid byte.\n"
)


@pytest.fixture
def wiki_with_broken_page(tmp_path):
    """Wiki holding one page that is not valid UTF-8."""
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    (root / "wiki" / "Broken Page.md").write_bytes(INVALID_BYTE_PAGE)
    (root / "wiki" / "Good Page.md").write_text(
        "# Good Page\n\nA perfectly normal page.\n", encoding="utf-8"
    )
    (root / "raw" / "source.md").write_text("# Raw Source\n\nBody.\n", encoding="utf-8")

    yield wiki
    wiki.close()


@pytest.fixture
def wiki_with_broken_source_page(tmp_path):
    """Wiki holding a *source summary* page that is not valid UTF-8."""
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    (root / "wiki" / "sources" / "Broken Source.md").write_bytes(
        INVALID_BYTE_SOURCE_PAGE
    )
    (root / "raw" / "source.md").write_text("# Raw Source\n\nBody.\n", encoding="utf-8")

    yield wiki
    wiki.close()


@pytest.fixture
def rule_spies(monkeypatch):
    """Record which rules ran to completion and which ones blew up."""
    completed: list[str] = []
    failed: list[str] = []
    load_failures: list[str] = []

    def wrap_run(orig):
        def wrapper(self, wiki):
            try:
                result = orig(self, wiki)
            except Exception as exc:
                failed.append(f"{self.name}:{type(exc).__name__}")
                raise
            completed.append(self.name)
            return result

        return wrapper

    def wrap_detect_all(orig):
        def wrapper(self, pages, wiki, results):
            try:
                result = orig(self, pages, wiki, results)
            except Exception as exc:
                failed.append(f"{self.name}:{type(exc).__name__}")
                raise
            completed.append(self.name)
            return result

        return wrapper

    def wrap_load_pages(orig):
        def wrapper(self, wiki):
            try:
                return orig(self, wiki)
            except Exception as exc:
                load_failures.append(f"{self.name}:{type(exc).__name__}")
                raise

        return wrapper

    for rule_cls in NORMAL_RULES:
        monkeypatch.setattr(rule_cls, "run", wrap_run(rule_cls.run))
    for rule_cls in CROSS_PAGE_RULES:
        monkeypatch.setattr(
            rule_cls, "detect_all", wrap_detect_all(rule_cls.detect_all)
        )
    monkeypatch.setattr(
        CrossPageRule, "_load_pages", wrap_load_pages(CrossPageRule._load_pages)
    )
    # `Rule.run` stays untouched: it is the shared implementation the
    # normal rules call through `super().run(...)`.

    return {"completed": completed, "failed": failed, "load_failures": load_failures}


def test_lint_survives_non_utf8_page(wiki_with_broken_page, monkeypatch, caplog):
    """``wiki.lint()`` must not raise on a page that is not valid UTF-8."""
    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])

    with caplog.at_level(logging.WARNING):
        result = wiki_with_broken_page.lint()

    assert "issues" in result
    assert "issue_count" in result
    assert result["mode"] == "check"

    rule_failures = [
        record.getMessage()
        for record in caplog.records
        if "lint rule" in record.getMessage()
    ]
    assert (
        rule_failures == []
    ), f"lint rules were silently disabled by the invalid byte: {rule_failures}"


def test_all_rules_complete_with_non_utf8_page(wiki_with_broken_page, rule_spies):
    """Every one of the 8 rules must run to completion on a bad page."""
    engine = LintEngine(wiki_with_broken_page, rules=RULES)

    issues = engine.run_all()

    assert isinstance(issues, list)
    assert rule_spies["load_failures"] == []
    assert rule_spies["failed"] == []
    assert set(rule_spies["completed"]) == ALL_RULE_NAMES


def test_rule_read_is_lossy_not_empty(wiki_with_broken_page, rule_spies):
    """The readable part of the page survives (not swallowed as empty)."""
    engine = LintEngine(wiki_with_broken_page, rules=RULES)
    engine.run_all()

    # The normal rules read the page themselves; the cross-page rules get
    # it through `_load_pages`. Both must see the readable text.
    assert rule_spies["failed"] == []
    assert set(rule_spies["completed"]) == ALL_RULE_NAMES

    pages = MissingCrossRefsRule()._load_pages(wiki_with_broken_page)
    broken = pages["Broken Page"]
    assert "Readable text" in broken
    assert "\ufffd" in broken


def test_knowledge_gap_survives_non_utf8_source_page(
    wiki_with_broken_source_page, rule_spies
):
    """The residual risk R1 is closed: the source page read is lossy.

    A source summary page under ``wiki/sources/`` that is not valid
    UTF-8 used to kill the ``knowledge_gap`` rule: that rule read the
    source pages with a strict read of its own
    (``lint/rules/knowledge_gaps.py``), and ``LintEngine.run_all``
    swallows the exception — so the rule silently disappeared from the
    lint result.

    The read is lossy now (``errors="replace"``), in the legacy path and
    in the snapshot path alike, so the rule survives and the readable
    part of the page is still analysed.

    Design: ``p4-lint-snapshot.md`` §11 R1, closed by ``p4b-lint-snapshot.md``.
    """
    engine = LintEngine(wiki_with_broken_source_page, rules=RULES)

    issues = engine.run_all()  # must not raise

    assert isinstance(issues, list)
    assert rule_spies["failed"] == [], (
        "no lint rule may fail on a non-UTF-8 source page, got "
        f"{rule_spies['failed']}"
    )
    assert (
        "knowledge_gap" in rule_spies["completed"]
    ), "the knowledge_gap rule must run to completion on a non-UTF-8 source page"
    assert rule_spies["load_failures"] == []


def test_knowledge_gap_reports_the_broken_source_page(wiki_with_broken_source_page):
    """The broken source page is still analysed (readable part kept).

    A page without wikilinks is an ``isolated_source`` gap: the rule
    must not skip the page because of the invalid byte.
    """
    engine = LintEngine(wiki_with_broken_source_page, rules=RULES)

    issues = engine.run_all()

    isolated = [issue for issue in issues if issue.get("type") == "isolated_source"]
    assert isolated, "the broken source page must still be reported"
    assert isolated[0]["page"] == "sources/Broken Source"
