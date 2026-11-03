"""Boundary tests for the shared wikilink insertion helper.

The insert step must not corrupt the page it edits: inserting into a URL,
inline code, a fenced block, or a markdown link produces broken content
that stays broken until someone edits it by hand.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.agent.maintenance.wikilink import (
    build_pattern,
    is_linked,
    link_first_occurrence,
    mask_unsafe,
)


@pytest.mark.parametrize(
    "content",
    [
        "See https://example.com/Foo for details.",
        "See https://example.com/Foo?a=1 here.",
        "Use `Foo` here to configure.",
        "Example:\n```python\nFoo = 1\n```\nEnd.",
        "See [the Foo docs](https://x.com) for more.",
    ],
)
def test_no_insertion_into_link_hostile_regions(content: str) -> None:
    """URLs, inline code, code blocks and markdown links stay untouched."""
    out = link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo")
    assert out == content


def test_insertion_after_existing_wikilink() -> None:
    content = "See [[Foo|the docs]] first. Foo later."
    out = link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo")
    assert out == "See [[Foo|the docs]] first. [[concepts/Foo]] later."


def test_insertion_before_existing_wikilink() -> None:
    content = "Intro [[Other]] text then Foo here."
    out = link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo")
    assert out == "Intro [[Other]] text then [[concepts/Foo]] here."


def test_plain_text_gets_the_link() -> None:
    out = link_first_occurrence(
        "Foo is a technique.", build_pattern("Foo"), "concepts/Foo"
    )
    assert out == "[[concepts/Foo]] is a technique."


def test_no_match_leaves_content_untouched() -> None:
    content = "Risk Parity is a technique."
    assert (
        link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo") == content
    )


def test_mask_preserves_offsets() -> None:
    """Blanking keeps every offset valid so matches map back to the source."""
    content = "See https://example.com/Foo and Foo here."
    masked = mask_unsafe(content)
    assert len(masked) == len(content)
    assert masked != content
    # the safe mention survives the mask
    assert masked.rstrip().endswith("Foo here.")


def test_mask_leaves_plain_text_intact() -> None:
    content = "Plain text mentioning Foo."
    assert mask_unsafe(content) == content


def test_concept_with_regex_metacharacters_is_escaped() -> None:
    """A concept like "C++" must be matched literally, not as a regex."""
    out = link_first_occurrence(
        "About C++ here.",
        build_pattern("C++"),
        "concepts/C++",
    )
    assert out == "About [[concepts/C++]] here."


def test_metacharacter_concept_does_not_match_other_text() -> None:
    """Without escaping, "C++" would also match "C" followed by anything."""
    content = "About C and D here."
    assert (
        link_first_occurrence(content, build_pattern("C++"), "concepts/C++") == content
    )


# ─── regression: the title must not be split inside a path ───────────


def test_title_inside_a_path_is_not_split() -> None:
    """``concepts/Foo`` must not become ``concepts/[[concepts/Foo]]``.

    The title pattern refuses to match next to a slash, so a mention
    written as a path is left alone (the path form is handled separately).
    """
    content = "See the concepts/Foo page for details."
    assert link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo") == content


def test_bare_title_is_still_matched_next_to_a_path() -> None:
    """A title that happens to follow a path is still linkable."""
    content = "In concepts/, Foo is mentioned plainly."
    out = link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo")
    assert "concepts/[[concepts/Foo]]" not in out
    assert "[[concepts/Foo]] is mentioned" in out


def test_heading_is_not_rewritten() -> None:
    """The page's own H1 title must stay plain."""
    content = "# Foo\n\nFoo is a concept here.\n"
    out = link_first_occurrence(content, build_pattern("Foo"), "concepts/Foo")
    assert out.startswith("# Foo\n")
    assert "[[concepts/Foo]] is a concept" in out


# ─── regression: don't add a second link to the same page ────────────


def test_is_linked_accepts_qualified_and_bare_forms() -> None:
    assert is_linked("See [[concepts/Foo]] first.", "concepts/Foo")
    assert is_linked("See [[Foo]] first.", "concepts/Foo")
    assert is_linked("See [[concepts/Foo|alias]] first.", "concepts/Foo")
    assert is_linked("See [[concepts/Foo#sec]] first.", "concepts/Foo")
    assert not is_linked("See Foo first.", "concepts/Foo")
