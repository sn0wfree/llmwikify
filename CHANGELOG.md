# Changelog

All notable changes to llmwikify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.38.0] - 2026-07-02 — Onboarding + CI (actual release)

> **Note**: This is the **actual published release** of v0.38.0. The previous
> `## [0.38.0] - 2026-06-22` section below documents the v0.38.0 development
> (nanobot v0.2.1 borrowings + auth refactor) that was merged on 2026-06-22
> but **never published to PyPI**. This section covers the 5 commits
> (302b15c, 0b6457c, 2fef73e, c763e0a, 977fe3b) that are actually shipped in
> the 2026-07-02 PyPI release.

### Added — New CLI tools (P3+)

- **`llmwikify doctor`** — System health check with 9 categories
  - Config file (existence + parse)
  - Python version (>= 3.10)
  - Core dependencies (llmwikify, yaml, duckdb, jinja2)
  - Optional extras (fastapi, fastmcp, watchdog, networkx, markitdown, tiktoken, httpx)
  - **LLM connectivity** (actual API call, 5s timeout, `max_tokens=5`, `"Say hi"`)
  - **Wiki directory** (wiki.md, .llmwikify.db, index.md, raw/)
  - **Permissions** (~/.llmwikify/ + wiki_root writability)
  - WebUI bundle (ui/webui/dist/index.html)
  - Server (GET /api/health)
  - Flags: `--skip-llm`, `--json`, `--wiki-root`
  - Exit codes: 0 (all pass), 1 (failed), 2 (config missing)

- **`llmwikify init-llm`** + `llmwikify init --llm` — One-command LLM config setup
  - Auto-detects provider from `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `MINIMAX_API_KEY`
  - Default model per provider
  - `--base-url` for OpenAI-compatible endpoints (DeepSeek, etc.)
  - `--overwrite` to replace existing config
  - Interactive prompt on first `init` if no config exists (default N)
  - `--no-llm-prompt` for non-tty/CI environments

### Fixed — Onboarding barriers (P1+P2)

- `wiki.md` no longer shows `v0.11.0` (now correctly shows `v0.38.0`)
  - Root cause: `_get_version()` imported from wrong package
- README Quick Start: 4 commands → 7 commands
  - `init → write_page → ingest → build-index → search → read_page → status → serve`
- README install hint: `pip install llmwikify` → `pip install 'llmwikify[extractors,web]'`
- CLI Reference: 12 → 32 commands (all 9 categories listed)
- Test count badge: 5900+ → 6100+ (verified via `pytest --collect-only -q`)
- TUTORIAL.md §0 broken cross-ref → inline Prerequisites line
- `serve --web` warns when WebUI bundle missing

### Added — Examples

- **`examples/04_chat_sse_client/play.py`** (new) — SSE client example
  - Was missing despite README claiming to run it
  - Supports 8 SSE event types: `session_created`, `reasoning`, `phase`,
    `tool_call`, `confirmation_required`, `save_warning`, `stream_end`, `error`
  - Configurable base URL, token, message via CLI args

### Changed — Polish (P4)

- `init` "Next steps" message no longer suggests `--agent` after first init
- `init_llm_cmd.py` — Extracted shared `create_llm_config()` function
  (used by both `init-llm` and `init --llm`)

### Documentation

- **`docs/ONBOARDING.md`** (new) — Onboarding guide + design rationale
  - 10 barriers fixed (with root cause + verify)
  - 4 design decisions (why merge init-llm into init, etc.)
- README LLM Setup section — 3 options (one-shot / standalone / interactive)
- README Doctor section — Full details (checks, exit codes, examples)
- `docs/CONFIGURATION_GUIDE.md` — Doctor chapter + global LLM config section

### CI / Release

- **`release-drafter.yml`** (new) — Auto-update draft releases on push to main
  - **Note**: Removed in v0.38.0 publish-on-tag refactor (replaced by tag-triggered pipeline)
- **`version-bump.yml`** (new) — Manual workflow to auto-PR version bumps
- **`dependency-review.yml`** (new) — PR-time dependency change review
- **README CI badges** — Tests, Lint, codecov
- **`publish-on-tag.yml`** (new) — Tag-triggered full release pipeline
  - Replaces old `release: published` trigger
  - `git push origin v0.38.0` → build → check → PyPI → GitHub Release
  - Version consistency check (pyproject.toml == tag)

### Build verified

- `python -m build` ✅
- `twine check dist/*` ✅
- 6192 tests collected (6092 + 100 new scenario tests)
- 6 workflows YAML syntax check ✅

### Migration from v0.30 → v0.38

This release jumps 8 minor versions (v0.30.0 → v0.38.0). The main changes:
- `MCPServer` Python API removed (use `llmwikify serve` CLI)
- Auth system refactored (PAT-based, see `llmwikify auth`)
- LLM config moved to `~/.llmwikify/llmwikify.json` (use `llmwikify init-llm`)
- New CLI: `doctor`, `init-llm`

### Documentation — Issue fix (outdated docs + missing tutorial)

针对 GitHub issues：
1. 文档中部分操作已过时
2. 缺一个完整的使用流程和案例

#### Fixed（过期内容修复，对齐 v0.38.0）

- **CONFIGURATION_GUIDE.md**：
  - 顶部版本 `v0.12.6` → `v0.38.0 (2026-06-30)`，footer 同步
  - 全文 8 处 `MCPServer` 引用改为 `WikiServer` + `llmwikify serve` CLI
  - 新增 3 个配置段：`server` (unified MCP+REST+WebUI)、`search` (FTS5/QMD)、
    `wikis` (multi-wiki registry)、`llm` (provider)
- **MCP_SETUP.md**：**全量重写**
  - 旧 `MCPServer(wiki).serve()` 路径 14 处替换为 `llmwikify serve` /
    `WikiServer`
  - 工具数 20 → 26（加 6 个 multi-wiki 工具表 + 2 个 scoped 变体说明）
  - 新增 Bearer auth + 远程暴露安全说明
  - 加 Claude Desktop / Cursor / opencode 配置示例
- **KNOWN_ISSUES.md**：
  - `Current Issues (v0.30.1)` 表全部标 resolved
  - 顶部新增 8 条 v0.31–v0.38 闭环记录（lifespan 迁移、MCPServer 废弃、
    tool 集 20→26、CLI/Agent 对齐、shim 清理、QuickResearch 报告持久化、
    SSE 自动重连、ingest 事务原子性）
- **REFERENCE_TRACKING_GUIDE.md**：10 处 `./llmwikify.py` → `llmwikify`
  CLI，footer 同步
- **examples/legacy/**：basic_usage / run_server / mcp_agent / django /
  flask / Dockerfile / docker-compose 全部加 `DEPRECATED` 横幅 + 指向
  新剧本
- **examples/run_server.py**：`from llmwikify.server import WikiServer`
  → `from llmwikify.interfaces.server import WikiServer`（3 处）
- **examples/mcp_agent.py**：`llmwikify mcp` → `llmwikify serve` 统一

#### Added（教程 + 剧本三件套）

- **docs/TUTORIAL.md** — **5 个端到端使用场景，~700 行中文**
  - 场景 1：个人阅读笔记 wiki（init/ingest/search/write/index/references/lint）
  - 场景 2：公司尽调知识库（batch/analyze-source/synthesize/graph）
  - 场景 3：多 wiki 协作（registry + remote + discovery）
  - 场景 4：Chat + ReAct Agent（SSE 流式 + 事件类型一览）
  - 场景 5：Quant 复现（paper → factor → DuckDB → backtest → L5）
  - 每场景固定 5 段：背景 / 步骤 / 架构图（ASCII + Mermaid）/ 底层产物
    映射 / 故障排查
  - 附录 A 配置文件优先级；B CLI vs Python 决策表；C MCP 客户端接入
- **examples/01_personal_reading_notes/** — init + ingest + search
  + write + build-index + references + lint 端到端剧本
- **examples/02_company_research_kb/** — batch + synthesize + GraphAnalyzer
- **examples/03_multi_wiki_registry/** — `WikiRegistry` + `WikiDiscovery`
  + set_default_wiki 全 Python API
- **examples/04_chat_sse_client/** — `httpx.stream` 消费 SSE，列 8 类事件
- **examples/05_paper_to_factor/** — `write_factor_yaml` + `update_index`
  + DuckDB 长表 schema
- **examples/legacy/** — 旧脚本收纳目录
- **examples/verify_playbooks.sh** — 4 剧本一键冒烟（4 passed, 0 failed）

#### Validation

- `bash examples/verify_playbooks.sh` → **4 passed, 0 failed**
- `ruff check examples/01-05_*/` → **All checks passed**
- `git grep -nE '\bMCPServer\b|from llmwikify\.server\b' docs/ examples/`
  README.md`（已弃用）→ 仅剩 deprecation 横幅中
