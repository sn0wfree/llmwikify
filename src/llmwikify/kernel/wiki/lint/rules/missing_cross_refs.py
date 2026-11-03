"""Rule: detect concepts mentioned in 2+ pages but not wikilinked."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from ...constants import (
    MAX_CROSS_REF_HINTS,
    MAX_MISSING_DISPLAY,
    MIN_MISSING_REF_COUNT,
)
from ...patterns import concept_pattern, path_pattern
from .. import CrossPageRule

if TYPE_CHECKING:
    from ...wiki import Wiki

logger = logging.getLogger(__name__)

#: Longest title (in words) that may be matched as a bare title. Longer
#: titles are still matched when written as a full path.
MAX_TITLE_WORDS = 4

#: A word sequence shared by more candidates than this is too generic to
#: be useful as an index key ("page" in a wiki full of "Page 12" titles).
#: Such a sequence is dropped — mentioning those pages is not worth the
#: scan cost, and skipping them keeps the rule conservative.
MAX_CANDIDATES_PER_GRAM = 30

#: Words are the unit of the inverted index below.
_WORD_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return _WORD_RE.findall(text.lower())


def _build_inverted_index(
    candidates: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build gram → candidate maps for bare titles and full paths.

    Matching every candidate against every page is quadratic: on a
    1400-page wiki the regex scan alone takes minutes. Instead each
    candidate is indexed by the word sequences it can be written as, and
    each page is scanned once for its own word sequences. Only the
    candidates a page actually mentions ever reach the regex stage.

    Sequences that are too generic (see ``MAX_CANDIDATES_PER_GRAM``) are
    dropped, otherwise a common word pulls every candidate into scope and
    the scan degrades back to quadratic.
    """
    title_index: dict[str, list[str]] = {}
    path_index: dict[str, list[str]] = {}

    for page_name in candidates:
        title = page_name.rsplit("/", 1)[-1]
        words = _tokenize(title)
        if 0 < len(words) <= MAX_TITLE_WORDS:
            for n in range(1, len(words) + 1):
                for i in range(len(words) - n + 1):
                    gram = " ".join(words[i : i + n])
                    title_index.setdefault(gram, []).append(page_name)
        if "/" in page_name:
            path_words = _tokenize(page_name)
            if path_words:
                path_index.setdefault(" ".join(path_words), []).append(page_name)

    def prune(index: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            gram: names
            for gram, names in index.items()
            if len(names) <= MAX_CANDIDATES_PER_GRAM
        }

    return prune(title_index), prune(path_index)


class MissingCrossRefsRule(CrossPageRule):
    """Find concepts mentioned in 2+ pages but not wikilinked.

    Extracted from ``WikiAnalyzer._detect_missing_cross_refs``.
    Behavior is preserved.
    """

    name = "missing_cross_ref"
    max_results = MAX_CROSS_REF_HINTS

    def detect_all(
        self,
        pages: dict[str, str],
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        existing_pages = set(pages.keys())
        concept_mentions: dict[str, list[str]] = {}
        skip_names = {wiki._index_page_name, wiki._log_page_name}

        # Page names carry a directory prefix ("concepts/Risk Parity") while
        # prose usually says "Risk Parity" — both forms count as a mention.
        # A title shared by two pages is ambiguous, so only the fully
        # qualified form may match for those. Sorting keeps the outcome
        # independent of set iteration order (PYTHONHASHSEED).
        title_to_page: dict[str, str] = {}
        ambiguous: set[str] = set()
        for page_name in sorted(existing_pages):
            title = page_name.rsplit("/", 1)[-1]
            if title in title_to_page and title_to_page[title] != page_name:
                ambiguous.add(title)
            else:
                title_to_page[title] = page_name

        # Precompute: strip wikilinks + lowercase once per page.
        stripped: dict[str, str] = {}
        linked: dict[str, set[str]] = {}
        for page_name, content in pages.items():
            targets: set[str] = set()
            for link in re.findall(r"\[\[(.*?)\]\]", content):
                target = wiki._parse_wikilink_target(link)
                if target in skip_names:
                    continue
                # Accept both link forms: "Gold" and "concepts/Gold".
                targets.add(target)
                targets.add(title_to_page.get(target, target))
            linked[page_name] = targets
            stripped[page_name] = re.sub(r"\[\[.*?\]\]", "", content).lower()

        # Compile patterns once; skip names too short for meaningful matching.
        candidates = sorted(
            c
            for c in existing_pages
            if len(c.rsplit("/", 1)[-1]) >= 3 and not c.startswith("Query:")
        )
        title_patterns: dict[str, re.Pattern] = {}
        path_patterns: dict[str, re.Pattern] = {}
        for c in candidates:
            title = c.rsplit("/", 1)[-1]
            if title not in ambiguous:
                title_patterns[c] = concept_pattern(title)
            if "/" in c:
                path_patterns[c] = path_pattern(c)

        title_index, path_index = _build_inverted_index(candidates)

        for page_name, content_text_l in stripped.items():
            page_links = linked[page_name]
            words = _tokenize(content_text_l)
            word_set = set(words)
            # Cheap inverted-index lookup narrows the candidates down to
            # the ones this page could possibly mention.
            mentioned: set[str] = set()
            for n in range(1, MAX_TITLE_WORDS + 1):
                if n > len(words):
                    break
                for i in range(len(words) - n + 1):
                    gram = " ".join(words[i : i + n])
                    mentioned.update(title_index.get(gram, ()))
                    mentioned.update(path_index.get(gram, ()))
            for candidate in mentioned:
                if candidate == page_name or candidate in page_links:
                    continue
                # Second cheap gate: every word of the title must occur
                # on the page. This rejects hits the word-sequence index
                # produced from a different word order.
                title_words = _tokenize(candidate.rsplit("/", 1)[-1])
                if title_words and not all(w in word_set for w in title_words):
                    continue
                title_hit = title_patterns.get(candidate)
                path_hit = path_patterns.get(candidate)
                if (title_hit and title_hit.search(content_text_l)) or (
                    path_hit and path_hit.search(content_text_l)
                ):
                    concept_mentions.setdefault(candidate, []).append(page_name)

        for concept, pages_list in sorted(
            concept_mentions.items(), key=lambda x: (-len(x[1]), x[0])
        ):
            if len(pages_list) >= MIN_MISSING_REF_COUNT:
                results.append(
                    {
                        "type": self.name,
                        "concept": concept,
                        "concept_title": concept.rsplit("/", 1)[-1],
                        "mentioning_pages": pages_list[:MAX_MISSING_DISPLAY],
                        "mention_count": len(pages_list),
                        "observation": (
                            f"'{concept}' is mentioned in {len(pages_list)} pages ({', '.join(pages_list[:3])}"
                            f"{'...' if len(pages_list) > 3 else ''}) but not linked. "
                            f"Consider adding [[{concept}]] wikilinks."
                        ),
                    }
                )

            if len(results) >= self.max_results:
                break
