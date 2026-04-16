# llmwikify Architecture

> Technical architecture document for developers

**Version**: 0.25.0  
**Last Updated**: 2026-04-13  
**Tests**: 674 passing (706 collected, 32 markitdown skipped)

---

## Overview

**llmwikify** is a modular Python package for building persistent, LLM-maintained knowledge bases. It has evolved from a single-file implementation (v0.10.0, 1,965 lines) into a fully modular architecture with 10+ submodules, 19 CLI commands, 17 MCP tools, and comprehensive test coverage.

### Design Principles

1. **Zero Domain Assumptions** — No hardcoded concepts
2. **Configuration-Driven** — User decides exclusion rules
3. **Performance by Default** — Batch operations, PRAGMA tuning
4. **Pure Tool Design** — Universal patterns only
5. **Modular Architecture** — Clear separation of concerns
6. **Knowledge Compounding** — Query answers saved back to wiki
7. **User Control** — Watch defaults to notify-only, graph analysis is opt-in

---

## Module Structure

```
src/llmwikify/
├── __init__.py              # Package entry point, create_wiki()
├── config.py                # Configuration system (load_config, DEFAULT_CONFIG)
├── llm_client.py            # LLM API client (OpenAI-compatible)
├── py.typed                 # PEP 561 type marker
│
├── core/                    # Core business logic
│   ├── __init__.py
│   ├── wiki.py              # Wiki class (~2,000 lines) — main orchestrator
│   ├── index.py             # WikiIndex class (FTS5 + references)
│   ├── query_sink.py        # QuerySink class — sink buffer management
│   ├── relation_engine.py   # Knowledge graph relations (SQLite)
│   ├── graph_export.py      # Graph visualization + community detection
│   ├── watcher.py           # File system watcher (watchdog)
│   ├── prompt_registry.py   # YAML+Jinja2 prompt template system
│   └── principle_checker.py # Prompt principle compliance checker
│
├── extractors/              # Content extractors
│   ├── __init__.py
│   ├── base.py              # ExtractedContent, detect_source_type(), extract()
│   ├── text.py              # Text/HTML extraction
│   ├── pdf.py               # PDF extraction (pymupdf)
│   ├── web.py               # Web URL extraction (trafilatura)
│   ├── youtube.py           # YouTube transcript extraction
│   └── markitdown_extractor.py  # MarkItDown unified extractor (Office, images, audio)
│
├── cli/                     # Command-line interface
│   ├── __init__.py
│   └── commands.py          # WikiCLI class (20 commands: 19 + mcp + serve)
│
├── mcp/                     # MCP server
│   ├── __init__.py
│   └── server.py            # FastMCP server (17 tools)
│
├── prompts/                 # Prompt templates
│   ├── __init__.py
│   └── _defaults/           # 7 YAML prompt templates
│       ├── analyze_source.yaml
│       ├── generate_wiki_ops.yaml
│       ├── ingest_instructions.yaml
│       ├── investigate_lint.yaml
│       ├── wiki_schema.yaml
│       └── wiki_synthesize.yaml
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │  CLI (20)    │  │  MCP (17)    │  │  Python API     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘  │
└─────────┼─────────────────┼──────────────────┼────────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────────────────────┐  │
│  │   Wiki          │◄─┤  Config (load_config)           │  │
│  │  (wiki.py)      │  └─────────────────────────────────┘  │
│  └────────┬────────┘                                        │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │  WikiIndex      │  │  RelationEngine                  │ │
│  │  (index.py)     │  │  (relation_engine.py)            │ │
│  └────────┬────────┘  └──────────────┬───────────────────┘ │
│           │                          │                     │
│           ▼                          ▼                     │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │  PromptRegistry │  │  GraphExport                     │ │
│  │  (YAML+Jinja2)  │  │  (graph_export.py)               │ │
│  └─────────────────┘  └──────────────────────────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │ PrincipleChecker│  │  FileSystemWatcher               │ │
│  │ (7 principles)  │  │  (watcher.py)                    │ │
│  └─────────────────┘  └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
          ▲
          │
┌─────────┴────────────────────────────────────────────────┐
│                   Extraction Layer                        │
│                                                          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐            │
│  │ text.py   │  │ pdf.py    │  │ web.py    │            │
│  └───────────┘  └───────────┘  └───────────┘            │
│  ┌───────────┐  ┌──────────────────────────────────┐    │
│  │ youtube.py│  │ markitdown_extractor.py          │    │
│  └───────────┘  │ (Office, images, audio, etc.)    │    │
│                  └──────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Wiki Class (`core/wiki.py`)

**Responsibility**: Main business logic orchestrator

**Key Methods** (25 public methods):

| Method | Description |
|--------|-------------|
| `init()` | Initialize wiki directory structure (idempotent) |
| `ingest_source()` | Process sources; all collected into `raw/` |
| `write_page()` | Write/update page (auto-updates index.md) |
| `read_page()` | Read page (supports sink files) |
| `search()` | FTS5 full-text search with sink status |
| `synthesize_query()` | Save query answers as persistent wiki pages |
| `write_relations()` | Write LLM-extracted relations to database |
| `get_relation_engine()` | Get RelationEngine instance |
| `lint()` | Health check (broken links, orphans, contradictions, investigations) |
| `recommend()` | Find missing pages and orphans |
| `hint()` | Smart prioritized suggestions |
| `status()` | Wiki status summary |
| `build_index()` | Rebuild FTS5 index from all wiki files |
| `export_index()` | Export reference index to JSON |
| `get_inbound_links()` | Pages linking to this page |
| `get_outbound_links()` | Pages this page links to |
| `read_schema()` / `update_schema()` | Manage wiki.md |
| `read_sink()` / `clear_sink()` | Delegate to QuerySink |
| `sink_status()` | Delegate to QuerySink |
| `close()` | Close database connections |

**Dependencies**: `WikiIndex`, `extractors.extract`, `RelationEngine`, `QuerySink`

### 1a. QuerySink Class (`core/query_sink.py`)

**Responsibility**: Manage query sink buffers for pending wiki updates. Extracted from Wiki in v0.24.0.

**Operations**:
- `get_info_for_page()` — Check if a page has a pending sink buffer
- `append_to_sink()` — Add a query answer to the sink buffer
- `read()` — Read all pending entries from a sink file
- `clear()` — Clear processed entries after merge
- `status()` — Overview of all sinks with urgency tracking
- `_detect_content_gaps()` / `_suggest_source_improvements()` / `_suggest_knowledge_growth()` — Sink entry quality analysis

### 2. WikiIndex Class (`core/index.py`)

**Responsibility**: SQLite database manager for FTS5 search and reference tracking

**Database Schema**:
```sql
-- FTS5 full-text search
CREATE VIRTUAL TABLE pages_fts USING fts5(
    page_name, content,
    tokenize='porter unicode61'
);