- Python API 实测：`Wiki(path).init(agent="generic")` /
  `ingest_source` / `search` / `write_page` / `build_index` /
  `get_inbound_links` / `lint` / `GraphAnalyzer.analyze()` /
  `WikiRegistry.register_wiki/set_default_wiki/list_wikis` /
  `WikiDiscovery.scan` / `write_factor_yaml` / `update_index` 全部
  与文档示例一致

## [0.37.0] - 2026-06-09

Full release notes: [`docs/releases/v0.37.0.md`](docs/releases/v0.37.0.md)

### Added — Triple ReAct Loop 统一

- **Single `ReActEngine`** (Phase 11) — 替代 ChatService / ResearchEngine /
  AutoResearch 三个散装 ReAct 实现
- **13-step round structure** — `pre_reason` / `reason` / `post_reason` /
  `decide_action` / `execute_action` / `process_observation` / ... /
  `on_round_complete`
- **7 lifecycle hooks** — `on_session_start` / `on_round_start` /
  `on_round_complete` / `on_session_complete` / `on_error` / `on_timeout` /
  `on_cancel`
- **Standard event types** — `reasoning` / `action` / `observation` /
  `round_complete` / `action_error` / `observation_error` / `phase` /
  `timeout` / `done`
- **`AbortSignal` cancellation** + configurable timeout (default 300s)
- **ChatReActBridge** — ChatService 通过新 bridge adapter 接入 ReActEngine
- **ResearchConfig adapter** — ResearchEngine 通过 `_build_react_config`
  接入
- **+55 ReAct unit tests**

### Fixed

- 3 套 ReAct 实现的生命周期钩子去重
- cancel/timeout 逻辑统一（之前 3 套独立实现各有 bug）

## [0.36.0] - 2026-06-09

Full release notes: [`docs/releases/v0.36.0.md`](docs/releases/v0.36.0.md)

### Hardening — AgentChat 全面硬化

- **5 critical bugs fixed** — tool result feedback loop;
  `save_message` 错误吞噬；UUID collision（8→32 字符）；
  React closure staleness；duplicate DB instances
- **Architecture merged** — ChatService delegates tool-calling loop to
  `ChatBase.aask_with_tools`
- **MemoryManager fully integrated** — 6 stores, all async, all used in
  chat flow
- **Reliability stack** — LLM/DB retry；rate limiting 60 req/min/IP on
  `/api/agent/*`；SSE heartbeat；cascade delete
- **Frontend UX** — Abort button；token reset；any-message regenerate；
  SSE auto-reconnect
- **+28 chat tests / +5 webui tests**

## [0.38.0] - 2026-06-22

Full release notes: [`docs/releases/v0.38.0.md`](docs/releases/v0.38.0.md)

### Added — Nanobot v0.2.1 Borrowings

- **Runtime Context Tag isolation** (Phase 12, apply-plan §12) —
  per-call tool-result sandbox via `[Runtime Context]…[/Runtime Context]`
  wrapping in `PromptBuilder`.
- **MessageBus in-process pub/sub** (Phase 13, apply-plan §13) —
  `MessageBus` dual `asyncio.Queue` (inbound unbounded / outbound
  bounded 1024) with backpressure drop + log. New `BusAdapter` for
  SSE→bus mirror + SSE→WS envelope translation (Phase 19-A).
- **WebSocket bidirectional channel** (Phase 14, apply-plan §14) —
  `WebSocketManager` + `_Connection` + `WsSessionMap` (chat_id →
  session_id). `/api/ws/agent?token=<api_key>` endpoint with
  `?token=` auth and `1008` close on mismatch.
- **AgentRunner shared executor** (Phase 15, apply-plan §15) —
  `AgentRunner[SpecT, ResultT]` ABC. `ChatRunnerV2` inherits it;
  `SubagentManager.parent_runner` type hint relaxed to base.
- **LLMProvider ABC + ProviderConfig + RetryMode + ThinkingStyle**
  (Phase 16, apply-plan §16) — provider-agnostic core with
  `from_dict()` / `to_dict()` round-trip; old `LLMProvider` Protocol
  + `BaseLLMProvider` retained for backward compat.

### Added — Bus+WS Wire-Up (Phase 19, apply-plan §19)

- **SSE handler mirrors to bus** — every SSE event in
  `/api/agent/chat` and `/confirmations/{id}/approve-and-continue`
  is wrapped as `OutboundMessage` and published to the default
  `MessageBus`. SSE wire format is **unchanged** (mirror is a
  side-effect).
- **WS `message` routes to `ChatOrchestrator.chat()`** (Phase 19-B) —
  replaces Phase 14 echo with real chat. Each yield is mirrored to
  bus + translated to WS envelope (`delta` / `stream_end` /
  `tool_call(phase=…)`) + fan-out via `WebSocketManager.send_to_chat`.
- **`WsSessionMap`** caches `session_id` from `session_created` /
  `session_init` events so subsequent WS messages on the same
  `chat_id` resume the conversation.

### Fixed

- **`set_session_metadata` upsert fix** (Phase 17, commit `472d890`) —
  the previous UPDATE-only implementation silently failed when the
  session row didn't exist yet, causing `GoalSkill` goal-state
  writes to be lost. Now `INSERT OR IGNORE` + `UPDATE` two-step
  upsert semantics.

### Test Coverage

- 22 real-server integration tests (Phase 17 + 19-C) — catch
  integration bugs that unit tests miss.
- 154 new unit tests across Phase 12-19.

## [0.35.0] - 2026-06-09

### Fixed
- **pyproject.toml version** updated from 0.31.0 to 0.35.0 (was missed in prior releases).

### Removed — Legacy Shims Cleanup
- **`core/`** directory (37 files) — backward-compat shims removed. All callers migrated to `kernel/`.
- **`web/`** directory (2 files) — backward-compat shim removed.
- **`_legacy/`** directory (4 files) — deprecated adapters/autoresearch/mcp shims removed.
- **`agent/backend/`** — remaining 7 shim files removed (routes.py, providers/, __init__.py).
- **`apps/agent/core/`** — `config_manager.py` and `runner.py` removed.

### Added
- **`ingest_skill` pipeline** — extract+write+read orchestration skill.

## [0.34.0] - 2026-06-09

### Removed — PPT 功能彻底删除
- **`apps/ppt/`** (11 files) — PPT generation pipeline deleted entirely.
- **`interfaces/server/http/ppt.py`** (320 LOC) — PPT REST routes deleted.
- **`agent/backend/ppt.*`** (11 shims) — Legacy PPT shims deleted.
- PPT rewrite deferred to v0.37.

### Removed — Old Wrappers Deleted
- **`apps/agent/core/db.py`** (460 LOC) — `AgentDatabase` wrapper deleted.
  All callers migrated to `ChatDatabase` / `AppDatabase`.
- **`apps/agent/core/service.py`** (138 LOC) — Old `AgentService` wrapper
  deleted. All callers migrated to `apps/chat/agent/agent_service.py`.

### Changed — CRUD Skills Wired to MemoryManager
- **`memory_skill`** rewritten to use `ConversationStore.add/list/search`
  API via `ctx.config['memory_manager']`.
- **CRUD skills** (`memory/notify/scheduler/dream`) now receive managers
  via `SkillService` auto-injection.

### Added — SkillService WikiService Injection
- **`SkillService`** now accepts `wiki_service` param and auto-injects
  `dream_editor`, `notification_manager`, `scheduler` into `ctx.config`
  on each `execute()` call. CRUD skills are now production-ready.
- **`WikiService`** exposes public `get_dream_editor()`,
  `get_notification_manager()`, `get_scheduler()` methods.

### Fixed — Runtime HTTP 500 Errors
- `chat_sse.py`: method names fixed (`list_sessions`→`list_chat_sessions`,
  `get_session`→`get_chat_session`, `get_messages`→`get_chat_messages`).
- `research.py`: import paths fixed (`.agent`→`.chat_sse`,
  `core.service`→`agent.agent_service`).
- `research/db.py`: `row["c"]`→`row[0]` for sqlite3 tuple results.

### Architecture
- 36 files changed, -4302 lines net (PPT removal).
- 4/4 architecture contracts PASS.
- 2357 tests pass, 8 pre-existing 3rd-party failures.

## [0.33.0] - 2026-06-09

### Added — 5+1-Service Architecture
- **`MemoryManager`** (`apps/chat/memory/`) — 6 stores:
  `ConversationStore`, `KnowledgeStore`, `ContextStore`,
  `ReActStateStore`, `UserPreferenceStore`, `MemoryIndex`.
  ~370 LOC, 14 tests.
- **`SkillService`** (`apps/chat/skills/service.py`) — facade over
  `SkillRegistry` + `SkillRuntime` with `register_all()` and
  `execute()` interface. ~120 LOC, 8 tests.
- **`HarnessService`** (`apps/chat/harness/service.py`) — facade over
  6 eval primitives (QualityGate, SourceFilter, StructureValidator,
  ResearchReviewer, ResearchRevisor, SourceAnalyzer) with
  lazy-init caching. ~110 LOC, 11 tests.
