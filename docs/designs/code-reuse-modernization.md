# Code Reuse & Typing Modernization

> Document the post-7-item-refactor codebase cleanup: remove real
> duplication, modernize typing imports, and prepare the ground
> for the future autoresearch rewrite (chat base + harness).
>
> **Status**: planned, 3 commits
> **Date**: 2026-06-07
> **Branch**: main

---

## 1. Background

After the 7-item refactor (Phases 1-3) + Level 2 WikiBackend Interface,
the codebase is functional and well-tested (1852 tests passing), but
a code-cleanliness audit identified three categories of issues:

### 1.1 Real code duplication (`autoresearch/` vs `agent/backend/research/`)

10 paired files were forked when `autoresearch` was promoted to an
"independent top-level project" (commit `d7641ed`-era). Most differ
by import paths or DB type signatures, not actual logic.

| File | autoresearch | agent.backend.research | diff | Re-exportable? |
|------|-------------|----------------------|------|----------------|
| `web_search.py` | 274 | 274 | **0** | ✅ (no DB dep) |
| `analyzer.py` | 92 | 93 | 5 | ❌ (DB type coupling) |
| `session.py` | 89 | 90 | 14 | ❌ (DB type coupling) |
| `synthesizer.py` | 145 | 145 | 4 | ❌ (DB type coupling) |
| `source_filter.py` | 329 | 265 | 65 | ❌ (additive behavior) |
| `quality_gate.py` | 341 | 178 | 164 | — (deferred) |
| `task_manager.py` | 236 | 144 | 115 | — (deferred) |
| `report.py` | 288 | 211 | 235 | — (deferred) |
| `review.py` | 131 | 126 | 179 | — (deferred) |
| `config.py` | 117 | 54 | 130 | — (deferred) |

The 4 DB-coupled files (analyzer, session, synthesizer, source_filter)
**look** like near-duplicates but are actually incompatible: they
operate on different SQLite databases (`autoresearch.db` vs
`agent.db`) with different schemas. A naive 1-line re-export would
break autoresearch callers that pass `AutoResearchDatabase` instances
to a class expecting `AgentDatabase`.

### 1.2 Outdated import paths (5 sites)

After the 7-item refactor moved `StreamableLLMClient` to
`llmwikify.llm.streamable` (canonical home), 5 import sites still
use the legacy `from ..llm_client import LLMClient`:

- `src/llmwikify/core/wiki_mixin_llm.py` (3 sites)
- `src/llmwikify/core/wiki_mixin_source_analysis.py` (1 site)
- `src/llmwikify/extractors/markitdown_extractor.py` (1 site)

The legacy `llm_client.py` file is kept for backward compatibility
(some tests still import `LLMClient` directly for the base-class
contract). The `llm/` subpackage's `__init__.py` does not currently
re-export `LLMClient` or `StreamableLLMClient`, forcing callers to
know the internal submodule path.

### 1.3 Pre-Python-3.10 typing idioms (9 files)

Python 3.10+ is the project floor (`requires-python = ">=3.10"`).
The new PEP 604 (`X | Y`) and PEP 585 (`list[X]`) syntax is fully
supported, but 9 files still import from `typing`:

- `Optional[X]` → `X | None`
- `List[X]` → `list[X]`
- `Dict[K, V]` → `dict[K, V]`
- `Union[X, Y]` → `X | Y`

Affected files: `server/core.py`, `mcp/adapter.py`, all 7 files in
`agent/backend/ppt/`.

---

## 2. Goals

1. **Eliminate one real duplicate** (the only safe one):
   `autoresearch/web_search.py` → 1-line re-export from
   `agent.backend.research.web_search`. Net: -272 LOC, 0 behavior
   change.
2. **Migrate 5 import sites** to the canonical `llm.streamable` path
   and re-export `LLMClient` + `StreamableLLMClient` from
   `llm/__init__.py` for discoverability.
3. **Modernize typing** in 9 files: drop `typing.Optional/List/Dict/
   Union` for the PEP 604/585 equivalents.

### Non-goals (explicit)

- **No re-export for the 4 DB-coupled files** (analyzer, session,
  synthesizer, source_filter) — they require type-adapter
  reconciliation which is a "big modification" we want to avoid.
- **No merging of the 5 large-diff files** (quality_gate, report,
  review, task_manager, config) — they are intentionally forked
  in anticipation of the autoresearch rewrite.
- **No deletion of any deprecation shim** (`mcp/server.py`,
  `agent/backend/adapters.py`, `server.create_unified_server`) —
  those are scheduled for `v0.33.0` removal per the existing
  PLAN.md and should be respected.
- **No structural changes to `WikiProtocol` or mixin architecture**
  (already cleaned up in the 7-item refactor).

---

## 3. Future: autoresearch rewrite (out of scope)

`autoresearch/` is being rebuilt as a **chat base + harness
engineering** framework. After that rewrite:

- The 4 DB-coupled duplicates will be re-examined in the new
  context (the new chat-base may not even use these classes).
- The 5 large-diff files will be re-architected from scratch.
- `web_search.py` re-export can be replaced by new harness code.

This plan is the **interim cleanup** — it reduces duplication
*now* without committing to architectural choices that may change
in the rewrite.

---

## 4. Commit-by-Commit Execution Plan

