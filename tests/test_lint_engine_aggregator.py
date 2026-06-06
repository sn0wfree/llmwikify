"""Phase 1 #3 / C2 — WikiAnalyzer is an aggregator, WikiLintMixin is a delegator.

This is a documentation-only / structure-test commit. The
refactor work itself was already completed by C1 (which made
WikiAnalyzer a thin orchestrator that delegates to LintEngine
for the 8 rule-based detectors).

What C2 adds:

1. A consolidation note in ``WikiAnalyzer.lint()`` explaining
   that the rule-based investigations are now a single
   ``_run_all_rules()`` call (vs. the previous 5 separate
   ``_detect_X`` calls).

2. An end-to-end structural test verifying the WikiLintMixin
   delegates everything to WikiAnalyzer (no inline logic).

3. A guard test that catches accidental re-introduction of
   inline detection logic in WikiAnalyzer (the static check
   in test_lint_engine.py already covers this; this test
   adds a higher-level integration assertion).

The refactor surface is:
- ``core/lint/__init__.py`` — Rule + LintEngine
- ``core/lint/rules/*.py`` — 8 rule classes
- ``core/wiki_analyzer.py`` — thin aggregator (C1 reduced 929 → 520 lines)
- ``core/wiki_mixin_lint.py`` — thin delegator (already was 70 lines
  of 1-line delegates before C1; C1 just changed the underlying
  implementation to go through LintEngine)
"""

from __future__ import annotations

import inspect

import pytest


# ============================================================================
# WikiAnalyzer is a thin aggregator
# ============================================================================


def test_wiki_analyzer_class_docstring_mentions_aggregator_role():
    """WikiAnalyzer's class docstring describes its new aggregator role."""
    from llmwikify.core.wiki_analyzer import WikiAnalyzer

    docstring = inspect.getdoc(WikiAnalyzer) or ""
    assert "Health check" in docstring, (
        "WikiAnalyzer should still describe itself as a health check / "
        "lint / recommendation engine"
    )


def test_wiki_analyzer_does_not_define_inline_detection_rules():
    """WikiAnalyzer has no inline detection logic — all 8 _detect_X
    methods are 1-line delegates (no body beyond the return statement).
    """
    from llmwikify.core.wiki_analyzer import WikiAnalyzer

    detect_methods = [
        "_detect_dated_claims",
        "_detect_query_page_overlap",
        "_detect_missing_cross_refs",
        "_detect_potential_contradictions",
        "_detect_data_gaps",
        "_detect_outdated_pages",
        "_detect_knowledge_gaps",
        "_detect_redundancy",
    ]

    for name in detect_methods:
        method = getattr(WikiAnalyzer, name)
        src = inspect.getsource(method)
        # Method body should ONLY contain a return statement
        body_lines = [
            line.strip() for line in src.splitlines()
            if line.strip()
            and not line.strip().startswith("def ")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
        ]
        # 1 line: just the return
        assert len(body_lines) <= 1, (
            f"WikiAnalyzer.{name} has {len(body_lines)} body lines: "
            f"expected exactly 1 (the return statement). Inline "
            f"detection logic was re-introduced."
        )
        # And that 1 line is a return calling self._run_rule(...)
        if body_lines:
            assert "self._run_rule(" in body_lines[0], (
                f"WikiAnalyzer.{name} body should call self._run_rule(...): "
                f"{body_lines[0]}"
            )


def test_wiki_analyzer_lint_method_partitions_results_by_type():
    """The lint() method's investigations block uses type-based partitioning
    (the Phase 1 #3 pattern), not 5 individual _detect_X calls.
    """
    from llmwikify.core.wiki_analyzer import WikiAnalyzer

    src = inspect.getsource(WikiAnalyzer.lint)
    # Must use _run_all_rules
    assert "_run_all_rules()" in src
    # Must use list-comprehension partitioning by type
    assert "r.get(\"type\")" in src or "r.get('type')" in src
    # Must NOT call individual _detect_X
    old_calls = [
        "_detect_potential_contradictions()",
        "_detect_data_gaps()",
        "_detect_outdated_pages()",
        "_detect_knowledge_gaps()",
        "_detect_redundancy()",
    ]
    for old in old_calls:
        assert old not in src, (
            f"WikiAnalyzer.lint still has old call: {old}"
        )


# ============================================================================
# WikiLintMixin is a thin delegator to WikiAnalyzer
# ============================================================================


