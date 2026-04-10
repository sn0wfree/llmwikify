# llmwikify Architecture

> Technical architecture document for developers

---

## Overview

**llmwikify** is built as a single-file implementation (v9.x) transitioning to a modular package structure (v0.10.x).

### Design Principles

1. **Zero Domain Assumptions** - No hardcoded concepts
2. **Configuration-Driven** - User decides exclusion rules
3. **Performance by Default** - Batch operations, PRAGMA tuning
4. **Pure Tool Design** - Universal patterns only

---

## Module Structure (v0.10.x)

```
src/llmwikify/
├── __init__.py              # Package entry point
├── llmwikify.py                  # Main implementation (1965 lines)
├── py.typed                 # Type stub marker
└── [future modules]
    ├── core/
    ├── extractors/
    ├── cli/
    └── mcp/
```

---

## Core Components

### 1. Data Classes (95 lines)

```python
@dataclass
class ExtractedContent:
    """Content extraction result"""
    text: str
    source_type: str
    title: str = ""
    metadata: dict = field(default_factory=dict)

@dataclass
class Link:
    """Wiki link representation"""
    target: str
    section: str = ""
    display: str = ""
    file: str = ""

@dataclass
class Issue:
    """Health check issue"""
    issue_type: str
    page: str
    message: str
    link: str = ""

@dataclass
class PageMeta:
    """Page metadata"""
    page_name: str
    file_path: str
    content_length: int
    word_count: int = 0
    link_count: int = 0
    updated_at: str = ""
```

### 2. Extractors (296 lines)

**Functions**:
- `detect_source_type()` - Auto-detect (youtube/url/pdf/md/txt/html)
- `extract()` - Main dispatcher
- `_extract_text_file()` - .md/.txt files
- `_extract_html_file()` - .html files
- `_extract_pdf()` - PDF via pymupdf (optional)
- `_extract_url()` - Web via trafilatura (optional)
- `_extract_youtube()` - Transcripts via youtube-transcript-api (optional)

**Dependencies** (all optional):
- `pymupdf>=1.23.0`
- `trafilatura>=1.7.0`
- `youtube-transcript-api>=0.6.0`

### 3. WikiIndex (401 lines)

**Database Schema**:
```sql
-- FTS5 full-text search
CREATE VIRTUAL TABLE pages_fts USING fts5(
    page_name, content,
    tokenize='porter unicode61'
);

-- Bidirectional links
CREATE TABLE page_links (
    id INTEGER PRIMARY KEY,
    source_page TEXT,
    target_page TEXT,
    section TEXT,
    display_text TEXT,
    file_path TEXT,
    created_at TIMESTAMP
);

-- Page metadata
CREATE TABLE pages (
    page_name TEXT PRIMARY KEY,
    file_path TEXT,
    content_length INTEGER,
    word_count INTEGER,
    link_count INTEGER,
    updated_at TIMESTAMP
);
```

**Key Methods**:
- `initialize()` - Create tables
- `upsert_page()` - Insert/update with link parsing
- `search()` - FTS5 with fallback
- `get_inbound_links()` - Pages linking TO
- `get_outbound_links()` - Pages linking FROM
- `build_index_from_files()` - Batch optimized
- `export_json()` - JSON export for compatibility

**Performance Optimizations**:
```python
# Batch inserts
conn.executemany("INSERT ...", data)

# PRAGMA tuning
conn.execute("PRAGMA journal_mode = MEMORY")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA cache_size = -64000")

# Single transaction
conn.execute("BEGIN IMMEDIATE")
# ... all operations ...
conn.commit()
```

### 4. Wiki Core (565 lines)

**Configuration System**:
```python
class Wiki:
    def __init__(self, root: Path, config: dict = None):
        # Load config: file > frontmatter > defaults
        self.config = config or self._load_config()
        
        # Universal patterns (cross-domain)
        self._default_exclude_patterns = [
            r'^\d{4}-\d{2}-\d{2}$',  # Dates
            r'^\d{4}-\d{2}$',        # Months
            r'^\d{4}-Q[1-4]$',       # Quarters
        ]
        
        # User overrides
        self._user_patterns = self.config.get('orphan_exclude_patterns', [])
```

