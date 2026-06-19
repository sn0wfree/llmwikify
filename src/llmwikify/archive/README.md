# `archive/` — Frozen Legacy Code

This directory contains code that was archived (via `git mv`, never
deleted) during the v0.42 → v0.4 god-class decomposition. **As of
2026-06-19, it is frozen**: no further refactors will land here. Files
will be physically removed in **v0.5** once the upstream callers have
been ported.

## Contents

| Path | LOC | Status | Used by |
|------|----:|--------|---------|
| `llmwikify_v0_41_legacy/` | 0 (emptied 2026-06-19) | **Empty** — `service.py` was deleted by B-7 (98a47bd) and 3 tests migrated + deleted in D5 | None (zero live imports) |
| `chat_legacy/` (subdir of above) | 0 (moved 2026-06-19) | **Removed** — all 9 modules git-mv'd to `apps/chat/research_engine/` | None (zero live imports) |
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

### Results (post D5 commit)

**`llmwikify_v0_41_legacy/`** — **fully emptied 2026-06-19**.
  - `service.py` (1236 LOC) was deleted by B-7 (98a47bd, 2026-06-18).
    Its logic was replaced by `apps/chat/agent/research_runner.py` +
    `apps/chat/agent/orchestrator.py`.
  - `chat_legacy/` (9 modules, ~2,800 LOC) was git-mv'd in D4 to
    `apps/chat/research_engine/`.
  - 3 dead tests (`test_apps_chat_agent_service.py` 1561 LOC +
    `test_compaction.py` 95 + `test_token_truncation.py` 86 = 1742 LOC)
    were uncollectable (`from llmwikify.apps.chat.agent.service import`
    — service.py gone) and **removed in D5**. Their uncovered scenarios
    were migrated to `tests/test_apps_chat_agent_context_manager.py`
    (18 cases for `AgentContext` + `ContextManager.compact()` +
    `ContextManager.truncate()`).

**`llmwikify_original.py`** — **removed 2026-06-19**. The
MODULARIZATION_REPORT.md still mentions the path (historical reference).

## Removal plan (v0.5)

### Done (2026-06-19)

✅ `llmwikify_original.py` deleted (-1965 LOC).

✅ `chat_legacy/` emptied — all 9 modules moved to
`apps/chat/research_engine/` (8 renamed + `__init__.py`).

✅ `llmwikify_v0_41_legacy/service.py` already deleted by B-7
(2026-06-18, 98a47bd).

✅ 3 dead archive tests (`test_apps_chat_agent_service.py` +
`test_compaction.py` + `test_token_truncation.py`, 1742 LOC)
uncollectable since B-7. **Removed in D5** with migration of
uncovered scenarios to `test_apps_chat_agent_context_manager.py`
(18 new cases).

### Remaining

1. `apps/chat/research_engine/` — 9 inlined modules + `__init__.py`.
   These are now production code; no longer archive.
2. `llmwikify_v0_41_legacy/` directory itself — only `README.md` +
   empty `__init__.py` remain. Safe to `git rm -r` in v0.5 cleanup.

## See also

- `llmwikify_v0_41_legacy/README.md` — god-class decomposition record.
- `docs/poc/plan-b-results.md` — Plan B 5-step state machine refactor
  results.