### Commit 1: `refactor(research): re-export web_search from agent.backend.research`

**Files**: 1 changed (autoresearch/web_search.py becomes 1-line
re-export; the agent.backend.research version stays as canonical).

**Net**: -272 LOC (autoresearch 274 → 2). Behavior identical
(0 diff, no DB type coupling).

**Tests**: full suite 1852 should still pass; no test changes
needed.

**Risk**: 🟢 Low. web_search has no `AgentDatabase` /
`AutoResearchDatabase` dependency, only `WebSearch(config: dict)`.

### Commit 2: `refactor(llm): migrate to llm.streamable + re-export`

**Files**: 5 changed (3 import-site migrations + 1 re-export +
1 trivial adjustment in markitdown_extractor).

- `src/llmwikify/core/wiki_mixin_llm.py` — 3 imports migrated
- `src/llmwikify/core/wiki_mixin_source_analysis.py` — 1 import
- `src/llmwikify/extractors/markitdown_extractor.py` — 1 import
- `src/llmwikify/llm/__init__.py` — re-export `LLMClient` and
  `StreamableLLMClient`

**Net**: ~+5 LOC. Behavior identical (StreamableLLMClient
extends LLMClient; subclass IS-A relationship).

**Tests**: full suite 1852 should still pass; `test_llm_client.py`
intentionally still uses the base `LLMClient` (no change).

**Risk**: 🟢 Low.

### Commit 3: `style: modernize typing imports (PEP 604/585)`

**Files**: 9 changed (mechanical replacement of
`Optional/List/Dict/Union` with `X | None / list / dict / X | Y`).

| File | Old imports | New style |
|------|------------|-----------|
| `server/core.py` | `Union` | `X \| Y` |
| `mcp/adapter.py` | `Any, Union` | `Any`, `X \| Y` |
| `agent/backend/ppt/harness.py` | `List, Optional` | `list`, `X \| None` |
| `agent/backend/ppt/schema.py` | `List, Optional` | `list`, `X \| None` |
| `agent/backend/ppt/engine.py` | `Any, Dict, List, Optional` | `Any, dict, list, X \| None` |
| `agent/backend/ppt/rules.py` | `Dict, Any, List, Optional` | `dict, Any, list, X \| None` |
| `agent/backend/ppt/chat_router.py` | `Any, AsyncGenerator, Dict, Optional` | `Any, AsyncGenerator, dict, X \| None` |
| `agent/backend/ppt/chat_engine.py` | `Any, AsyncGenerator, Dict, List, Optional` | `Any, AsyncGenerator, dict, list, X \| None` |
| `agent/backend/ppt/themes.py` | `Dict, List` | `dict, list` |

**Net**: 0 LOC (annotation-only). Behavior identical.

**Tests**: full suite 1852 should still pass.

**Risk**: 🟢 Very low. Mechanical replacement; new syntax is
backed by the typing module at runtime.

---

## 5. Verification

After each commit:
1. `python3 -m pytest tests/ --ignore=tests/e2e -q` — must be
   1852/1852 (or 1851 with the pre-existing flaky
   `test_research.py::test_engine_init_with_model_layering`)
2. No new deprecation warnings should appear
3. Final commit should also pass `graphify-out` regen if the
   dependency graph changes (this should not change since no
   public API is affected)

---

## 6. Rollback

Each commit is independently revertable:

- **Commit 1 revert**: restore `autoresearch/web_search.py` from
  the deleted version (the 274 lines are preserved in git
  history).
- **Commit 2 revert**: revert import sites to use `LLMClient`
  again; remove the re-export lines from `llm/__init__.py`.
- **Commit 3 revert**: trivial; just revert the import
  statements.

---

## 7. Time and LOC Budget

| Commit | LOC Δ | Time | Risk |
|--------|------|------|------|
| 1: web_search re-export | -272 / +0 | 5 min | 🟢 |
| 2: LLM migration + re-export | +5 / -5 | 30 min | 🟢 |
| 3: Typing modernization | 0 / 0 (annotation) | 30 min | 🟢 |
| **Total** | **-267** | **~1h** | **🟢 all** |

---

## 8. Future Roadmap (post this plan)

| Priority | Item | Effort | Value |
|----------|------|--------|-------|
| 🟡 Medium | autoresearch rewrite as chat base + harness | ~weeks | Architectural clarity |
| 🟡 Medium | Delete deprecation shims (mcp/server.py, adapters.py, etc.) | 1 commit, ~1h | Cleanup |
| 🟢 Low | v0.33.0 deprecation removal | 1 commit | API surface |
| 🟢 Low | InMemoryBackend for tests | 1 commit, ~3-4h | 5-6s test speedup |

---

## 9. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-07 | web_search re-export only (skip 4 DB-coupled) | Type-safety; re-export would break autoresearch |
| 2026-06-07 | Keep `llm_client.py` file | Backward compat for `test_llm_client.py` base-class tests |
| 2026-06-07 | Re-export `LLMClient` + `StreamableLLMClient` from `llm/` | Discoverability — users don't need to know `streamable` submodule |
| 2026-06-07 | Skip deletion of deprecation shims | Per PLAN.md, scheduled for v0.33.0 |
| 2026-06-07 | Skip merge of 5 large-diff files | autoresearch rewrite will replace them anyway |
