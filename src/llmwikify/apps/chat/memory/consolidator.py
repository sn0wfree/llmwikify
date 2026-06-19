"""Consolidator — per-session evict + LLM summarize (Phase 6).

Borrowed from nanobot agent/memory.py:444 (Consolidator class).

When ``AgentContext.messages`` exceeds the token threshold, evict old
messages (keep N most recent), call the LLM to summarize them, and
write the summary to BOTH:

  1. SQLite ``memory_consolidations`` table (raw summary + token counts)
  2. Filesystem ``~/.llmwikify/memory/sessions/{session_id}.md``
     (human-readable markdown)

Design notes (apply-plan.md §6.2):

  - ``maybe_consolidate`` is the main entry; returns ``None`` if no
    consolidation happened (token threshold not reached or throttled).
  - Throttle: ``min_consolidation_interval_sec`` (default 60s) per session.
  - LLM call is async; failures are logged + swallowed (caller continues).
  - Markdown write is optional (``enable_wiki_write=False`` skips it
    for unit tests).
  - Storage path: ``data_dir/memory/sessions/{session_id}.md`` (created
    on first write).

Phase 6 (2026-06-19). See ``docs/poc/compare.md`` §10.8 for full
rationale.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.memory.consolidation_store import (
    ConsolidationRecord,
    MemoryConsolidationStore,
)
from llmwikify.foundation.llm.token_estimator import count_messages

logger = logging.getLogger(__name__)


@dataclass
class ConsolidatorConfig:
    """Configuration for Consolidator."""

    trigger_token_threshold: int = 4000
    keep_recent_messages: int = 8
    min_consolidation_interval_sec: float = 60.0
    summary_max_tokens: int = 1024
    enable_md_write: bool = True


@dataclass
class ConsolidationResult:
    """Outcome of a consolidation attempt (returned to caller)."""

    record: ConsolidationRecord
    md_path: Path | None
    messages_evicted: int
    tokens_before: int
    tokens_after: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "consolidation_id": self.record.id,
            "md_path": str(self.md_path) if self.md_path else None,
            "messages_evicted": self.messages_evicted,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
        }


# ─── LLM summarization prompt (new, not reused from microcompact) ──

SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a memory consolidator. Given a conversation excerpt, "
    "produce a concise summary that preserves: (1) key facts learned, "
    "(2) decisions made, (3) topics discussed. Output ONLY the summary, "
    "no preamble. Aim for ~200-400 words."
)


class Consolidator:
    """Per-session eviction + LLM summarization (borrowed from nanobot).

    Usage:
        consol = Consolidator(
            memory_manager=mm,
            db=app_db.chat,
            provider=llm_provider,
            data_dir=app_db.data_dir,
        )
        result = await consol.maybe_consolidate(
            session_id="abc",
            messages=list(ctx.messages),
            session_tokens=ctx.total_tokens,
        )
        if result:
            ctx.compacted_count += 1
    """

    def __init__(
        self,
        memory_manager: Any,
        db: Any,                       # ChatDatabase (only need .db_path)
        provider: Any,                 # LLMProvider with .achat(messages, ...)
        data_dir: Path | str,
        config: ConsolidatorConfig | None = None,
    ):
        self.memory_manager = memory_manager
        self.db_path = str(getattr(db, "db_path", data_dir))
        self.provider = provider
        self.data_dir = Path(data_dir)
        self.config = config or ConsolidatorConfig()

        # Lazy-init stores
        self._store: MemoryConsolidationStore | None = None

        # Per-session throttling timestamps
        self._last_consolidation: dict[str, float] = {}

        # Memory dir
        self._memory_sessions_dir = self.data_dir / "memory" / "sessions"

    # ─── lazy property ─────────────────────────────────────────

    @property
    def store(self) -> MemoryConsolidationStore:
        if self._store is None:
            self._store = MemoryConsolidationStore(self.db_path)
            self._store.init_schema()
        return self._store

    # ─── public API ────────────────────────────────────────────

    async def maybe_consolidate(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        session_tokens: int,
    ) -> ConsolidationResult | None:
        """Try to consolidate. Returns ``None`` if no-op.

        Conditions checked:
          1. Token threshold met (session_tokens >= trigger)
          2. Enough messages to evict (len(messages) > keep_recent)
          3. Not throttled (min_consolidation_interval_sec)
        """
        if session_tokens < self.config.trigger_token_threshold:
            return None
        if len(messages) <= self.config.keep_recent_messages:
            return None
        now = time.time()
        last = self._last_consolidation.get(session_id, 0.0)
        if (now - last) < self.config.min_consolidation_interval_sec:
            return None

        # Pick range: [0 : len - keep_recent)
        end_idx = len(messages) - self.config.keep_recent_messages
        to_evict = messages[:end_idx]
        if not to_evict:
            return None

        # Throttle stamp
        self._last_consolidation[session_id] = now

        # LLM summarize (fail-soft: log + return None)
        try:
            summary = await self._summarize(to_evict)
        except Exception:
            logger.warning(
                "Consolidator: LLM summarize failed for session %s",
                session_id,
                exc_info=True,
            )
            return None

        # Compute token delta
        tokens_before = count_messages(to_evict, "unknown")
        summary_msg = [{"role": "system", "content": summary}]
        tokens_after = count_messages(summary_msg, "unknown")

        # Double-write: SQLite + markdown
        md_path: Path | None = None
        if self.config.enable_md_write:
            try:
                md_path = self._write_markdown(
                    session_id, to_evict, summary,
                    tokens_before, tokens_after,
                )
            except Exception:
                logger.warning(
                    "Consolidator: markdown write failed for session %s",
                    session_id,
                    exc_info=True,
                )

        # SQLite insert (single source of truth)
        record_id = self.store.add(
            session_id=session_id,
            start_msg_idx=0,
            end_msg_idx=end_idx,
            summary=summary,
            md_file_path=str(md_path) if md_path else None,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

        record = self.store.get(record_id)
        assert record is not None

        logger.info(
            "Consolidator: session=%s evicted %d msgs (%d→%d tokens)",
            session_id, len(to_evict), tokens_before, tokens_after,
        )

        return ConsolidationResult(
            record=record,
            md_path=md_path,
            messages_evicted=len(to_evict),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

    # ─── internals ─────────────────────────────────────────────

    async def _summarize(self, messages: list[dict[str, str]]) -> str:
        """Call the LLM to summarize evicted messages.

        Uses provider.achat(messages=[...], temperature=0.1, max_tokens=...),
        a thin async call interface borrowed from the existing chat
        memory integration pattern.
        """
        # Build chat history for summarization
        formatted = [{"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT}]
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            formatted.append({"role": role, "content": content})

        response = await self.provider.achat(
            messages=formatted,
            temperature=0.1,
            max_tokens=self.config.summary_max_tokens,
        )
        # response is dict-like {"content": "..."}
        content = (
            response.get("content", "")
            if isinstance(response, dict)
            else str(response)
        )
        if not content:
            raise ValueError("LLM returned empty summary")
        return content.strip()

    def _write_markdown(
        self,
        session_id: str,
        evicted: list[dict[str, str]],
        summary: str,
        tokens_before: int,
        tokens_after: int,
    ) -> Path:
        """Write per-session summary to ~/.llmwikify/memory/sessions/{id}.md."""
        self._memory_sessions_dir.mkdir(parents=True, exist_ok=True)
        md_path = self._memory_sessions_dir / f"{session_id}.md"
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        body = (
            f"# Session {session_id} Summary\n\n"
            f"- created_at: {timestamp}\n"
            f"- messages_evicted: {len(evicted)}\n"
            f"- tokens_saved: ~{max(0, tokens_before - tokens_after)}\n"
            f"- tokens_before: {tokens_before}\n"
            f"- tokens_after: {tokens_after}\n\n"
            f"## Summary\n\n{summary}\n"
        )
        md_path.write_text(body, encoding="utf-8")
        return md_path


__all__ = ["ConsolidationResult", "Consolidator", "ConsolidatorConfig"]