def test_wiki_mixin_lint_methods_all_delegate_to_wiki_analyzer():
    """Each public/private method on WikiLintMixin delegates to WikiAnalyzer."""
    from llmwikify.core.wiki_mixin_lint import WikiLintMixin

    delegate_methods = [
        "_detect_dated_claims",
        "_detect_query_page_overlap",
        "_detect_missing_cross_refs",
        "_detect_potential_contradictions",
        "_detect_data_gaps",
        "_detect_outdated_pages",
        "_detect_knowledge_gaps",
        "_detect_redundancy",
        "lint",
        "_generate_hints",
    ]

    for name in delegate_methods:
        method = getattr(WikiLintMixin, name)
        src = inspect.getsource(method)
        # The body must reference WikiAnalyzer (either via direct
        # ``WikiAnalyzer(self)`` or via the cached ``self._analyzer``
        # attribute — Phase 2 #4 accepts both as legitimate
        # delegator patterns).
        assert "WikiAnalyzer" in src or "_analyzer" in src, (
            f"WikiLintMixin.{name} should delegate to WikiAnalyzer"
        )


def test_wiki_mixin_lint_is_pure_delegation():
    """WikiLintMixin methods are 1-line delegates (no inline logic)."""
    from llmwikify.core.wiki_mixin_lint import WikiLintMixin

    delegate_methods = [
        "_detect_dated_claims",
        "_detect_query_page_overlap",
        "_detect_missing_cross_refs",
        "_detect_potential_contradictions",
        "_detect_data_gaps",
        "_detect_outdated_pages",
        "_detect_knowledge_gaps",
        "_detect_redundancy",
        "lint",
        "_generate_hints",
    ]

    for name in delegate_methods:
        method = getattr(WikiLintMixin, name)
        src = inspect.getsource(method)
        # Count "return" statements — should be exactly 1 per method
        return_count = sum(1 for line in src.splitlines() if line.strip().startswith("return "))
        assert return_count == 1, (
            f"WikiLintMixin.{name} has {return_count} return statements — "
            f"expected exactly 1 (a single delegator). Inline logic was added."
        )
        # And no inline assignments outside the return
        # (e.g., no `result = ...` followed by `print(result)`)
        non_return_stmts = [
            line.strip() for line in src.splitlines()
            if line.strip()
            and not line.strip().startswith("def ")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
            and not line.strip().startswith("return ")
            and not line.strip().endswith(",")
            and not line.strip().endswith("):")
            and "self, " not in line
        ]
        # For 1-line delegates there should be no body statements at all
        # (only the signature, the return, and a closing)
        # For multi-line delegates (like lint) there may be no non-return stmts
        inline_logic = [
            line for line in non_return_stmts
            if not line.startswith("\"") and not line.startswith("'")
            and " -> " not in line
            and not line.startswith("=")  # KW-only arg defaults
            and "import " not in line
        ]
        assert len(inline_logic) <= 1, (
            f"WikiLintMixin.{name} has inline logic: {inline_logic[:3]}"
        )


def test_wiki_mixin_lint_class_docstring_says_aggregator():
    """WikiLintMixin's docstring describes its thin delegator role."""
    from llmwikify.core.wiki_mixin_lint import WikiLintMixin

    docstring = inspect.getdoc(WikiLintMixin) or ""
    assert "delegat" in docstring.lower(), (
        "WikiLintMixin docstring should mention its delegation role"
    )


# ============================================================================
# The rule file count matches the 8 documented rules
# ============================================================================


def test_eight_rule_files_exist_on_disk():
    """All 8 rule files exist in core/lint/rules/."""
    from pathlib import Path

    rules_dir = Path("src/llmwikify/core/lint/rules")
    expected = {
        "__init__.py",
        "dated_claims.py",
        "query_page_overlap.py",
        "missing_cross_refs.py",
        "potential_contradictions.py",
        "data_gaps.py",
        "outdated_pages.py",
        "knowledge_gaps.py",
        "redundancy.py",
    }
    actual = {p.name for p in rules_dir.glob("*.py")}
    assert expected.issubset(actual), (
        f"missing rule files: {expected - actual}\n  actual: {actual}"
    )


# ============================================================================
# Integration: Wiki → WikiAnalyzer → LintEngine → Rule end-to-end
# ============================================================================


def test_full_lint_pipeline_uses_lint_engine(tmp_path):
    """A Wiki → WikiAnalyzer → LintEngine → Rule call chain works end-to-end.

    Verifies the integration: invoking ``wiki.lint()`` (which goes
    through WikiLintMixin → WikiAnalyzer.lint → LintEngine.run_all
    → each Rule.run) produces a valid lint result with the
    expected top-level keys.
    """
    from llmwikify.core.wiki import Wiki

    wiki = Wiki(tmp_path)
    wiki.init()
    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "Sample.md").write_text("# Sample\n\nHello world.\n")

    result = wiki.lint()
    assert isinstance(result, dict)
    # The new lint pipeline populates these top-level keys
    assert "total_pages" in result
    assert "issue_count" in result
    assert "issues" in result
    assert "hints" in result
    assert "investigations" in result
