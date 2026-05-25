# llmwikify Architecture

> Technical architecture document for developers
> **Version**: 0.30.1 | **Last Updated**: 2026-04-27 | **Tests**: 1008+ Python + 38+ Frontend

---

## Overview

**llmwikify** is a modular Python package for building persistent, LLM-maintained knowledge bases. It evolved from a single-file implementation (v0.10.0, 1,965 lines) into a fully modular architecture with 22 CLI commands, 20 MCP tools, and 1008+ tests.

### Design Principles

1. **Zero Domain Assumptions** — No hardcoded concepts, user-configurable exclusions
2. **Configuration-Driven** — `.wiki-config.yaml` controls behavior
3. **Performance by Default** — Batch operations, PRAGMA tuning
4. **Pure Tool Design** — Universal patterns, works for any domain
5. **Knowledge Compounding** — Query answers saved back to wiki
6. **User Control** — Watch defaults to notify-only, analysis is opt-in
7. **Stay Involved** — LLM suggests, human decides (Karpathy principle)

---

## Module Structure

```
src/llmwikify/
├── __init__.py              # Package entry, __version__
├── config.py                # Configuration system
├── llm_client.py            # LLM API client (OpenAI-compatible)
│
├── core/                    # Core business logic
│   ├── wiki.py              # Wiki Class (~135 lines) — orchestrator, inherits 12 mixins
│   ├── wiki_mixin_utility.py      # Utility methods (slug, timestamps, templates)
│   ├── wiki_mixin_link.py         # Wikilink resolution, fixing, inbound/outbound
│   ├── wiki_mixin_schema.py       # wiki.md schema reading, updating, page types
│   ├── wiki_mixin_init.py         # Initialization, directories, MCP config
│   ├── wiki_mixin_page_io.py      # Page read/write, search, log, index update
│   ├── wiki_mixin_source_analysis.py  # Source analysis, caching, summary pages
│   ├── wiki_mixin_llm.py          # LLM calls with retry, source processing
│   ├── wiki_mixin_relation.py     # Relation engine, graph analysis, operations
│   ├── wiki_mixin_ingest.py       # Source ingestion, extraction, raw collection
│   ├── wiki_mixin_query.py        # Query page creation, similarity, sink
│   ├── wiki_mixin_synthesis.py    # Cross-source synthesis suggestions
│   ├── wiki_mixin_status.py       # Status reporting, recommendations, hints
│   ├── wiki_mixin_lint.py         # Health check (delegates to WikiAnalyzer)
│   ├── wiki_analyzer.py           # WikiAnalyzer — standalone lint/recommend engine
│   ├── index.py             # WikiIndex (FTS5 + references + relations)
│   ├── query_sink.py        # QuerySink — sink buffer management
│   ├── relation_engine.py   # Knowledge graph relations (SQLite)
│   ├── graph_export.py      # Graph visualization + community detection
│   ├── graph_analyzer.py    # GraphAnalyzer — PageRank, communities, suggestions
│   ├── synthesis_engine.py  # SynthesisEngine — cross-source analysis
│   ├── watcher.py           # File system watcher (watchdog)
│   ├── prompt_registry.py   # YAML+Jinja2 prompt template system
│   └── principle_checker.py # Prompt principle compliance checker
│
├── extractors/              # Content extractors
│   ├── base.py              # ExtractedContent, detect_source_type(), extract()
│   ├── text.py              # Text/HTML extraction
│   ├── pdf.py               # PDF extraction (pymupdf)
│   ├── web.py               # Web URL extraction (trafilatura)
│   ├── youtube.py           # YouTube transcript extraction
│   └── markitdown_extractor.py  # MarkItDown unified extractor
│
├── cli/                     # Command-line interface
│   └── commands.py          # WikiCLI class (22 commands)
│
├── mcp/                     # MCP protocol
│   ├── server.py            # Legacy FastMCP server (deprecated)
│   └── adapter.py           # MCPAdapter — MCP protocol wrapper for FastAPI
│
├── server/                  # Unified FastAPI Server (v0.30.1+)
│   ├── core.py              # WikiServer — orchestrates MCP + REST + WebUI
│   ├── constants.py         # Shared configuration constants
│   ├── http/                # HTTP layer
│   │   ├── routes.py        # REST API endpoint registrations (/api/wiki/*)
│   │   └── middleware.py    # CORS + API key authentication
│   └── utils/               # Utilities
│       └── webui.py         # React SPA static file mounting
│
├── prompts/                 # Prompt templates
│   └── _defaults/           # 7 YAML prompt templates
│
├── agent/                   # Agent Layer (v0.30.0+)
│   ├── __init__.py          # Module exports
│   ├── wiki_agent.py        # WikiAgent main class
│   ├── runner.py            # Agent runner
│   ├── scheduler.py         # Task scheduler (croniter)
│   ├── memory.py            # Agent memory management
│   ├── tools.py             # Agent toolset
│   ├── hooks.py             # Hooks system
│   ├── notifications.py     # Notification system
│   └── dream_editor.py      # Dream editor — async proposal + confirmation
│
└── web/                     # Web UI (optional)
    └── webui/               # React + TypeScript SPA (v0.30.0+)
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                  Frontend Layer (Web UI)                     │
│  React + TypeScript SPA │ 18 Components │ D3.js Graph       │
│  Editor │ FileTree │ Insights │ AgentChat │ TaskMonitor     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
┌────────────────────────┴────────────────────────────────────┐
│                  Application Layer                           │
│  CLI (22 commands) │ MCP (20 tools) │ Python API            │
│  Agent Layer (8 subsystems) ─ Dream Editor + Confirmations   │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                      Core Layer                              │
│                                                              │
│  Wiki (12 mixins) ── main orchestrator                      │
│  ├── WikiUtilityMixin    (slug, timestamps, templates)      │
│  ├── WikiLinkMixin       (wikilink resolution, fixing)      │
│  ├── WikiSchemaMixin     (wiki.md read/update)              │
│  ├── WikiInitMixin       (directories, MCP config)          │
│  ├── WikiPageIOMixin     (page CRUD, search, index)         │
│  ├── WikiSourceAnalysisMixin (source analysis, caching)     │
│  ├── WikiLLMMixin        (LLM calls, retry)                 │
│  ├── WikiRelationMixin   (relations, graph analysis)        │
│  ├── WikiIngestMixin     (source ingestion, extraction)     │
│  ├── WikiQueryMixin      (query pages, sink)                │
│  ├── WikiSynthesisMixin  (cross-source synthesis)           │
│  ├── WikiStatusMixin     (status, recommendations, hints)   │
│  └── WikiLintMixin       (health check → WikiAnalyzer)      │
│                                                              │
│  WikiAnalyzer (composition) — read-only lint/recommend      │
│  ├── WikiIndex (FTS5 + references + relations)              │
│  ├── RelationEngine (knowledge graph)                       │
│  ├── GraphAnalyzer (PageRank, communities, suggestions)     │
│  ├── SynthesisEngine (cross-source analysis)                │
│  ├── QuerySink (pending updates buffer)                     │
│  ├── PromptRegistry (YAML+Jinja2 templates)                 │
│  └── GraphExport (visualization + community detection)      │
│                                                              │
│  External: Config │ PrincipleChecker │ FileSystemWatcher    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                   Extraction Layer                          │
│  text │ pdf │ web │ youtube │ markitdown                   │
└─────────────────────────────────────────────────────────────┘
```

