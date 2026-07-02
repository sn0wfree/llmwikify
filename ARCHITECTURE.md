# llmwikify Architecture

> Technical architecture for developers.
> **Version:** 0.38.0 | **Last updated:** 2026-07-02 | **Tests:** 6100+ Python collected

---

## Overview

**llmwikify** combines a persistent, LLM-maintained knowledge base with a
quant-research **paper → factor → backtest** pipeline. The codebase is
organised into four cooperating layers plus a standalone `reproduction/`
module:

| Layer | Responsibility |
|-------|----------------|
| **`kernel/`** | Core engines — wiki domain model, multi-wiki, search, knowledge graph, storage |
| **`foundation/`** | LLM client, prompt registry, extractors, configuration, IO |
| **`apps/`** | Application services — wiki, chat (ReAct + Skills), research, agent runtime |
| **`interfaces/`** | CLI, MCP, FastAPI server (REST + MCP + Web UI), Web bundle |
| **`reproduction/`** | Paper → 6-layer Factor → DuckDB → Backtest → L5 reflection |

### Design Principles

1. **Zero domain assumptions** — no hardcoded concepts, user-configurable exclusions
2. **Configuration-driven** — `.wiki-config.yaml` + `~/.llmwikify/llmwikify.json`
3. **Single message source-of-truth** — business data binds to `assistant` messages
4. **Pure tool design** — works for any domain
5. **Knowledge compounding** — query answers are saved back to the wiki
6. **User control** — watch defaults to notify-only, analysis is opt-in
7. **Stay involved** — LLM suggests, human decides (Karpathy principle)
8. **Quant separation** — `quant/` is independent of `wiki/`

---

## Module Structure

```
src/llmwikify/
├── __init__.py
├── __main__.py
│
├── kernel/                       # Core engines
│   ├── wiki/
│   │   ├── wiki.py               # Wiki orchestrator (composes 12 mixins)
│   │   ├── protocols.py          # Typed protocols
│   │   ├── constants.py
│   │   ├── prompt_registry.py
│   │   ├── mixins/
│   │   │   ├── core/             # init.py, schema.py, utility.py
│   │   │   ├── io/               # page_io.py, link.py, ingest.py, source_analysis.py
│   │   │   └── analysis/         # lint.py, llm.py, query.py, relation.py, status.py, synthesis.py
│   │   ├── engines/              # analyzer.py, relation.py, synthesis.py
│   │   └── lint/                 # rule-based lint engine + rules/
│   │
│   ├── multi_wiki/               # Multi-wiki registry
│   │   ├── registry.py
│   │   ├── instance.py
│   │   ├── discovery.py
│   │   └── remote.py             # HTTP client for remote llmwikify
│   │
│   ├── search/                   # QMD hybrid search client
│   │   ├── qmd_client.py
│   │   └── qmd_index.py
│   │
│   ├── graph/                    # Knowledge graph
│   │   ├── analyzer.py           # PageRank, communities, suggestions
│   │   ├── export.py             # HTML / SVG / GraphML
│   │   └── visualizer.py
│   │
│   ├── storage/                  # Persistence
│   │   ├── backend.py
│   │   ├── index.py              # FTS5 + references + relations
│   │   ├── query_sink.py
│   │   └── watcher.py            # Filesystem watcher
│   │
│   └── principle_checker.py      # Prompt principle compliance
│
├── foundation/                   # Cross-cutting primitives
│   ├── config.py
│   ├── io.py
│   ├── llm_client.py             # OpenAI-compatible client + retry/backoff
│   ├── llm/
│   │   ├── spec.py               # LLMSpec (LAL)
│   │   ├── resolver.py           # from_spec / inheritance
│   │   ├── streamable.py         # Streaming + tool-call accumulation
│   │   ├── token_budget.py / token_estimator.py / budget_decorator.py
│   │   ├── context_windows.py / provider_models.py / errors.py
│   ├── prompts/
│   │   ├── prompt_registry.py    # YAML + Jinja2 templates with overrides
│   │   └── _defaults/            # Built-in prompts (incl. repro_*.yaml)
│   ├── extractors/               # text / pdf / web / youtube / markitdown
│   └── templates/
```