- **`AgentService`** (`apps/chat/agent/agent_service.py`) — composition
  root wiring `AppDatabase` + `ChatService` + `WikiService` + 3 new
  services. ~220 LOC, 10 tests. Backward compat: old methods
  (`chat`, `run_dream`, `list_notifications`, etc.) all delegate.

### Architecture
- **Service responsibilities**:
  | Service | LOC | Role |
  |---|---|---|
  | ChatService | 463 | SSE chat + DB + session |
  | WikiService | 440 | multi-wiki + dream/notify/scheduler/tool |
  | SkillService (NEW) | 120 | skill facade |
  | HarnessService (NEW) | 110 | eval facade |
  | MemoryManager (NEW) | 370 | memory base (6 stores) |
  | AgentService (NEW) | 220 | composition root |

### Notes
- Backward compat preserved: `apps/agent/core/{db,service}.py`
  wrappers kept and will be removed in v0.34.0.
- Full release notes: `docs/releases/v0.33.0.md`.

## [0.32.5] - 2026-06-09

### Added — Skill Pipeline Split (Phase 12a-d)
- **`gather_skill` + `report_skill`** — Extracted from `research_skill.py` into dedicated Skill classes. `research_skill` now composes them as `gather` + `report` phases of the 7-step ReAct pipeline.
- **4 CRUD skills** — `memory_skill`, `notify_skill`, `scheduler_skill`, `dream_skill`. Currently registered in `SkillRegistry` but not wired into any service (dead code, pending v0.33.0 service injection).
- **`wiki_query_skill`** — 28-action aggregator unifying `WikiToolRegistry` (21 tools) + MCP (29 tools) into a single entry point.
- **`asyncio_mode=auto`** in `pytest.ini` — 154 async tests unblocked. Mock test isolation fix.
- 76 new tests (23 gather/report + 36 CRUD + 17 wiki_query).

### Added — 3-Facade Database (Stage A0-E)
- **`BaseDatabase`** (`apps/db_base.py`) — shared SQLite lifecycle (auto-migration, schema init, size check).
- **`ResearchDatabase`** (`apps/research/db.py`, 727 lines, 27 methods) — owns 4 research tables.
- **`WikiDatabase`** (`apps/wiki/db.py`, 403 lines, 17 methods) — owns 4 wiki-ops tables.
- **`AppDatabase`** (`apps/db.py`, 56 lines) — aggregates 3 facades, single injection point.
- **`context_entries` table** (NEW) — for v0.33.0 MemoryManager.

### Changed
- **`ChatDatabase` shrinks to 4 tables** — `chat_sessions`, `chat_messages`, `tool_calls`, `context_entries`. The 17 wiki-domain and 27 research-domain methods are thin delegates (via lazy `self._wiki` and `self._research`).
- **DB filename: `autoresearch.db` → `.llmwiki_agent.db`** — auto-migrated on first access.
- **`AgentService` accepts `AppDatabase`** — optional `app_db` parameter; constructs internally if not provided.
- **`AutoResearchDatabase = ChatDatabase` (subclass)** — initializes all 3 facades for backward compat.

### Removed
- **PPT archived** — 5 PPT tests deleted (`test_ppt_chat_presentation_persistence.py`). 6 PPT skills, 3 PPT tables, 16 PPT methods removed from `AgentDatabase` wrapper. PPT rewrite deferred to v0.37.

### Fixed
- **`migrate_db_v1_to_v2`** — test helper uses `autoresearch_sessions` table name; migration script creates target table directly.
- **Architecture contract** — `test_agent_providers_uses_chat_providers` updated to check new import paths.

### Test Statistics
| Metric | v0.32.0 | v0.32.5 | Delta |
|---|---|---|---|
| Passing tests | 2164 | **2348** | +184 |
| Pre-existing failures | 13 | 4 | -9 |
| Architecture contracts | 4/4 | 4/4 | — |

The 4 remaining failures are 3rd-party env issues (pymupdf, youtube_transcript_api), not v0.32.5 regressions.

### Migration
- DB filename auto-renamed (`autoresearch.db` → `.llmwiki_agent.db`), no action needed.
- All old import paths still work via deprecation wrappers (removed in v0.33.0).
- Prefer `AppDatabase` over separate facades in new code.

### Notes
- Full release notes: `docs/releases/v0.32.5.md`.
- Next: v0.33.0 (5+1-service architecture, ~14h per `docs/designs/v0.33-service-refactor.md`).

## [0.32.0] - 2026-06-08

### Added — Phase 1: Skill framework (`apps/chat/skills/`)
- **`Skill` ABC + `SkillAction` + `SkillContext` + `SkillResult` + `SkillManifest`** — 5 dataclasses/classes that form the unified contract for any chat-facing capability.
- **`SkillRegistry`** — process-wide, thread-safe collection of registered skills. `default_registry()` singleton + `reset_default_registry()` for test isolation.
- **`SkillRuntime`** — executor with JSON Schema subset validation (`required` + `type` + `additionalProperties: false`), 6-tier error hierarchy (`SkillError` → 5 subclasses), exception → `SkillResult.fail(...)` translation.
- **6 error types**: `SkillNotFoundError`, `ActionNotFoundError`, `SkillValidationError`, `SkillExecutionError`, `ConfirmationRequiredError`.
- **79 new unit tests** covering Skill ABC, Registry, Runtime, 6 error types, manifest aggregation.
- Location: `src/llmwikify/apps/chat/skills/{base,registry,runtime,errors}.py`

### Added — Phase 5: 23 base actions
- **14 base actions** (`search`, `extract`, `read`, `write`, `lint`, `plan`, `analyze`, `summarize`, `score`, `revise`, `filter`, `graph`, `reason`, `observe`) — each a thin wrapper over existing wiki / engine / DB methods.
- **8 detect actions** (`detect_{knowledge_gaps,data_gaps,outdated_pages,dated_claims,query_page_overlap,missing_cross_refs,potential_contradictions,redundancy}`) — extracted from `kernel/wiki/mixins/analysis/lint.py::_detect_*` methods via a `DetectActionSkill` base class.
- **1 clarify action** (`clarify`) — rule-based fallback for `ResearchClarifier.clarify`.
- **`actions/__init__.py` contract**: `assert len(ALL_ACTIONS) == 23` on import — silent-drift guard for the inventory.
- **86 new tests** covering all 23 actions, OpenAI schema generation, runtime validation.
- Location: `src/llmwikify/apps/chat/skills/actions/`

### Added — Phase 8: ReactLoop framework
- **`ReactConfig` (13-field dataclass)** + **`ReactLoop` class** with `run(ctx)` async generator.
- **5 event types** yielded by `run()`: `reasoning`, `action_error`, `observation_error`, `round_complete`, `phase(done)`.
- **9 lifecycle hooks**: `restore_state`, `done_condition`, `on_before_act`, `on_after_act` (gate intervention), `on_before_observe`, `on_after_observe`, `persist_state`, `max_rounds`, `reason_prompt`.
- `reason` callable (LLM-driven or rule-based) + `observe` callable (state → observations).
- 40 new tests covering all hooks, edge cases (unknown action, max_iterations cap, action_error).
- Location: `src/llmwikify/apps/chat/agent/react_loop.py`

### Added — Phase 6: research_skill
- **`ResearchSkill`** — thin ReactLoop wrapper composing 7 phase handlers:
  1. `plan` → `plan_skill.plan`
  2. `gather` → inline (will be split into `gather_skill` pipeline in v0.32.5)
  3. `analyze` → `analyze_skill.analyze`
  4. `synthesize` → `summarize_skill.summarize`
  5. `score` → `score_skill.score` (3-dim: length/structure/citations)
  6. `revise` → `revise_skill.revise` (only if score < 0.5)
  7. `report` → inline markdown assembly
- **3 public actions**: `run_research`, `resume_research`, `cancel_research`.
- **State persistence**: every round serializes the full state (15+ fields) into `research_steps.result_json` (new table from Phase 3). Resume loads the last step.
- 52 new tests covering handler unit tests, end-to-end, persistence, cancel flow.
- Location: `src/llmwikify/apps/chat/skills/research_skill.py`

### Added — Phase 3: ChatDatabase consolidation + research_steps
- **`ChatDatabase`** class consolidating the two pre-refactor research databases into one file (`apps/chat/db.py`).
- **4 tables** in one SQLite file (`data_dir/autoresearch.db`):
  - `autoresearch_sessions` (unchanged schema, +9 framework JSON columns)
  - `autoresearch_sub_queries`
  - `autoresearch_sources`
  - **`research_steps`** (NEW) — one row per ReAct/6-step round, persists the 15+ ResearchState fields
- **`AutoResearchDatabase = ChatDatabase`** alias for backward compat (same class).
- **New API**: `save_step` / `get_step` / `list_steps` / `delete_steps` / `update_step_status` / `save_research_state` / `load_research_state`.
- **Migration script**: `scripts/migrate_db_v1_to_v2.py` — dry-run + backup + copy from old `agent.db::research_sessions` to new `autoresearch.db::autoresearch_sessions`. 9 tests cover end-to-end.
- 25 + 9 new tests.