### 3. RelationEngine (`core/relation_engine.py`)

Knowledge graph relations stored in SQLite:
- 8 relation types: `is_a`, `uses`, `related_to`, `contradicts`, `supports`, `replaces`, `optimizes`, `extends`
- 3 confidence levels: `EXTRACTED`, `INFERRED`, `AMBIGUOUS`
- Operations: neighbors, shortest path, stats, context, contradiction detection, orphan concepts

### 4. GraphAnalyzer (`core/graph_analyzer.py`) — v0.28.0+

Comprehensive graph analysis (read-only, suggestions only):
- **PageRank centrality** — Identify core concepts
- **Hub/Authority nodes** — High out-degree / in-degree pages
- **Community detection** — Auto-labeled communities via Leiden
- **Bridge nodes** — Nodes connecting multiple communities
- **Suggested pages** — Orphan concepts, under-connected pages

### 5. SynthesisEngine (`core/synthesis_engine.py`) — v0.28.0+

Cross-source analysis (read-only, suggestions only):
- **Reinforced claims** — Claims confirmed by multiple sources
- **New contradictions** — Conflicts between new and existing content
- **Knowledge gaps** — Topics needing more information
- **New entities** — Suggest creating pages for new entities

### 6. GraphExport (`core/graph_export.py`)

