"""Track C: incremental knowledge enrichment right after an ingest.

Track A (``auto_ingest``) writes the pages an LLM produced from a fresh
document; Track B (``gap_filler``) re-checks the whole wiki on a weekly
timer. Neither looks at what the *new* document did to the rest of the
knowledge base — a document lands and the wiki is left with pages that
nobody links to and concepts that exist only in one file.

This module closes that gap. It runs right after Track A wrote its pages
and does three things:

1. **Cross-reference repair** — a concept the new document is about (or
   that it explicitly cross-references) but that other pages mention in
   plain text only, gets a wikilink at its first mention. Mechanical,
   written straight to the page.
2. **Orphan source repair** — a source page from the new document that
   nothing references gets linked from the pages that mention it.
   Mechanical, written straight to the page.
3. **Missing page proposal** — a page the LLM suggested for the document
   but that does not exist yet becomes a *proposal* for a human to
   review, reusing the existing ``WikiDreamProposalManager`` queue.

The units to work on come from the LLM analysis of the document:
``cross_refs`` (existing pages the document relates to) and
``suggested_pages`` (pages worth creating), plus the pages the ingest
actually wrote. Unlike Track B this never scans the whole wiki — the two
tracks therefore complement each other instead of overlapping.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.wiki.dream_editor import WikiDreamProposalManager

from .config import EnricherConfig
from .wikilink import build_pattern, is_linked, link_first_occurrence

logger = logging.getLogger(__name__)

#: Page directories that hold concept-like knowledge units.
_CONCEPT_DIRS = ("concepts", "entities", "comparisons", "synthesis", "claims")

#: Source pages live in their own directory and are enriched separately.
_SOURCE_DIR = "sources"

#: Every directory a knowledge unit may live in. A cross-reference may
#: name a page by its bare title, so all of them are search roots.
_PAGE_DIRS = _CONCEPT_DIRS + (_SOURCE_DIR,)

#: The wiki's own structural pages. They live at the wiki root and are
#: never knowledge units to enrich.
_STRUCTURAL_PAGES = frozenset({"index", "log", "overview"})


@dataclass
class EnrichResult:
    """Summary of one enrichment pass."""

    concepts_checked: int = 0
    sources_checked: int = 0
    links_added: int = 0
    pages_touched: int = 0
    proposals_created: int = 0
    errors: int = 0
    skipped_units: int = 0
    skipped: bool = False
    ran_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "concepts_checked": self.concepts_checked,
            "sources_checked": self.sources_checked,
            "links_added": self.links_added,
            "pages_touched": self.pages_touched,
            "proposals_created": self.proposals_created,
            "errors": self.errors,
            "skipped_units": self.skipped_units,
            "skipped": self.skipped,
            "ran_at": self.ran_at,
        }


def collect_units(
    exec_result: dict[str, Any] | None,
    analysis: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Extract the units an ingest introduced.

    Args:
        exec_result: Result of ``wiki.execute_operations()`` — its
            ``results`` list carries the page name of every write.
        analysis: The ``analysis`` block of ``wiki._llm_process_source()``
            — holds ``cross_refs`` (existing pages the document relates
            to) and ``suggested_pages`` (pages worth creating).

    Returns:
        ``(concept_pages, source_pages, suggested_pages)``.
    """
    concepts: list[str] = []
    sources: list[str] = []
    suggested: list[str] = []

    def add(name: str) -> None:
        """Classify a page name into concept / source buckets.

        Pages written by the ingest normally carry a directory prefix
        (``concepts/Foo``). A bare name means the page landed at the
        wiki root — the LLM omitted ``page_type`` — and it is still a
        knowledge unit worth enriching, so everything that is not a
        source page goes to the concept bucket. The wiki's own
        structural pages (index/log/overview) are excluded.
        """
        name = (name or "").strip().strip("/")
        if not name:
            return
        if name.startswith(f"{_SOURCE_DIR}/"):
            if name not in sources:
                sources.append(name)
        elif name in _STRUCTURAL_PAGES:
            return
        elif name not in concepts:
            concepts.append(name)

    if exec_result:
        for item in exec_result.get("results", []) or []:
            if item.get("action") == "write_page" and item.get("status") == "done":
                add(str(item.get("page", "")))

    if analysis:
        # cross_refs name existing pages — the LLM may use the bare title
        # ("Risk Parity") or the qualified path ("concepts/Risk Parity").
        for name in analysis.get("cross_refs", []) or []:
            if isinstance(name, str) and name.strip():
                add(name)
        for item in analysis.get("suggested_pages", []) or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                name = name.strip()
                if name not in suggested:
                    suggested.append(name)

    return concepts, sources, suggested


