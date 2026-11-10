"""Shared wikilink insertion helper.

Both maintenance tracks need the same non-trivial step: put a wikilink on
the first plain-text mention of a concept **without** corrupting the
surrounding content.

Classes of corruption to avoid:

1. Inserting inside an existing wikilink — ``See [[Foo|the docs]] first. Foo
   later.`` must become ``See [[Foo|the docs]] first. [[Foo]] later.``
2. Inserting inside a region where a link does not belong — a URL
   (``https://example.com/Foo``), inline code (`` `Foo` ``), a fenced code
   block, a markdown link (``[the Foo docs](url)``) or a heading
   (``# Foo``). Blind insertion turns ``https://example.com/Foo`` into
   ``https://example.com/[[concepts/Foo]]``, i.e. a broken URL.
3. Inserting a second link to a page that is already linked — the page
   would end up mentioning it twice.

All three are handled by blanking the unsafe regions first (replacing them
with spaces of the same length, so every offset stays valid) and then
searching the blanked copy.
"""

from __future__ import annotations

import re

from llmwikify.kernel.wiki.patterns import concept_pattern

#: Regions where a wikilink must never be inserted.
#:
#: Order matters: structural regions (code, markdown links, wikilinks) are
#: blanked before the bare-URL rule, because the URL pattern is greedy
#: enough to swallow a trailing ``)`` — which would then break the
#: markdown-link pattern that runs after it.
_UNSAFE_REGIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"```.*?```", re.DOTALL),  # fenced code block
    re.compile(r"`[^`\n]*`"),  # inline code
    re.compile(r"^[ \t]*#{1,6}[ \t].*$", re.MULTILINE),  # markdown heading
    re.compile(r"\[[^\]\n]*\]\([^)\n]*\)"),  # markdown link
    re.compile(r"\[\[.*?\]\]"),  # existing wikilink
    re.compile(r"https?://\S+"),  # bare URL
)


def _blank(text: str) -> str:
    """Replace a matched region with spaces, preserving length."""
    return " " * len(text)


def mask_unsafe(content: str) -> str:
    """Return ``content`` with link-hostile regions blanked out.

    Offsets in the result map one-to-one onto ``content``, so a match
    found here can be applied to the original.
    """
    masked = content
    for pattern in _UNSAFE_REGIONS:
        masked = pattern.sub(lambda m: _blank(m.group(0)), masked)
    return masked


def is_linked(content: str, target: str) -> bool:
    """True when ``content`` already links to ``target``.

    Both the qualified form (``[[concepts/Risk Parity]]``) and the bare
    title (``[[Risk Parity]]``) count — they name the same page.
    """
    title = target.rsplit("/", 1)[-1]
    for match in re.finditer(r"\[\[([^\]]+)\]\]", content):
        link = match.group(1).split("|")[0].split("#")[0].strip()
        if link == target or link.rsplit("/", 1)[-1] == title:
            return True
    return False


def link_first_occurrence(content: str, pattern: re.Pattern, concept: str) -> str:
    """Replace the first eligible plain-text mention with ``[[concept]]``.

    Args:
        content: Page body to rewrite.
        pattern: Word-boundary pattern for the concept (case-insensitive).
        concept: Link target written inside the brackets.

    Returns:
        Updated content, or the original when no eligible mention exists.
    """
    hit = pattern.search(mask_unsafe(content))
    if not hit:
        return content
    return content[: hit.start()] + f"[[{concept}]]" + content[hit.end() :]


def link_markdown_citation(content: str, pattern: re.Pattern, concept: str) -> str:
    """Link a markdown citation that mentions the concept.

    Source pages are often cited only as ``[Source: Title](raw/...)``.
    ``link_first_occurrence`` refuses those regions (inserting inside a
    markdown link would corrupt it), but lint still counts the title as a
    plain mention — so the fixer must place the wikilink beside the
    citation rather than inside it.
    """
    for match in re.finditer(r"\[([^\]\n]+)\]\(([^)\n]+)\)", content):
        text = match.group(1)
        if "[[" in text or not pattern.search(text):
            continue
        return content[: match.start()] + f"[[{concept}]] " + content[match.start() :]
    return content


def build_pattern(concept: str) -> re.Pattern:
    """Word-boundary pattern for a concept name (case-insensitive).

    Delegates to :func:`llmwikify.kernel.wiki.patterns.concept_pattern` so
    the lint rule and the fixer match concepts identically.
    """
    return concept_pattern(concept)
