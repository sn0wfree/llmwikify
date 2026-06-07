"""In-memory notification queue for Agent events with optional DB persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class NotificationManager:
    """Manages agent notifications in memory with optional SQLite persistence.

    Features:
    - Auto-generated UUID-based IDs
    - Timestamped entries
    - Read/unread tracking
    - Configurable max size (default 100)
    - LRU eviction when max size exceeded
    - SQLite persistence when db and wiki_id are provided
    """

    def __init__(self, max_size: int = 100, db: Any = None, wiki_id: str | None = None):
        self._notifications: list[dict[str, Any]] = []
        self._max_size = max_size
        self.db = db
        self.wiki_id = wiki_id
        if db and wiki_id:
            self._notifications = db.list_notifications(wiki_id, unread_only=False)

    def add(
        self,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        n = {
            "id": str(uuid.uuid4())[:8],
            "type": event_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        self._notifications.append(n)
        if len(self._notifications) > self._max_size:
            self._notifications = self._notifications[-self._max_size:]
        if self.db and self.wiki_id:
            n["wiki_id"] = self.wiki_id
            self.db.save_notification(n)
        return n

    def list_unread(self) -> list[dict[str, Any]]:
        if self.db and self.wiki_id:
            return self.db.list_notifications(self.wiki_id, unread_only=True)
        return [n for n in self._notifications if not n["read"]]

    def list_all(self) -> list[dict[str, Any]]:
        if self.db and self.wiki_id:
            return self.db.list_notifications(self.wiki_id, unread_only=False)
        return list(self._notifications)

    def mark_read(self, notification_id: str) -> bool:
        for n in self._notifications:
            if n["id"] == notification_id:
                n["read"] = True
                if self.db:
                    self.db.mark_notification_read(notification_id)
                return True
        return False

    def mark_all_read(self) -> int:
        count = sum(1 for n in self._notifications if not n["read"])
        for n in self._notifications:
            n["read"] = True
        if self.db and self.wiki_id:
            for n in self._notifications:
                if not n.get("read"):
                    self.db.mark_notification_read(n["id"])
        return count

    def unread_count(self) -> int:
        if self.db and self.wiki_id:
            return self.db.get_unread_count(self.wiki_id)
        return sum(1 for n in self._notifications if not n["read"])

    def clear(self) -> None:
        self._notifications = []