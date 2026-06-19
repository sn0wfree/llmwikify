"""WikiDelegate — wraps WikiDatabase's 17 chat-domain methods.

The wiki domain (dream_proposals, notifications, confirmations,
ingest_log) lives in ``apps.wiki.db.WikiDatabase``.

For backward compatibility, ChatDatabase exposes 17 thin 1-line
delegates (``self._wiki.save_dream_proposal(...)``). This class is
the extracted wrapper that holds the same 17 delegates so ChatDatabase
can simply do ``self._wiki_delegate.save_dream_proposal(...)``.

All 17 methods are pure 1-line forwarders — no logic, no schema.
The real implementation is in ``apps/wiki/db.py``.

Methods (17):
    save_dream_proposal, get_dream_proposals,
    update_dream_proposal_status, get_dream_proposal_stats,
    save_notification, list_notifications, mark_notification_read,
    get_unread_count,
    save_confirmation, get_confirmations, update_confirmation_status,
    update_confirmation_arguments, get_confirmation, delete_confirmation,
    log_ingest, get_ingest_log, get_ingest_entry

DEPRECATED: New code should use ``apps.wiki.db.WikiDatabase`` directly.
These delegates are kept for back-compat with 32 production callers
identified in the 2026-06-19 audit.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WikiDelegate:
    """Thin wrapper around WikiDatabase's chat-domain methods.

    Holds a lazy ``WikiDatabase`` instance. All methods are
    1-line forwarders.
    """

    def __init__(self, data_dir):
        self._data_dir = data_dir

    @property
    def _wiki(self):
        """Lazy WikiDatabase instance."""
        if not hasattr(self, "_wiki_db"):
            from llmwikify.apps.wiki.db import WikiDatabase
            self._wiki_db = WikiDatabase(self._data_dir)
        return self._wiki_db

    # ─── Dream proposals (delegate → WikiDatabase) ──────────────

    def save_dream_proposal(self, proposal: dict) -> None:
        return self._wiki.save_dream_proposal(proposal)

    def get_dream_proposals(
        self,
        wiki_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        return self._wiki.get_dream_proposals(wiki_id, status, limit)

    def update_dream_proposal_status(
        self, proposal_id: str, status: str,
    ) -> None:
        return self._wiki.update_dream_proposal_status(proposal_id, status)

    def get_dream_proposal_stats(self, wiki_id: str) -> dict:
        return self._wiki.get_dream_proposal_stats(wiki_id)

    # ─── Notifications (delegate → WikiDatabase) ────────────────

    def save_notification(self, n: dict) -> None:
        return self._wiki.save_notification(n)

    def list_notifications(
        self, wiki_id: str, unread_only: bool = False,
    ) -> list[dict]:
        return self._wiki.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> None:
        return self._wiki.mark_notification_read(notification_id)

    def get_unread_count(self, wiki_id: str) -> int:
        return self._wiki.get_unread_count(wiki_id)

    # ─── Confirmations (delegate → WikiDatabase) ────────────────

    def save_confirmation(self, c: dict) -> None:
        return self._wiki.save_confirmation(c)

    def get_confirmations(
        self, wiki_id: str, status: str | None = None,
    ) -> list[dict]:
        return self._wiki.get_confirmations(wiki_id, status)

    def update_confirmation_status(
        self, confirmation_id: str, status: str,
    ) -> None:
        return self._wiki.update_confirmation_status(
            confirmation_id, status,
        )

    def update_confirmation_arguments(
        self, confirmation_id: str, arguments: dict,
    ) -> None:
        return self._wiki.update_confirmation_arguments(
            confirmation_id, arguments,
        )

    def get_confirmation(self, confirmation_id: str) -> dict | None:
        return self._wiki.get_confirmation(confirmation_id)

    def delete_confirmation(self, confirmation_id: str) -> None:
        return self._wiki.delete_confirmation(confirmation_id)

    # ─── Ingest log (delegate → WikiDatabase) ───────────────────

    def log_ingest(self, entry: dict) -> None:
        return self._wiki.log_ingest(entry)

    def get_ingest_log(
        self, wiki_id: str, limit: int = 20,
    ) -> list[dict]:
        return self._wiki.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self._wiki.get_ingest_entry(ingest_id)


__all__ = ["WikiDelegate"]