```
├── apps/                         # Application services
│   ├── wiki/
│   │   ├── service.py            # Wiki application service
│   │   └── db.py
│   │
│   ├── chat/                     # Chat + ReAct + Skills
│   │   ├── base.py / session.py / state.py
│   │   ├── config.py / config_manager.py
│   │   ├── db.py / db_migrations.py
│   │   ├── prompts.py / engine_helpers.py
│   │   ├── analyzer.py / clarifier.py / gatherer.py
│   │   ├── synthesizer.py / structure_validator.py
│   │   ├── reasoning_checker.py / quality_gate.py
│   │   ├── retry_managers.py / source_filter.py
│   │   ├── eval_harness.py / task_manager.py / research_agent.py
│   │   ├── providers/            # base / minimax / xiaomi / registry
│   │   ├── memory/
│   │   ├── harness/              # service / quality_gate / review / source_*
│   │   ├── agent/                # agent_service / orchestrator
│   │   │                         # react_engine / react_loop / chat_react
│   │   │                         # bridge_backend / research_bridge
│   │   │                         # tool_executor / context_manager / context_store
│   │   │                         # event_log / prompt_builder / text_mode_tool
│   │   └── skills/
│   │       ├── registry.py / runtime.py / service.py / base.py
│   │       ├── plugin_loader.py
│   │       ├── wiki_query_skill.py
│   │       ├── research_skill.py
│   │       ├── autoresearch_compound_skill.py
│   │       ├── actions/          # plan / observe / read / reason / revise /
│   │       │                     # search / score / clarify / extract / filter /
│   │       │                     # analyze / graph / lint / detect/
│   │       ├── pipelines/
│   │       ├── workflows/
│   │       └── crud/
│   │
│   ├── research/
│   │   ├── base.py / web_search.py / db.py
│   │
│   └── agent/                    # Agent runtime
│       ├── dream_editor.py       # Async proposal + human confirmation
│       ├── hooks.py
│       ├── notifications/
│       ├── scheduler/            # croniter-based task scheduler
│       └── tools/
│
├── reproduction/                 # Quant reproduction pipeline (20-phase refactor complete)
│   ├── common/                   # 基础设施 (config, paths, errors, utils, llm_factory, run_id, telemetry)
│   ├── data_source/              # 数据源 (router, universe, quantnodes_adapter, akshare, clickhouse, ifind)
│   ├── codegen/                  # 代码生成 (llm_code, react_engine, compiler, repair, semantic, metadata)
│   │   └── ast/                  # AST 处理 (compiler, nodes, complexity, extractor)
│   ├── prompts/                  # Prompt 系统 (group, registry, loader, renderer, store)
│   │   └── builtin/              # 内置模板 (code_gen, react_feedback, metadata_extract, track_a/b, hypothesis_test, risk_analyze)
│   ├── backtest_pkg/             # 回测 (factor_backtest, run_backtest, metrics, strategies, l5_validation, l5_orchestrator, factor_value_store, quantnodes_repro)
│   ├── persist/                  # 持久化 (factor_library, sessions, run)
│   ├── paper_understanding/      # 论文理解 (extract_paper, extract_factors, extract_strategy, quant_wiki, schemas, contracts)
│   │   └── llm_extraction/       # LLM 提取 (orchestrator, planner, track_a, track_b, validator, ...)
│   └── pipeline/                 # 流水线框架 (config, runner, workspace, react, stages/)
│
└── interfaces/
    ├── cli/
    │   ├── _app.py / _base.py / _config.py / _output.py
    │   └── commands/             # 30 subcommand modules
    ├── mcp/
    │   ├── adapter.py            # MCPAdapter (FastMCP wrapper)
    │   ├── server.py             # Legacy entry (deprecated)
    │   └── tools.py              # 26 wiki tools
    ├── server/                   # Unified FastAPI server
    │   ├── core.py               # WikiServer
    │   ├── constants.py
    │   ├── http/
    │   │   ├── routes.py         # /api/wiki, /api/wikis, /api/search/cross
    │   │   ├── chat_sse.py       # /api/agent/* (chat, sessions, dream, ingest, confirmations)
    │   │   ├── paper.py          # /api/paper/*
    │   │   ├── factor.py         # /api/factor/*
    │   │   ├── strategy.py       # /api/strategy/*
    │   │   ├── reproduction.py   # /api/reproduction/*
    │   │   ├── middleware.py
    │   │   └── _models.py
    │   └── utils/
    │       └── webui.py
    └── web/
        └── server.py             # Web bundle entry
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Frontend (React SPA)                         │
│  Editor │ FileTree │ Graph │ Insights │ Chat │ Quant pages           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────┴───────────────────────────────────────┐
│                           interfaces/                                │
│  CLI (30 commands)  │  MCP (26 tools)  │  FastAPI (REST + MCP + UI)  │
│                                                                      │
│  HTTP routers: /api/wiki  /api/wikis  /api/search/cross              │
│                /api/agent /api/paper  /api/factor                    │
│                /api/strategy /api/reproduction /api/log/error        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────────┐
│                              apps/                                   │
│  wiki.service  │  chat (ChatService → ReActEngine + Skills)          │
│                │  research (web search + structured reasoning)       │
│                │  agent (DreamEditor, Scheduler, Hooks, Notif.)      │
└──────┬─────────────────────────────────────────────────┬─────────────┘
       │                                                 │
┌──────┴─────────────┐                       ┌───────────┴─────────────┐
│      kernel/       │                       │     reproduction/       │
│  wiki + mixins     │                       │  Paper → Factor →       │
│  multi_wiki        │                       │  Backtest → L5          │
│  search (QMD)      │                       │  factor_library         │
│  graph             │                       │  factor_value_store     │
│  storage (FTS5,    │                       │  factor_backtest        │
│   index, watcher)  │                       │  l5_orchestrator        │
└──────┬─────────────┘                       └───────────┬─────────────┘
       │                                                 │
┌──────┴─────────────────────────────────────────────────┴─────────────┐
│                          foundation/                                 │
│  llm_client + LAL (spec / resolver / streamable / token budget)      │
│  prompt_registry + _defaults/ (incl. repro_*.yaml)                   │
│  extractors (text/pdf/web/youtube/markitdown) │ config │ io          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Wiki Engine (`kernel/wiki/`)

The `Wiki` orchestrator composes 12 mixins, grouped by intent:

| Group | Mixin | Responsibility |
|-------|-------|----------------|
| **core** | `WikiInitMixin` | Initialise directories, MCP config |
| | `WikiSchemaMixin` | Read/update `wiki.md`, page types |
| | `WikiUtilityMixin` | Slug, timestamps, templates |
| **io** | `WikiPageIOMixin` | Page CRUD, search, log, index update |
| | `WikiLinkMixin` | Wikilink resolution, fixing, inbound/outbound |
| | `WikiIngestMixin` | Source ingestion, extraction, raw collection |
| | `WikiSourceAnalysisMixin` | Source analysis, caching, summary pages |
| **analysis** | `WikiLLMMixin` | LLM calls with retry, source processing |
| | `WikiQueryMixin` | Query page creation, similarity, sink |
| | `WikiRelationMixin` | Relation engine, graph analysis, operations |
| | `WikiSynthesisMixin` | Cross-source synthesis suggestions |
| | `WikiStatusMixin` | Status reporting, recommendations, hints |
| | `WikiLintMixin` | Health check (delegates to `kernel/wiki/lint/`) |

### Engines (`kernel/wiki/engines/`)
- `analyzer.py` — Read-only lint + recommend engine
- `relation.py` — 8 relation types × 3 confidence levels (SQLite)
- `synthesis.py` — Cross-source synthesis suggestions

### Graph (`kernel/graph/`)
- `analyzer.py` — PageRank, hubs/authorities, community auto-labelling, bridge nodes, suggested pages
- `export.py` — Interactive HTML (pyvis), GraphML (Gephi/yEd), SVG (graphviz), Leiden/Louvain communities, surprise score
- `visualizer.py` — Helper visualisation primitives

### Storage (`kernel/storage/`)
- `index.py` — `WikiIndex` (FTS5 + references + relations)
- `query_sink.py` — Sink buffer (urgency: ok / attention / aging / stale)
- `watcher.py` — Filesystem watcher (watchdog)
- `backend.py` — Storage backend abstraction

### Multi-Wiki (`kernel/multi_wiki/`)
| Component | Role |
|-----------|------|
| `WikiRegistry` | Manages multiple Wiki instances (local + remote), lifecycle |
| `WikiInstance` | Wraps a Wiki + metadata (id, name, type, status) |
| `RemoteWiki` | HTTP client for remote llmwikify servers |
| `WikiDiscovery` | Auto-discover `.wiki-config.yaml` directories |

---

## Chat / ReAct (`apps/chat/`)

`apps/chat/` exposes the user-facing chat experience. The v0.37 default
flow routes every chat request through `ChatReActBridge → ReActEngine`:

| Component | Responsibility |
|-----------|----------------|
| `ChatService` | Public chat entry; orchestrates session, memory, harness, providers |
| `agent/agent_service.py` | Tool-augmented assistant; `use_react_engine` toggles ReAct vs legacy |
| `agent/react_engine.py` | `ReActEngine` — observe / reason / act, up to 4 tool rounds, configurable timeout |
| `agent/react_loop.py` | Lower-level ReAct loop primitives |
| `agent/chat_react.py` / `bridge_backend.py` | ReAct bridge into ChatService streaming |
| `agent/research_bridge.py` | Bridge to `apps/research/` |
| `agent/tool_executor.py` | Skill / tool invocation |
| `agent/context_manager.py` / `context_store.py` | Per-session context |
| `agent/orchestrator.py` | Orchestration glue (legacy + ReAct paths) |
| `agent/event_log.py` / `prompt_builder.py` / `text_mode_tool.py` | Event logging, prompt assembly, plain-text mode |
| `harness/` | Quality gate, review, source filter, structure validator |
| `providers/` | LLM provider adapters (`minimax`, `xiaomi`, registry) |
| `memory/` | Short / long-term memory |

### Streaming events

| Event | Meaning |
|-------|---------|
| `reasoning` | LLM chain-of-thought |
| `phase` | Research engine domain marker |
| `confirmation_required` | Pause for user approval |
| `save_warning` | DB write failed but stream continues (`{type, reason}`) |
| `timeout` | 300 s exceeded |
| Tool round events | Up to 4 tool-call rounds |

### Skills system (`apps/chat/skills/`)

| File / dir | Role |
|------------|------|
| `registry.py` / `runtime.py` / `service.py` / `base.py` | Skill registration & execution |
| `plugin_loader.py` | Discover skills from `~/.llmwikify/skills/` |
| `wiki_query_skill.py` | Wiki-aware Q&A |
| `research_skill.py` | Web research skill |
| `autoresearch_compound_skill.py` | Compound autoresearch flow |
| `actions/` | Atomic actions (plan, observe, read, reason, revise, search, score, clarify, extract, filter, analyze, graph, lint, detect) |
| `pipelines/` | Linear skill pipelines |
| `workflows/` | Dynamic workflow DSL (LAL) — strict validation, alias rejection, subagent inheritance |
| `crud/` | Skill-level CRUD helpers |

`SkillResult.ok` serialises as `{"data": ..., "status": "ok"}`. `RunState` uses
`inputs_data: dict` (not `inputs`) and `float` timestamps.

### Research engine (`apps/research/`)
- `base.py` — Research engine entry
- `web_search.py` — Web search + provider switching
- `db.py` — Research run persistence

### Agent runtime (`apps/agent/`)
- `dream_editor.py` — Async proposal generation, **human-confirm gate** (Karpathy "stay involved")
- `scheduler/` — `croniter`-based periodic tasks
- `hooks.py` — Pre/post operation callbacks
- `notifications/` — User notifications, progress
- `tools/` — Wiki tool bindings shared with the chat agent

---

## Reproduction Pipeline (`reproduction/`)

> **20-phase refactor complete** (2026-06-24): 8 subpackages, 0 top-level files.

The reproduction module is intentionally separate from the wiki engine.
Its canonical storage is the project-level `quant/` directory:

```
quant/
├── factors/{asset_type}/{category}/{slug}.yaml   # 6-layer Factor YAML
├── factors/index.yaml                            # Library index
├── papers/{paper_id}/                            # Paper artefacts
├── factorbacktest/*.md                           # Backtest reports
├── strategies/                                   # Strategy markdown
├── datacache/                                    # Cached input data
└── factor.duckdb                                 # Long-table factor values
```

### 6-Layer Factor Model

| Layer | Name | Question | Output |
|-------|------|----------|--------|
| **L1** | Logic | What is this factor? Formula? | Definition + maths |
| **L2** | Computation | How is it computed in code? | Steps + parameters |
| **L3** | Financial intuition | What does it describe in finance? | Theory + intuition |
| **L4** | Hypotheses | What do we hypothesise? | Hypothesis list + final meaning |
| **L5** | Validation | Backtest + hypothesis testing | IC, RankIC, groups, long-short, stability |
| **L6** | Risk | When does it fail? | Failure conditions + risk exposure |

Reference: [docs/designs/factor_library_framework.md](docs/designs/factor_library_framework.md).

### Pipeline Stages

```
POST /api/paper/start
  → kernel.ingest_source()                    # PDF/DOCX/URL/MD via MarkItDown
  → paper_understanding.extract_paper.extract_paper_structure()    (repro_extract.yaml)
  → paper_understanding.extract_factors.extract_factors()          (repro_factor.yaml)
        OR repro_factor_full.yaml (single-call 6-layer)
  → interfaces.server.http.paper._extract_factor_from_page()
        → 6-layer dict (L5/L6 left empty by default)
  → persist.factor_library.write_factor_yaml()
        → quant/factors/.../*.yaml
        → rebuild quant/factors/index.yaml
  → (optional) backtest_pkg.factor_backtest.run_factor_backtest()
        → quant/factorbacktest/*.md + DuckDB
  → (optional) backtest_pkg.l5_orchestrator (stability + OOS K-fold)
        → fill L5 / suggest L6
```

### Key APIs

| Module | Function | Purpose |
|--------|----------|---------|
| `persist/factor_library.py` | `read_factor_yaml`, `write_factor_yaml`, `list_factors`, `list_factors_by_category`, `update_index` | 6-layer YAML CRUD |
| `backtest_pkg/factor_value_store.py` | `compute_and_store_factor`, `query_factor_values`, `list_stored_factors`, `store_factor_values` | DuckDB long-table |
| `backtest_pkg/factor_backtest.py` | `run_factor_backtest`, `run_factor_backtest_universe`, `_compute_factor_values` | Single-stock + cross-sectional |
| `backtest_pkg/l5_orchestrator.py` / `l5_validation.py` | Reflection + stability + OOS K-fold | Drive L5 |
| `paper_understanding/quant_wiki.py` | Directory layout helpers | `quant/` scaffolding |
| `paper_understanding/extract_paper.py` / `extract_factors.py` | LLM extraction stages | Paper → JSON → factors |
| `paper_understanding/llm_extraction/` | Helpers for 6-layer JSON extraction | Multi-call merge |
| `data_source/ifind.py` / `quantnodes_adapter.py` | External data adapters | iFinD + QuantNodes |

### Supported factor families (`_compute_factor_values`)

`momentum`, `volatility`, `ma_cross`, `rsi`, `value`, `quality`, `size`,
`growth`, `signal_composite`, plus LLM-generated formula code (Parquet
ingestion → factor formula).

### REST surface
- `POST /api/paper/start`, `GET /api/paper/list`, `POST /api/paper/upload`,
  `GET /api/paper/{paper_id}/artifacts`
- `GET /api/factor/list`, `GET/PUT /api/factor/library/{name:path}`,
  `POST /api/factor/{slug}/backtest`, `GET /api/factor/{slug}/backtest`
- `GET /api/strategy/list`, `POST /api/strategy/{slug}/backtest`
- `GET /api/reproduction/list`, `POST /api/reproduction/start`

---

## Foundation Layer (`foundation/`)

### LLM Access Layer (`foundation/llm/`)

| Module | Role |
|--------|------|
| `spec.py` | `LLMSpec` — declarative model config |
| `resolver.py` | `from_spec` + subagent inheritance with strict validation |
| `streamable.py` | Streaming responses + tool-call accumulation |
| `token_budget.py` / `token_estimator.py` / `budget_decorator.py` | Token budgeting |
| `context_windows.py` / `provider_models.py` | Provider capability tables |
| `errors.py` | LAL-specific failure semantics (no legacy fallback) |

`llm_client.py` adds OpenAI-compatible chat with configurable retry,
exponential backoff, `Retry-After` honoring, and streaming reuse for
non-streaming `chat()`. `api.minimaxi.com` is constrained to ≤ 3 concurrent
connections (6 triggers throttle).

### Prompts (`foundation/prompts/`)

`PromptRegistry` loads YAML + Jinja2 templates from `_defaults/` (built-in)
plus optional user dirs. Provider-specific overrides (OpenAI vs Ollama),
context injection from wiki state, and post-process validation with
configurable retry attempts.

Built-in prompts include `repro_extract.yaml`, `repro_factor.yaml`,
`repro_factor_full.yaml`, plus the wiki, lint, synthesis and skill prompts.

### Extractors (`foundation/extractors/`)
- `markitdown_extractor.py` — Unified MarkItDown extractor
- `pdf.py` (pymupdf), `web.py` (trafilatura), `youtube.py` (transcript API), `text.py`

---

## Interfaces (`interfaces/`)

### CLI (`interfaces/cli/`)

`_app.py` builds the top-level parser; each command in
`interfaces/cli/commands/*.py` exposes a `name`, optional aliases, and a
`setup_parser()` method. Currently 30 subcommands (see README §CLI Commands).

### MCP (`interfaces/mcp/`)
- `adapter.py` — `MCPAdapter` wraps FastMCP; preferred entry
- `tools.py` — Registers 26 wiki tools; some (`wiki_search`, `wiki_status`)
  accept an optional `wiki_id` to scope across the multi-wiki registry
- `server.py` — Legacy `create_mcp_server` / `serve_mcp` wrappers
  (`DeprecationWarning`, scheduled for removal in v0.33+)

### Unified FastAPI Server (`interfaces/server/`)

| File | Purpose |
|------|---------|
| `core.py` | `WikiServer` — composes MCP adapter + REST routers + WebUI mount + auth |
| `constants.py` | Default host / port |
| `http/routes.py` | `/api/wiki/*` (single-wiki), `/api/wikis/*` (multi-wiki registry), `/api/search/cross`, `/api/log/error` |
| `http/chat_sse.py` | `/api/agent/*` — chat (SSE), sessions, dream, ingest log, confirmations, config, tools |
| `http/paper.py` | `/api/paper/*` — extraction pipeline (start, status, list, upload, artifacts) |
| `http/factor.py` | `/api/factor/*` — factor library CRUD + backtest |
| `http/strategy.py` | `/api/strategy/*` |
| `http/reproduction.py` | `/api/reproduction/*` — long-running sessions |
| `http/middleware.py` | CORS + API key auth |
| `utils/webui.py` | React SPA static mount |

OpenAPI docs: `/docs` (Swagger UI), `/redoc`.

### Web bundle (`interfaces/web/`)
- `server.py` — Web bundle entry shim

---

## Data Flow

### Wiki ingest

```
Source (PDF/URL/YouTube/MD)
  → foundation.extractors.extract()                # detect type + extract
  → kernel.wiki.mixins.io.ingest.ingest_source()   # collect to raw/, log
  → kernel.wiki.mixins.io.source_analysis ...      # LLM extraction (cached)
  → kernel.wiki.mixins.analysis.synthesis ...      # cross-source compare (optional)
  → kernel.wiki.mixins.io.page_io ...              # write pages, relations
  → kernel.wiki.mixins.analysis.lint               # health check, gaps
```

### Query compounding

```
Question
  → kernel.storage.index (FTS5)
  → kernel.wiki.mixins.io.page_io.read_page()
  → LLM synthesis (foundation.llm_client)
  → kernel.wiki.mixins.analysis.query.synthesize_query()  # save as "Query: ..."
  → Knowledge compounds — answer persists as a wiki page
```

### Chat (v0.37 ReAct)

```
HTTP POST /api/agent/chat (SSE)
  → apps.chat.ChatService.chat()
  → apps.chat.agent.bridge_backend.ChatReActBridge
  → apps.chat.agent.react_engine.ReActEngine.run()
        ├─ reason → emit `reasoning`
        ├─ act → ToolExecutor → Skill / Wiki tool
        ├─ observe → next round (≤ 4)
  → SSE events streamed back (reasoning / phase / confirmation_required /
                              save_warning / timeout / done)
```

### Paper → Factor → Backtest (reproduction)

```
POST /api/paper/start
  → BackgroundTask: extract → build pages → write quant/factors/<...>.yaml
                  → optional auto-backtest → quant/factorbacktest/*.md
                  → optional L5 reflection → fill L5 / suggest L6
```

---

## Performance

| Metric | Value |
|--------|-------|
| FTS5 search | sub-second on hundreds of pages |
| Index building | ~30,000 files/sec |
| Batch operations | 10–20× faster than naive |

```python
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")
# ON CONFLICT preserves created_at
# executemany() for batch inserts
```

LLM throttling: `api.minimaxi.com` ≤ 3 concurrent. Streaming retry
applies to the initial connection only.

---

## Testing

- **6100+ Python tests** collected (`pytest --collect-only -q`)
- Frontend: Vitest + React Testing Library (`src/llmwikify/web/webui`)
- pytest with coverage target ≥ 85%
- Test isolation via temp directories
- Optional dependency tests skipped gracefully (markitdown, graph, agent)
- Quant reproduction lives under `tests/reproduction/`

```bash
pytest                                           # all tests
pytest tests/reproduction/                       # quant pipeline
pytest tests/test_apps_chat_agent_react_engine.py  # ReAct
pytest tests/test_v022_relations.py              # graph relations
```

---

## Project Configuration

- Project root config: `~/.llmwikify/llmwikify.json`
- Per-wiki config: `.wiki-config.yaml`
- Skills: `~/.llmwikify/skills/`
- Subagent definitions: `.claude/agents/<name>.md` (default `isolation: worktree`)
- Server invocation: `llmwikify serve --web --port 8765 --host 0.0.0.0` (no `--reload`)
- Health check: `curl http://localhost:8765/api/health`

---

## Migration & Versioning

| Range | Notes |
|-------|-------|
| v0.30 → v0.31 | Multi-wiki registry under `kernel/multi_wiki/` |
| v0.32 | Skills system restructure (`apps/chat/skills/*`) |
| v0.33 | Service-layer split; `interfaces/mcp/server.py` deprecated |
| v0.36 | Hardening: 32-char message IDs, rate limiting, `confirmation_required` / `save_warning` / `timeout` SSE events |
| v0.37 | ReAct loop unification — `ChatService` defaults to `ChatReActBridge` |
| v0.38 | Nanobot v0.2.1 borrowings — `MessageBus` in-process pub/sub; `WebSocketManager` + `/api/ws/agent`; `AgentRunner[SpecT, ResultT]` ABC; `LLMProvider` ABC + `ProviderConfig` + `RetryMode` + `ThinkingStyle`. Additive — no breaking changes. |

See [docs/MIGRATION_v0.36.md](docs/MIGRATION_v0.36.md),
[docs/MIGRATION_v0.38.md](docs/MIGRATION_v0.38.md), and the top-level
[MIGRATION.md](MIGRATION.md).

---

*Last updated: 2026-06-30 · Version: 0.38.0*
