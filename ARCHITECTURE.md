# llmwikify Architecture

> Technical architecture document for developers

**Version**: 0.11.0  
**Last Updated**: 2026-04-10

---

## Overview

**llmwikify** is built as a modular package structure (v0.11.0+), evolved from single-file implementation (v0.10.0).

### Design Principles

1. **Zero Domain Assumptions** - No hardcoded concepts
2. **Configuration-Driven** - User decides exclusion rules
3. **Performance by Default** - Batch operations, PRAGMA tuning
4. **Pure Tool Design** - Universal patterns only
5. **Modular Architecture** - Clear separation of concerns

---

## Module Structure (v0.11.0+)

```
src/llmwikify/
├── __init__.py              # Package entry point
├── core/                    # Core business logic
│   ├── wiki.py              # Wiki class
│   └── index.py             # WikiIndex class (FTS5 + references)
├── extractors/              # Content extractors
│   ├── base.py              # Base classes and functions
│   ├── text.py              # Text/HTML extraction
│   ├── pdf.py               # PDF extraction (optional: pymupdf)
│   ├── web.py               # Web URL extraction (optional: trafilatura)
│   └── youtube.py           # YouTube extraction (optional: youtube-transcript-api)
├── cli/                     # Command-line interface
│   └── commands.py          # WikiCLI class and main()
├── mcp/                     # MCP server
│   └── server.py            # MCPServer class
└── utils/                   # Utility functions
    └── helpers.py           # slugify, now, etc.
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐     │
│  │  CLI (cli/) │  │  MCP (mcp/) │  │  Python API     │     │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘     │
└─────────┼────────────────┼──────────────────┼──────────────┘
          │                │                  │
          ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
│  ┌─────────────────┐  ┌─────────────────────────────┐      │
│  │   Wiki (wiki)   │◄─┤  Config (embedded)          │      │
│  └────────┬────────┘  └─────────────────────────────┘      │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │  WikiIndex      │                                        │
│  │  (index)        │                                        │
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
          ▲
          │
┌─────────┴────────────────────────────────────────────────┐
│                    Utility Layer                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  helpers.py - slugify, now, etc.                 │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Wiki Class (`core/wiki.py`)

**Responsibility**: Main business logic orchestrator

**Key Methods**:
- `init()` - Initialize wiki directory structure
- `ingest_source()` - Process sources (PDF/URL/YouTube)
- `write_page()` / `read_page()` - Page management
- `search()` - Full-text search
- `lint()` - Health check
- `recommend()` - Smart recommendations
- `build_index()` - Build reference index

**Dependencies**:
- `core.index.WikiIndex`
- `extractors.extract`

---

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
- `initialize()` - Create database schema
- `upsert_page()` - Insert/update page with link parsing
- `search()` - FTS5 full-text search
- `get_inbound_links()` / `get_outbound_links()` - Reference queries
- `build_index_from_files()` - Batch index building
- `export_json()` - Export for Obsidian compatibility

**Performance**:
- 0.06s for 157 pages
- 2,833 files/sec processing speed
- Batch operations with executemany()

---

### 3. Extractors (`extractors/`)

**Responsibility**: Content extraction from various sources

**Modules**:

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
    # ... extraction logic
```

---

### 4. CLI (`cli/commands.py`)

**Responsibility**: Command-line interface

**Commands** (10 total):
- `init` - Initialize wiki
- `ingest` - Ingest sources
- `write_page` / `read_page` - Page operations
- `search` - Full-text search
- `lint` - Health check
- `status` - Status overview
- `log` - Record log entry
- `build-index` - Build reference index
- `recommend` - Smart recommendations

---

### 5. MCP Server (`mcp/server.py`)

**Responsibility**: Model Context Protocol server

**Tools** (8 total):
- `wiki_init` - Initialize wiki
- `wiki_ingest` - Ingest source
- `wiki_write_page` / `wiki_read_page` - Page operations
- `wiki_search` - Search
- `wiki_lint` - Health check
- `wiki_status` - Status
- `wiki_log` - Log entry

---

## Data Flow

### Ingest Flow

```
Source (PDF/URL/YouTube)
  │
  ▼
extractors.extract() - Auto-detect type
  │
  ▼
Specific extractor (e.g., extract_pdf())
  │
  ▼
ExtractedContent (text, title, metadata)
  │
  ▼
Wiki.ingest_source()
  │
  ▼
Wiki.write_page()
  │
  ▼
WikiIndex.upsert_page() - Parse links, update FTS5
```

### Search Flow

```
User Query
  │
  ▼
Wiki.search()
  │
  ▼
WikiIndex.search() - FTS5 query
  │
  ▼
Ranked Results (page_name, score, snippet)
```

---

## Configuration

### .wiki-config.yaml

```yaml
orphan_pages:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates
    - '^meeting-.*'          # Meeting notes
  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages
  archive_directories:
    - 'archive'
    - 'logs'
```

### Loading

```python
class Wiki:
    def __init__(self, root: Path, config: dict = None):
        self.config = config or self._load_config()
```

---

## Performance Optimizations

### Database

```python
# PRAGMA tuning
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")

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
├── conftest.py              # Fixtures
├── test_wiki_core.py        # Wiki class tests
├── test_index.py            # WikiIndex tests
├── test_cli.py              # CLI tests
├── test_extractors.py       # Extractor tests
└── test_recommend.py        # Recommendation tests
```

### Coverage

- **Total Tests**: 48
- **Target Coverage**: >85%
- **Current Status**: 31 passed, 17 in progress (modularization)

---

## Version History

### v0.11.0 (Current) - Modular Architecture

- ✅ Split into 11 module files
- ✅ Clear separation of concerns
- ✅ Public API stability maintained
- ✅ Optional dependencies for extractors

### v0.10.0 - Single File Implementation

- ✅ 1,965 lines in `llmwikify.py`
- ✅ All core features implemented
- ✅ 48 passing tests

---

## Future Enhancements

### v0.12.0 (Planned)

- [ ] Web UI (optional)
- [ ] Graph visualization
- [ ] Incremental index updates
- [ ] More extractors (Word, Excel)

### v1.0.0 (Roadmap)

- [ ] Stable API guarantee
- [ ] Complete documentation
- [ ] Performance benchmarks
- [ ] Production hardening

---

*Last updated: 2026-04-10 | Version: 0.11.0*