### Added — Phase 7: 5 harness eval classes
- **5 evaluation classes** → `apps/chat/harness/`:
  - `QualityGate` (4 base gates + 4 framework gates)
  - `SourceFilter` (filter_sources + compute_quality_score)
  - `ResearchReviewer` + `ResearchRevisor` (LLM-as-judge)
  - `StructureValidator` (3-layer structure scoring)
  - `SourceAnalyzer` (entity recognition)
- 5 backward-compat shim files at the old paths (removed in v0.33.0).
- 32 new tests covering package structure, shim identity, class instantiation, GateResult dataclass.
- Location: `src/llmwikify/apps/chat/harness/`

### Added — Phase 4: providers migrate
- **`apps/chat/providers/`** package: `__init__.py`, `base.py`, `registry.py`, `xiaomi.py`, `minimax.py` (4 LLM provider files, 261 LOC).
- 5 backward-compat shim files at the old `agent/backend/providers.*` paths.
- `pyproject.toml` updated to register the new package.

### Added — Phase 2: eval_harness rename
- **`apps/chat/eval_harness.py`** (renamed from `harness.py`) — frees the `harness/` package slot for Phase 7.

### Added — Phase 9: REST routes migrate
- **3 REST route modules** → `interfaces/server/http/`:
  - `agent.py` → `chat_sse.py` (renamed: the SSE feature is a chat concern, not an agent concern)
  - `ppt.py`
  - `research.py`
- **Removed L3→L4 dependency** in `apps/chat/routes.py` via dependency inversion: the LLM client is now passed explicitly via `set_autoresearch_deps(llm_client=agent_service._get_llm(), ...)` at L4 startup.
- 4 backward-compat shim files at `agent/backend/routes{,_agent,_ppt,_research}.py`.
- 24 new tests covering new home, shims, no L3→L4 import.

### Added — Phase 10: ChatBase + Skill integration
- **`ChatBase.register_skills(registry)`** — bulk-register all skill actions as LLM tools with qualified names (`<skill>.<action>`).
- **`ChatBase.tools_schema(registry)`** — generate OpenAI function-calling JSON schema for the LLM.
- **`ChatBase.invoke_tool(name, args, ctx)`** + **`ainvoke_tool(name, args, ctx)`** — sync/async split that bridges to the async `SkillRuntime.execute` (uses `asyncio.run()` when no event loop is running).
- **`ChatBase.ask_with_tools(prompt, ...)`** — full OpenAI-style tool-call loop with `DEFAULT_MAX_TOOL_ITERATIONS = 8` cap.
- **Fixed 3 latent bugs** discovered by the new test suite:
  1. `invoke_tool()` was returning an unawaited coroutine (now sync/async split with `ainvoke_tool`)
  2. `_extract_content_and_tool_calls()` only normalized tool_calls for object replies, not dicts (now always normalizes via `_normalize_tool_call_dict`)
  3. `asyncio` import was missing
- **`_SkillToolProxy`** — internal wrapper that resolves a qualified tool name back to a skill action via the registry.
- 41 new tests covering construction, register_skills, tools_schema, invoke_tool, ask_with_tools, edge cases.

### Changed
- **Backward compatibility**: 28 MCP `@mcp.tool` definitions in `interfaces/mcp/tools.py` are **byte-identical** to v0.31 — no MCP client breakage.
- **All old import paths** still work via 14 deprecation shim files in `_legacy/`, `core/`, and `agent/backend/`. Scheduled for removal in v0.33.0.
- **Test growth**: 1911 → 2164 passing (+253 tests), 116 skip, 4/4 architecture contracts green.
- **New CLI**: `python -m scripts.migrate_db_v1_to_v2 [--data-dir DIR] [--apply]` to migrate pre-Phase-3 research data.

### Deprecated (will be removed in v0.33.0)
- `llmwikify.apps.chat.quality_gate` → use `llmwikify.apps.chat.harness.quality_gate`
- `llmwikify.apps.chat.source_filter` → use `llmwikify.apps.chat.harness.source_filter`
- `llmwikify.apps.chat.review` → use `llmwikify.apps.chat.harness.review`
- `llmwikify.apps.chat.structure_validator` → use `llmwikify.apps.chat.harness.structure_validator`
- `llmwikify.apps.chat.analyzer` → use `llmwikify.apps.chat.harness.source_analyzer`
- `llmwikify.apps.agent.routes.*` → use `llmwikify.interfaces.server.http.*`
- `llmwikify.apps.agent.backend.providers.*` → use `llmwikify.apps.chat.providers.*`
- 14 shim files emit `DeprecationWarning` on import.

### Notes
- **PPTSkill** (3 PPT-related skills) is **deferred to v0.37** — see `docs/KNOWN_ISSUES.md`.
- The 8 pre-existing 3rd-party-dep test failures (pymupdf, duckduckgo_search, tavily, youtube_transcript_api) are environment issues, NOT v0.32 regressions. They remain failures in the baseline; fix in a separate release.
- v0.32.5 is the next minor release — it will add: `gather_skill` / `report_skill` pipelines, `wiki_query_skill` aggregator, dream_skill, notify_skill, scheduler_skill, memory_skill, Tauri desktop packaging.

## [Unreleased]

### Changed — Phase 3 #6: CLI `mcp` / `serve` consolidation
- **`mcp` is now an argparse alias of `serve`** — full backward compatibility. Type `llmwikify mcp ...` and it works just like `llmwikify serve ...`. The `mcp` alias will be removed in **v0.34.0**.
- **New `llmwikify help` subcommand** — lists all available commands plus the alias table. Use `llmwikify help --aliases` to see just the aliases.
- **`mcp` no longer appears as a separate entry in `llmwikify --help`** — but `serve`'s help text now includes `(alias: mcp)` to make the relationship explicit. The `--help` text examples have been updated to use `serve`.
- **Bonus capability** — `mcp` users now have access to all of `serve`'s flags, e.g. `llmwikify mcp --web` (previously an argparse error).
- **`mcp/server.py` 1-line delegations** — the 3 deprecated functions (`create_mcp_server`, `serve_mcp`, `create_unified_server`) now delegate to `MCPAdapter` and `WikiServer`. The deprecation warning is still emitted on import for external users but is silenced for internal callers.
- **`init` MCP templates** — unchanged. The `command: ["llmwikify", "mcp"]` config written by `init --agent ...` still works because `mcp` is now an alias. The new `test_init_template_supports_both_mcp_and_serve_aliases` test verifies the template can be safely rewritten with `serve` in v0.34.0+.

### Documentation
- New: `docs/archive/done/cli-help-and-aliases.md` — full explanation of the `mcp` → `serve` alias, deprecation timeline, port/protocol access points, and migration guide.
- `README.md` — examples updated to use `llmwikify serve` (with notes about the `mcp` alias).

### Added — Unified FastAPI Server
- **New `server/` module** — Unified FastAPI-based server architecture:
  - `server/core.py` — `WikiServer` class orchestrates MCP + REST + WebUI
  - `server/http/routes.py` — REST API endpoint registrations
  - `server/http/middleware.py` — CORS + optional API key authentication
  - `server/utils/webui.py` — React SPA static file mounting
  - `server/constants.py` — Shared configuration constants
- **129 new unit tests**:
  - 26 tests for `RelationEngine` (neighbors, paths, statistics, contradictions)
  - 24 tests for FastAPI routes (all `/api/wiki/*` endpoints, auth middleware)
  - 15 tests for `WikiServer` core (configuration, setup, MCP mounting)
  - 64 existing tests updated/refactored

### Fixed — Code Quality & Bugs
- **27+ silent exception catches fixed** — All `except Exception:` now capture exception objects and log details with warning level
- **Health check AttributeError** — Fixed `wiki.initialized` reference → correct `wiki.is_initialized()` method call
- **Type annotations** — Added missing type hints for `Wiki.__init__`, `Wiki.close()`, `MCPAdapter.asgi_app`
- **Circular imports** — Fixed import cycles in `mcp/__init__.py` and `server/__init__.py`

### Changed
- **Starlette → FastAPI migration**: Server now uses FastAPI with auto-generated OpenAPI docs at `/docs`
- **Test coverage**: 879 → 1008+ Python tests passing

## [0.30.0] - 2026-04-24

### Added — Phase 2: Wiki Mixin Refactoring (2026-04-21)
- **12 new Mixin classes** extracted from `wiki.py` (2724 → 135 lines, -95%):
  - `WikiUtilityMixin` — slug generation, timestamps, templates, page iteration
  - `WikiLinkMixin` — wikilink resolution, fixing, inbound/outbound links
  - `WikiSchemaMixin` — wiki.md read/update, page type mapping
  - `WikiInitMixin` — directory setup, core files, MCP config, skill files
  - `WikiPageIOMixin` — page CRUD, search, log, index file update
  - `WikiSourceAnalysisMixin` — source analysis, caching, summary pages
  - `WikiLLMMixin` — LLM calls with retry, source processing, synthesis
  - `WikiRelationMixin` — relation engine, graph analysis, operations
  - `WikiIngestMixin` — source ingestion, extraction, raw collection
  - `WikiQueryMixin` — query pages, similarity matching, sink integration
  - `WikiSynthesisMixin` — cross-source synthesis suggestions
  - `WikiStatusMixin` — status reporting, recommendations, hints
  - `WikiLintMixin` — health check (delegates to WikiAnalyzer)
