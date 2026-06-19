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
| `llmwikify_v0_41_legacy/chat_legacy/` | ~2,800 | Frozen 2026-06-19 | `apps/chat/research_agent.py`, `apps/chat/clarifier.py`, `apps/chat/harness/review.py` + tests |
| `llmwikify_original.py` | 1,965 | **Pending removal** | None — only mentioned in `archive/reports/MODULARIZATION_REPORT.md` |
| `reports/` | n/a | Reference docs only | None |

## Frozen-status legend

- **Frozen**: the file is on read-only semantically. Bug fixes are not
  expected, but the file remains importable for back-compat verification.
- **Pending removal**: no production code references this file. Safe to
  delete once `git grep` confirms no live imports.

## Audit methodology

The "Used by" column above is the result of this grep, run 2026-06-19:

```bash
grep -rn "from llmwikify.archive" src/ tests/ | grep -v __pycache__
```

### Results

**`llmwikify_v0_41_legacy/service.py`** — referenced only by
`tests/test_apps_chat_agent_service.py` (legacy test file). The
`ChatService` class itself is **not** instantiated by any production
code (all paths use `ChatOrchestrator` via `AgentService`).

**`llmwikify_v0_41_legacy/chat_legacy/engine.py`** — imported by
**production code**:

- `src/llmwikify/apps/chat/research_agent.py` — wraps `ResearchEngine`
- (via re-export) `src/llmwikify/apps/chat/__init__.py` for
  `from llmwikify.apps.chat import ResearchEngine`

This means `chat_legacy/` is **not yet fully frozen** — the
`ResearchAgent` class still wraps the legacy engine. A future refactor
would inline `ResearchEngine` into `apps/chat/research_engine.py` and
drop the archive dependency.

**`llmwikify_v0_41_legacy/chat_legacy/llm_step.py`** — `run_prompt`
helper used by:

- `src/llmwikify/apps/chat/clarifier.py` — clarification prompts
- `src/llmwikify/apps/chat/harness/review.py` — Harness review prompts
- `tests/test_llm_step.py` — direct unit tests

Same pattern: production code paths still route through archive.

**`llmwikify_original.py`** — original v0.10 single-file implementation.
**No imports found** outside `archive/reports/MODULARIZATION_REPORT.md`.
Safe to delete in v0.5 cleanup.

## Removal plan (v0.5)

Before deleting `chat_legacy/`:

1. Inline `ResearchEngine` into `apps/chat/research_engine.py`.
2. Inline `run_prompt` into `apps/chat/llm_step.py` (or fold into
   `StreamableLLMClient.chat_with_tools`).
3. Update `apps/chat/__init__.py` to import from new locations.
4. Update tests (`test_autoresearch.py`, `test_engine_observer_resume.py`,
   `test_llm_step.py`) to drop `archive.` prefixes.
5. Run `git grep "from llmwikify.archive"` — must return zero hits
   outside `archive/` itself.
6. `git rm` the entire `chat_legacy/` tree.

Before deleting `llmwikify_original.py`:

- Run `git grep "llmwikify_original" src/ tests/` — must return zero
  hits.
- The historical reference in `MODULARIZATION_REPORT.md` is fine
  (mentions the path that was archived).

## See also

- `llmwikify_v0_41_legacy/README.md` — god-class decomposition record.
- `llmwikify_v0_41_legacy/chat_legacy/README.md` — autoresearch v0.41
  archive record.
- `docs/poc/plan-b-results.md` — Plan B 5-step state machine refactor
  results.