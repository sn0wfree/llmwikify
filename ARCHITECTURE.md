# llmwikify Architecture

> Technical architecture document for developers
> **Version**: 0.30.0 | **Last Updated**: 2026-04-24 | **Tests**: 879+ Python + 38+ Frontend

---

## Overview

**llmwikify** is a modular Python package for building persistent, LLM-maintained knowledge bases. It evolved from a single-file implementation (v0.10.0, 1,965 lines) into a fully modular architecture with 22 CLI commands, 20 MCP tools, and 879+ tests.

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
├── mcp/                     # MCP server
│   └── server.py            # FastMCP server (20 tools)
│
├── prompts/                 # Prompt templates
│   └── _defaults/           # 7 YAML prompt templates
│
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
    ├── server.py            # Starlette + Uvicorn unified server
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

## Project Status

See [docs/plans/PROJECT_STATUS_0.30.0.md](docs/plans/PROJECT_STATUS_0.30.0.md) for:
- Capability maturity levels by module
- Test coverage analysis
- Outstanding work priorities
- Code quality status

---

*Last updated: 2026-04-24 | Version: 0.30.0*