-- Reference links
CREATE TABLE page_links (
    source_page, target_page, section, display_text, file_path
);

-- Page metadata
CREATE TABLE pages (
    page_name, file_path, content_length, word_count, link_count
);

-- Knowledge graph relations (v0.22.0+)
CREATE TABLE relations (
    source, target, relation, confidence, source_file, context
);
```

**Performance**: 0.06s for 157 pages, 2,833 files/sec processing speed

### 3. RelationEngine (`core/relation_engine.py`)

**Responsibility**: Manage knowledge graph relations stored in SQLite

**Operations**:
- `add_relation()` / `add_relations()` — Insert relations
- `get_neighbors()` — Get relations for a concept (in/out/both)
- `get_path()` — Shortest path between concepts (NetworkX)
- `get_stats()` — Graph statistics
- `get_context()` — Original context for a relation
- `detect_contradictions()` — Find conflicting relations
- `find_orphan_concepts()` — Concepts without wiki pages

**Relation Types**: `is_a`, `uses`, `related_to`, `contradicts`, `supports`, `replaces`, `optimizes`, `extends`

**Confidence Levels**: `EXTRACTED` (explicit), `INFERRED` (deduced), `AMBIGUOUS` (uncertain)

### 4. GraphExport (`core/graph_export.py`)

**Responsibility**: Graph visualization, community detection, and surprise analysis

**Features**:
- `build_graph()` — Combined graph from wikilinks + relations
- `export_html()` — Interactive HTML (pyvis) with community colors
- `export_graphml()` — GraphML format (Gephi/yEd)
- `export_svg()` — SVG (graphviz)
- `detect_communities()` — Leiden/Louvain algorithms
- `compute_surprise_score()` — Multi-dimensional unexpected connection scoring
- `generate_report()` — Automated surprising connections report

**Surprise Score Dimensions**:
1. Confidence weight (AMBIGUOUS=3 > INFERRED=2 > EXTRACTED=1)
2. Cross-source-type bonus (+2)
3. Cross-knowledge-domain bonus (+2)
4. Cross-community bonus (+1)
5. Peripheral-to-hub bonus (+1)

### 5. FileSystemWatcher (`core/watcher.py`)

**Responsibility**: Watch directory for file changes

**Features**:
- Event types: created, modified, deleted, moved
- Debounce support (configurable seconds)
- Auto-ingest mode or notify-only mode (default)
- Git post-commit hook installation/removal
- Thread-safe timer-based debouncing

### 6. Extractors (`extractors/`)

**Responsibility**: Content extraction from various sources

| Module | Function | Optional Dependency |
|--------|----------|-------------------|
| `base.py` | `extract()`, `detect_source_type()` | None |
| `text.py` | `extract_text_file()`, `extract_html_file()` | None |
| `pdf.py` | `extract_pdf()` | `pymupdf` |
| `web.py` | `extract_url()` | `trafilatura` |
| `youtube.py` | `extract_youtube()` | `youtube-transcript-api` |
| `markitdown_extractor.py` | `MarkItDownExtractor` | `markitdown[all]` |

**Fallback Strategy**:
```
MarkItDown-enhanced format → Try MarkItDown → Fallback to legacy extractors → Fallback to text read → Return error
```

### 7. PromptRegistry (`core/prompt_registry.py`)

**Responsibility**: YAML+Jinja2 prompt template management

**Features**:
- Provider-specific overrides (OpenAI vs Ollama conditionals)
- Context injection (dynamic wiki state into prompts)
- Post-process validation (schema validation, required keys)
- Retry on failure with configurable attempts
- Custom directory support (user-defined templates)

### 8. PrincipleChecker (`core/principle_checker.py`)

**Responsibility**: Check prompt templates against LLM Wiki Principles

**7 Principles Checked**:
1. Contradiction detection instructions
2. Fabrication warnings
3. Observational language
4. Zero domain assumption
5. Wikilink usage conventions
6. Log operation instructions
7. Data gap detection

### 9. CLI (`cli/commands.py`)

**Responsibility**: Command-line interface

**20 Commands**:
| Category | Commands |
|----------|----------|
| Core | `init`, `ingest`, `analyze-source`, `write_page`, `read_page`, `search` |
| Health | `lint` (with `--format=full/brief/recommendations`), `status` |
| References | `references`, `build-index` (with `--export-only`) |
| Query | `synthesize`, `sink-status` |
| Watch | `watch` |
| Graph | `graph-query`, `export-graph`, `community-detect`, `report` |
| Batch | `batch` |
| Server | `mcp` |
| Log | `log` |

### 10. MCP Server (`mcp/server.py`)

**Framework**: FastMCP (PrefectHQ) — modern, Pythonic MCP server

**17 Tools**: `wiki_init`, `wiki_ingest`, `wiki_write_page`, `wiki_read_page`, `wiki_search`, `wiki_lint`, `wiki_status`, `wiki_log`, `wiki_recommend`, `wiki_build_index`, `wiki_read_schema`, `wiki_update_schema`, `wiki_synthesize`, `wiki_sink_status`, `wiki_references`, `wiki_graph`, `wiki_graph_analyze`, `wiki_analyze_source`

**Unified Graph Tools** (replaces 7 separate tools):
- `wiki_graph` — `action: query|path|stats|write` — All graph query and mutation operations
- `wiki_graph_analyze` — `action: export|detect|report` — All graph analysis operations

**Transports**: STDIO (default), HTTP, SSE

**API**:
- `create_mcp_server(wiki, config)` → returns FastMCP instance
- `serve_mcp(wiki, transport, host, port, config)` → runs the server

---

## Data Flow

### Ingest Flow

```
Source (PDF/URL/YouTube/text file)
  │
  ▼
