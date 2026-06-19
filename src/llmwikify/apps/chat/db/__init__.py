"""ChatDatabase repositories (Phase 5 god-class split).

The 926-LOC ChatDatabase class was split into 7 repositories in 2026-06-19:

  1. ChatSessionRepository    — chat_sessions (8 methods)
  2. ChatMessageRepository    — chat_messages (4 methods)
  3. ToolCallRepository       — tool_calls (3 methods)
  4. PermissionRepository     — chat_permissions (2 methods)
  5. ResearchDelegate         — 27 research-domain delegates
  6. WikiDelegate             — 17 wiki-domain delegates
  7. AdminStatsRepository     — cross-table admin/stats (5 methods)

ChatDatabase (in ``db/_facade.py``) is now a thin facade that holds
references to all 7 and delegates each call. Public API is unchanged.

Backward compat re-exports:
  - ``get_chat_db_path()`` — path helper
  - ``DB_SIZE_WARNING_MB`` — re-exported from apps.db_base
"""
from ._facade import (
    DB_SIZE_WARNING_MB,
    AutoResearchDatabase,
    ChatDatabase,
    get_autoresearch_db_path,
    get_chat_db_path,
)
from .admin_stats_repo import AdminStatsRepository
from .base import ChatDBBase
from .chat_message_repo import ChatMessageRepository
from .chat_session_repo import ChatSessionRepository
from .permission_repo import PermissionRepository
from .research_delegate import ResearchDelegate
from .tool_call_repo import ToolCallRepository
from .wiki_delegate import WikiDelegate

__all__ = [
    "AdminStatsRepository",
    "AutoResearchDatabase",
    "ChatDBBase",
    "ChatDatabase",
    "ChatMessageRepository",
    "ChatSessionRepository",
    "DB_SIZE_WARNING_MB",
    "PermissionRepository",
    "ResearchDelegate",
    "ToolCallRepository",
    "WikiDelegate",
    "get_autoresearch_db_path",
    "get_chat_db_path",
]
