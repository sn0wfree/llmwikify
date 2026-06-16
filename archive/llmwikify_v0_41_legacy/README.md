# llmwikify v0.41 Legacy Service Archive

This directory contains the pre-v0.41 `ChatService` monolith and its
associated tests, **archived on 2026-06-16** as part of the
god-class elimination effort.

## Why archived

In v0.41, the `ChatService` class (1,236 lines, 9+ responsibilities) was
decomposed into six focused components:

- `src/llmwikify/apps/chat/agent/orchestrator.py` — SSE chat loop + ReAct bridge
- `src/llmwikify/apps/chat/agent/context_manager.py` — session state, compaction, truncation
- `src/llmwikify/apps/chat/agent/tool_executor.py` — tool dispatch + persistence
- `src/llmwikify/apps/chat/agent/prompt_builder.py` — system prompt construction
- `src/llmwikify/apps/chat/agent/bridge_backend.py` — adapter for legacy 5-method interface
- `src/llmwikify/apps/chat/agent/text_mode_tool.py` — text-mode `[TOOL_CALL]` parser

Production never instantiates `ChatService`; all paths use
`ChatOrchestrator` via `AgentService`. The files here are kept for
historical reference only — they sit outside the `tests/` tree and
are not collected by pytest.

## Contents

| File | LOC | Purpose |
|------|----:|---------|
| `service.py` | 1,236 | Legacy monolithic `ChatService` |
| `test_apps_chat_agent_service.py` | 1,561 | Tests targeting `ChatService` private API |
| `test_apps_chat_agent_chat_react_bridge.py` | 1,126 | Tests using `ChatService` as bridge backend |
| `test_compaction.py` | 95 | Tests for `_compact_messages` (now in `ContextManager`) |
| `test_token_truncation.py` | 86 | Tests for `_truncate_messages` (now in `ContextManager`) |

## Replacement coverage

All behavior previously tested here is now covered by component-level
tests in the main `tests/` tree:

- `tests/test_apps_chat_agent_agent_service.py` — end-to-end
  `AgentService` / `ChatOrchestrator` behavior
- `tests/test_apps_chat_agent_*_*.py` — per-component coverage
  (orchestrator, context_manager, tool_executor, prompt_builder, etc.)

## Reference

- Decomposition plan: `docs/designs/v0.41-chat-service-split.md`
- Historical releases: `docs/releases/v0.36.0.md`, `docs/releases/v0.37.0.md`
- Frontend SSE contract: `ui/webui/src/api.ts` (`SaveWarningEvent`)

## Restoration

If you ever need to resurrect this code:

```bash
git mv archive/llmwikify_v0_41_legacy/service.py src/llmwikify/apps/chat/agent/
git mv archive/llmwikify_v0_41_legacy/test_*.py tests/
# Then re-add the imports in tests/test_foundation_llm_lal_errors.py
```

But seriously — don't. The decomposition is final.