- `export_html()` — Interactive HTML (pyvis) with community colors
- `export_graphml()` — GraphML format (Gephi/yEd)
- `export_svg()` — SVG (graphviz)
- `detect_communities()` — Leiden/Louvain algorithms
- `compute_surprise_score()` — Unexpected connection scoring
- `generate_report()` — Surprising connections report

### 7. QuerySink (`core/query_sink.py`)

Manages pending wiki updates:
- Append, read, clear sink entries
- Urgency tracking: ok / attention (7d) / aging (14d) / stale (30d)
- Content gap analysis

### 8. PromptRegistry (`core/prompt_registry.py`)

YAML+Jinja2 prompt template management:
- Provider-specific overrides (OpenAI vs Ollama)
- Context injection from wiki state
- Post-process validation with retry attempts
- Custom directory support

### 9. Agent Layer (`agent/`) — v0.30.0+

Autonomous wiki maintenance system with 8 sub-components:

| Component | Responsibility |
|-----------|----------------|
| `WikiAgent` | Main orchestrator, tool dispatch, decision making |
| `AgentRunner` | Execution loop, state management, error handling |
| `TaskScheduler` | Cron-based scheduled tasks (croniter) |
| `AgentMemory` | Short/long-term memory, context window management |
| `AgentTools` | Wiki tool bindings, MCP integration |
| `HooksSystem` | Event hooks, pre/post operation callbacks |
| `NotificationManager` | User notifications, progress updates |
| `DreamEditor` | Async proposal generation, human confirmation flow |

**Design Principle**: "Stay involved" — Agent proposes, human confirms via Dream system. No auto-execution without explicit approval.

### 10. Web UI (`web/webui/`) — v0.30.0+

React + TypeScript Single Page Application:

| Component Group | Features |
|-----------------|----------|
| **Core UI** | Markdown Editor, FileTree, PageTree with type icons |
| **Knowledge** | D3.js Graph View (PageRank sizing, community coloring), SearchBar |
| **Health** | HealthStatus panel, KnowledgeGrowth metrics |
| **Insights** | Synthesis (cross-source), Knowledge Gaps, Graph Analysis |
| **Agent** | AgentChat interface, TaskMonitor, DreamProposals, Confirmations |
| **History** | IngestLog, EditHistory, DreamLog, Notifications |

**Unified Server**: Starlette + Uvicorn serves both REST API and static frontend.

---

## Data Flow

### Ingest Flow

```
Source (PDF/URL/YouTube)
  → extractors.extract() — Auto-detect type, extract text
  → Wiki.ingest_source() — Collect to raw/, log, return data
  → Wiki.analyze_source() — LLM extracts entities, relations, claims
  → Wiki.suggest_synthesis() — Compare against existing sources (optional)
  → Wiki.execute_operations() — Write pages, relations
  → Wiki.lint() — Health check, detect gaps
```

### Query Compounding Flow

```
User Question
  → Wiki.search() — FTS5 search
  → Wiki.read_page() — Read relevant pages
  → LLM synthesizes answer
  → Wiki.synthesize_query() — Save as "Query: {Topic}" page
  → Knowledge compounds — answer persists as wiki page
```

### Watch Flow

```
File created in raw/
  → FileSystemWatcher detects event
  → (Default) Print notification
  → (--auto-ingest) Wiki.ingest_source() + LLM processing
```

---

## Performance

