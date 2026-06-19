"""Dream — 2-phase fact extractor (Phase 6).

Borrowed from nanobot agent/memory.py:859 (Dream class).

Two-phase memory processor:

  Phase 1 (analysis):
    Read ``memory_consolidations`` since the last dream cursor (or all
    if first run). Group by session, fetch the summary text, batch into
    ``max_batch_size`` chunks.

  Phase 2 (extraction):
    Call the LLM to extract durable facts from each batch. Each fact is
    written to BOTH:
      1. SQLite ``memory_facts`` table (raw fact + source_session_id)
      2. Filesystem ``~/.llmwikify/memory/facts/`` (per-fact .md + index)

Cursor persistence:
  ``~/.llmwikify/memory/.dream_cursor`` stores the last-run timestamp
  so subsequent runs are incremental. Mirrors nanobot's cursor file.

Triggering (set up in Step 4):
  - ``/dream`` slash command (via ``DreamSkill``)
  - APScheduler daily 03:00 (via ``DreamScheduler``)

Design notes (apply-plan §6.2):

  - ``run()`` is the main entry; returns ``DreamResult`` with counts.
  - Phase 1 LLM call is fail-soft (returns empty list on failure).
  - Markdown write is optional (``enable_md_write=False`` skips).
  - Cursor updated only on successful Phase 2 (atomic commit pattern).

Phase 6 (2026-06-19). See ``docs/poc/compare.md`` §10.8.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.memory.consolidation_store import (
    MemoryConsolidationStore,
)
from llmwikify.apps.chat.memory.facts_store import (
    FactSource,
    MemoryFactsStore,
)

logger = logging.getLogger(__name__)


@dataclass
class DreamConfig:
    """Configuration for Dream background processor."""

    max_batch_size: int = 20
    max_iterations: int = 10
    enable_md_write: bool = True
    stale_threshold_days: int = 14
    timeout_seconds: float = 300.0
    min_consolidations_to_run: int = 1


@dataclass
class DreamResult:
    """Outcome of one Dream run."""

    consolidations_scanned: int
    facts_extracted: int
    facts_written: int
    cursor: float
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "consolidations_scanned": self.consolidations_scanned,
            "facts_extracted": self.facts_extracted,
            "facts_written": self.facts_written,
            "cursor": self.cursor,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ─── LLM prompt (new, not reused) ────────────────────────────────

FACT_EXTRACTION_SYSTEM_PROMPT = (
    "You are a fact extractor. Given a conversation summary, extract "
    "durable facts that should be remembered long-term. A fact is a "
    "concrete statement about the user, their preferences, their work, "
    "or world knowledge they care about. "
    "Output one fact per line, prefixed with '- '. "
    "Skip transient details (timestamps, single-use data). "
    "Aim for 3-10 facts per summary."
)

CURSOR_FILENAME = ".dream_cursor"


class Dream:
    """Two-phase memory processor (borrowed from nanobot).

    Usage:
        dream = Dream(
            memory_manager=mm,
            db=app_db.chat,
            provider=llm_provider,
            data_dir=app_db.data_dir,
        )
        result = await dream.run()  # full incremental scan
        # OR scope to one session:
        result = await dream.run_for_session("s1")
    """

    def __init__(
        self,
        memory_manager: Any,
        db: Any,
        provider: Any,
        data_dir: Path | str,
        config: DreamConfig | None = None,
    ):
        self.memory_manager = memory_manager
        self.db_path = str(getattr(db, "db_path", data_dir))
        self.provider = provider
        self.data_dir = Path(data_dir)
        self.config = config or DreamConfig()

        # Lazy-init stores
        self._consolidation_store: MemoryConsolidationStore | None = None
        self._facts_store: MemoryFactsStore | None = None

        # Filesystem paths
        self._memory_dir = self.data_dir / "memory"
        self._facts_dir = self._memory_dir / "facts"
        self._cursor_path = self._memory_dir / CURSOR_FILENAME

    # ─── lazy properties ─────────────────────────────────────────

    @property
    def consolidation_store(self) -> MemoryConsolidationStore:
        if self._consolidation_store is None:
            self._consolidation_store = MemoryConsolidationStore(self.db_path)
            self._consolidation_store.init_schema()
        return self._consolidation_store

    @property
    def facts_store(self) -> MemoryFactsStore:
        if self._facts_store is None:
            self._facts_store = MemoryFactsStore(self.db_path)
            self._facts_store.init_schema()
        return self._facts_store

    # ─── cursor management ──────────────────────────────────────

    def _read_cursor(self) -> float:
        """Read the dream cursor timestamp. Returns 0.0 if no cursor."""
        try:
            if self._cursor_path.exists():
                return float(self._cursor_path.read_text().strip())
        except (ValueError, OSError):
            logger.warning("Dream: failed to read cursor", exc_info=True)
        return 0.0

    def _write_cursor(self, value: float) -> None:
        """Persist cursor timestamp. Atomic via tmp+rename."""
        try:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self._cursor_path.with_suffix(".tmp")
            tmp_path.write_text(str(value), encoding="utf-8")
            tmp_path.replace(self._cursor_path)
        except OSError:
            logger.warning("Dream: failed to write cursor", exc_info=True)

    # ─── public API ─────────────────────────────────────────────

    async def run(self) -> DreamResult:
        """Run incremental Dream scan (since last cursor).

        Returns ``DreamResult``. Never raises; logs and continues on errors.
        """
        start = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._run_impl(),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Dream: timed out after %.0fs", self.config.timeout_seconds)
            return DreamResult(
                consolidations_scanned=0,
                facts_extracted=0,
                facts_written=0,
                cursor=self._read_cursor(),
                elapsed_seconds=time.monotonic() - start,
            )
        except Exception:
            logger.exception("Dream: run failed")
            return DreamResult(
                consolidations_scanned=0,
                facts_extracted=0,
                facts_written=0,
                cursor=self._read_cursor(),
                elapsed_seconds=time.monotonic() - start,
            )

    async def _run_impl(self) -> DreamResult:
        start_mono = time.monotonic()
        cursor = self._read_cursor()
        records = self.consolidation_store.list_since(cursor)
        if len(records) < self.config.min_consolidations_to_run:
            logger.debug("Dream: nothing to process (%d consolidations)", len(records))
            return DreamResult(
                consolidations_scanned=len(records),
                facts_extracted=0,
                facts_written=0,
                cursor=cursor,
                elapsed_seconds=time.monotonic() - start_mono,
            )

        # Batch
        facts_extracted_total = 0
        facts_written_total = 0
        last_consolidation_ts = cursor
        for batch in self._batched(records, self.config.max_batch_size):
            facts = await self._extract_facts(batch)
            facts_extracted_total += len(facts)
            written = await self._write_facts(facts)
            facts_written_total += written
            # Track the latest consolidation timestamp in this batch
            last_consolidation_ts = max(
                last_consolidation_ts,
                max(r.created_at for r in batch),
            )

        # Update cursor atomically
        if last_consolidation_ts > cursor:
            self._write_cursor(last_consolidation_ts)

        return DreamResult(
            consolidations_scanned=len(records),
            facts_extracted=facts_extracted_total,
            facts_written=facts_written_total,
            cursor=last_consolidation_ts if last_consolidation_ts > cursor else cursor,
            elapsed_seconds=time.monotonic() - start_mono,
        )

    async def run_for_session(self, session_id: str) -> DreamResult:
        """Run Dream for one specific session (regardless of cursor)."""
        start = time.monotonic()
        records = self.consolidation_store.list_by_session(session_id)
        if not records:
            return DreamResult(0, 0, 0, 0.0, 0.0)

        # Reverse so oldest first for processing
        records = list(reversed(records))
        facts_extracted_total = 0
        facts_written_total = 0
        for batch in self._batched(records, self.config.max_batch_size):
            facts = await self._extract_facts(batch)
            facts_extracted_total += len(facts)
            written = await self._write_facts(facts)
            facts_written_total += written

        return DreamResult(
            consolidations_scanned=len(records),
            facts_extracted=facts_extracted_total,
            facts_written=facts_written_total,
            cursor=max(r.created_at for r in records),
            elapsed_seconds=time.monotonic() - start,
        )

    # ─── Phase 1 + 2 ───────────────────────────────────────────

    async def _extract_facts(self, records: list[Any]) -> list[dict[str, Any]]:
        """Phase 2: call LLM to extract facts from a batch of summaries.

        Returns a list of dicts with keys: content, source_session_id,
        confidence (default 1.0).
        """
        # Build batched prompt
        user_content = "Extract durable facts from these conversation summaries:\n\n"
        for r in records:
            user_content += (
                f"--- Session: {r.session_id} (ts={r.created_at:.0f}) ---\n"
                f"{r.summary}\n\n"
            )

        try:
            response = await self.provider.achat(
                messages=[
                    {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            content = (
                response.get("content", "")
                if isinstance(response, dict)
                else str(response)
            )
        except Exception:
            logger.warning("Dream: LLM extraction failed", exc_info=True)
            return []

        # Parse "- fact" lines
        facts: list[dict[str, Any]] = []
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("- "):
                fact_content = line[2:].strip()
            elif re.match(r"^\d+[\.\)]\s", line):
                fact_content = re.sub(r"^\d+[\.\)]\s", "", line).strip()
            else:
                continue
            if len(fact_content) < 5:  # skip noise
                continue
            # Pick the most recent session_id in the batch (best effort)
            source_session_id = records[-1].session_id
            facts.append({
                "content": fact_content,
                "source_session_id": source_session_id,
                "source_type": "dream_extraction",
                "confidence": 1.0,
            })
        return facts

    async def _write_facts(self, facts: list[dict[str, Any]]) -> int:
        """Phase 2 write: SQLite + optional markdown."""
        if not facts:
            return 0
        written = 0
        for f in facts:
            try:
                fid = self.facts_store.add(
                    content=f["content"],
                    source_type=f.get("source_type", "dream_extraction"),
                    source_session_id=f.get("source_session_id"),
                    confidence=f.get("confidence", 1.0),
                )
                written += 1
                if self.config.enable_md_write:
                    self._write_fact_markdown(fid, f)
            except Exception:
                logger.warning("Dream: write_fact failed", exc_info=True)
        return written

    def _write_fact_markdown(
        self, fact_id: str, fact: dict[str, Any]
    ) -> None:
        """Write per-fact markdown + append to index."""
        try:
            self._facts_dir.mkdir(parents=True, exist_ok=True)
            md_path = self._facts_dir / f"{fact_id}.md"
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            body = (
                f"# Fact {fact_id[:8]}\n\n"
                f"- created_at: {timestamp}\n"
                f"- source_session_id: {fact.get('source_session_id', 'N/A')}\n"
                f"- source_type: {fact.get('source_type', 'dream_extraction')}\n"
                f"- confidence: {fact.get('confidence', 1.0)}\n\n"
                f"## Content\n\n{fact['content']}\n"
            )
            md_path.write_text(body, encoding="utf-8")

            # Append to index
            index_path = self._facts_dir / "index.md"
            with index_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"- [{timestamp}] [{fact_id[:8]}] {fact['content']}\n"
                )
        except OSError:
            logger.warning("Dream: markdown write failed", exc_info=True)

    # ─── helpers ───────────────────────────────────────────────

    @staticmethod
    def _batched(items: list, size: int):
        """Yield successive ``size``-sized chunks from ``items``."""
        for i in range(0, len(items), size):
            yield items[i : i + size]


__all__ = ["Dream", "DreamConfig", "DreamResult"]