extractors.extract() — Auto-detect type
  │
  ▼
Specific extractor (e.g., extract_pdf())
  │
  ▼
ExtractedContent (text, title, metadata)
  │
  ▼
Wiki.ingest_source()
  ├── Collects source to raw/ (if not already there)
  ├── Returns extracted data + current index for LLM
  └── Logs to log.md
  │
  ▼ (LLM self-create mode: --self-create)
Wiki._llm_process_source()
  ├── generate_wiki_ops → write_page operations
  ├── Extract relations (if enabled in prompt)
  └── Execute operations
  │
  ▼
Wiki.write_relations()
  └── Stores in SQLite relations table
```

### Query Compounding Flow

```
User Question
  │
  ▼
Wiki.search() — FTS5 search
  │
  ▼
Wiki.read_page() — Read relevant pages
  │
  ▼
LLM synthesizes answer
  │
  ▼
Wiki.synthesize_query()
  ├── Creates "Query: {Topic}" page
  ├── Appends Sources section (wiki + raw links)
  ├── Auto-indexes in FTS5
  └── Logs to log.md
  │
  ▼
Answer persists as wiki page — knowledge compounds
```

### Watch Flow

```
File created in raw/
  │
  ▼
FileSystemWatcher detects event
  │
  ├── (Default) Print notification with ingest hint
  │
  └── (--auto-ingest) Call wiki.ingest_source()
        │
        ├── (--self-create) LLM processes and creates pages
        └── Log to log.md
