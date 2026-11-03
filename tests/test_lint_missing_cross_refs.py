"""Boundary tests for the missing_cross_ref lint rule.

Covers the layered-wiki cases the original tests missed: the existing
suite only used flat (root-level) pages, where the page name happened to
equal the title, so the rule looked healthy while it never fired on a
real ``wiki/concepts/`` layout.
"""

from __future__ import annotations

from llmwikify.kernel.wiki.lint.rules.missing_cross_refs import MissingCrossRefsRule


def _detect(pages: dict[str, str], wiki) -> list[dict]:
    """Run the rule over an explicit page map."""
    results: list[dict] = []
    MissingCrossRefsRule().detect_all(pages, wiki, results)
    return results


def test_detects_plain_title_mention_in_layered_wiki(wiki_instance):
    """Prose says "Foo" while the page is "concepts/Foo" — must be found."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")
    wiki_instance.write_page("sources/Baz", "# Baz\n\nAlso about Foo.\n")

    results = _detect(
        {
            "concepts/Foo": "# Foo\n\nContent.\n",
            "sources/Bar": "# Bar\n\nAbout Foo here.\n",
            "sources/Baz": "# Baz\n\nAlso about Foo.\n",
        },
        wiki_instance,
    )

    assert len(results) == 1
    assert results[0]["concept"] == "concepts/Foo"
    assert results[0]["concept_title"] == "Foo"
    assert set(results[0]["mentioning_pages"]) == {"sources/Bar", "sources/Baz"}


def test_detects_qualified_path_mention(wiki_instance):
    """Prose that spells out the path is a mention too."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nSee concepts/Foo.\n",
        "sources/Baz": "# Baz\n\nAlso concepts/Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert [r["concept"] for r in results] == ["concepts/Foo"]


def test_already_linked_title_form_not_flagged(wiki_instance):
    """``[[Foo]]`` counts as linked even though the page is concepts/Foo."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout [[Foo]] here.\n",
        "sources/Baz": "# Baz\n\nAlso about [[Foo]].\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_already_linked_qualified_form_not_flagged(wiki_instance):
    """``[[concepts/Foo]]`` counts as linked as well."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout [[concepts/Foo]] here.\n",
        "sources/Baz": "# Baz\n\nAlso about [[concepts/Foo]].\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_ambiguous_title_excluded(wiki_instance):
    """Two pages sharing a title: the bare title cannot identify one."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "entities/Foo": "# Foo\n\nOther content.\n",
        "sources/Bar": "# Bar\n\nAbout Foo here.\n",
        "sources/Baz": "# Baz\n\nAlso about Foo.\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_ambiguous_title_still_matches_qualified_path(wiki_instance):
    """With an ambiguous title, the qualified path still identifies a page."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "entities/Foo": "# Foo\n\nOther content.\n",
        "sources/Bar": "# Bar\n\nSee concepts/Foo.\n",
        "sources/Baz": "# Baz\n\nAlso concepts/Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert [r["concept"] for r in results] == ["concepts/Foo"]


def test_single_mention_below_threshold(wiki_instance):
    """One mentioning page is below MIN_MISSING_REF_COUNT."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout Foo here.\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_flat_pages_keep_legacy_behaviour(wiki_instance):
    """Root-level pages: page name == title, unchanged from before."""
    pages = {
        "Machine Learning": "# ML\n\nContent.\n",
        "AI Overview": "# AI\n\nMachine learning is a subset of AI.\n",
        "Data Science": "# DS\n\nMachine learning is used here.\n",
    }
    results = _detect(pages, wiki_instance)

    assert len(results) == 1
    assert results[0]["concept"] == "Machine Learning"
    assert results[0]["concept_title"] == "Machine Learning"


def test_self_page_not_reported(wiki_instance):
    """A page mentioning its own title is not a missing cross-ref."""
    pages = {
        "concepts/Foo": "# Foo\n\nFoo is a concept.\n",
        "sources/Bar": "# Bar\n\nAbout Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert all(r["concept"] != "concepts/Foo" for r in results)
