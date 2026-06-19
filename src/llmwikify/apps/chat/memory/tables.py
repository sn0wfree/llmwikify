"""SQL DDL constants for Phase 6 memory tables.

Borrowed from nanobot agent/memory.py architecture (Consolidator + Dream)
but adapted to llmwikify's SQLite storage model.

Tables:
    memory_consolidations  — per-session summary records (from Consolidator)
    memory_facts          — long-term extracted facts (from Dream)

Created via ``IF NOT EXISTS`` so they coexist with the 21 existing
tables. Indexes are created separately.

See docs/poc/apply-plan.md §6 for the full design rationale.
"""

from __future__ import annotations

# ─── memory_consolidations (Consolidator output) ─────────────────

CREATE_MEMORY_CONSOLIDATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS memory_consolidations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    start_msg_idx INTEGER NOT NULL,
    end_msg_idx INTEGER NOT NULL,
    summary TEXT NOT NULL,
    md_file_path TEXT,
    tokens_before INTEGER,
    tokens_after INTEGER,
    created_at REAL NOT NULL
)
"""

CREATE_IDX_MEMORY_CONSOLIDATIONS_SESSION = """
CREATE INDEX IF NOT EXISTS idx_memory_consolidations_session
ON memory_consolidations(session_id, created_at)
"""


# ─── memory_facts (Dream output) ───────────────────────────────

CREATE_MEMORY_FACTS_TABLE = """
CREATE TABLE IF NOT EXISTS memory_facts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source_session_id TEXT,
    source_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    last_referenced_at REAL,
    created_at REAL NOT NULL
)
"""

CREATE_IDX_MEMORY_FACTS_SOURCE = """
CREATE INDEX IF NOT EXISTS idx_memory_facts_source
ON memory_facts(source_type)
"""

CREATE_IDX_MEMORY_FACTS_CREATED = """
CREATE INDEX IF NOT EXISTS idx_memory_facts_created
ON memory_facts(created_at)
"""


# ─── Combined init (idempotent) ─────────────────────────────────

ALL_PHASE6_DDL = [
    CREATE_MEMORY_CONSOLIDATIONS_TABLE,
    CREATE_IDX_MEMORY_CONSOLIDATIONS_SESSION,
    CREATE_MEMORY_FACTS_TABLE,
    CREATE_IDX_MEMORY_FACTS_SOURCE,
    CREATE_IDX_MEMORY_FACTS_CREATED,
]


__all__ = [
    "ALL_PHASE6_DDL",
    "CREATE_MEMORY_CONSOLIDATIONS_TABLE",
    "CREATE_MEMORY_FACTS_TABLE",
    "CREATE_IDX_MEMORY_CONSOLIDATIONS_SESSION",
    "CREATE_IDX_MEMORY_FACTS_SOURCE",
    "CREATE_IDX_MEMORY_FACTS_CREATED",
]