```

---

## Configuration

### .wiki-config.yaml

```yaml
directories:
  raw: "raw"
  wiki: "wiki"

database:
  name: ".llmwikify.db"

reference_index:
  name: "reference_index.json"
  auto_export: true

orphan_detection:
  default_exclude_patterns: []
  exclude_frontmatter: []
  archive_directories: []

performance:
  batch_size: 100

llm:
  enabled: false
  provider: "openai"
  model: "gpt-4o"
  base_url: "http://localhost:11434"
  api_key: ""
  timeout: 120

mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"

prompts:
  custom_dir: null
```

---

## Performance Optimizations

### Database
```python
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")

# ON CONFLICT preserves created_at
# Batch operations with executemany()
```

### Index Building
Progress reporting with batch size control and speed tracking.

---

## Testing Strategy

### Test Structure (22 files, 522 collected, 490 passing)

| Category | Files | Tests |
|----------|-------|-------|
| Core | `test_wiki_core.py`, `test_index.py`, `test_recommend.py` | 46 |
| Extractors | `test_extractors.py`, `test_v020_markitdown_extractor.py` | 48 |
| LLM/Prompts | `test_llm_client.py`, `test_prompt_registry.py`, `test_v018_*.py`, `test_v019_*.py` | 127 |
| Query/Sink | `test_query_flow.py`, `test_sink_flow.py` | 82 |
| Watch | `test_v021_watch.py` | 23 |
| Relations | `test_v022_relations.py` | 26 |
| Graph | `test_v023_graph.py` | 13 |
| CLI | `test_cli.py` | 9 |
| Fixes/Improvements | `test_p0_p3_fixes.py` | 21 |
| Features | `test_v015_features.py`, `test_v016_investigations.py` | 52 |
| Fixtures | `conftest.py`, `fixtures/` | — |

### Coverage Target: >85%

---

## Version History

### v0.26.0 — Single Schema Source (AGENTS.md Removed)
- **AGENTS.md Removed**: wiki.md is now the single source of truth for all conventions, page types, and workflows
- **Agent-Aware Init**: `llmwikify init --agent <type>` generates MCP config only:
  - `opencode` → `opencode.json` + skill files
  - `claude` → `.mcp.json`
  - `codex` → `.opencode.json`
  - `generic` → wiki structure only
- **Complexity Reduced**: Removed 3 template files, eliminated info duplication between AGENTS.md and wiki.md
- **Raw Source Analysis**: Auto-analyzes `raw/` directory, includes stats in generated files
- **Schema Conflict Detection**: Warns on existing `wiki.md`/`WIKI.md`, supports `--force`/`--merge`

### v0.25.0 — Agent-Aware Init + One-Command Setup
- **Agent-Aware Init**: `llmwikify init --agent <type>` generated complete project setup with AGENTS.md (deprecated in v0.26.0)
- **Raw Source Analysis**: Auto-analyzes `raw/` directory, includes stats in generated files
- **Schema Conflict Detection**: Warns on existing `wiki.md`/`WIKI.md`, supports `--force`/`--merge`
- **492 tests passing** (+18 new for init --agent)

### v0.24.0 — CLI Simplification + Dead Code Removal + QuerySink Extraction
- **CLI Reduced**: 22 → 19 commands (hint, recommend, export-index merged into lint/build-index)
- **MCP Reduced**: 21 → 16 tools (7 graph/relation tools merged into 2 unified tools)
- **Dead Code Removed**: `ingest_source.yaml`, `_llm_process_source_single()`, `prompt_chaining.ingest` config
- **Dead Config Removed**: `performance.cache_size` (never used), `files.*` config options (hardcoded)
- **Dead Files Removed**: `utils/helpers.py` (duplicated in Wiki class)
- **QuerySink Extracted**: ~480 lines of sink logic moved from Wiki to dedicated `QuerySink` class
- **Wiki Reduced**: 2,477 → 2,021 lines
- **Prompt Templates**: 8 → 7 (deprecated `ingest_source.yaml` removed)
- **Sink Location**: `sink/` → `wiki/.sink/` — sink moved to hidden wiki subdirectory, matching its semantic role as wiki's operation buffer
- **490 tests passing** (522 collected, 32 markitdown skipped)

### v0.23.0 — Graph Visualization + Community Detection
- **Graph Export**: Interactive HTML (pyvis), SVG (graphviz), GraphML (Gephi)
- **Community Detection**: Leiden/Louvain algorithms with resolution control
- **Surprise Score**: Multi-dimensional unexpected connection analysis
- **CLI**: `graph-query`, `export-graph`, `community-detect`, `report` commands
- **490 tests passing** (+50 new)

### v0.22.0 — Knowledge Graph Relations
- **Relation Engine**: LLM auto-extracts concept relationships during ingest
- **8 Relation Types**: is_a, uses, related_to, contradicts, supports, replaces, optimizes, extends
- **3 Confidence Levels**: EXTRACTED, INFERRED, AMBIGUOUS
- **Contradiction Detection**: Automatic conflict detection between relations
- **Orphan Concepts**: Identify concepts without corresponding wiki pages

### v0.21.0 — File Watcher
- **FileSystemWatcher**: Watch `raw/` for new file arrivals (watchdog)
- **Git Post-Commit Hook**: Auto-rebuild knowledge graph on every commit
- **Debounce Support**: Configurable, handles rapid file changes
- **Auto-Ingest Mode**: Optional `--auto-ingest` flag (default: notify-only)

### v0.20.0 — MarkItDown Integration
- Unified file extractor for Office, images, audio, EPub, ZIP
- 20+ file types with graceful fallback
- LLM Vision ready configuration

### v0.19.0 — Prompt Harness Engineering
- Principle Compliance Checker (7 principles)
- Offline Prompt Evaluation (8 checks)
- Golden Source Framework (5 test scenarios)
- wiki_synthesize externalized

### v0.18.0 — Prompt Externalization
- YAML + Jinja2 templates
- Provider overrides
- Chaining mode
- Validation & retry

### v0.12.0–v0.17.0 — Foundation
- Complete CLI commands
- Auto-index on page write
- Raw source collection
- Query knowledge compounding
- Query sink with urgency tracking
- Smart investigations

---

*Last updated: 2026-04-13 | Version: 0.24.0*
