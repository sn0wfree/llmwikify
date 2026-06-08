"""AppDatabase — single-entry aggregate of the 3 database facades.

Per v0.33-service-refactor.md, ``AppDatabase`` is the one
injection that services receive. It exposes three sub-databases:

  - ``.chat``:     ``ChatDatabase``     (chat + context tables)
  - ``.research``: ``ResearchDatabase``  (research tables)
  - ``.wiki``:     ``WikiDatabase``     (wiki-ops tables)

Usage::

    from llmwikify.apps.db import AppDatabase

    db = AppDatabase(data_dir)
    db.chat.create_chat_session(wiki_id="w1")
    db.research.create_research_session(wiki_id="w1", query="q")
    db.wiki.save_notification({"wiki_id": "w1", ...})
"""

from __future__ import annotations

from pathlib import Path

from llmwikify.apps.chat.db import ChatDatabase
from llmwikify.apps.research.db import ResearchDatabase
from llmwikify.apps.wiki.db import WikiDatabase


class AppDatabase:
    """Aggregate of 3 database facades over one physical file.

    All three facades share ``data_dir/.llmwiki_agent.db`` but
    expose only their own domain's methods. This class
    aggregates them so callers need one injection, not three.
    """

    def __init__(self, data_dir: Path | str):
        data_dir = Path(data_dir)
        self.chat = ChatDatabase(data_dir)
        self.research = ResearchDatabase(data_dir)
        self.wiki = WikiDatabase(data_dir)

    # Convenience properties for backward compat ──────────────
    # Some callers access db.db_path directly (e.g. CLI tools).
    # Route through chat.db_path (canonical).

    @property
    def db_path(self) -> Path:
        return self.chat.db_path

    @property
    def data_dir(self) -> Path:
        return self.chat.data_dir


__all__ = ["AppDatabase"]
