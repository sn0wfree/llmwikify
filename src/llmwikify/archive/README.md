# `archive/` — Frozen Legacy Code

This directory contains code that was archived (via `git mv`, never
deleted) during the v0.42 → v0.4 god-class decomposition. **As of
2026-06-19, it is frozen**: no further refactors will land here. Files
will be physically removed in **v0.5** once the upstream callers have
been ported.

## Contents

| Path | LOC | Status | Used by |
|------|----:|--------|---------|
| `llmwikify_v0_41_legacy/` | ~3,800 | Frozen 2026-06-16 | Tests only |
| `llmwikify_v0_41_legacy/chat_legacy/` | 0 (moved 2026-06-19) | **Empty** — all 9 modules git-mv'd to `apps/chat/research_engine/` | None (zero live imports) |
| `llmwikify_original.py` | ~~1,965~~ | **Removed 2026-06-19** | None |
| `reports/` | n/a | Reference docs only | None |

## Frozen-status legend

- **Frozen**: the file is on read-only semantically. Bug fixes are not
  expected, but the file remains importable for back-compat verification.
- **Empty**: the directory's contents were git-mv'd to a new location.
  No live imports remain; safe to `git rm -r` the entire directory.
- **Pending removal**: no production code references this file. Safe to
  delete once `git grep` confirms no live imports.

## Audit methodology

The "Used by" column above is the result of this grep, run 2026-06-19:

```bash
grep -rn "from llmwikify.archive" src/ tests/ | grep -v __pycache__
```

### Results (post D4 commit)

**`llmwikify_v0_41_legacy/service.py`** — referenced only by
`tests/test_apps_chat_agent_service.py` (legacy test file). The
`ChatService` class itself is **not** instantiated by any production
code (all paths use `ChatOrchestrator` via `AgentService`).

**`llmwikify_v0_41_legacy/chat_legacy/`** — **empty after 2026-06-19**.
All 9 modules (engine, actions, gates, llm_step, observer, reasoner,
report, resume, routes, __init__) were git-mv'd to
`apps/chat/research_engine/`. Zero live imports remain.

**`llmwikify_original.py`** — **removed 2026-06-19**. The
MODULARIZATION_REPORT.md still mentions the path (historical reference).

## Removal plan (v0.5)

### Done (2026-06-19)

✅ `llmwikify_original.py` deleted (-1965 LOC).

✅ `chat_legacy/` emptied — all 9 modules moved to
`apps/chat/research_engine/` (8 renamed + `__init__.py`).

### Remaining

1. `apps/chat/research_engine/` — 9 inlined modules + `__init__.py`.
   These are now production code; no longer archive.
2. `llmwikify_v0_41_legacy/service.py` (1236 LOC) + 3 tests
   (~2800 LOC) — referenced only by tests, kept for back-compat
   verification. Safe to delete in v0.5.

## See also

- `llmwikify_v0_41_legacy/README.md` — god-class decomposition record.
- `docs/poc/plan-b-results.md` — Plan B 5-step state machine refactor
  results.