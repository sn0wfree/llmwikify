# llmwikify

> **Build persistent, LLM-maintained knowledge bases** — Based on Karpathy's LLM Wiki Principles

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 110 passing](https://img.shields.io/badge/tests-110%20passing-brightgreen.svg)](https://github.com/sn0wfree/llmwikify)

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
- Inbound/outbound link queries
- JSON export for Obsidian compatibility

### 🧠 Smart Recommendations
- Missing page detection (frequently referenced but don't exist)
- Orphan page identification (with intelligent exclusion)
- Cross-reference opportunities
- Smart hints for wiki improvement

### 🔀 Query Knowledge Compounding (v0.12.6+)
- **wiki_synthesize** — Save query answers as persistent wiki pages
- Auto-generated `Query: {Topic}` pages with structured Sources sections
- Smart duplicate detection with date suffix for multiple runs
- `update_existing=True` to revise previous answers
- Auto-links to wiki pages and raw sources
- Auto-logs to `log.md` with parseable format
- Answers compound in the knowledge base just like ingested sources

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

### 📦 Zero Core Dependencies
- Standard library only
- Optional dependencies for extended functionality:
  - `pymupdf` — PDF extraction
  - `trafilatura` — Web scraping
  - `youtube-transcript-api` — YouTube transcripts
  - `mcp` — MCP server support
  - `pyyaml` — Configuration loading

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

# Ingest a URL (text saved to raw/)
llmwikify ingest https://example.com/article

# Ingest a YouTube video (transcript saved to raw/)
llmwikify ingest https://youtube.com/watch?v=abc123
```

All sources are automatically collected into `raw/` for centralized management.

### 3. Build Index
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

### 4. Search and Query
```bash
# Full-text search
llmwikify search "gold mining" -l 10

# Query page references
llmwikify references "Company Name"

# Get smart recommendations
llmwikify recommend

# Get wiki health hints
llmwikify hint
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

# Write page (auto-updates index.md)
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
# → Creates "Query: Compare Gold And Copper Mining" page
# → Auto-adds Sources section with wikilinks and raw links
# → Auto-logs to log.md

# Get references
inbound = wiki.get_inbound_links("Company Page")
outbound = wiki.get_outbound_links("Company Page")

# Get recommendations
recs = wiki.recommend()
print(f"Missing pages: {recs['missing_pages']}")
print(f"Orphan pages: {recs['orphan_pages']}")

# Get smart hints
hints = wiki.hint()
print(f"Total hints: {hints['summary']['total_hints']}")
```

---

## 🗄️ MCP Server (13 Tools)

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

### Quick Start
```python
from llmwikify import Wiki, MCPServer

wiki = Wiki("/path/to/wiki")
server = MCPServer(wiki)  # Auto-reads config from wiki.config["mcp"]
server.serve()            # STDIO transport (default)
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

# MCP server settings
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"  # or "http" or "sse"
```

### Design Principle: Zero Domain Assumptions

llmwikify does **NOT** assume:
- ❌ "Daily summary" concept
- ❌ "Company page" concept
- ❌ Any domain-specific page types

llmwikify provides:
- ✅ Universal patterns (dates, quarters)
- ✅ Frontmatter markers (redirect_to)
- ✅ Directory structures (archive/, logs/)
- ✅ User-configurable rules

This makes llmwikify truly general-purpose:
- **Mining News Wiki**: Dates = daily summaries
- **Personal KB**: Dates = journal entries
- **Project Docs**: Dates = release notes
- **Research Wiki**: Dates = experiment logs

---

## 📊 CLI Commands (15 Total)

| Command | Description | Example |
|---------|-------------|---------|
| `init` | Initialize wiki | `llmwikify init` |
| `ingest` | Ingest PDF/URL/YouTube | `llmwikify ingest doc.pdf` |
| `write_page` | Create/update page | `llmwikify write_page Test -c "..."` |
| `read_page` | Read page | `llmwikify read_page Test` |
| `search` | Full-text search | `llmwikify search "gold" -l 10` |
| `lint` | Health check | `llmwikify lint` |
| `status` | Status overview | `llmwikify status` |
| `log` | Record log entry | `llmwikify log ingest doc.pdf` |
| `references` | Show references | `llmwikify references "Agnico"` |
| `build-index` | Build reference index | `llmwikify build-index` |
| `export-index` | Export JSON | `llmwikify export-index -o out.json` |
| `batch` | Batch ingest | `llmwikify batch raw/pdfs/ -l 10` |
| `hint` | Smart suggestions | `llmwikify hint` |
| `recommend` | Recommendations | `llmwikify recommend` |
| `serve` | Start MCP server | `llmwikify serve` |

---

## 🗄️ Database Schema

```sql
-- FTS5 full-text search
CREATE VIRTUAL TABLE pages_fts USING fts5(
    page_name, content,
    tokenize='porter unicode61'
);

-- Bidirectional link tracking
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
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/llmwikify

# Run specific module
pytest tests/test_query_flow.py -v

# Run and generate HTML report
pytest --cov=src/llmwikify --cov-report=html
```

**Test Coverage**: 110 tests, all passing

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_wiki_core.py` | 36 | Wiki class (init, ingest, pages, schema, lint) |
| `test_query_flow.py` | 27 | Query synthesis (basic, sources, logging, duplicates, full flow) |
| `test_index.py` | 8 | WikiIndex (FTS5, links, export) |
| `test_recommend.py` | 5 | Recommendation engine |
| `test_cli.py` | 8 | CLI commands |
| `test_extractors.py` | 12 | Content extractors |
| `test_llm_client.py` | 14 | LLM client config and JSON parsing |

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
│  1. Core Layer                                              │
│     Wiki (wiki.py) — Business logic, synthesize_query       │
│     WikiIndex (index.py) — FTS5 + Reference Tracking        │
└─────────────────────────────────────────────────────────────┘
                               ▲
                               │
┌─────────┴────────────────────────────────────────────────┐
│                   Extraction Layer                        │
│  text.py │ pdf.py │ web.py │ youtube.py                 │
└──────────────────────────────────────────────────────────┘
                               ▲
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
┌────────────────────────┐        ┌────────────────────────┐
│  CLI (15 commands)     │        │  MCP Server (13 tools) │
└────────────────────────┘        └────────────────────────┘
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

### v0.12.0 (Completed)
- ✅ Complete CLI commands (15 total)
- ✅ Auto-index on page write
- ✅ wiki.md template generation
- ✅ Hint and recommend commands
- ✅ wiki_read_schema / wiki_update_schema MCP tools
- ✅ Raw source collection (all sources into raw/)
- ✅ Source citation conventions in wiki.md
- ✅ MCP config auto-read from wiki.config
- ✅ **wiki_synthesize — Query knowledge compounding cycle**
- ✅ 110 tests passing

### v0.13.0 (Planned)
- [ ] Enhanced wiki_lint: contradiction detection, stale claims, data gaps
- [ ] Enhanced wiki_search: include_content, include_sources, include_links
- [ ] Expose wiki_hint as MCP tool
- [ ] Incremental index updates

### v1.0.0 (Roadmap)
- [ ] Web UI (optional)
- [ ] Graph visualization (graphviz/Mermaid)
- [ ] MCP server authentication (API key / token)
- [ ] More extractors (Word, Excel)
- [ ] Stable API guarantee
- [ ] Production hardening

---

## 🙏 Acknowledgments

- **Andrej Karpathy** — [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- **llm-wiki-kit** — Original inspiration
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