- **Public API unchanged** — all 879 Python tests + 38 frontend tests pass without modification
- **Mixin composition** — `Wiki` class inherits from all 12 mixins in dependency order
- **WikiAnalyzer preserved** — `WikiLintMixin` delegates to `WikiAnalyzer` (Phase 1 extraction)

### Added — Web UI Enhancements (2026-04-22 ~ 2026-04-24)
- **Collapsible Sidebar** — Toggle sidebar visibility, auto-expand groups
- **Pinned Pages** — Quick access to frequently used pages
- **Page Tree Enhancement** — Dynamic colors by page type, type icons, search filtering, sorting options
- **Graph Visualization Upgrade** — D3.js with PageRank-based node sizing, community coloring, bridge node highlighting, suggested pages as dashed nodes
- **Project Metadata Display** — `llmwikify · project-name` format using wiki root directory name
- **Version Display** — `v0.30.0` version number right-aligned in sidebar header
- **Status API Enhancement** — Backend `status()` endpoint returns `version` and `root` fields

### Added — Agent Layer (Completed v0.30.0)
- **8 Agent sub-systems fully implemented**:
  - `WikiAgent` — Main orchestrator class
  - `AgentRunner` — Execution loop and state management
  - `TaskScheduler` — Cron-based scheduled task execution (croniter)
  - `AgentMemory` — Short/long-term memory management
  - `AgentTools` — Wiki tool bindings and MCP integration
  - `HooksSystem` — Event hooks with pre/post operation callbacks
  - `NotificationManager` — User notification system
  - `DreamEditor` — Asynchronous proposal generation with human confirmation flow
- **All 85+ Agent tests passing**
- **Dream Confirmation Flow**: Agent proposes changes → Human reviews/confirms → Changes applied

### Fixed — Code Quality (2026-04-22 ~ 2026-04-24)
- **Mypy Type Checking**: Resolved all core CLI, index, and protocol type errors. Configured optional dependencies.
- **Ruff Lint**: Resolved all lint issues, updated config format.
- **E2E Tests**: Fixed selector issues, added type stubs.
- **Graph Stability**: Improved node position persistence, smooth transitions.

### Changed
- `wiki.py` reduced from 2724 lines to 135 lines (only `__init__` + lazy properties)
- `core/__init__.py` exports all 12 mixin classes alongside `Wiki`, `WikiIndex`, `QuerySink`, `WikiAnalyzer`
- TypeScript API interfaces updated with new optional `version` and `root` fields
- Frontend built and bundled with latest changes

### Architecture
- Mixin files total: 2603 lines across 12 files
- Clear separation of concerns: each mixin has single responsibility
- Independently testable: each mixin can be tested in isolation
- Agent layer fully decoupled from core via MCP protocol
- Web UI fully integrated with MCP REST API

### Tests
- **879+ Python tests passing** (all)
- **38+ Frontend tests passing** (Vitest + React Testing Library)
- **85+ Agent layer tests passing**

## [0.29.0] - 2026-04-17

### Added — Web UI P1 Integration
- **3 new MCP tools**: `wiki_suggest_synthesis`, `wiki_knowledge_gaps`, `wiki_graph_analyze(action="analyze")`
- **Insights Panel** in Web UI sidebar with 3 tabs:
  - **Synthesis** — cross-source reinforced claims, contradictions, knowledge gaps
  - **Gaps** — outdated pages, knowledge gaps, redundant pages detection
  - **Graph** — PageRank hubs, bridge nodes, suggested pages from graph analysis
- **Graph view upgraded** — uses `wiki_graph_analyze('analyze')` instead of per-page fetch:
  - Node sizing based on PageRank centrality score
  - Node coloring by detected community (Leiden/Louvain)
  - Bridge nodes highlighted with orange stroke + indicator
  - Suggested pages shown as dashed-outline ghost nodes
  - Analysis summary overlay showing community count, bridge count, top hubs
- **Health panel expanded** — added "stale pages" indicator alongside broken links and orphans
- **Click-to-load insights** — panels load on demand, refreshable via ↻ button

### Changed
- `wiki_graph_analyze` MCP tool now supports `action="analyze"` for P1.3 graph analysis
- Graph visualization now renders from single API call instead of N sequential requests
- `graph.js` refactored with `buildFromAnalysis()` primary path + `buildFromReferences()` fallback

### Fixed
- Web UI no longer limited to v0.27.0 feature set — all P1 features now accessible
- `heightlightedNodes` typo fixed to `highlightedNodes` in GraphView class

## [0.28.0] - 2026-04-17

### Added — P0: Enhanced Source Page Format
- **Source pages now include 6 structured sections** (was 3):
  1. `## Summary` — Document overview and analytical perspective
  2. `## Key Entities & Relations` — Entity list with types/attributes + relation graph
  3. `## Key Claims & Facts` — Claims with confidence levels + key facts
  4. `## Contradictions & Gaps` — Potential contradictions and data gaps (optional, only if detected)
  5. `## Cross-References` — `[[wikilink]]` references to related wiki pages
  6. `## Sources` — Citation with `[Source: Title](raw/filename)` format
- All 9 `analyze_source` extraction fields now mapped to Source page sections
- `wiki_schema.yaml` updated with complete Source page template example

### Added — P1.1: Cross-Source Synthesis Engine
- **`SynthesisEngine` class** (`core/synthesis_engine.py`) — compares new sources against existing wiki
  - `_find_reinforced_claims()` — detects claims confirmed by multiple sources
  - `_find_new_contradictions()` — finds conflicts between new and existing content
  - `_find_knowledge_gaps()` — identifies topics needing more information
  - `_find_new_entities()` — suggests creating pages for new entities
  - `_find_topic_overlap()` — detects redundant topic coverage
- **`Wiki.suggest_synthesis()` method** — analyze sources and return suggestions (not auto-executed)
  - Respects "stay involved" principle — human decides what to do with suggestions
  - Returns: reinforced claims, contradictions, knowledge gaps, suggested updates, new entities
- **CLI: `llmwikify suggest-synthesis [source]`** — generate cross-source synthesis suggestions
  - `--json` flag for programmatic consumption

### Added — P1.2: Smart Lint 2.0
- **`_detect_outdated_pages()`** — pages referencing years ≥2 years old
- **`_detect_knowledge_gaps()`** — unreferenced entities, isolated source pages without wikilinks
- **`_detect_redundancy()`** — similar page names, potentially duplicate content
- **Lint output enhanced** — investigations now include Contradictions, Data Gaps, Outdated Pages, Knowledge Gaps, Redundancy sections
- **CLI: `llmwikify knowledge-gaps`** — focused knowledge gap analysis command

### Added — P1.3: Knowledge Graph Analyzer
- **`GraphAnalyzer` class** (`core/graph_analyzer.py`) — comprehensive graph analysis
  - PageRank centrality scoring to identify core concepts
  - Hub/Authority node identification (high out-degree / in-degree)
  - Community detection with automatic labeling
  - Bridge node detection (nodes connecting multiple communities)
  - Suggested page generation for orphan concepts and under-connected pages
- **`Wiki.graph_analyze()` method** — run full graph analysis
- **`Wiki.graph_suggested_pages_report()` method** — generate human-readable report
- **CLI: `llmwikify graph-analyze`** — analyze knowledge graph structure
  - `--json` for programmatic output
  - `--report` for detailed suggested pages report

### Changed
- Source page format significantly enriched — from 3 sections to 6 sections
- Lint investigations expanded from 2 to 5 categories
- All new features respect "stay involved" principle — suggestions only, no auto-execution

### Fixed
- Test infrastructure updated for new graph analyzer methods
- CLI command registration for all new P1 features

### Tests
- **24 new tests** across 2 files: `test_p1_features.py` (12) + `test_p1_3_graph_analyzer.py` (12)
- All tests passing: 760 total (was 736)

## [0.27.0] - 2026-04-16

### Changed
- **Wikilink Resolution**: `_resolve_wikilink_target` now uses two-layer strategy (direct path → SQLite index), no longer performs filesystem rglob scans.
- **Index Page Names**: `page_name` in SQLite index now stores full relative paths (e.g., `concepts/Factor Investing` instead of `Factor Investing`), ensuring consistent resolution across all operations.
- **Wikilink Convention**: `wiki_schema.yaml` now requires directory prefix in wikilinks (e.g., `[[concepts/Factor Investing]]` instead of `[[Factor Investing]]`).

