"""In-memory notification queue for Agent events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class NotificationManager:
    """Manages agent notifications in memory.

    Features:
    - Auto-generated UUID-based IDs
    - Timestamped entries
    - Read/unread tracking
    - Configurable max size (default 100)
    - LRU eviction when max size exceeded
    """

    def __init__(self, max_size: int = 100):
        self._notifications: list[dict[str, Any]] = []
        self._max_size = max_size

    def add(
        self,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a notification.

        Args:
            event_type: Type of event (info, success, warning, error)
            message: Human-readable message
            data: Optional structured data

        Returns:
            The created notification dict
        """
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
        return n

    def list_unread(self) -> list[dict[str, Any]]:
        """Return all unread notifications."""
        return [n for n in self._notifications if not n["read"]]

    def list_all(self) -> list[dict[str, Any]]:
        """Return all notifications."""
        return list(self._notifications)

    def mark_read(self, notification_id: str) -> bool:
        """Mark a notification as read.

        Returns:
            True if found and marked, False otherwise
        """
        for n in self._notifications:
            if n["id"] == notification_id:
                n["read"] = True
                return True
        return False

    def mark_all_read(self) -> int:
        """Mark all notifications as read.

        Returns:
            Number of notifications marked
        """
        count = sum(1 for n in self._notifications if not n["read"])
        for n in self._notifications:
            n["read"] = True
        return count

    def unread_count(self) -> int:
        """Return count of unread notifications."""
        return sum(1 for n in self._notifications if not n["read"])

    def clear(self) -> None:
        """Clear all notifications."""
        self._notifications = []