| Metric | Value |
|--------|-------|
| FTS5 search | 0.06s for 157 pages |
| Index building | ~30,000 files/sec |
| Batch operations | 10-20x faster than naive |

### Optimizations
```python
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")
# ON CONFLICT preserves created_at
# executemany() for batch inserts
```

---

## Testing

- **879 Python tests** across 39+ test files, all passing
- **38 frontend tests** across 8 test files (Vitest + React Testing Library)
- pytest with coverage target >85%
- Test isolation via temp directories
- Optional dependency tests skipped gracefully (markitdown, graph)

---

## Multi-Wiki Management (v0.31.0+)

### Overview

支持在单个服务器实例中管理多个知识库（本地目录 + 远程服务器），提供统一的 Web UI 和 API 进行跨 Wiki 操作。

### Architecture

```
User → WikiServer → WikiRegistry
                    ├── WikiInstance("project-a", Wiki("/path/a"))
                    ├── WikiInstance("project-b", Wiki("/path/b"))
                    └── WikiInstance("remote-x", RemoteWiki("http://..."))
```

**核心组件**:

| 组件 | 职责 |
|------|------|
| `WikiRegistry` | 管理多个 Wiki 实例，提供发现、注册、生命周期管理 |
| `WikiInstance` | 包装 Wiki + 元数据（ID、名称、类型、状态） |
| `RemoteWiki` | HTTP 客户端，连接远程 llmwikify 服务器 |
| `WikiDiscovery` | 目录扫描器，自动发现 `.wiki-config.yaml` |
| `CrossWikiSearch` | 跨 Wiki 搜索，合并和排序结果 |

### Configuration

`.wiki-config.yaml` 扩展：

```yaml
wikis:
  default: "project-a"
  local:
    - id: "project-a"
      name: "Project A"
      path: "."
    - id: "project-b"
      name: "Project B"
      path: "/path/to/project-b"
  remote:
    - id: "remote-docs"
      name: "Remote Docs"
      url: "http://wiki-server:8765"
      api_key: "${WIKI_DOCS_API_KEY}"
  discovery:
    enabled: true
    scan_paths: [".", "../", "~/wikis"]
    scan_depth: 2
```

### API Endpoints

**新增端点**:
```
GET    /api/wikis                    # Wiki 列表
POST   /api/wikis                    # 注册 Wiki
GET    /api/wikis/{wiki_id}          # Wiki 详情
PUT    /api/wikis/{wiki_id}          # 更新配置
DELETE /api/wikis/{wiki_id}          # 删除 Wiki
POST   /api/wikis/{wiki_id}/reload   # 重新索引
GET    /api/search/cross             # 跨 Wiki 搜索
POST   /api/wikis/scan               # 触发目录扫描
```

**现有端点扩展** (添加 `wiki_id` 参数):
```
GET    /api/wiki/{wiki_id}/status
GET    /api/wiki/{wiki_id}/search?q=...
GET    /api/wiki/{wiki_id}/page/{name}
POST   /api/wiki/{wiki_id}/page
```

### Implementation Phases

| 阶段 | 时间 | 范围 |
|------|------|------|
| Phase 1 | Week 1-2 | 核心 Registry (WikiRegistry, 发现, 远程客户端) |
| Phase 2 | Week 2-3 | API 层 (多 Wiki 端点, 向后兼容) |
| Phase 3 | Week 3-4 | 前端 (WikiSelector, 跨 Wiki 搜索, WikiManager) |
| Phase 4 | Week 4-5 | MCP 集成 (工具添加 `wiki_id`) |
| Phase 5 | Week 5-6 | CLI + 文档 + 优化 |

详细设计见: [docs/plans/MULTI_WIKI_PLAN.md](docs/plans/MULTI_WIKI_PLAN.md)

---

## Project Status

See [docs/plans/PROJECT_STATUS_0.30.0.md](docs/plans/PROJECT_STATUS_0.30.0.md) for:
- Capability maturity levels by module
- Test coverage analysis
- Outstanding work priorities
- Code quality status

---

*Last updated: 2026-05-24 | Version: 0.31.0*