### Added
- **`resolve_by_name` Method**: New `WikiIndex.resolve_by_name()` for efficient page resolution via SQL lookup with basename fallback.
- **`fix_wikilinks` Method**: Auto-repair broken wikilinks by adding directory prefix. Supports `dry_run` mode, handles section links and aliases, reports ambiguous matches.
- **`lint(mode="fix")` Auto-Fix**: Running lint with `mode="fix"` now automatically repairs broken wikilinks and reports changes.

### Fixed
- **Graph Export**: Hardcoded entity paths in `graph_export.py` now strip directory prefix before slugifying, fixing clickable entity nodes in HTML export.
- **Orphan Detection Consistency**: Index now uses full paths, matching the format used by `get_inbound_links()` and `get_outbound_links()`.

## [0.26.0] - 2026-04-16

### Added
- **Source Analysis & Caching**: `analyze-source` CLI command and `wiki_analyze_source` MCP tool:
  - Analyzes raw source files and caches LLM extraction results (entities, suggested pages, relations)
  - Cache embedded as HTML comments in source summary pages, keyed by content hash
  - Supports `--all` (analyze all sources) and `--force` (re-analyze changed sources)
- **Schema-Aware Lint Gap Detection**: `lint()` now reads source analysis cache to detect:
  - Missing custom type pages (e.g., Model, MacroFactor) defined in wiki.md
  - Orphan concepts in relations table without wiki pages
  - Missing cross-references and schema non-compliance
- **Ingest Analysis Integration**: `ingest_source()` now returns `analysis` and `lint_hint` fields:
  - `analysis`: LLM-extracted entities, suggested pages, topics, and relations
  - `lint_hint`: Auto-detected gaps (missing suggested pages) with fix suggestions
- **Relations Deduplication**: `add_relation()` in RelationEngine now deduplicates based on (source, target, relation, source_file)
- **Agent-Aware Init**: `llmwikify init --agent <type>` generates a complete project setup in one command:
  - `--agent opencode` → `opencode.json` + skill files + `wiki.md` + `.gitignore`
  - `--agent claude` → `.mcp.json` + `wiki.md` + `.gitignore`
  - `--agent codex` → `.opencode.json` + skill files + `wiki.md` + `.gitignore`
  - `--agent generic` → `wiki.md` + `.gitignore` only
- **Raw Source Analysis**: Init auto-analyzes `raw/` directory structure and includes stats in generated files
- **Schema Conflict Detection**: Warns when `wiki.md` or `WIKI.md` already exists, with `--force`/`--merge` options
- **`mcp` CLI Subcommand**: Start MCP server for Agent interaction (`llmwikify mcp`), default stdio transport
- **`--merge` MCP Config Regeneration**: `llmwikify init --agent <type> --merge` now regenerates MCP config files in addition to merging wiki.md

### Changed
- **Single Schema Source**: AGENTS.md removed. wiki.md is now the single source of truth for all conventions, page types, and workflows. LLM reads wiki.md directly via `wiki_read_schema`.
- **Complexity Reduced**: Removed 3 agent template files, eliminated info duplication between AGENTS.md and wiki.md
- **MCP Server → FastMCP**: Replaced low-level `mcp.server.Server` with FastMCP (`@mcp.tool` decorators). 377 lines → 180 lines. Cleaner API, automatic schema generation, and industry-standard framework.
- **Dependency**: `mcp>=1.0.0` → `fastmcp>=3.0.0`
- **API**: `MCPServer(wiki)` replaced by `create_mcp_server(wiki)` + `serve_mcp(wiki)`
- **`serve` CLI Subcommand**: Reserved for future self-hosted Agent with LLM API integration (no longer MCP server entry point)

### Planned
- Web UI (optional)
- Self-hosted Agent mode (`serve`) — Direct LLM API integration without external Agent
- Incremental index updates
- Stable API guarantee
- Production hardening

---

## [0.24.0] - 2026-04-13

### Changed
- **CLI Simplified**: Removed 3 redundant commands (22 → 19):
  - Removed `hint` — merged into `lint --format=brief`
  - Removed `recommend` — merged into `lint --format=recommendations`
  - Removed `export-index` — merged into `build-index --export-only`
- **`lint` command** now supports `--format` flag:
  - `--format=full` (default) — Full health check (existing behavior)
  - `--format=brief` — Quick suggestions (replaces old `hint`)
  - `--format=recommendations` — Missing and orphan pages (replaces old `recommend`)
- **`build-index` command** now supports `--export-only` flag to export without rebuilding (replaces old `export-index`)

### Removed (Dead Code Cleanup)
- **`ingest_source.yaml` prompt** — Deprecated single-call LLM path fully removed. LLM ingest now always uses the chained `analyze_source → generate_wiki_ops` pipeline
- **`_llm_process_source_single()` method** — Removed. `_llm_process_source()` now always uses chained mode
- **`prompt_chaining.ingest` config option** — Removed. Chained mode is the only mode
- **`performance.cache_size` config option** — Removed. Was defined but never used in any code
- **`files.*` config options** — `files.index`, `files.log`, `files.config`, `files.config_example` removed. These internal filenames are now hardcoded.
- **`utils/helpers.py`** — `slugify()` and `now()` were duplicated as `_slugify()` and `_now()` on the `Wiki` class and never imported from `utils`.

### Refactored
- **QuerySink Extracted**: ~480 lines of sink-related logic moved from `Wiki` (2,477 lines) to a new dedicated `QuerySink` class (`core/query_sink.py`, 444 lines). Wiki is now ~2,021 lines. Public API unchanged; internal methods moved to `wiki.query_sink`.
- **Sink Location**: Moved `sink/` to `wiki/.sink/` — sink is now a hidden subdirectory of the wiki layer, matching its semantic role as wiki's operation buffer. Obsidian auto-hides it; API paths change from `sink/X.sink.md` to `wiki/.sink/X.sink.md` (old paths still work via backward compat layer).

### MCP Server
- **MCP tools simplified**: Merged 7 graph/relation tools into 2 unified tools (21 → 16):
  - `wiki_graph` — `action: query|path|stats|write` — All graph query operations
  - `wiki_graph_analyze` — `action: export|detect|report` — All graph analysis operations

### Breaking Changes
- `llmwikify hint` → use `llmwikify lint --format=brief`
- `llmwikify recommend` → use `llmwikify lint --format=recommendations`
- `llmwikify export-index` → use `llmwikify build-index --export-only`
- MCP tools renamed: `wiki_relations_neighbors`, `wiki_relations_path`, `wiki_relations_stats`, `wiki_write_relations`, `wiki_export_graph`, `wiki_community_detect`, `wiki_report` → `wiki_graph`, `wiki_graph_analyze`
- Sink path: `sink/X.sink.md` → `wiki/.sink/X.sink.md` (old paths auto-redirect for backward compat)

---

## [0.23.0] - 2026-04-12

### Added
- **Graph Visualization** — Export knowledge graph in multiple formats:
  - Interactive HTML (pyvis) — clickable nodes, community color-coding, zoom/pan
  - SVG (graphviz) — static, publication-ready diagrams
  - GraphML (Gephi, yEd compatible) — for advanced analysis
- **Community Detection** — Automatic topic clustering via Leiden/Louvain algorithms:
  - Resolution parameter controls granularity (default 1.0)
  - JSON output for programmatic consumption
  - Handles edge cases: empty graphs, isolated nodes, single nodes
- **Surprise Score Reports** — Multi-dimensional unexpected connection analysis:
  - 5 scoring dimensions: confidence weight, cross-source-type, cross-knowledge-domain, cross-community, peripheral-to-hub
  - Human-readable explanations for each scored connection
  - `report --top N` for top surprising connections
- **CLI Commands** (3 new): `export-graph`, `community-detect`, `report`
- **Optional `[graph]` dependency**: networkx, pyvis, python-louvain
- **13 new tests** in `test_v023_graph.py`

### Principle Coverage
- **"Obsidian's graph view"** — ✅ NetworkX + pyvis interactive HTML export
- **"Organized by category"** — ✅ Leiden community detection
- **"suggesting new questions"** — ✅ Surprise Score highlights unexpected connections
- **"pick what's useful, ignore what isn't"** — ✅ `[graph]` optional dependency
- **"The LLM writes and maintains all of it"** — ✅ No `graph_index.md` generated; community results go to stdout/JSON

---

## [0.22.0] - 2026-04-12

### Added
- **Knowledge Graph Relations** — LLM auto-extracts concept relationships during ingest:
  - 8 relation types: `is_a`, `uses`, `related_to`, `contradicts`, `supports`, `replaces`, `optimizes`, `extends`
  - 3 confidence levels: `EXTRACTED` (explicit), `INFERRED` (deduced), `AMBIGUOUS` (uncertain)
- **RelationEngine** — SQLite-backed relationship management:
  - `add_relation()` / `add_relations()` — Insert single or batch relations
  - `get_neighbors()` — Bidirectional neighbor queries with confidence filtering
  - `get_path()` — Shortest path between concepts (NetworkX BFS)
  - `get_stats()` — Graph statistics (nodes, edges, degree distribution)
  - `get_context()` — Original source context for a relation
  - `detect_contradictions()` — Find conflicting relations (e.g., `supports` vs `contradicts`)
  - `find_orphan_concepts()` — Concepts mentioned but without wiki pages
