"""Track B: lint-driven knowledge-gap detection and proposal-based filling.

Two gap classes with different write policies (user decision):

- missing_cross_ref  → mechanical fix: insert [[concept]] wikilink at first
  word-boundary occurrence in each mentioning page. Auto-approved (no LLM).
- unreferenced_entity → content generation: LLM drafts a new page via the
  wiki's own analyze/synthesize prompt chain, queued as a proposal for
  human review (WikiDreamProposalManager).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager

from .config import GapFillerConfig

logger = logging.getLogger(__name__)


@dataclass
class GapItem:
    """A prioritized knowledge gap extracted from lint results."""

    gap_type: str
    priority: int
    data: dict[str, Any]
    concept: str = ""


@dataclass
class GapCycleResult:
    """Summary of one gap-filling cycle (for health history)."""

    detected: int = 0
    processed: int = 0
    mechanical_fixes: int = 0
    proposals_created: int = 0
    skipped_low_priority: int = 0
    errors: int = 0
    ran_at: float = field(default_factory=time.time)


def calc_priority(gap: dict[str, Any]) -> int:
    """Priority score 0-100 (design doc §Gap priority)."""
    gap_type = gap.get("type", "")
    mentions = int(gap.get("mention_count", 1) or 1)
    if gap_type == "unreferenced_entity":
        return min(100, 50 + mentions * 10)
    if gap_type == "missing_cross_ref":
        return min(80, 30 + mentions * 10)
    if gap_type == "isolated_source":
        return 20
    if gap_type == "potentially_outdated":
        return 25
    return 0


def extract_gaps(lint_result: dict[str, Any]) -> list[GapItem]:
    """Extract gap items from ``wiki.lint()`` result (hints + investigations)."""
    found: list[GapItem] = []
    seen: set[tuple[str, str]] = set()

    hints = lint_result.get("hints", {}) or {}
    for item in hints.get("informational", []) or []:
        gap_type = item.get("type", "")
        concept = str(item.get("concept", ""))
        if gap_type not in ("missing_cross_ref", "unreferenced_entity"):
            continue
        if (gap_type, concept) in seen:
            continue
        seen.add((gap_type, concept))
        found.append(GapItem(gap_type=gap_type, priority=calc_priority(item), data=item, concept=concept))

    investigations = lint_result.get("investigations", {}) or {}
    for item in investigations.get("knowledge_gaps", []) or []:
        gap_type = item.get("type", "")
        concept = str(item.get("concept", item.get("page", "")))
        if gap_type not in ("unreferenced_entity", "isolated_source"):
            continue
        if (gap_type, concept) in seen:
            continue
        seen.add((gap_type, concept))
        found.append(GapItem(gap_type=gap_type, priority=calc_priority(item), data=item, concept=concept))

    return sorted(found, key=lambda g: g.priority, reverse=True)


class GapFiller:
    """Per-wiki gap filler. All blocking calls go through ``to_thread``."""

    def __init__(
        self,
        wiki: Any,
        wiki_id: str,
        config: GapFillerConfig,
        llm_semaphore: asyncio.Semaphore,
        proposal_manager: WikiDreamProposalManager | None = None,
    ) -> None:
        self.wiki = wiki
        self.wiki_id = wiki_id
        self.config = config
        self.llm_semaphore = llm_semaphore
        self._proposal_manager = proposal_manager or WikiDreamProposalManager(
            wiki_id=wiki_id,
        )
        self.last_result: GapCycleResult | None = None

    async def run_cycle(self) -> GapCycleResult:
        """Detect gaps once, then fill high-priority ones (mechanical or proposal)."""
        result = GapCycleResult()
        try:
            lint_result = await asyncio.to_thread(
                self.wiki.lint, mode="check",
            )
        except Exception as exc:
            result.errors += 1
            logger.warning("[%s] gap_filler lint failed: %s", self.wiki_id, exc)
            self.last_result = result
            return result

        gaps = extract_gaps(lint_result)
        result.detected = len(gaps)

        budget = self.config.max_per_cycle
        for gap in gaps:
            if gap.priority < self.config.min_priority:
                result.skipped_low_priority += 1
                continue
            if budget <= 0:
                result.skipped_low_priority += 1
                continue
            budget -= 1
            try:
                if gap.gap_type == "missing_cross_ref":
                    fixed = await self._fix_missing_cross_ref(gap)
                    result.mechanical_fixes += fixed
                elif gap.gap_type == "unreferenced_entity":
                    created = await self._propose_entity_page(gap)
                    result.proposals_created += created
                result.processed += 1
            except Exception as exc:
                result.errors += 1
                logger.warning(
                    "[%s] gap_filler failed on %s/%s: %s",
                    self.wiki_id, gap.gap_type, gap.concept, exc,
                )

        self.last_result = result
        logger.info(
            "[%s] gap_filler: %d detected, %d processed "
            "(%d mechanical, %d proposals, %d errors)",
            self.wiki_id, result.detected, result.processed,
            result.mechanical_fixes, result.proposals_created, result.errors,
        )
        return result

    # ── mechanical fix: missing_cross_ref ──────────────────────────────

    async def _fix_missing_cross_ref(self, gap: GapItem) -> int:
        """Insert ``[[concept]]`` at first plain-text occurrence per mentioning page.

        Returns number of pages actually modified. Mirrors the rule's own
        word-boundary detection (missing_cross_refs.py:52-53) so a fixed
        page no longer triggers the rule.
        """
        if not self.config.auto_approve_mechanical:
            return 0
        concept = gap.concept
        if not concept:
            return 0
        pattern = re.compile(r"\b" + re.escape(concept) + r"\b", re.IGNORECASE)
        fixed = 0
        for page_name in gap.data.get("mentioning_pages", []):
            page = await asyncio.to_thread(self.wiki.read_page, page_name)
            if page.get("error") or page.get("is_sink"):
                continue
            content = page.get("content", "")
            stripped = re.sub(r"\[\[.*?\]\]", "", content)
            if not pattern.search(stripped):
                continue
            # replace first occurrence OUTSIDE any existing wikilink
            new_content = self._link_first_occurrence(content, pattern, concept)
            if new_content == content:
                continue
            await asyncio.to_thread(self.wiki.write_page, page_name, new_content)
            fixed += 1
        return fixed

    @staticmethod
    def _link_first_occurrence(content: str, pattern: re.Pattern, concept: str) -> str:
        """Replace the first non-wikilink word-boundary match with ``[[concept]]``."""
        out: list[str] = []
        pos = 0
        for m in re.finditer(r"\[\[.*?\]\]", content):
            before = content[pos:m.start()]
            hit = pattern.search(before)
            if hit:
                out.append(before[:hit.start()])
                out.append(f"[[{concept}]]")
                out.append(before[hit.end():])
                out.append(content[m.start():])
                return "".join(out)
            out.append(before)
            out.append(m.group(0))
            pos = m.end()
        tail = content[pos:]
        hit = pattern.search(tail)
        if hit:
            out.append(tail[:hit.start()])
            out.append(f"[[{concept}]]")
            out.append(tail[hit.end():])
            return "".join(out)
        return content

    # ── content generation: unreferenced_entity ────────────────────────

    async def _propose_entity_page(self, gap: GapItem) -> int:
        """Draft a page for an orphan concept; queue as proposal for review."""
        concept = gap.concept
        if not concept:
            return 0
        try:
            related = await asyncio.to_thread(self.wiki.search, concept, 5)
        except TypeError:
            related = await asyncio.to_thread(self.wiki.search, concept)
        except Exception as exc:
            logger.warning("[%s] gap_filler search failed for %s: %s", self.wiki_id, concept, exc)
            related = []

        related_names = [
            r.get("page_name") or r.get("name") or str(r)
            for r in (related or [])[:5]
        ]
        draft = (
            f"# {concept}\n\n"
            f"Auto-generated stub by gap_filler "
            f"(unreferenced entity detected by lint).\n\n"
            f"## Overview\n\n(pending human review)\n\n"
            f"## Related\n\n"
            + "".join(f"- [[{n}]]\n" for n in related_names if n and n != concept)
        )
        self._proposal_manager.create_proposal(
            page_name=concept,
            edit_type="create",
            content=draft,
            reason=f"gap_filler: unreferenced_entity (priority {gap.priority})",
        )
        return 1

    def status(self) -> dict[str, Any]:
        last = self.last_result
        return {
            "wiki_id": self.wiki_id,
            "last_cycle": {
                "detected": last.detected,
                "processed": last.processed,
                "mechanical_fixes": last.mechanical_fixes,
                "proposals_created": last.proposals_created,
                "skipped_low_priority": last.skipped_low_priority,
                "errors": last.errors,
                "ran_at": last.ran_at,
            } if last else None,
        }
