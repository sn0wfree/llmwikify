"""MemoryManager — unified memory base (v0.33.0).

Per v0.33-service-refactor.md, this is one of the 6 components
in the 5+1-service architecture. It exposes 6 stores:

  - ConversationStore   → app_db.chat (chat_messages)
  - KnowledgeStore      → wiki.query_sink
  - ContextStore        → app_db.chat (context_entries NEW)
  - ReActStateStore     → app_db.research (research_steps)
  - UserPreferenceStore → JSON file
  - MemoryIndex         → in-memory unified search

The MemoryManager provides a single interface for storing
and retrieving different kinds of memory, backed by the
appropriate database facades.

Async support (Phase 3.5 / v0.36):
  Every store exposes an ``a*`` async variant (e.g.
  ``ConversationStore.alist``, ``ContextStore.aadd``) that
  wraps the sync method in ``asyncio.to_thread`` so the
  SQLite-bound work doesn't block the event loop. The
  sync APIs remain for non-async callers (tests, scripts).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from llmwikify.apps.db import AppDatabase

logger = logging.getLogger(__name__)


# Default user_id for chat-layer preferences. The chat layer
# has no per-user identity (no auth); preferences are scoped
# to the local user / installation.
DEFAULT_CHAT_USER_ID = "default"


def _run_sync(sync_fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a sync callable in a thread pool.

    Centralised helper so the async wrappers below all use
    the same executor semantics.
    """
    return asyncio.to_thread(sync_fn, *args, **kwargs)


