"""Memory Layers - QuerySink integration + conversation memory.

Integrates existing QuerySink with Agent conversation history.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Stores agent conversation history in JSONL format."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_file = data_dir / "history.jsonl"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, content: str, metadata: dict | None = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
        }
        if metadata:
            entry["metadata"] = metadata
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_recent(self, limit: int = 20) -> list[dict]:
        if not self.history_file.exists():
            return []
        entries = []
        with open(self.history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries[-limit:]

    def get_all(self) -> list[dict]:
        if not self.history_file.exists():
            return []
        entries = []
        with open(self.history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def clear(self) -> None:
        if self.history_file.exists():
            self.history_file.unlink()


class SinkMemory:
    """Agent-aware wrapper around QuerySink."""

    def __init__(self, wiki: Any):
        self.wiki = wiki

    def append_answer(
        self,
        page_name: str,
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
    ) -> str:
        return self.wiki.query_sink.append_to_sink(
            page_name=page_name,
            query=query,
            answer=answer,
            source_pages=source_pages or [],
            raw_sources=raw_sources or [],
        )

    def read_sink(self, page_name: str) -> dict:
        return self.wiki.query_sink.read(page_name)

    def get_sink_status(self) -> dict:
        return self.wiki.query_sink.status()

    def get_pending_pages(self) -> list[str]:
        status = self.get_sink_status()
        return [s["page_name"] for s in status.get("sinks", []) if s["entry_count"] > 0]

    def get_new_entries_since(self, page_name: str, since: str | None = None) -> list[dict]:
        sink_data = self.read_sink(page_name)
        if sink_data.get("status") != "ok":
            return []
        entries = sink_data.get("entries", [])
        if since is None:
            return entries
        return [e for e in entries if e.get("timestamp", "") > since]


class MemoryManager:
    """Unified memory manager combining conversation and sink memory."""

    def __init__(self, wiki: Any, data_dir: Path):
        self.conversation = ConversationMemory(data_dir)
        self.sink = SinkMemory(wiki)
        self.wiki = wiki

    def store_conversation(self, role: str, content: str, metadata: dict | None = None) -> None:
        self.conversation.append(role, content, metadata)

    def store_knowledge(
        self,
        page_name: str,
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
    ) -> str:
        self.conversation.append(
            "system",
            f"Knowledge stored to sink for page: {page_name}",
            {"page_name": page_name, "query": query},
        )
        return self.sink.append_answer(page_name, query, answer, source_pages, raw_sources)

    def get_context(self, max_messages: int = 10) -> list[dict]:
        return self.conversation.get_recent(max_messages)

    def get_pending_work(self) -> dict:
        return {
            "pending_pages": self.sink.get_pending_pages(),
            "sink_status": self.sink.get_sink_status(),
        }
