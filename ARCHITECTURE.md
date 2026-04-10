# llmwikify Architecture

> Technical architecture document for developers

**Version**: 0.12.6  
**Last Updated**: 2026-04-10

---

## Overview

**llmwikify** is built as a modular package structure (v0.11.0+), evolved from single-file implementation (v0.10.0). Current version: **v0.12.6** with 13 MCP tools, 15 CLI commands, and 110 passing tests.

### Design Principles

1. **Zero Domain Assumptions** — No hardcoded concepts
2. **Configuration-Driven** — User decides exclusion rules
3. **Performance by Default** — Batch operations, PRAGMA tuning
4. **Pure Tool Design** — Universal patterns only
5. **Modular Architecture** — Clear separation of concerns
6. **Knowledge Compounding** — Query answers saved back to wiki as persistent pages

---

## Module Structure (v0.11.0+)

```
src/llmwikify/
├── __init__.py              # Package entry point, create_wiki()
├── core/                    # Core business logic
│   ├── wiki.py              # Wiki class (~1,260 lines)
│   └── index.py             # WikiIndex class (FTS5 + references)
├── extractors/              # Content extractors
│   ├── base.py              # detect_source_type(), extract()
│   ├── text.py              # Text/HTML extraction
│   ├── pdf.py               # PDF extraction (optional: pymupdf)
│   ├── web.py               # Web URL extraction (optional: trafilatura)
│   └── youtube.py           # YouTube extraction (optional: youtube-transcript-api)
├── cli/                     # Command-line interface
│   └── commands.py          # WikiCLI class (15 commands)
├── mcp/                     # MCP server
│   └── server.py            # MCPServer class (13 tools)
├── config.py                # Configuration system
└── llm_client.py            # LLM API client (optional)
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐     │
│  │  CLI (15)   │  │  MCP (13)   │  │  Python API     │     │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘     │
└─────────┼────────────────┼──────────────────┼──────────────┘
          │                │                  │
          ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
│  ┌─────────────────┐  ┌─────────────────────────────┐      │
│  │   Wiki          │◄─┤  Config (load_config)       │      │
│  │  (wiki.py)      │  └─────────────────────────────┘      │
│  └────────┬────────┘                                        │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │  WikiIndex      │                                        │
│  │  (index.py)     │                                        │
│  └─────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
          ▲
          │
┌─────────┴────────────────────────────────────────────────┐
│                   Extraction Layer                        │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐            │
│  │ text.py   │  │ pdf.py    │  │ web.py    │            │
│  └───────────┘  └───────────┘  └───────────┘            │
│  ┌───────────┐                                          │
│  │ youtube.py│                                          │
│  └───────────┘                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Wiki Class (`core/wiki.py`)

**Responsibility**: Main business logic orchestrator

**Key Methods**:
- `init()` — Initialize wiki directory structure (idempotent, overwrite support)
- `ingest_source()` — Process sources; all collected into `raw/`
- `write_page()` / `read_page()` — Page management (auto-updates index.md)
- `search()` — FTS5 full-text search
- `synthesize_query()` — **Save query answers as persistent wiki pages** (v0.12.6+)
- `lint()` — Health check (broken links, orphan pages)
- `recommend()` — Smart recommendations (missing pages, orphans)
- `hint()` — Smart suggestions for wiki improvement
- `build_index()` — Build reference index
- `read_schema()` / `update_schema()` — Manage wiki.md
- `get_inbound_links()` / `get_outbound_links()` — Reference queries

**Dependencies**:
- `core.index.WikiIndex`
- `extractors.extract`

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
```

**Key Methods**:
- `initialize()` — Create database schema
- `upsert_page()` — Insert/update page with link parsing (ON CONFLICT preserves created_at)
- `search()` — FTS5 full-text search with BM25 ranking and highlighted snippets
- `get_inbound_links()` / `get_outbound_links()` — Reference queries
- `build_index_from_files()` — Batch index building with progress reporting
- `export_json()` — Export for Obsidian compatibility

**Performance**:
- 0.06s for 157 pages
- 2,833 files/sec processing speed
- Batch operations with executemany()

### 3. Extractors (`extractors/`)

**Responsibility**: Content extraction from various sources

| Module | Function | Optional Dependency |
|--------|----------|-------------------|
| `base.py` | `extract()`, `detect_source_type()` | None |
| `text.py` | `extract_text_file()`, `extract_html_file()` | None |
| `pdf.py` | `extract_pdf()` | `pymupdf` |
| `web.py` | `extract_url()` | `trafilatura` |
| `youtube.py` | `extract_youtube()` | `youtube-transcript-api` |

**Lazy Import Pattern**:
```python
def extract_pdf(path):
    try:
        import pymupdf
    except ImportError:
        return ExtractedContent(
            text="",
            metadata={"error": "pymupdf not installed"}
        )
```

### 4. CLI (`cli/commands.py`)

**Responsibility**: Command-line interface

**Commands** (15 total):
- `init` — Initialize wiki
- `ingest` — Ingest sources
- `write_page` / `read_page` — Page operations
- `search` — Full-text search
- `lint` — Health check
- `status` — Status overview
- `log` — Record log entry
- `references` — Show page references
- `build-index` — Build reference index
- `export-index` — Export JSON
- `batch` — Batch ingest
- `hint` — Smart suggestions
- `recommend` — Recommendations
- `serve` — Start MCP server

### 5. MCP Server (`mcp/server.py`)

**Responsibility**: Model Context Protocol server

