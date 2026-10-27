"""B1 regression: contradiction rule behavior after moving regexes out of loops.

Locks value / year / negation detection contracts + copula prefilter.
Must stay green on Windows and Linux.
"""

from __future__ import annotations

from llmwikify.kernel.wiki.lint.rules.potential_contradictions import (
    PotentialContradictionsRule,
)

rule = PotentialContradictionsRule()


def _neg(pages: dict[str, str]) -> list[dict]:
    results: list[dict] = []
    rule._detect_negation_patterns(pages, results)
    return results


def _year(pages: dict[str, str]) -> list[dict]:
    results: list[dict] = []
    rule._detect_year_conflicts(pages, results)
    return results


def _value(pages: dict[str, str]) -> list[dict]:
    results: list[dict] = []
    rule._detect_value_conflicts(pages, results, set())
    return results


# ─── value_conflict ───────────────────────────────────────────────


def test_value_conflict_different_values():
    results = _value({"a.md": "sector: technology\n", "b.md": "sector: finance\n"})
    assert len(results) == 1
    r = results[0]
    assert r["type"] == "value_conflict"
    assert r["attribute"] == "sector"
    assert {p["value"] for p in r["pages"]} == {"technology", "finance"}


def test_value_conflict_same_value_ignored():
    assert _value({"a.md": "sector: tech\n", "b.md": "sector: tech\n"}) == []


def test_value_conflict_single_page_ignored():
    assert _value({"a.md": "sector: tech\n", "b.md": "unrelated: other\n"}) == []


def test_value_conflict_skips_headings_and_urls():
    pages = {
        "a.md": "# sector: heading\nhttp://example.com/x:1\n",
        "b.md": "sector: finance\n",
    }
    # heading / url lines are skipped — only one real sector fact
    assert _value(pages) == []


def test_value_conflict_short_key_ignored():
    assert _value({"a.md": "x: aa\n", "b.md": "x: bb\n"}) == []


# ─── year_conflict ────────────────────────────────────────────────


def test_year_conflict_different_years():
    results = _year(
        {
            "a.md": "Bitcoin was launched in 2009.\n",
            "b.md": "Bitcoin was launched in 2011.\n",
        }
    )
    assert len(results) == 1
    assert results[0]["type"] == "year_conflict"
    # Original regex is lazy: entity group may include "was" before the verb.
    assert results[0]["entity"].strip().startswith("Bitcoin")
    years = {c["year"] for c in results[0]["claims"]}
    assert years == {"2009", "2011"}


def test_year_conflict_same_year_ignored():
    pages = {
        "a.md": "Bitcoin was launched in 2009.\n",
        "b.md": "Bitcoin was launched in 2009.\n",
    }
    assert _year(pages) == []


def test_year_conflict_founded_verb():
    results = _year(
        {
            "a.md": "Acme was founded in 1999.\n",
            "b.md": "Acme was founded in 2001.\n",
        }
    )
    assert results and results[0]["type"] == "year_conflict"


def test_year_conflict_no_year_ignored():
    assert _year({"a.md": "Bitcoin was launched recently.\n"}) == []


# ─── negation_pattern ─────────────────────────────────────────────


def test_negation_both_polarities():
    results = _neg(
        {
            "a.md": "The protocol is secure.\n",
            "b.md": "The protocol is not secure.\n",
        }
    )
    assert len(results) == 1
    r = results[0]
    assert r["type"] == "negation_pattern"
    assert r["subject"].lower() == "the protocol"
    flags = {c["negated"] for c in r["claims"]}
    assert flags == {True, False}


def test_negation_single_polarity_not_reported():
    assert _neg(
        {"a.md": "The protocol is secure.\n", "b.md": "The protocol is robust.\n"}
    ) == []


def test_negation_no_longer():
    results = _neg(
        {
            "a.md": "The service is stable.\n",
            "b.md": "The service is no longer stable.\n",
        }
    )
    assert results and results[0]["type"] == "negation_pattern"


def test_negation_were_and_are():
    results = _neg(
        {
            "a.md": "Nodes are online.\n",
            "b.md": "Nodes were not online.\n",
        }
    )
    assert results and results[0]["type"] == "negation_pattern"


def test_negation_skips_headings_and_blank():
    results = _neg(
        {
            "a.md": "\n# Heading is not a claim\n\nThe protocol is secure.\n",
            "b.md": "The protocol is not secure.\n",
        }
    )
    subjects = [r["subject"].lower() for r in results if r["type"] == "negation_pattern"]
    assert subjects == ["the protocol"]


def test_negation_prefilter_skips_non_copula_prose():
    results = _neg(
        {
            "a.md": "Mining uses heavy equipment. The protocol is secure.\n",
            "b.md": "Mining uses heavy machinery. The protocol is not secure.\n",
        }
    )
    subjects = {r["subject"].lower() for r in results if r["type"] == "negation_pattern"}
    assert "the protocol" in subjects
    assert not any(s.startswith("mining") for s in subjects)


def test_negation_prefilter_keeps_copula_lines():
    # long line without copula must not create false subjects
    long_noise = "alpha beta gamma delta epsilon zeta eta theta " * 8
    results = _neg(
        {
            "a.md": f"{long_noise}\nThe system is degraded.\n",
            "b.md": f"{long_noise}\nThe system is not degraded.\n",
        }
    )
    subjects = {r["subject"].lower() for r in results if r["type"] == "negation_pattern"}
    assert subjects == {"the system"}


def test_negation_max_results_cap():
    pages: dict[str, str] = {}
    for i in range(rule.max_results + 3):
        pages[f"p{i}.md"] = (
            f"Subject{i} is fine.\n"
            f"Subject{i} is not fine.\n"
        )
    results = _neg(pages)
    assert len(results) <= rule.max_results


# ─── detect_all orchestration ─────────────────────────────────────


def test_detect_all_finds_multiple_kinds():
    pages = {
        "a.md": (
            "sector: technology\n"
            "Bitcoin was launched in 2009.\n"
            "The protocol is secure.\n"
        ),
        "b.md": (
            "sector: finance\n"
            "Bitcoin was launched in 2011.\n"
            "The protocol is not secure.\n"
        ),
    }
    results: list[dict] = []
    rule.detect_all(pages, wiki=None, results=results)  # type: ignore[arg-type]
    types = {r["type"] for r in results}
    assert "value_conflict" in types
    assert "year_conflict" in types
    assert "negation_pattern" in types


def test_detect_all_empty_pages():
    results: list[dict] = []
    rule.detect_all({}, wiki=None, results=results)  # type: ignore[arg-type]
    assert results == []