class ConversationStore:
    """Stores chat conversation history via ChatDatabase.

    Backed by the ``chat_messages`` table in the chat facade.
    One row per message (role/content/tool_calls).
    """

    def __init__(self, chat_db: Any):
        self.db = chat_db

    def add(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> str:
        """Append a message to the conversation."""
        import uuid
        msg_id = str(uuid.uuid4())
        self.db.save_chat_message({
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_calls": json.dumps(tool_calls) if tool_calls else None,
        })
        return msg_id

    def list(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict]:
        """List messages in a session (chronological order)."""
        return self.db.get_chat_messages(
            session_id, limit=limit if limit is not None else 50,
        )

    def search(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search messages by content substring."""
        messages = self.list(session_id)
        results = [
            m for m in messages
            if query.lower() in m.get("content", "").lower()
        ]
        return results[:limit]

    # ── async wrappers (Phase 3.5 / v0.36) ───────────────────

    async def aadd(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> str:
        """Async variant of ``add`` (Phase 3.5 / v0.36)."""
        return await _run_sync(self.add, session_id, role, content, tool_calls)

    async def alist(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict]:
        """Async variant of ``list`` (Phase 3.5 / v0.36)."""
        return await _run_sync(self.list, session_id, limit)

    async def asearch(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Async variant of ``search`` (Phase 3.5 / v0.36)."""
        return await _run_sync(self.search, session_id, query, limit)


class KnowledgeStore:
    """Stores knowledge via wiki.query_sink.

    Thin wrapper over the wiki instance. The wiki itself
    provides the page-based storage; this class is a
    named entry point in the MemoryManager.
    """

    def __init__(self, wiki: Any):
        self.wiki = wiki

    def add(self, page_name: str, content: str) -> None:
        """Write a knowledge page to the wiki."""
        if not self.wiki.is_initialized():
            return
        self.wiki.write_page(page_name, content)

    def get(self, page_name: str) -> str | None:
        """Read a knowledge page from the wiki."""
        if not self.wiki.is_initialized():
            return None
        return self.wiki.read_page(page_name)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search the wiki for pages matching query."""
        if not self.wiki.is_initialized():
            return []
        try:
            results = self.wiki.search_pages(query, limit=limit)
            return results
        except AttributeError:
            return []


class ContextStore:
    """Stores ephemeral context entries via ChatDatabase.

    Backed by the ``context_entries`` table in the chat facade.
    Used for per-session context that doesn't fit in chat_messages
    (e.g., RAG chunks, tool results, intermediate reasoning).
    """

    def __init__(self, chat_db: Any):
        self.db = chat_db

    def add(
        self,
        session_id: str,
        entry_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Add a context entry."""
        import uuid
        entry_id = str(uuid.uuid4())
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(
                """INSERT INTO context_entries
                   (id, session_id, entry_type, content, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    entry_id,
                    session_id,
                    entry_type,
                    content,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            conn.commit()
        return entry_id

    def list(
        self,
        session_id: str,
        entry_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List context entries for a session."""
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if entry_type:
                rows = conn.execute(
                    """SELECT * FROM context_entries
                       WHERE session_id = ? AND entry_type = ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (session_id, entry_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM context_entries
                       WHERE session_id = ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def clear(self, session_id: str) -> int:
        """Delete all context entries for a session. Returns count."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM context_entries WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount

    # ── async wrappers (Phase 3.5 / v0.36) ───────────────────

    async def aadd(
        self,
        session_id: str,
        entry_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Async variant of ``add`` (Phase 3.5 / v0.36)."""
        return await _run_sync(
            self.add, session_id, entry_type, content, metadata,
        )

    async def alist(
        self,
        session_id: str,
        entry_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Async variant of ``list`` (Phase 3.5 / v0.36)."""
        return await _run_sync(
            self.list, session_id, entry_type, limit,
        )

    async def aclear(self, session_id: str) -> int:
        """Async variant of ``clear`` (Phase 3.5 / v0.36)."""
        return await _run_sync(self.clear, session_id)


class ReActStateStore:
    """Stores ReAct/6-step research state via ResearchDatabase.

    Backed by the ``research_steps`` table in the research facade.
    Each row is a snapshot of ResearchState at a given step.
    """

    def __init__(self, research_db: Any):
        self.db = research_db

    def save(
        self,
        session_id: str,
        step_num: int,
        state: dict,
    ) -> str:
        """Save a research state snapshot."""
        self.db.save_research_state(session_id, step_num, state)
        return f"{session_id}:{step_num}"

    def load(self, session_id: str, step_num: int) -> dict | None:
        """Load a research state snapshot."""
        return self.db.load_research_state(session_id, step_num)

    def latest(self, session_id: str) -> dict | None:
        """Load the most recent research state."""
        steps = self.db.list_steps(session_id)
        if not steps:
            return None
        return self.load(session_id, steps[-1]["step_num"])


class UserPreferenceStore:
    """Stores user preferences in a JSON file.

    Simple key-value storage, no schema. Each user
    (identified by user_id) has its own JSON file.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._prefs_file = self.data_dir / "user_preferences.json"
        if not self._prefs_file.exists():
            self._prefs_file.write_text("{}")

    def _load(self) -> dict:
        try:
            return json.loads(self._prefs_file.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save(self, prefs: dict) -> None:
        self._prefs_file.write_text(json.dumps(prefs, indent=2))

    def get(self, user_id: str, key: str, default: Any = None) -> Any:
        prefs = self._load()
        return prefs.get(user_id, {}).get(key, default)

    def set(self, user_id: str, key: str, value: Any) -> None:
        prefs = self._load()
        if user_id not in prefs:
            prefs[user_id] = {}
        prefs[user_id][key] = value
        self._save(prefs)

    def all(self, user_id: str) -> dict:
        return self._load().get(user_id, {})

    # ── async wrappers (Phase 3.5 / v0.36) ───────────────────

    async def aget(self, user_id: str, key: str, default: Any = None) -> Any:
        return await _run_sync(self.get, user_id, key, default)

    async def aset(self, user_id: str, key: str, value: Any) -> None:
        await _run_sync(self.set, user_id, key, value)

    async def aall(self, user_id: str) -> dict:
        return await _run_sync(self.all, user_id)


class MemoryIndex:
    """In-memory unified search across all stores.

    Provides a single ``search(query)`` interface that
    hits all 5 stores and returns ranked results.
    """

    def __init__(
        self,
        conversation: ConversationStore | None = None,
        knowledge: KnowledgeStore | None = None,
        context: ContextStore | None = None,
        react_state: ReActStateStore | None = None,
        preferences: UserPreferenceStore | None = None,
    ):
        self.conversation = conversation
        self.knowledge = knowledge
        self.context = context
        self.react_state = react_state
        self.preferences = preferences

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search across all stores for matching content."""
        results: list[dict] = []

        if self.conversation and session_id:
            for msg in self.conversation.search(session_id, query, limit):
                results.append({
                    "source": "conversation",
                    "content": msg.get("content", ""),
                    "metadata": {
                        "role": msg.get("role"),
                        "msg_id": msg.get("id"),
                    },
                })

        if self.knowledge:
            for page in self.knowledge.search(query, limit):
                results.append({
                    "source": "knowledge",
                    "content": page.get("content", page.get("preview", "")),
                    "metadata": {
                        "page": page.get("name") or page.get("title"),
                    },
                })

        if self.context and session_id:
            for entry in self.context.list(session_id, limit=limit):
                content = entry.get("content", "")
                if query.lower() in content.lower():
                    results.append({
                        "source": "context",
                        "content": content,
                        "metadata": {
                            "entry_type": entry.get("entry_type"),
                            "entry_id": entry.get("id"),
                        },
                    })

        return results[:limit]

    # ── async wrapper (Phase 3.5 / v0.36) ───────────────────

    async def asearch(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Async variant of ``search`` (Phase 3.5 / v0.36)."""
        return await _run_sync(self.search, query, session_id, limit)


class MemoryManager:
    """Memory base — facade over 6 stores.

    Provides a single injection point for the 5+1-service
    architecture. Services receive ``MemoryManager`` and
    access stores via attributes.
    """

    def __init__(
        self,
        app_db: AppDatabase,
        wiki: Any = None,
        data_dir: Path | None = None,
    ):
        self.app_db = app_db
        self.conversation = ConversationStore(app_db.chat)
        self.react_state = ReActStateStore(app_db.research)
        self.context = ContextStore(app_db.chat)
        self.knowledge = KnowledgeStore(wiki) if wiki else None
        self.preferences = UserPreferenceStore(
            data_dir or app_db.data_dir
        )
        self.index = MemoryIndex(
            conversation=self.conversation,
            knowledge=self.knowledge,
            context=self.context,
            react_state=self.react_state,
            preferences=self.preferences,
        )


__all__ = [
    "MemoryManager",
    "ConversationStore",
    "KnowledgeStore",
    "ContextStore",
    "ReActStateStore",
    "UserPreferenceStore",
    "MemoryIndex",
]
