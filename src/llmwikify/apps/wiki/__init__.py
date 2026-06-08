"""WikiService — orchestration layer for wiki operations.

WikiService manages the lifecycle of wiki-related subsystems:
dream proposals, notifications, confirmations, scheduler,
ingest audit, and multi-wiki registry.

It does NOT duplicate wiki CRUD operations (read/write/search/lint
etc.) — those are provided by WikiToolRegistry (tool calling) and
WikiQuerySkill (Skill framework).

Design ref: ``v0.32-execution-plan.md`` Phase 13d
"""

from llmwikify.apps.wiki.db import WikiDatabase
from llmwikify.apps.wiki.service import WikiService

__all__ = ["WikiDatabase", "WikiService"]
