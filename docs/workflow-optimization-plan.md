# Chat & Deep Research Workflow Optimization Plan

## Chat Workflow Optimizations

### P0 — Critical Fixes

#### 1. Context restored from DB on session resume
**Problem:** `_get_or_create_context()` creates blank context for old sessions. LLM has no memory of prior turns.
**Fix:** When session exists in DB, load messages via `db.get_messages()` and populate `AgentContext.messages`.
**Files:** `service.py` `_get_or_create_context()`, `db.py` `get_messages()`

#### 2. Tool spec includes parameter schemas
**Problem:** `_get_toolspec()` returns empty `properties: {}` and `required: []`. LLM must guess argument names and types.
**Fix:** Add `parameters` dict to `_register()` — each tool declares its arg names, types, required fields. `_get_toolspec()` reads them.
**Files:** `tools.py` `_register()` and all `_register()` call sites, `service.py` `_get_toolspec()`

#### 3. Confirmation flow: tool result fed back to LLM
**Problem:** After user approves confirmation, tool executes but result is never sent back to LLM. Conversation just ends.
**Fix:** After confirmation approval, append tool result to context and trigger a new LLM turn to generate follow-up response.
**Files:** `routes/agent.py` confirmation endpoint, `service.py` new method `_continue_after_confirmation()`

### P1 — Performance

#### 4. Async HTTP client (httpx instead of requests)
**Problem:** `requests.post(stream=True)` blocks the event loop, blocking all concurrent users.
**Fix:** Replace `requests` with `httpx.AsyncClient` in `StreamableLLMClient`.
**Files:** `adapters.py` `stream_chat()`, `chat()`, `chat_with_tools()`

### P2 — Features & UX

#### 5. Markdown rendering in chat bubbles
**Problem:** LLM responses shown as raw text, no formatting.
**Fix:** Add `react-markdown` + `remark-gfm` to render LLM output in `MessageBubble`.
**Files:** `AgentChat.tsx` `MessageBubble`, `package.json`

#### 6. Context window management
**Problem:** Entire conversation history sent to LLM. Long conversations exceed model limits.
**Fix:** Truncate messages to fit within model's context window. Strategy: keep system + last N messages, summarize older ones or drop them.
**Files:** `service.py` `chat()`, `_truncate_messages()`

---

## Deep Research Workflow Optimizations

### P0 — Critical Fixes

#### 7. Multiple search results per sub-query
**Problem:** `num_results=1` hardcoded in `gatherer.py` line 76. Each sub-query produces at most 1 source.
**Fix:** Use `config.web_search_results_per_query` (default 5). Gather all results, deduplicate by URL.
**Files:** `gatherer.py` `_gather_one()`

#### 8. Full content persisted in DB
**Problem:** Only 500-char `content_preview` stored. Analyzer and report generator work with fragments.
**Fix:** Add `content` TEXT column to `research_sources`. Store full content (truncated to `max_source_content_length`). Analyzer reads full content.
**Files:** `db.py` schema + migration, `gatherer.py`, `analyzer.py`, `report.py`

#### 9. Parallel source analysis
**Problem:** `analyze_sources()` iterates sequentially with `await asyncio.to_thread()` per source.
**Fix:** Use `asyncio.Semaphore` + `asyncio.gather()` with configurable parallelism, same pattern as gatherer.
**Files:** `analyzer.py` `analyze_sources()`

### P1 — Behavior Fixes

#### 10. Rating affects synthesis weighting
**Problem:** Sort-by-rating only affects call order, not synthesis output.
**Fix:** Pass `rating` to `SynthesisEngine.analyze_new_source()`. High-rated sources get more weight in aggregation. Add `rating_weight` multiplier to synthesis output.
**Files:** `synthesizer.py`, `core/synthesis_engine.py`

#### 11. Resume from checkpoint (not restart)
**Problem:** Resume re-runs entire pipeline from stage 1.
**Fix:** Track `current_step` in DB. On resume, skip completed stages. Gathered sources already in DB are reused.
**Files:** `engine.py` `run()`, `session.py`, `routes/research.py` resume endpoint

#### 12. Retry logic for failed operations
**Problem:** `max_retry_attempts: 3` in config but never used.
**Fix:** Add retry decorator with exponential backoff to LLM calls, web extraction, and search.
**Files:** `engine.py`, `gatherer.py`, `analyzer.py`, `report.py`, `review.py`

### P2 — Quality

#### 13. Reviewer failure handling
**Problem:** Reviewer defaults to `approved=True` on LLM failure.
**Fix:** Default to `approved=False` with error message, allow user to manually approve or retry.
**Files:** `review.py` `review()`

---

## Implementation Order

1. **Chat P0:** #1 context restore → #2 tool schemas → #3 confirmation feedback
2. **Research P0:** #7 multi-search → #8 full content → #9 parallel analysis
3. **Chat P1:** #4 async HTTP
4. **Research P1:** #10 rating weighting → #11 checkpoint resume → #12 retry logic
5. **Chat P2:** #5 markdown rendering → #6 context window management
6. **Research P2:** #13 reviewer failure

## Verification

- Run existing tests after each change: `python -m pytest tests/test_research.py tests/test_xiaomi_provider.py -x`
- Manual test: resume old chat session → verify LLM remembers prior turns
- Manual test: run Deep Research with multiple sub-queries → verify 5+ sources gathered
- Manual test: rate sources → verify high-rated sources influence report
