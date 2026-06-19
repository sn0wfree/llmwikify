"""AutoCompact — proactively consolidate idle chat sessions (Phase 9).

Borrowed from nanobot v0.2.1 ``agent/autocompact.py`` (84 LOC) but
adapted to llmwikify's SQLite-backed sessions:

  - Source of truth for "last activity" is ``chat_sessions.updated_at``
    (already maintained by every write path).
  - Consolidation reuses the existing :class:`Consolidator`
    (Phase 6/7), so AutoCompact is just a TTL-driven trigger, not a
    new compression engine.
  - Active sessions are skipped via ``ChatOrchestrator.get_all_session_status``
    (statuses ``running`` / ``confirmation_required`` mean "in flight").
  - In-flight archival jobs are tracked in ``self._archiving`` so a
    second tick before the first finishes doesn't double-fire.

A tick is a single call to :meth:`check_expired`. Callers decide when
to tick (manual ``/auto_compact`` slash, FastAPI lifespan periodic
task, cron). No internal timer is started so unit tests stay
deterministic.

Phase 9 (2026-06-20). See AGENTS.md "记忆清洁" guidance for why we
keep this an opt-in TTL trigger instead of an aggressive default.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection, Iterable
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# nanobot defaults: 8 most recent messages preserved verbatim, the rest
# are LLM-summarized. We respect Consolidator's own keep_recent_messages
# config; AutoCompact only owns the TTL decision.
_ACTIVE_STATUSES: frozenset[str] = frozenset({
    "running",
    "in_progress",
    "confirmation_required",
})


def _parse_ts(value: Any) -> datetime | None:
    """Best-effort parse of an SQLite timestamp string.

    SQLite ``datetime('now')`` produces ``"YYYY-MM-DD HH:MM:SS"`` which
    is *not* ISO-8601 (no ``T``). Accept both forms; return ``None``
    on any failure so the caller treats unparseable rows as "fresh".
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        logger.debug("AutoCompact: cannot parse timestamp %r", value)
        return None


class AutoCompact:
    """TTL-driven idle-session consolidator.

    Usage::

        auto = AutoCompact(
            chat_db=app_db.chat,
            memory_manager=memory_manager,
            ttl_minutes=30,
        )

        # Tick periodically. The orchestrator supplies the set of
        # currently-active sessions so we never compact a running
        # chat under the user's feet.
        await auto.check_expired(active_session_keys=orchestrator.active_keys())
    """

    def __init__(
        self,
        chat_db: Any,
        memory_manager: Any,
        ttl_minutes: int = 30,
        max_messages_per_session: int = 200,
    ) -> None:
        self.chat_db = chat_db
        self.memory_manager = memory_manager
        self._ttl_minutes = max(0, int(ttl_minutes))
        self._max_messages_per_session = max(1, int(max_messages_per_session))
        self._archiving: set[str] = set()

    # ─── public API ───────────────────────────────────────────────

    @property
    def ttl_minutes(self) -> int:
        return self._ttl_minutes

    def is_expired(
        self, updated_at: Any, *, now: datetime | None = None,
    ) -> bool:
        """True iff ``updated_at`` is at least ``ttl_minutes`` in the past."""
        if self._ttl_minutes <= 0:
            return False
        ts = _parse_ts(updated_at)
        if ts is None:
            return False
        anchor = now or datetime.now()
        return (anchor - ts) >= timedelta(minutes=self._ttl_minutes)

    def list_expired_sessions(
        self,
        active_session_keys: Collection[str] = (),
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return session rows whose updated_at is past the TTL.

        Skips:
          - Sessions in ``active_session_keys`` (currently running)
          - Sessions already being archived this cycle (``self._archiving``)
        """
        active = set(active_session_keys)
        out: list[dict[str, Any]] = []
        try:
            sessions = self.chat_db.list_chat_sessions()
        except Exception:
            logger.warning("AutoCompact: list_chat_sessions failed", exc_info=True)
            return out
        for row in sessions:
            sid = row.get("id")
            if not sid or sid in active or sid in self._archiving:
                continue
            if self.is_expired(row.get("updated_at"), now=now):
                out.append(row)
        return out

    async def check_expired(
        self,
        active_session_keys: Collection[str] = (),
        *,
        scheduler: Callable[[Awaitable[Any]], Any] | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Schedule consolidation for every expired session. Returns ids touched.

        ``scheduler`` is invoked once per session with the awaitable that
        performs the consolidation. The default (``scheduler=None``)
        ``await``s every job sequentially in the calling task — fine for
        CLI / test usage. A FastAPI lifespan would pass
        ``asyncio.create_task`` so jobs run concurrently in the
        background.
        """
        if self.memory_manager is None or self.memory_manager.consolidator is None:
            return []
        expired = self.list_expired_sessions(active_session_keys, now=now)
        if not expired:
            return []
        touched: list[str] = []
        for row in expired:
            sid = row["id"]
            self._archiving.add(sid)
            touched.append(sid)
            coro = self._archive(sid)
            if scheduler is not None:
                scheduler(coro)
            else:
                await coro
        return touched

    # ─── internals ────────────────────────────────────────────────

    async def _archive(self, session_id: str) -> Any:
        """Consolidate one session. Failures are logged + swallowed."""
        try:
            messages = self._load_messages(session_id)
            if not messages:
                return None
            session_tokens = sum(
                len(str(m.get("content", ""))) // 4 for m in messages
            )
            return await self.memory_manager.consolidate_session(
                session_id=session_id,
                messages=messages,
                session_tokens=session_tokens,
            )
        except Exception:
            logger.warning(
                "AutoCompact: consolidate failed for %s", session_id,
                exc_info=True,
            )
            return None
        finally:
            self._archiving.discard(session_id)

    def _load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Load up to ``max_messages_per_session`` messages for one session."""
        try:
            return self.chat_db.get_chat_messages(
                session_id, limit=self._max_messages_per_session,
            )
        except Exception:
            logger.warning(
                "AutoCompact: get_chat_messages failed for %s", session_id,
                exc_info=True,
            )
            return []


__all__ = ["AutoCompact"]


# ─── Helper for orchestrator-side integration ────────────────────


def active_keys_from_status_map(status_map: dict[str, str]) -> Iterable[str]:
    """Filter a ``{session_id: status}`` map down to in-flight session ids.

    Mirrors ``ChatOrchestrator.get_all_session_status`` shape. Exposed
    so callers can plug AutoCompact into the existing status mechanism
    without dragging in orchestrator imports here.
    """
    return [sid for sid, st in status_map.items() if st in _ACTIVE_STATUSES]
