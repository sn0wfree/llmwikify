"""B1 regression: contradiction rule still finds value/year/negation hits.

Covers the prefilter + module-level regex path (compile no longer
lives inside the page×line loops).
"""

from __future__ import annotations

from pathlib import Path

from llmwikify.kernel.wiki.lint.rules.potential_contradictions import (
    PotentialContradictionsRule,
)

rule = PotentialContradictionsRule()


def test_value_conflict_detected():
    pages = {
        "a.md": "sector: technology\n",
        "b.md": "sector: finance\n",
    }
    results: list = []
    rule._detect_value_conflicts(pages, results, set())
    assert any(r["type"] == "value_conflict" for r in results)


def test_year_conflict_detected():
    pages = {
        "a.md": "Bitcoin was launched in 2009.\n",
        "b.md": "Bitcoin was launched in 2011.\n",
    }
    results: list = []
    rule._detect_year_conflicts(pages, results)
    assert any(r["type"] == "year_conflict" for r in results)


def test_negation_both_polarities_detected():
    pages = {
        "a.md": "The protocol is secure.\n",
        "b.md": "The protocol is not secure.\n",
    }
    results: list = []
    rule._detect_negation_patterns(pages, results)
    assert any(r["type"] == "negation_pattern" for r in results)


def test_negation_prefilter_skips_non_copula_lines():
    """Lines without is/are/was/were must not hit the assertion regex."""
    pages = {
        "a.md": "Mining uses heavy equipment. The protocol is secure.\n",
        "b.md": "Mining uses heavy machinery. The protocol is not secure.\n",
    }
    results: list = []
    rule._detect_negation_patterns(pages, results)
    subjects = {r["subject"].lower() for r in results if r["type"] == "negation_pattern"}
    assert "the protocol" in subjects
    # equipment/machinery lines have no copula — no subject from them alone
    assert "mining uses heavy equipment" not in subjects


def test_negation_single_polarity_not_reported():
    pages = {
        "a.md": "The protocol is secure.\n",
        "b.md": "The protocol is robust.\n",
    }
    results: list = []
    rule._detect_negation_patterns(pages, results)
    assert not any(r["type"] == "negation_pattern" for r in results)