**Key Methods**:
- `init()` - Initialize directory structure
- `ingest_source()` - Process source files
- `write_page()` - Create/update pages
- `read_page()` - Read pages
- `lint()` - Health check
- `recommend()` - Smart recommendations
- `build_index()` - Build with stats

**Orphan Exclusion Logic**:
```python
def _should_exclude_orphan(self, page_name: str, page_path: Path) -> bool:
    # 1. Frontmatter markers (redirect_to)
    # 2. Universal patterns (dates, quarters)
    # 3. User patterns (config)
    # 4. Directory structure (archive/, logs/)
    return True/False
```

### 5. MCP Server (71 lines)

**Tools** (8 total):
- `wiki_init(agent: str)`
- `wiki_ingest(source: str)`
- `wiki_write_page(page_name: str, content: str)`
- `wiki_read_page(page_name: str)`
- `wiki_search(query: str, limit: int)`
- `wiki_lint()`
- `wiki_status()`
- `wiki_log(operation: str, details: str)`

**Dependency**: `mcp>=1.0.0` (optional)

### 6. CLI (376 lines)

**Commands** (15 total):
- `init` - Initialize wiki
- `ingest` - Ingest sources
- `write_page` - Write pages
- `read_page` - Read pages
- `search` - Full-text search
- `lint` - Health check
- `status` - Status overview
- `log` - Record log
- `references` - Show references
- `build-index` - Build index
- `export-index` - Export JSON
- `batch` - Batch ingest
- `hint` - Smart suggestions
- `recommend` - Recommendations
- `serve` - MCP server

---

## Data Flow

### Ingestion Flow
```
Source → detect_source_type() → extract() → ExtractedContent
  → Wiki.ingest_source() → raw/ storage
  → LLM creates pages → Wiki.write_page()
  → WikiIndex.upsert_page() → DB tables
```

### Search Flow
```
Query → WikiCLI.search() → Wiki.search()
  → WikiIndex.search() → FTS5 MATCH
  → Results (page_name, snippet, score)
```

### Reference Tracking Flow
```
Page content → _parse_links() → Link objects
  → upsert_page() → page_links table
  → get_inbound_links() / get_outbound_links()
```

---

## Performance Benchmarks

| Metric | v0.9.0 Optimized | Naive Implementation |
|--------|----------------|---------------------|
| 157 pages | 0.06s | 30-60s |
| Speed | 2833 files/sec | ~5 files/sec |
| Improvement | **500-1000x** | baseline |

**Optimizations Applied**:
1. Batch `executemany()` - 5-10x
2. Single transaction - 10x
3. PRAGMA tuning - 2-3x
4. In-memory operations - 2x

---

## Testing Strategy

**Test Pyramid**:
- Unit tests: 30% (core logic)
- Integration tests: 10% (full flows)
- Functional tests: 60% (CLI commands)

**Coverage Target**: >85%

**Test Files**:
- `tests/test_index.py` - WikiIndex tests (8 cases)
- `tests/test_wiki_core.py` - Wiki core tests (16 cases)
- `tests/test_cli.py` - CLI command tests (8 cases)
- `tests/test_extractors.py` - Extractor tests (12 cases)
- `tests/test_recommend.py` - Recommendation tests (5 cases)

**Total**: 49 test cases

---

## Future Modularization (v0.11.x)

```
src/llmwikify/
├── __init__.py
├── core/
│   ├── llmwikify.py          # Wiki class
│   ├── index.py         # WikiIndex class
│   └── config.py        # Configuration
├── extractors/
│   ├── base.py          # Base extractor
│   ├── pdf.py           # PDF extraction
│   ├── url.py           # URL extraction
│   └── youtube.py       # YouTube extraction
├── cli/
│   └── commands.py      # CLI commands
├── mcp/
│   └── server.py        # MCP server
└── utils/
    └── helpers.py       # Utility functions
```

---

*Last updated: 2026-04-10 | Version: 0.10.0*
