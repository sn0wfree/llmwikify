# llmwikify

> **Build persistent, LLM-maintained knowledge bases** — Based on Karpathy's LLM Wiki Principles

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 490 passing](https://img.shields.io/badge/tests-490%20passing-brightgreen.svg)](https://github.com/sn0wfree/llmwikify)

---

> ⚠️ **Beta Release** — This project is currently in beta testing. You may encounter bugs, incomplete features, or breaking changes. Please report issues on [GitHub](https://github.com/sn0wfree/llmwikify/issues). Feedback and contributions are welcome!

---

## 🎯 What is llmwikify?

**llmwikify** is a general-purpose LLM-Wiki management tool that helps you build and maintain a persistent knowledge base using LLMs. Unlike RAG systems that rediscover knowledge from scratch on every query, llmwikify incrementally builds and maintains a structured, interlinked wiki that compounds over time.

### Core Philosophy

> **The wiki is a persistent, compounding artifact.** The cross-references are already there. The contradictions have already been flagged. The synthesis already reflects everything you've read.

Based on [Karpathy's LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md):
- 📚 **Raw sources** — Your immutable source documents (PDFs, URLs, YouTube videos), all collected into `raw/`
- 📝 **The wiki** — LLM-maintained markdown pages with cross-references
- ⚙️ **The schema** — `wiki.md` that tells the LLM how to maintain the wiki

---

## ✨ Features

### 🔍 Full-Text Search
- SQLite FTS5 with Porter stemmer and BM25 ranking
- Ranked results with highlighted snippets
- LIKE fallback for FTS5 syntax errors
- 0.06 seconds for 157 pages

### 🔗 Bidirectional Reference Tracking
- Automatic `[[wikilink]]` detection and parsing
- Section-level granularity (`[[Page#section|display]]`)
- Inbound/outbound link queries with context
- JSON export for Obsidian compatibility

### 🔀 Query Knowledge Compounding (v0.12.6+)
- **wiki_synthesize** — Save query answers as persistent wiki pages
- Auto-generated `Query: {Topic}` pages with structured Sources sections
- Smart duplicate detection with date suffix for multiple runs
- `merge_or_replace` parameter: sink, merge, or replace strategies
- Auto-links to wiki pages and raw sources
- Auto-logs to `log.md` with parseable format

### 🔄 Query Sink (v0.13.0+)
- Compound answers without creating duplicate pages
- Pending entries saved to `sink/` for later review
- Urgency tracking: ok / attention (7d+) / aging (14d+) / stale (30d+)
- Dedup detection flags entries with >70% text similarity

### 📥 Enhanced Ingest (v0.15.0+)
- Rich metadata: file_type, file_size, word_count, has_images, content_preview
- Auto-collects all sources into `raw/` directory
- LLM self-create mode (`--self-create`) for automatic page creation

### 🧹 Smart Lint with Investigations (v0.15.0+)
- `dated_claim` (critical): Pages referencing years ≥3 years older than latest raw source
- `topic_overlap` (informational): Query pages with ≥85% keyword overlap
- `missing_cross_ref` (informational): Concepts mentioned but not wikilinked
- `contradictions`: Cross-page conflicts (value, year, negation patterns)
- `data_gaps`: Unsourced claims and vague temporal references
- `--generate-investigations`: LLM-suggested questions and sources

### 🕰️ File Watcher (v0.21.0+)
- Watch `raw/` directory for new file arrivals
- Default: notify-only (respects "stay involved" principle)
- Optional: auto-ingest with `--auto-ingest`
- Git post-commit hook integration
- Debounce support for rapid file changes

### 🔗 Knowledge Graph Relations (v0.22.0+)
- LLM auto-extracts concept relationships during ingest
- 8 relation types: `is_a`, `uses`, `related_to`, `contradicts`, `supports`, `replaces`, `optimizes`, `extends`
- 3 confidence levels: `EXTRACTED`, `INFERRED`, `AMBIGUOUS`
- Graph queries: neighbors, shortest path, statistics, context lookup
- Contradiction detection between relations

### 📈 Community Detection (v0.23.0+)
- Leiden/Louvain algorithms for automatic topic clustering
- Resolution control for community granularity
- JSON output for programmatic consumption

### 🎯 Surprise Score Reports (v0.23.0+)
- Multi-dimensional unexpected connection analysis
- Scores based on: confidence, cross-source-type, cross-community, peripheral-to-hub
- Human-readable explanations for each surprise

### 📊 Graph Visualization (v0.23.0+)
- Interactive HTML (pyvis) — click nodes, filter by community
- SVG export (graphviz)
- GraphML export (Gephi, yEd compatible)

### 🚀 Performance Optimized
- Batch inserts with `executemany()`
- PRAGMA optimizations (MEMORY journal, OFF synchronous)
- Progress reporting for large collections
- ON CONFLICT preserves `created_at` on page updates
- 10-20x faster than naive implementation

### 🔧 Pure Tool Design
- **Zero domain assumptions** — No hardcoded concepts
- **Configuration-driven** — You decide what to exclude via `.wiki-config.yaml`
- **Universal patterns** — Date formats, frontmatter markers, directory structures

---

## 📦 Installation

### Basic Installation (Zero Dependencies)
```bash
pip install llmwikify
```

### Full Installation (All Features)
```bash
pip install llmwikify[all]
```

### Development Installation
```bash
git clone https://github.com/sn0wfree/llmwikify.git
cd llmwikify
pip install -e ".[dev]"
```

### Feature-Specific Extras
| Extra | Purpose | Key Packages |
|-------|---------|-------------|
| `extractors` | Enhanced file extraction | markitdown[all], pymupdf, trafilatura |
| `mcp` | MCP server support | mcp>=1.0.0 |
| `watch` | File system watching | watchdog>=3.0.0 |
| `graph` | Graph visualization + community detection | networkx, pyvis, python-louvain |
| `all` | Everything above | All of the above |
| `dev` | Development tools | All + pytest, black, ruff, mypy |

---

## 🔌 Enhanced File Extraction (v0.20.0+)

llmwikify supports a wide range of file formats through **MarkItDown** integration with graceful fallback:

| Format | Extensions | Extractor |
|--------|-----------|-----------|
| PDF | `.pdf` | MarkItDown + pymupdf fallback |
| Word | `.docx`, `.doc` | MarkItDown |
| Excel | `.xlsx`, `.xls` | MarkItDown |
| PowerPoint | `.pptx`, `.ppt` | MarkItDown |
| Images | `.jpg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`, `.svg` | MarkItDown (LLM vision ready) |
| Audio | `.mp3`, `.wav`, `.m4a` | MarkItDown (speech transcription) |
| Data | `.csv`, `.json`, `.xml` | MarkItDown |
| E-book | `.epub` | MarkItDown |
| Archive | `.zip` | MarkItDown |
| Outlook | `.msg` | MarkItDown |
| HTML | `.html`, `.htm` | MarkItDown + regex fallback |
| Web | URL | trafilatura |
| YouTube | youtube.com, youtu.be | youtube-transcript-api |
| Text | `.md`, `.txt` | Built-in (no dependency) |

```bash
pip install llmwikify[extractors]
```

---

## 🚀 Quick Start

### 1. Initialize a Wiki
```bash
llmwikify init
```

Output:
```
Wiki initialized at /path/to/wiki
  raw/     → drop source files here (all sources collected here)
  wiki/    → LLM-maintained wiki pages
  .llmwikify.db → SQLite index
  wiki.md  → conventions and workflows for the LLM
  .wiki-config.yaml.example → configuration template
```

### 2. Ingest Sources
```bash
# Ingest a PDF (copied to raw/)
llmwikify ingest document.pdf

# LLM smart mode: auto-create wiki pages
llmwikify ingest document.pdf --self-create

# Ingest a URL
llmwikify ingest https://example.com/article

# Ingest a YouTube video
llmwikify ingest https://youtube.com/watch?v=abc123
```

### 3. Watch for New Files (v0.21.0+)
```bash
# Watch raw/ directory, notify only (default)
llmwikify watch

# Auto-ingest new files
llmwikify watch --auto-ingest --self-create

# Install git post-commit hook
llmwikify watch --git-hook
```

### 4. Build Index
```bash
llmwikify build-index
```

Output:
```
  Processing: 100/157 (63.7%) - 29591.5 files/sec

Total pages: 157
Total links: 636
Elapsed: 0.06s
```

### 5. Search and Query
```bash
# Full-text search
llmwikify search "gold mining" -l 10

# Query page references
llmwikify references "Company Name"

# Get lint recommendations
llmwikify lint --format=recommendations

# Get quick health suggestions
llmwikify lint --format=brief
```

### 6. Knowledge Graph (v0.22.0+)
```bash
# View concept relationships
llmwikify graph-query neighbors "Attention"

# Find shortest path between concepts
llmwikify graph-query path "FlashAttention" "PageAttention"

# View graph statistics
llmwikify graph-query stats

# View relation context
llmwikify graph-query context 1
```

### 7. Community Detection (v0.23.0+)
```bash
# Detect knowledge communities
llmwikify community-detect

# Output as JSON
llmwikify community-detect --json

# Adjust resolution (higher = more granular)
llmwikify community-detect --resolution 1.5
```

### 8. Graph Visualization (v0.23.0+)
```bash
# Export interactive HTML
llmwikify export-graph --format html --output graph.html

# Export for Gephi/yEd
llmwikify export-graph --format graphml

# Generate surprise report
llmwikify report --top 10
```

---

## 💻 Python API

```python
from llmwikify import Wiki, create_wiki
from pathlib import Path

# Create/open a wiki
wiki = create_wiki("/path/to/wiki")

# Initialize
wiki.init()

# Ingest source (returns data for LLM processing)
result = wiki.ingest_source("document.pdf")
print(f"Source: {result['title']}, saved to: {result['source_raw_path']}")

# LLM smart processing
wiki.write_page("Test Page", "# Test\n\nContent with [[Link]]")

# Search
results = wiki.search("gold mining", limit=10)
for r in results:
    print(f"{r['page_name']}: {r['snippet']}")

# Synthesize query answer (compounds knowledge)
wiki.synthesize_query(
    query="Compare gold and copper mining",
    answer="# Mining Comparison\n\n...",
    source_pages=["Gold Mining", "Copper Mining"],
    raw_sources=["raw/report.pdf"],
)

# Write relations (v0.22.0+)
relations = [
    {"source": "Attention", "target": "Softmax", "relation": "uses", "confidence": "EXTRACTED"},
    {"source": "FlashAttention", "target": "KV Cache", "relation": "optimizes", "confidence": "INFERRED"},
]
wiki.write_relations(relations, source_file="transformer_paper.pdf")

# Query relations (v0.22.0+)
engine = wiki.get_relation_engine()
neighbors = engine.get_neighbors("Attention")
path = engine.get_path("FlashAttention", "PageAttention")
stats = engine.get_stats()

# Get recommendations
recs = wiki.recommend()

# Sink management
status = wiki.sink_status()
entries = wiki.read_sink("topic")
wiki.clear_sink("topic")

# Get smart hints
hints = wiki.hint()
```

---

## 🗄️ MCP Server (17 Tools)

The MCP server exposes wiki operations as tools for LLMs.

| Tool | Description |
|------|-------------|
| `wiki_init` | Initialize wiki directory structure |
| `wiki_ingest` | Ingest a source file (auto-collects to raw/) |
| `wiki_write_page` | Write/update a wiki page |
| `wiki_read_page` | Read a wiki page |
| `wiki_search` | Full-text search with snippets |
| `wiki_lint` | Health check (broken links, orphan pages) |
| `wiki_status` | Get wiki status overview |
| `wiki_log` | Append entry to wiki log |
| `wiki_recommend` | Get recommendations (missing pages, orphans) |
| `wiki_build_index` | Build reference index from all pages |
| `wiki_read_schema` | Read wiki.md (schema/conventions) |
| `wiki_update_schema` | Update wiki.md with new conventions |
| `wiki_synthesize` | **Save query answer as wiki page** (knowledge compounding) |
| `wiki_sink_status` | Overview of query sinks with entry counts |
| `wiki_references` | Show page references (inbound/outbound wikilinks) |
| `wiki_graph` | Query/modify knowledge graph (neighbors, path, stats, write relations) |
| `wiki_graph_analyze` | Analyze graph (export visualization, detect communities, surprise report) |

### Quick Start
```python
from llmwikify import Wiki, serve_mcp

wiki = Wiki("/path/to/wiki")
serve_mcp(wiki)  # STDIO transport (default), reads config from wiki.config["mcp"]
```

See [MCP Setup Guide](docs/MCP_SETUP.md) for transport options and configuration.

---

## ⚙️ Configuration

### .wiki-config.yaml

```yaml
# Orphan detection exclusions
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Date format (2025-07-31)
    - '^meeting-.*'          # Meeting notes

  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages

  archive_directories:
    - 'archive'
    - 'logs'

# LLM configuration
llm:
  enabled: false
  provider: "openai"  # openai, ollama, lmstudio
  model: "gpt-4o"
  api_key: "env:OPENAI_API_KEY"

# MCP server settings
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"  # stdio, http, sse

# Custom prompt templates
prompts:
  custom_dir: null  # Path to custom prompt directory
```

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `WIKI_ROOT` | Override default wiki root directory |
| `LLM_API_KEY` | LLM API key (supports `env:VAR_NAME` syntax in config) |
| `LLM_BASE_URL` | LLM API base URL |
| `LLM_MODEL` | LLM model name |
| `LLM_PROVIDER` | LLM provider (openai, ollama, lmstudio) |

### Design Principle: Zero Domain Assumptions

llmwikify does **NOT** assume:
- ❌ "Daily summary" concept
- ❌ "Company page" concept
- ❌ Any domain-specific page types

This makes llmwikify truly general-purpose:
- **Mining News Wiki**: Dates = daily summaries
- **Personal KB**: Dates = journal entries
- **Project Docs**: Dates = release notes
- **Research Wiki**: Dates = experiment logs

---

## 📊 CLI Commands (19 Total)

| Command | Description | Example |
|---------|-------------|---------|
| `init` | Initialize wiki | `llmwikify init` |
| `ingest` | Ingest PDF/URL/YouTube | `llmwikify ingest doc.pdf --self-create` |
| `write_page` | Create/update page | `llmwikify write_page Test -c "..."` |
| `read_page` | Read page | `llmwikify read_page Test` |
| `search` | Full-text search | `llmwikify search "gold" -l 10` |
| `lint` | Health check | `llmwikify lint --format=brief` |
| `status` | Status overview | `llmwikify status` |
| `log` | Record log entry | `llmwikify log ingest doc.pdf` |
| `references` | Show references | `llmwikify references "Agnico" --detail` |
| `build-index` | Build/export reference index | `llmwikify build-index --export-only` |
| `batch` | Batch ingest | `llmwikify batch raw/pdfs/ --self-create` |
| `sink-status` | Sink buffer overview | `llmwikify sink-status` |
| `synthesize` | Save query as page | `llmwikify synthesize "Q?" -a "A..."` |
| `watch` | Watch for new files | `llmwikify watch --auto-ingest` |
| `graph-query` | Query knowledge graph | `llmwikify graph-query neighbors "A"` |
| `export-graph` | Export graph visualization | `llmwikify export-graph --format html` |
| `community-detect` | Detect communities | `llmwikify community-detect --json` |
| `report` | Surprise connections report | `llmwikify report --top 10` |
| `mcp` | Start MCP server for Agent interaction | `llmwikify mcp` |
| `serve` | Start self-hosted Agent (reserved) | `llmwikify serve` |

---

## 🗄️ Database Schema

```sql
-- FTS5 full-text search
CREATE VIRTUAL TABLE pages_fts USING fts5(
    page_name, content,
    tokenize='porter unicode61'
);

-- Bidirectional wikilink tracking
CREATE TABLE page_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_page TEXT NOT NULL,
    target_page TEXT NOT NULL,
    section TEXT,
    display_text TEXT,
    file_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Page metadata
CREATE TABLE pages (
    page_name TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    content_length INTEGER,
    word_count INTEGER,
    link_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge graph relations (v0.22.0+)
CREATE TABLE relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    confidence TEXT NOT NULL,
    source_file TEXT,
    context TEXT,
    wiki_pages TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Relation Types

| Type | Semantic | Example |
|------|----------|---------|
| `is_a` | Classification | FlashAttention **is_a** Attention optimization |
| `uses` | Dependency | Attention **uses** Softmax |
| `related_to` | Loose association | Transformer **related_to** NLP |
| `contradicts` | Conflict | Paper A **contradicts** Paper B |
| `supports` | Evidence | Experiment **supports** hypothesis |
| `replaces` | Replacement | FlashAttention **replaces** Standard Attention |
| `optimizes` | Optimization | KV Cache **optimizes** inference |
| `extends` | Extension | LoRA **extends** fine-tuning methods |

### Confidence Levels

| Level | Meaning |
|-------|---------|
| `EXTRACTED` | Relationship explicitly stated in source |
| `INFERRED` | Relationship deduced from context |
| `AMBIGUOUS` | Relationship uncertain, flagged for review |

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/llmwikify

# Run specific module
pytest tests/test_v023_graph.py -v

# Run and generate HTML report
pytest --cov=src/llmwikify --cov-report=html
```

**Test Coverage**: 490 tests, all passing (32 markitdown tests skipped due to heavy deps)

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_wiki_core.py` | 33 | Wiki class (init, ingest, pages, schema, lint) |
| `test_query_flow.py` | 27 | Query synthesis (basic, sources, logging, duplicates) |
| `test_sink_flow.py` | 55 | Query sink buffer (append, read, clear, urgency) |
| `test_prompt_registry.py` | 34 | Prompt template loading and rendering |
| `test_v019_principle_checker.py` | 33 | Principle compliance checker |
| `test_v015_features.py` | 34 | Enhanced ingest + lint features |
| `test_v019_wiki_synthesize.py` | 31 | wiki_synthesize prompt externalization |
| `test_v020_markitdown_extractor.py` | 32 | MarkItDown extractor integration |
| `test_v018_integration.py` | 23 | Phase 3 integration tests |
| `test_v018_prompt_engineering.py` | 25 | Phase 3 prompt engineering |
| `test_v019_eval_prompts.py` | 26 | Offline prompt evaluation |
| `test_v022_relations.py` | 26 | Knowledge graph relations engine |
| `test_v021_watch.py` | 23 | File system watcher |
| `test_v016_investigations.py` | 18 | Smart investigations |
| `test_v019_harness_regression.py` | 15 | Prompt regression tests + golden sources |
| `test_extractors.py` | 16 | Content extractors |
| `test_p0_p3_fixes.py` | 21 | Bug fixes and improvements |
| `test_llm_client.py` | 13 | LLM client config and JSON parsing |
| `test_index.py` | 8 | WikiIndex (FTS5, links, export) |
| `test_cli.py` | 9 | CLI commands |
| `test_recommend.py` | 5 | Recommendation engine |
| `test_v023_graph.py` | 13 | Graph export and community detection |

---

## 📚 Use Cases

### 1. Mining News Wiki
```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Daily summaries
    - '^weekly-.*'           # Weekly insights
  archive_directories:
    - 'daily'
    - 'analysis'
```

**Results**: 89 → 2 orphan pages (97.8% false positive elimination)

### 2. Personal Knowledge Base
```yaml
orphan_detection:
  exclude_patterns:
    - '^book-note-.*'
    - '^course-.*'
  archive_directories:
    - 'journal'
    - 'notes'
```

### 3. Project Documentation
```yaml
orphan_detection:
  exclude_patterns:
    - '^release-.*'
    - '^meeting-.*'
    - '^rfc-.*'
  archive_directories:
    - 'releases'
    - 'meetings'
```

### 4. Research Wiki
```yaml
orphan_detection:
  exclude_patterns:
    - '^experiment-.*'
    - '^paper-note-.*'
  archive_directories:
    - 'experiments'
    - 'papers'
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     llmwikify Architecture                  │
└─────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Core Layer                                                 │
│  Wiki (wiki.py)             — Business logic orchestrator   │
│  WikiIndex (index.py)       — FTS5 + Reference Tracking     │
│  RelationEngine             — Knowledge graph relations     │
│  GraphExport                — Visualization + communities   │
│  FileSystemWatcher          — File change detection         │
│  PromptRegistry             — YAML+Jinja2 prompt management │
│  PrincipleChecker           — Prompt compliance checking    │
└─────────────────────────────────────────────────────────────┘
                                 ▲
                                 │
┌─────────────────────────────────────────────────────────────┐
│                   Extraction Layer                          │
│  text.py │ pdf.py │ web.py │ youtube.py │                  │
│  markitdown_extractor.py (Office, images, audio, etc.)     │
└─────────────────────────────────────────────────────────────┘
                                 ▲
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
┌────────────────────────┐        ┌────────────────────────┐
│  CLI (19 commands)     │        │  MCP Server (17 tools) │
└────────────────────────┘        └────────────────────────┘
```

### Data Flow

**Ingest Flow:**
```
Source (PDF/URL/YouTube/text file)
  → extractors.extract() — Auto-detect type
  → ExtractedContent (text, title, metadata)
  → Wiki.ingest_source() — Collects to raw/, logs
  → (LLM --self-create) — Creates wiki pages + extracts relations
  → Wiki.write_relations() — Stores in SQLite relations table
```

**Query Compounding Flow:**
```
User Question → Wiki.search() → LLM synthesizes answer
  → Wiki.synthesize_query() → Creates "Query: {Topic}" page
  → Answer persists as wiki page — knowledge compounds
```

---

## 📖 Documentation

- **[Configuration Guide](docs/CONFIGURATION_GUIDE.md)** — Detailed configuration options
- **[Chinese Config Guide](docs/CONFIG_GUIDE.md)** — 中文配置指南
- **[LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)** — Karpathy's original vision
- **[Reference Tracking Guide](docs/REFERENCE_TRACKING_GUIDE.md)** — How references work
- **[MCP Setup Guide](docs/MCP_SETUP.md)** — MCP server configuration
- **[Migration Guide](MIGRATION.md)** — Version migration notes
- **[Architecture](ARCHITECTURE.md)** — Technical architecture
- **[Roadmap Plan](docs/plans/v021-v023-roadmap.md)** — v0.21.0–v0.23.0 implementation plan

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Report bugs** — [GitHub Issues](https://github.com/sn0wfree/llmwikify/issues)
2. **Fix bugs** — Submit a PR
3. **Add features** — Open an issue first to discuss
4. **Improve docs** — PRs welcome
5. **Share use cases** — Add your `.wiki-config.yaml` to examples/

### Development Setup
```bash
git clone https://github.com/sn0wfree/llmwikify.git
cd llmwikify
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/llmwikify
ruff check src/llmwikify

# Type check
mypy src/llmwikify
```

---

## 📈 Roadmap

### ✅ v0.23.0 (Released)
- **Graph Visualization**: Interactive HTML (pyvis), SVG (graphviz), GraphML (Gephi)
- **Community Detection**: Leiden/Louvain algorithms for automatic topic clustering
- **Surprise Score Reports**: Multi-dimensional unexpected connection analysis
- **Graph Query CLI**: `graph-query` subcommand (neighbors/path/stats/context)

### ✅ v0.24.0 (Released)
- **CLI Simplified**: 22 → 19 commands (hint, recommend, export-index merged)
- **MCP Simplified**: 21 → 16 tools (7 graph/relation tools merged into 2)
- **Dead Code Removed**: `ingest_source.yaml`, single-call LLM path, `prompt_chaining.ingest` config
- **Dead Config Removed**: `performance.cache_size` (never used)
- **490 tests passing** (522 collected, 32 markitdown skipped)

### v0.25.0 (Planned)
- **Semantic Cache** — Cache LLM responses by semantic similarity, reduce redundant API calls
- **Incremental Index Updates** — Update FTS5 index per-page instead of full rebuild
- **MCP Authentication** — Secure MCP server with API key authentication
- **Web UI** (optional) — Lightweight Flask/FastAPI interface for browsing wiki

### v1.0.0 (Future)
- Stable API guarantee
- Production hardening
- Comprehensive error handling and recovery

### ✅ v0.22.0 (Released)
- **Knowledge Graph Relations**: LLM auto-extracts concept relationships during ingest
- **Relation Engine**: 8 relation types, 3 confidence levels, SQLite storage
- **Contradiction Detection**: Automatic conflict detection between relations
- **Orphan Concept Detection**: Identify concepts without wiki pages
- **+26 new tests**

### ✅ v0.21.0 (Released)
- **File Watcher**: Watch `raw/` for new file arrivals (watchdog)
- **Git Post-Commit Hook**: Auto-rebuild knowledge graph on every commit
- **Debounce Support**: Configurable, handles rapid file changes
- **Auto-Ingest Mode**: Optional `--auto-ingest` flag (default: notify-only)
- **+23 new tests**

### ✅ v0.20.0 (Released)
- **MarkItDown Integration**: Unified file extractor for Word, Excel, PowerPoint, images, audio, EPub, ZIP
- **Enhanced Format Support**: 20+ file types with graceful fallback
- **+32 new tests**

### ✅ v0.19.0 (Released)
- **Prompt Harness Engineering**: Systematic prompt quality evaluation
- **Principle Compliance Checker**: 7 principles checked across all prompts
- **Offline Prompt Evaluation**: 8 automated checks
- **Golden Source Framework**: 5 test scenarios with mock LLM
- **+76 new tests**

### ✅ v0.18.0 (Released)
- **Prompt Externalization**: All hardcoded prompts → YAML + Jinja2 templates
- **Provider Overrides**: OpenAI, Ollama, Anthropic specific variants
- **Chaining Mode**: Two-step ingest (analyze_source → generate_wiki_ops)
- **Validation & Retry**: Schema validation with configurable retry

### ✅ v0.12.0–v0.17.0 (Completed)
- ✅ Complete CLI commands (19 after v0.24.0 simplification)
- ✅ Auto-index on page write
- ✅ Raw source collection (all sources into raw/)
- ✅ wiki_synthesize — Query knowledge compounding
- ✅ Query sink feature with urgency tracking
- ✅ Smart recommendations and hints
- ✅ Smart investigations with LLM suggestions
- ✅ Enhanced ingest metadata

### v1.0.0 (Roadmap)
- [ ] Web UI (optional)
- [ ] MCP server authentication
- [ ] Incremental index updates
- [ ] Stable API guarantee
- [ ] Production hardening

---

## 🙏 Acknowledgments

- **[llm-wiki-kit](https://github.com/iamsashank09/llm-wiki-kit)** — Original inspiration and foundational design by Sashank. This project extends the core concepts of LLM-maintained wikis with enhanced CLI tools, MCP server support, query knowledge compounding, and configuration-driven flexibility.
- **Andrej Karpathy** — [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- **graphify** — Inspiration for Surprise Score algorithm and knowledge graph analysis
- **Obsidian** — Markdown wiki platform
- **MCP (Model Context Protocol)** — LLM integration standard

---

## 📄 License

MIT License — See [LICENSE](LICENSE) file for details.

---

## 📬 Contact

- **GitHub**: [@sn0wfree](https://github.com/sn0wfree)
- **Email**: linlu1234567@sina.com
- **Discussions**: [GitHub Discussions](https://github.com/sn0wfree/llmwikify/discussions)

---

*Built with ❤️ based on Karpathy's LLM Wiki Principles*
