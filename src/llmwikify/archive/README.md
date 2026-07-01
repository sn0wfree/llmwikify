# `archive/` — Frozen Legacy Code

> ⚠️ **历史参考，不维护**。当前架构以 [`ARCHITECTURE.md`](../../../ARCHITECTURE.md) v0.38 为准。
> `reports/` 子目录是 v0.13–v0.41 时代的设计/迁移报告，仅作考古。

This directory contained code archived (via `git mv`, never deleted)
during the v0.42 → v0.4 god-class decomposition. **As of 2026-06-19,
all v0.41 archive content has been physically removed** (D6-3 cleanup).
Only reference docs (`reports/`) and this README remain.

## Contents

| Path | LOC | Status | Used by |
|------|----:|--------|---------|
| `llmwikify_v0_41_legacy/` | n/a | **Removed 2026-06-19** — `service.py` (deleted by B-7 98a47bd), 9 chat_legacy modules (git-mv'd in D4), and 3 dead tests (D5) all gone | None |
| `chat_legacy/` (subdir of above) | n/a | **Removed** with parent (D4: all 9 modules git-mv'd to `apps/chat/research_engine/`) | None |
| `llmwikify_original.py` | n/a | **Removed 2026-06-19** (01ea6ae, -1965 LOC) | None |
| `reports/` | n/a | Reference docs only (MODULARIZATION_REPORT.md etc.) | None |

## Why archived then deleted

The v0.42 → v0.4 god-class decomposition produced three categories of
legacy code. The archive served as a safety net during refactoring
(`git mv` preserves history; nothing is ever lost). After all upstream
callers migrated and 0 live imports remained, the v0.5 cleanup
deleted the archive physically.

**Total archived → deleted**:
  - `service.py` (1,236 LOC) — deleted by B-7 (98a47bd, 2026-06-18)
  - 9 `chat_legacy/` modules (~2,800 LOC) — git-mv'd in D4 to `apps/chat/research_engine/`
  - 3 dead tests (1,742 LOC) — uncollectable since B-7, migrated + removed in D5
  - `llmwikify_original.py` (1,965 LOC) — deleted in `01ea6ae` (2026-06-19)

## See also

- `docs/poc/plan-b-results.md` — Plan B 5-step state machine refactor results.
- `docs/poc/compare.md` — Phase 5 god class split documentation (§10).
- `docs/poc/apply-plan.md` — nanobot借鉴 → llmwikify 实施 (P1-1 OpenAI, P1-2 CommandRouter, P1-3 PromptBuilder).