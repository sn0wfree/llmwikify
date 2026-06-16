# chat_legacy/

This directory contains the v0.41 autoresearch chat layer, git-mv'd
from `src/llmwikify/apps/chat/` in commit `d4a23dd` (v0.42+).

## Files (9)

| File | What it was | Replaced by |
|---|---|---|
| `engine.py` | `ResearchEngine` (ReAct research loop orchestrator) | `apps/chat/agent/orchestrator.py::ChatOrchestrator` + `agent/react_engine.py::ReActEngine` |
| `actions.py` | 8 free-function `action_*` (ReAct research actions) | Built into `ReActEngine`'s action protocol |
| `observer.py` | `ResearchObserver` (state refresh after each action) | `apps/chat/agent/research_bridge.py::translate_react_events` |
| `gates.py` | `ResearchGates` (framework/quality compliance checks) | `apps/chat/agent/orchestrator.py` gate logic |
| `reasoner.py` | `ResearchReasoner` (ReAct Thought step) | `apps/chat/agent/react_engine.py::ReActEngine` |
| `report.py` | `ReportGenerator` | `apps/chat/skills/research_skill.py` |
| `llm_step.py` | `run_prompt` helper (unified LLM call layer) | `foundation/llm/streamable.py::StreamableLLMClient` |
| `resume.py` | `ResearchResumeLoader` (hydrate state from DB) | `apps/chat/agent/orchestrator.py` session resume path |
| `routes.py` | `/api/autoresearch/*` FastAPI router | **REMOVED** from `interfaces/server/http/routes.py:524-525` |

## Why archived, not deleted

1. **Git history preservation** — `git mv` (not delete+add) keeps
   rename detection, so `git log --follow` works for blame.
2. **Emergency rollback** — if a regression is found in
   `apps/chat/agent/`, the v0.41 layer can be reactivated by
   re-mounting `routes.py` and updating `__init__.py` exports.
3. **Test reference** — tests like `test_autoresearch.py` still
   test the v0.41 layer for back-compat verification.
4. **External callers** — `__init__.py` re-exports keep
   `from llmwikify.apps.chat import ResearchEngine` working.

## Back-compat shim

`src/llmwikify/apps/chat/__init__.py` re-exports:

```python
# Submodule access
from llmwikify.apps.chat import actions  # works
from llmwikify.apps.chat import engine   # works (via sys.modules injection)
import llmwikify.apps.chat.engine        # works (via sys.modules injection)

# Class access
from llmwikify.apps.chat import ResearchEngine  # works
from llmwikify.apps.chat import ResearchGates   # works
from llmwikify.apps.chat import ResearchState   # works
```

## Removal plan

These files will be **removed in v0.5** (target: 2 minor versions
after v0.42). Before removal:

1. Verify no production code imports from this path
2. Delete all 9 files
3. Remove the re-export block in `__init__.py`
4. Remove the sys.modules injection loop
5. Update `docs/diagnostics/chat-architecture-2026-06.md` to mark
   the cleanup as complete

## See also

- [`docs/diagnostics/chat-architecture-2026-06.md`](../../../docs/diagnostics/chat-architecture-2026-06.md) — full architecture analysis
- Commit `d4a23dd` — Phase 1.1 (compat-preserving archive)
- Commit `<this commit>` — Phase 1.2 (DEPRECATED removal + README)