- **`relations` SQLite table** — Stores source, target, relation, confidence, source_file, context, wiki_pages
- **`Wiki.write_relations()` / `Wiki.get_relation_engine()`** — Public API for relation management
- **`graph-query` CLI subcommand** — `neighbors`, `path`, `stats`, `context` queries
- **26 new tests** in `test_v022_relations.py`

### Principle Coverage
- **"noting where new data contradicts old claims"** — ✅ Contradiction detection between relations
- **"The cross-references are already there"** — ✅ Relation engine auto-extracts concept relationships

---

## [0.21.0] - 2026-04-12

### Added
- **File Watcher** — Monitor `raw/` directory for new file arrivals (watchdog):
  - Event types: created, modified, deleted, moved
  - Debounce support (configurable seconds, default 2)
  - Thread-safe timer-based debouncing
- **Two operating modes**:
  - **Notify-only** (default) — Prints event details with ingest hint (respects "stay involved" principle)
  - **Auto-ingest** (`--auto-ingest`) — Automatically calls `ingest_source()` on new files
- **Git post-commit hook** — Optional installation/removal:
  - Runs `llmwikify batch raw/ --smart` after each commit
  - Clean uninstall restores original hook
- **`watch` CLI command** — `--auto-ingest`, `--smart`, `--debounce`, `--dry-run`, `--git-hook`
- **Optional `[watch]` dependency**: watchdog>=3.0.0
- **23 new tests** in `test_v021_watch.py`

### Principle Coverage
- **"incrementally builds and maintains a persistent wiki"** — ✅ Watch mode automates ingest
- **"stay involved"** — ✅ Default is notify-only; `--auto-ingest` is explicit opt-in
- **"The wiki is just a git repo"** — ✅ Git post-commit hook integration

---

## [0.20.0] - 2026-04-12

### Added
- **MarkItDown Integration** — Unified file extractor for 20+ formats:
  - Office: Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`)
  - Images: `.jpg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`, `.svg`
  - Audio: `.mp3`, `.wav`, `.m4a` (speech transcription ready)
  - Data: `.csv`, `.json`, `.xml`
  - E-book: `.epub`, Archive: `.zip`, Outlook: `.msg`
- **Graceful fallback strategy**: MarkItdown → legacy extractors → text read → error
- **32 new tests** in `test_v020_markitdown_extractor.py`

### Changed
- `ingest_source()` now uses MarkItDown as primary extractor when available
- `extract()` auto-detection prioritizes MarkItDown for non-text/URL/YouTube sources

---

## [0.19.0] - 2026-04-11

### Added
- **Prompt Harness Engineering** — Systematic prompt quality evaluation:
  - `PromptRegistry` — YAML+Jinja2 template system with provider-specific overrides
  - `PrincipleChecker` — 7 principle compliance checks across all prompts
  - Offline prompt evaluation — 8 automated quality checks
  - Golden Source Framework — 5 test scenarios with mock LLM
  - Prompt regression testing with golden source fixtures
- **Context injection** — Dynamic wiki state injection into prompt templates
- **Post-process validation** — Schema validation with configurable retry attempts
- **Provider overrides** — OpenAI, Ollama, Anthropic-specific prompt variants
- **Chaining mode** — Two-step ingest (`analyze_source` → `generate_wiki_ops`)
- **76 new tests** across 4 test files:
  - `test_v019_principle_checker.py` (34 tests)
  - `test_v019_wiki_synthesize.py` (31 tests)
  - `test_v019_eval_prompts.py` (26 tests)
  - `test_v019_harness_regression.py` (16 tests)

### Principle Coverage
- All 7 LLM Wiki Principles checked programmatically across every prompt template

---

## [0.18.0] - 2026-04-11

### Added
- **Prompt Externalization** — All hardcoded prompts moved to YAML + Jinja2 templates:
  - 8 default templates in `prompts/_defaults/`
  - Custom prompt directory support via config
  - Provider-specific conditional rendering in templates
- **Validation & Retry** — JSON schema validation for LLM responses with configurable retry attempts
- **Chaining Mode** — Two-step ingest pipeline: `analyze_source` (understand content) → `generate_wiki_ops` (plan wiki operations)
- **27 new tests** in `test_v018_integration.py` + `test_v018_prompt_engineering.py`

### Changed
- **BREAKING**: LLM prompts no longer hardcoded in Python; loaded from YAML templates
- `llm_client.py` updated to use `PromptRegistry` for template rendering

---

## [0.17.0] - 2026-04-11

### Added
- **Enhanced CLI** — Additional commands and UX improvements:
  - Improved error messages and progress reporting
  - Batch ingest with `--limit` support
  - Better help text and command grouping
- **Performance tuning** — Database PRAGMA optimizations and batch insert improvements
- **Bug fixes** — Various stability improvements from v0.16.x

---

## [0.16.0] - 2026-04-11

### Added
- **Smart Investigations** — Contradiction detection and data gap analysis for wiki health:
  - `_detect_potential_contradictions()` — Cross-page contradiction scanning:
    - `value_conflict`: Same entity has different values (e.g., revenue: $10M vs $15M)
    - `year_conflict`: Same event has different years (e.g., launched in 2020 vs 2022)
    - `negation_pattern`: One page asserts X, another asserts not X
  - `_detect_data_gaps()` — Data quality gap detection:
    - `unsourced_claims`: Pages with assertions but no `## Sources` section
    - `vague_temporal`: Pages using vague time references (recently, soon, last year)
  - `_llm_generate_investigations()` — LLM-driven investigation suggestions:
    - Generates specific questions to resolve contradictions
    - Recommends source types to fill data gaps
    - Graceful fallback when LLM not available
- **`lint(generate_investigations=True)`** — Optional enhanced analysis:
  - `investigations.contradictions[]` — Observational hints (max 3), no severity classification
  - `investigations.data_gaps[]` — Observational hints (max 3), no severity classification
  - `investigations.suggested_questions[]` — LLM-generated (only when enabled)
  - `investigations.suggested_sources[]` — LLM-generated (only when enabled)
- **18 new tests** in `test_v016_investigations.py` — Comprehensive coverage

### Changed
- `lint()` return structure now includes `investigations` key (independent from `hints`)
- Investigations are **not** classified as critical/informational — pure observations for LLM judgment

### Principle Coverage
- **Lint: "contradictions between pages"** — ✅ New (value_conflict, year_conflict, negation_pattern)
- **Lint: "data gaps that could be filled with a web search"** — ✅ New (unsourced_claims, vague_temporal)
- **Lint: "suggesting new questions to investigate"** — ✅ New (LLM-generated)
- **Lint: "new sources to look for"** — ✅ New (LLM-generated)
- **Zero domain assumption** — ✅ Investigations are observations, not judgments
- **Pure tool design** — ✅ LLM makes final decisions; `generate_investigations=False` skips LLM calls

---

## [0.15.0] - 2026-04-10

### Added
- **Enhanced `ingest_source()` metadata** — returns rich file metadata for LLM context:
  - `file_type` — detected from extension (markdown, pdf, text, html, etc.)
  - `file_size` — byte size of the raw source file
  - `word_count` — word count of extracted text
  - `has_images` / `image_count` — detects markdown image references
  - `text_extracted` — boolean flag
  - `content_preview` — first 200 chars of extracted text
  - **No summary returned** — respects "LLM reads source" principle
- **Clue-based lint detection** — three new observation types, LLM makes final judgment:
  - `dated_claim` (critical, max 3): Pages referencing years ≥3 years older than latest raw source
  - `topic_overlap` (informational, max 2): Query: pages with ≥85% keyword Jaccard overlap
  - `missing_cross_ref` (informational, max 3): Concepts mentioned in 2+ pages without wikilink
- **`hints` structure in `lint()`** — two-tier classification:
  - `hints.critical[]` — demands attention (max 3)
  - `hints.informational[]` — optional context (max 5)
  - Total max 8 hints per lint pass
- **`_detect_file_type()` helper** — static method for file extension detection

### Changed
- `lint()` return structure now includes `hints: {critical: [...], informational: [...]}`
- All lint hints use observational language (non-directive, respects LLM autonomy)

### Principle Coverage
- **Ingest: "LLM reads source, discusses key takeaways"** — ✅ Enhanced (metadata, not summary)
- **Lint: "stale claims superseded by newer sources"** — ✅ New (dated_claim, clue-based)
- **Lint: "missing cross-references"** — ✅ New (missing_cross_ref, clue-based)
- **Zero domain assumption** — ✅ All hints are observations, not judgments

---

## [0.14.0] - 2026-04-10