class KnowledgeEnricher:
    """Per-wiki incremental enrichment (Track C).

    All blocking wiki calls go through ``asyncio.to_thread``.

    The enricher makes no LLM calls: cross-reference repair is pure text
    work and missing pages become proposals with a stub body. It
    therefore carries neither an LLM semaphore nor a rate limiter — the
    wiki reads and writes are bounded by the caller's own concurrency
    instead.
    """

    def __init__(
        self,
        wiki: Any,
        wiki_id: str,
        config: EnricherConfig,
        proposal_manager: WikiDreamProposalManager | None = None,
    ) -> None:
        self.wiki = wiki
        self.wiki_id = wiki_id
        self.config = config
        self._proposal_manager = proposal_manager or WikiDreamProposalManager(
            wiki_id=wiki_id,
        )
        # Pages already proposed in this pass — the same suggestion must
        # not queue two identical proposals.
        self._proposed_pages: set[str] = set()
        self.last_result: EnrichResult | None = None

    async def enrich(
        self,
        llm_result: dict[str, Any] | None = None,
        exec_result: dict[str, Any] | None = None,
    ) -> EnrichResult:
        """Enrich the knowledge base around the units of one ingest.

        Args:
            llm_result: Result of ``wiki._llm_process_source()`` — its
                ``analysis`` block drives cross-refs and suggestions.
            exec_result: Result of ``wiki.execute_operations()`` — tells
                which pages the ingest actually wrote.
        """
        result = EnrichResult()
        if not self.config.enabled:
            result.skipped = True
            self.last_result = result
            return result

        analysis = (llm_result or {}).get("analysis") or {}
        concepts, sources, suggested = collect_units(exec_result, analysis)
        result.concepts_checked = len(concepts)
        result.sources_checked = len(sources)

        budget = max(0, self.config.max_units_per_doc)
        for concept_page in concepts:
            if budget <= 0:
                break
            budget -= 1
            try:
                await self._link_references(concept_page, result)
            except Exception as exc:
                result.errors += 1
                logger.warning(
                    "[%s] enricher failed on %s: %s",
                    self.wiki_id,
                    concept_page,
                    exc,
                )

        for source_page in sources:
            if budget <= 0:
                break
            budget -= 1
            try:
                await self._link_references(source_page, result)
            except Exception as exc:
                result.errors += 1
                logger.warning(
                    "[%s] enricher failed on %s: %s",
                    self.wiki_id,
                    source_page,
                    exc,
                )

        for name in suggested:
            if budget <= 0:
                break
            budget -= 1
            try:
                await self._propose_page(name, result)
            except Exception as exc:
                result.errors += 1
                logger.warning(
                    "[%s] enricher failed to propose %s: %s",
                    self.wiki_id,
                    name,
                    exc,
                )

        self.last_result = result
        logger.info(
            "[%s] enricher: %d concept(s), %d source(s) checked — "
            "%d link(s) added, %d proposal(s), %d error(s)",
            self.wiki_id,
            result.concepts_checked,
            result.sources_checked,
            result.links_added,
            result.proposals_created,
            result.errors,
        )
        return result

    # ── types 1 & 2: cross-reference / orphan-source repair ──────────

    async def _link_references(self, page_name: str, result: EnrichResult) -> None:
        """Link pages that mention ``page_name`` but never link to it."""
        # Resolve to the real page path so the link we insert is the
        # canonical one even when the LLM named the page by title. A name
        # that resolves to nothing would produce a link to a page that
        # does not exist — skip it instead.
        target = await self._resolve_page(page_name)
        if target is None:
            result.skipped_units += 1
            return
        title = target.rsplit("/", 1)[-1]
        pattern = build_pattern(title)
        candidates = await self._pages_mentioning(title)
        touched = 0
        for candidate in candidates:
            if candidate == target:
                continue
            if touched >= self.config.max_links_per_unit:
                break
            page = await asyncio.to_thread(self.wiki.read_page, candidate)
            if page.get("error") or page.get("is_sink"):
                continue
            content = page.get("content", "")
            if is_linked(content, target):
                continue
            if not self._has_plain_mention(content, pattern):
                continue
            new_content = link_first_occurrence(content, pattern, target)
            if new_content == content:
                continue
            await asyncio.to_thread(self.wiki.write_page, candidate, new_content)
            result.links_added += 1
            touched += 1
            result.pages_touched += 1

    # ── type 3: missing page → proposal ──────────────────────────────

    async def _propose_page(self, name: str, result: EnrichResult) -> None:
        """Queue a page proposal when the suggested page does not exist."""
        if not self.config.propose_missing_pages:
            return
        target = await self._resolve_page(name)
        if target is not None:
            return
        if name in self._proposed_pages:
            return
        self._proposed_pages.add(name)
        related = await self._pages_mentioning(name)
        links = "".join(f"- [[{page}]]\n" for page in related[:5])
        content = (
            f"# {name}\n\n"
            f"Auto-generated stub by enricher "
            f"(page suggested while ingesting a new source).\n\n"
            f"## Overview\n\n(pending human review)\n\n"
            f"## Related\n\n{links}"
        )
        await asyncio.to_thread(
            self._proposal_manager.create_proposal,
            name,
            "create",
            content,
            "enricher: page suggested by the new source has no page yet",
            [{"source_name": name}],
        )
        result.proposals_created += 1

    # ── helpers ─────────────────────────────────────────────────────

    async def _resolve_page(self, name: str) -> str | None:
        """Resolve a name to the page it refers to, or None when absent.

        The LLM may name a page by title ("Risk Parity") or by qualified
        path ("concepts/Risk Parity"); both must resolve.
        """
        candidates = [name]
        if "/" not in name:
            candidates = [f"{d}/{name}" for d in _PAGE_DIRS] + [name]
        for candidate in candidates:
            page = await asyncio.to_thread(self.wiki.read_page, candidate)
            if not page.get("error"):
                return candidate
        return None

    async def _pages_mentioning(self, title: str) -> list[str]:
        """Pages whose indexed content mentions ``title``."""
        try:
            hits = await asyncio.to_thread(self.wiki.search, title, 10)
        except TypeError:
            hits = await asyncio.to_thread(self.wiki.search, title)
        except Exception as exc:
            logger.warning(
                "[%s] enricher search failed for %s: %s", self.wiki_id, title, exc
            )
            return []
        names: list[str] = []
        for hit in hits or []:
            name = hit.get("page_name") if isinstance(hit, dict) else None
            if isinstance(name, str) and name:
                names.append(name)
        return names

    @staticmethod
    def _has_plain_mention(content: str, pattern: re.Pattern) -> bool:
        """True when the concept appears as plain text (not already linked)."""
        stripped = re.sub(r"\[\[.*?\]\]", "", content)
        return bool(pattern.search(stripped))

    def status(self) -> dict[str, Any]:
        last = self.last_result
        return {
            "wiki_id": self.wiki_id,
            "enabled": self.config.enabled,
            "last_run": last.as_dict() if last else None,
        }
