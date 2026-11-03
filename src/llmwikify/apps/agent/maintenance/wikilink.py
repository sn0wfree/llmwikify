"""Shared wikilink insertion helper.

Both maintenance tracks need the same non-trivial step: put a wikilink on
the first plain-text mention of a concept **without** corrupting an
existing wikilink that happens to contain the same words.

Example: content ``"See [[Foo|the docs]] first. Foo later."`` must become
``"See [[Foo|the docs]] first. [[Foo]] later."`` — the mention inside the
existing link is skipped.
"""

from __future__ import annotations

import re


def link_first_occurrence(content: str, pattern: re.Pattern, concept: str) -> str:
    """Replace the first non-wikilink word-boundary match with ``[[concept]]``.

    Args:
        content: Page body to rewrite.
        pattern: Word-boundary pattern for the concept (case-insensitive).
        concept: Link target written inside the brackets.

    Returns:
        Updated content, or the original when no eligible mention exists.
    """
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"\[\[.*?\]\]", content):
        before = content[pos : m.start()]
        hit = pattern.search(before)
        if hit:
            out.append(before[: hit.start()])
            out.append(f"[[{concept}]]")
            out.append(before[hit.end() :])
            out.append(content[m.start() :])
            return "".join(out)
        out.append(before)
        out.append(m.group(0))
        pos = m.end()
    tail = content[pos:]
    hit = pattern.search(tail)
    if hit:
        out.append(tail[: hit.start()])
        out.append(f"[[{concept}]]")
        out.append(tail[hit.end() :])
        return "".join(out)
    return content


def build_pattern(concept: str) -> re.Pattern:
    """Word-boundary pattern for a concept name (case-insensitive)."""
    return re.compile(r"\b" + re.escape(concept) + r"\b", re.IGNORECASE)