### Added
- **`merge_or_replace` parameter** in `synthesize_query()` — replaces `update_existing` with three explicit strategies:
  - `"sink"` (default) — append to sink buffer for later review
  - `"merge"` — LLM reads old content, consolidates, replaces formal page
  - `"replace"` — overwrite the formal page entirely
- **Sink suggestion generation** — each sink entry now includes actionable observations:
  - **Content Gap detection**: compares new answer with formal page to find missing topics
  - **Source quality analysis**: checks for missing citations, new sources, completeness
  - **Query pattern analysis**: detects repeated questions, increasing complexity trends
  - **Knowledge growth suggestions**: identifies new concepts, possible contradictions
- **Sink dedup detection**: flags entries with >70% text similarity to existing sink entries
- **Sink urgency tracking** in `sink_status()`: ok / attention (7d+) / aging (14d+) / stale (30d+)
- **`sink_warnings` in `lint()`**: reports stale/aging sinks that need attention
- **Observational hint format** in `synthesize_query()`: non-directive language respects LLM autonomy

### Changed
- **BREAKING**: `update_existing` parameter removed from `synthesize_query()` and MCP tool
- **BREAKING**: `wiki_synthesize` MCP tool now uses `merge_or_replace` (string enum) instead of `update_existing` (boolean)
- `synthesize_query()` returns `status: "merged"` or `"replaced"` instead of `"updated"`
- Hint format changed from `suggestion` (directive) to `observation` + `options` (non-directive)

---

## [0.13.0] - 2026-04-10

### Added
- **Query Sink feature** — Compound answers without creating duplicate pages
  - When a similar query page exists, new answers append to `sink/` instead of creating timestamped copies
  - Sink files: `sink/Query: Topic.sink.md` — one per formal query page
  - Chronological entries with timestamp, query, answer, and sources
  - Bidirectional linking: sink frontmatter → formal page, formal page frontmatter → sink
- **New methods on Wiki class**:
  - `sink_status()` — overview of all sinks with entry counts
  - `read_sink(page_name)` — read pending entries from a sink file
  - `clear_sink(page_name)` — clear processed entries after merge
  - `_append_to_sink()` — internal method to append entries
  - `_get_sink_info_for_page()` — get sink status for a page
  - `_find_or_create_sink_file()` — find or create sink file
  - `_update_page_sink_meta()` — update formal page frontmatter with sink metadata
- **Enhanced `synthesize_query()`**: returns `status: "sunk"` when answer goes to sink
- **Enhanced `read_page()`**: returns `has_sink` and `sink_entries`, supports reading sink files via `sink/` prefix
- **Enhanced `search()`**: attaches `has_sink` and `sink_entries` to each result
- **Enhanced `lint()`**: includes `sink_status` in return value
- **Enhanced `_update_index_file()`**: shows pending sink entry count in index.md
- **New MCP tool**: `wiki_sink_status` — overview of all query sinks
- **Updated wiki.md template**: documents sink workflow and conventions
- **27 new tests** in `test_sink_flow.py` — comprehensive sink feature coverage

---

## [0.12.6] - 2026-04-10

### Added
- **wiki_synthesize MCP tool** — Query knowledge compounding cycle
  - `synthesize_query()` saves query answers as persistent wiki pages
  - Auto-generates page names: `Query: {Topic}` with date suffix for duplicates
  - Smart duplicate detection via keyword overlap (Jaccard similarity ≥ 0.3)
  - `update_existing=True` revises existing page instead of creating new
  - Auto-appends structured Sources section:
    - Wiki pages as `[[wikilinks]]`
    - Raw sources as `[Source: filename](raw/path)` markdown links
  - Auto-logs to `log.md` with parseable format: `## [timestamp] query | ... → [[page]]`
  - New page auto-indexed in FTS5 and `index.md`
- **27 new tests** in `test_query_flow.py` — comprehensive coverage of synthesize scenarios

---

## [0.12.5] - 2026-04-10

### Added
- **Raw source collection**: All ingest sources unified into `raw/` directory
  - URL/YouTube: extracted text saved to `raw/`
  - Local files outside `raw/`: copied in (cross-platform safe via `read_bytes`/`write_bytes`)
  - Local files already in `raw/`: no copy needed
  - Returns `source_raw_path` and `hint` for LLM guidance
- **Source citation conventions** in generated `wiki.md`:
  - Raw sources cited with standard markdown links: `[Source: Title](raw/filename)`
  - Explicitly prohibits `[[raw/filename]]` wikilink syntax
  - Two approaches: page-level `## Sources` section or inline citations
- **MCP config auto-read**: `MCPServer(wiki)` now reads from `wiki.config["mcp"]` when no explicit config passed

### Changed
- `ingest_source()` now returns `source_raw_path` field alongside `source_name`
- `ingest_source()` instructions updated with citation guidance (step 6-7)
- Log entries for ingest now include raw path: `Source (url): Title → raw/slug.md`

### Testing
- 4 new test cases: raw collection, skip, duplicate, instruction validation
- Total: 83 → 87 tests passing

---

## [0.12.4] - 2026-04-10

### Added
- **wiki_read_schema MCP tool** — Read `wiki.md` (schema/conventions file)
  - Returns content, file path, and hint to save copy before changes
- **wiki_update_schema MCP tool** — Update `wiki.md` with new conventions
  - Validates format (warnings only, does not block)
  - Returns suggestions for post-update actions
- **wiki.md reference in ingest** — `ingest_source()` instructions now direct LLM to `wiki.md` for conventions

### Changed
- `ingest_source()` instructions updated: "See wiki.md for wiki conventions and workflows"

---

## [0.12.3] - 2026-04-10

### Changed
- **Pure-data wiki_ingest**: `ingest_source()` returns extracted data for LLM processing, does NOT automatically create wiki pages
- **URL raw persistence**: URL/YouTube extracted text always saved to `raw/` for persistence
- **Optional LLM smart CLI**: `_llm_process_source()` and `execute_operations()` are optional, only used when LLM client configured
- **Unified error handling**: All operations return structured dicts with `error` key on failure

---

## [0.12.2] - 2026-04-10

### Improved
- **ON CONFLICT for pages table**: `created_at` preserved on updates, only mutable fields changed
- **FTS5 snippet highlighting**: Search results include `**highlighted**` snippets via FTS5 snippet function
- **LIKE fallback**: FTS5 syntax errors gracefully fall back to `LIKE` search

---

## [0.12.1] - 2026-04-10

### Changed
- **Optimized wiki_init**:
  - Removed `agent` parameter (zero domain assumption)
  - Added `overwrite` parameter for idempotent re-initialization
  - Always skips `wiki.md` and config example if they exist
  - Structured return with `created_files`, `skipped_files`, `existing_files`

---

## [0.12.0] - 2026-04-10

### Added
- **Phase 1: Complete CLI commands** — 15 commands total
  - `init`, `ingest`, `write_page`, `read_page`, `search`
  - `lint`, `status`, `log`, `references`, `build-index`
  - `export-index`, `batch`, `hint`, `recommend`, `serve`
- **Auto-index**: `write_page()` automatically updates `index.md`
- **wiki.md template**: Generated on `init()` with conventions and workflows
- **hint command**: Smart suggestions for wiki improvement
- **recommend command**: Missing pages and orphan detection

---

## [0.11.1] - 2026-04-10

### Changed
- **Enforced zero domain assumption**: All exclusion patterns empty by default
  - `default_exclude_patterns`: `[]` (was: dates, months, quarters)
  - `exclude_frontmatter`: `[]` (was: `redirect_to`)
  - `archive_directories`: `[]` (was: archive, logs, history)
- Users must explicitly configure exclusions in `.wiki-config.yaml`

---

## [0.11.0] - 2026-04-10

### Changed
- **Modular package structure** — evolved from single-file `llmwikify.py`
  - `core/wiki.py` — Wiki class (business logic)
  - `core/index.py` — WikiIndex class (FTS5 + reference tracking)
  - `extractors/` — Content extractors (text, pdf, web, youtube)
  - `cli/commands.py` — CLI interface
  - `mcp/server.py` — MCP server
  - `utils/helpers.py` — Utility functions
- **Configuration system**: `config.py` with `load_config()`, `get_default_config()`
- **Public API stability maintained** across refactor

### Added
- Optional dependencies for extractors (`pymupdf`, `trafilatura`, `youtube-transcript-api`)

---

## [0.10.0] - 2026-04-10

### Changed
- Renamed core module from `wiki.py` to `llmwikify.py` for consistency
- Updated version numbering scheme from `v10.0.0` to `v0.10.0`

### Fixed
- Module import paths in all test files
- Documentation references to core module

---

## [0.9.0] - 2026-04-09

### Added
- SQLite FTS5 full-text search
- Bidirectional reference tracking
- MCP server support (8 tools)
- CLI with 15 commands
- Smart recommendations engine
- Configuration system (.wiki-config.yaml)
- Comprehensive test suite (48 tests)

### Features
- Zero core dependencies (standard library only)
- Optional dependencies for extended functionality
- Performance optimized (1000x faster than naive implementation)
- Pure tool design (zero domain assumptions)