**Tools** (13 total):
| Tool | Description |
|------|-------------|
| `wiki_init` | Initialize wiki |
| `wiki_ingest` | Ingest source (auto-collects to raw/) |
| `wiki_write_page` / `wiki_read_page` | Page operations |
| `wiki_search` | Full-text search |
| `wiki_lint` | Health check |
| `wiki_status` | Status overview |
| `wiki_log` | Log entry |
| `wiki_recommend` | Missing pages, orphans |
| `wiki_build_index` | Build reference index |
| `wiki_read_schema` | Read wiki.md |
| `wiki_update_schema` | Update wiki.md |
| `wiki_synthesize` | **Save query answer as wiki page** |

**Configuration Priority**:
1. Explicit `config` parameter to `MCPServer()`
2. `wiki.config["mcp"]` (from `.wiki-config.yaml`)
3. `DEFAULT_CONFIG` (stdio, 127.0.0.1:8765)

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
  ▼ (LLM processes via MCP tools)
Wiki.write_page()
  ├── Creates/updates wiki page
  ├── Updates FTS5 index and page_links
  └── Auto-updates index.md
```

### Query Compounding Flow (v0.12.6+)

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

### Search Flow

```
User Query
  │
  ▼
Wiki.search(query, limit, include_content, include_sources, include_links)
  │
  ▼
WikiIndex.search() — FTS5 BM25 query with snippet highlighting
  │
  ▼
Ranked Results (page_name, score, snippet, [content, sources, links])
```

---

## Configuration

### .wiki-config.yaml

```yaml
# Directory structure
directories:
  raw: "raw"
  wiki: "wiki"

# File names
files:
  index: "index.md"
  log: "log.md"

# Database
database:
  name: ".llmwikify.db"

# Orphan detection exclusions
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates
    - '^meeting-.*'          # Meeting notes
  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages
  archive_directories:
    - 'archive'
    - 'logs'

# Performance
performance:
  batch_size: 100

# MCP server
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"
```

### Loading

```python
class Wiki:
    def __init__(self, root: Path, config: dict = None):
        self.config = config or load_config(root)
```

---

## Performance Optimizations

### Database

```python
# PRAGMA tuning
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")

# ON CONFLICT preserves created_at
INSERT INTO pages (...) VALUES (...)
  ON CONFLICT(page_name) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP

# Batch operations
conn.executemany("INSERT ...", data)

# Result: 10-20x faster than naive implementation
```

### Index Building

```python
# Progress reporting
for i, file in enumerate(files):
    if i % batch_size == 0:
        elapsed = time.time() - start
        speed = i / elapsed
        print(f"\r  {i}/{total} - {speed:.1f} files/sec", end='')
```

---

## Testing Strategy

### Test Structure

```
tests/
├── conftest.py              # Fixtures (temp_wiki, wiki_instance, sample_content)
├── test_wiki_core.py        # Wiki class tests (36 tests)
├── test_query_flow.py       # Query synthesis tests (27 tests)
├── test_index.py            # WikiIndex tests (8 tests)
├── test_recommend.py        # Recommendation tests (5 tests)
├── test_cli.py              # CLI tests (8 tests)
├── test_extractors.py       # Extractor tests (12 tests)
└── test_llm_client.py       # LLM client tests (14 tests)
```

### Coverage

- **Total Tests**: 110
- **All Passing**: ✅
- **Target Coverage**: >85%

---

## Version History

### v0.12.6 (Current) — Query Knowledge Compounding
- ✅ wiki_synthesize MCP tool
- ✅ Auto-generated Query pages with Sources sections
- ✅ Smart duplicate detection (Jaccard similarity)
- ✅ Raw source references in synthesized pages
- ✅ 27 new tests in test_query_flow.py

### v0.12.5 — Raw Source Collection
- ✅ All ingest sources unified into raw/
- ✅ Cross-platform safe copy (read_bytes/write_bytes)
- ✅ Source citation conventions in wiki.md
- ✅ MCP config auto-read from wiki.config

### v0.12.4 — Schema Management
- ✅ wiki_read_schema / wiki_update_schema MCP tools
- ✅ wiki.md reference in ingest instructions

### v0.12.3 — Pure-Data Ingest
- ✅ ingest_source returns data without auto-creating pages
- ✅ URL raw persistence
- ✅ Unified error handling

### v0.12.2 — Search Improvements
- ✅ ON CONFLICT for pages table
- ✅ FTS5 snippet highlighting
- ✅ LIKE fallback for syntax errors

### v0.12.1 — Init Optimization
- ✅ Idempotent init with overwrite support
- ✅ Structured return values

### v0.12.0 — Complete CLI
- ✅ 15 CLI commands
- ✅ Auto-index on page write
- ✅ wiki.md template generation

### v0.11.1 — Zero Domain Assumption
- ✅ All exclusion patterns empty by default

### v0.11.0 — Modular Architecture
- ✅ Split into 11+ module files
- ✅ Configuration system
- ✅ Public API stability

### v0.10.0 — Single File
- ✅ 1,965 lines in llmwikify.py
- ✅ All core features
- ✅ 48 passing tests

---

## Future Enhancements

### v0.13.0 (Planned)
- [ ] Enhanced wiki_lint: contradiction detection, stale claims, data gaps
- [ ] Enhanced wiki_search: include_content, include_sources, include_links
- [ ] Expose wiki_hint as MCP tool
- [ ] Incremental index updates

### v1.0.0 (Roadmap)
- [ ] Web UI (optional)
- [ ] Graph visualization
- [ ] MCP server authentication
- [ ] Stable API guarantee
- [ ] Production hardening

---

*Last updated: 2026-04-10 | Version: 0.12.6*
