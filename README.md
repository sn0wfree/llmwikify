# llmwikify

> **Build persistent, LLM-maintained knowledge bases** - Based on Karpathy's LLM Wiki Principles

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/sn0wfree/llmwikify/actions/workflows/tests.yml/badge.svg)](https://github.com/sn0wfree/llmwikify/actions)

---

## 🎯 What is llmwikify?

**llmwikify** is a general-purpose LLM-Wiki management tool that helps you build and maintain a persistent knowledge base using LLMs. Unlike RAG systems that rediscover knowledge from scratch on every query, llmwikify incrementally builds and maintains a structured, interlinked wiki that compounds over time.

### Core Philosophy

> **The wiki is a persistent, compounding artifact.** The cross-references are already there. The contradictions have already been flagged. The synthesis already reflects everything you've read.

Based on [Karpathy's LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md):
- 📚 **Raw sources** - Your immutable source documents (PDFs, URLs, YouTube videos)
- 📝 **The wiki** - LLM-maintained markdown pages with cross-references
- ⚙️ **The schema** - Configuration that tells the LLM how to maintain the wiki

---

## ✨ Features

### 🔍 Full-Text Search
- SQLite FTS5 with Porter stemmer
- Ranked results with snippets
- 0.06 seconds for 157 pages

### 🔗 Bidirectional Reference Tracking
- Automatic link detection ([[Page Name]] syntax)
- Inbound/outbound link queries
- JSON export for Obsidian compatibility

### 🧠 Smart Recommendations
- Missing page detection (frequently referenced but don't exist)
- Orphan page identification (with intelligent exclusion)
- Cross-reference opportunities
- Content gap analysis

### 🚀 Performance Optimized
- Batch inserts with `executemany()`
- PRAGMA optimizations (MEMORY journal, OFF synchronous)
- Progress reporting for large collections
- 10-20x faster than naive implementation

### 🔧 Pure Tool Design
- **Zero domain assumptions** - No hardcoded concepts like "daily summary"
- **Configuration-driven** - You decide what to exclude via `.wiki-config.yaml`
- **Universal patterns** - Date formats, frontmatter markers, directory structures

### 📦 Zero Core Dependencies
- Standard library only
- Optional dependencies for extended functionality:
  - `pymupdf` - PDF extraction
  - `trafilatura` - Web scraping
  - `youtube-transcript-api` - YouTube transcripts
  - `mcp` - MCP server support
  - `pyyaml` - Configuration loading

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
# Create wiki structure
llmwikify init --agent claude

# Output:
# Wiki initialized at /path/to/wiki
#   raw/     → drop source files here
#   wiki/    → LLM-maintained wiki pages
#   .llm-wiki-kit.db → SQLite index
#   .wiki-config.yaml.example → configuration template
```

### 2. Ingest Sources
```bash
# Ingest a PDF
llmwikify ingest document.pdf

# Ingest a URL
llmwikify ingest https://example.com/article

# Ingest a YouTube video
llmwikify ingest https://youtube.com/watch?v=abc123
```

### 3. Build Index
```bash
# Build reference index (with performance stats)
llmwikify build-index

# Output:
# === Building Reference Index ===
# Scanning: /path/to/wiki
#
#   Processing: 100/157 (63.7%) - 29591.5 files/sec - ETA: 0s
#
# === Index Built ===
# Total pages: 157
# Total links: 636
# ⏱️  Elapsed: 0.06s
# 📈 Speed: 2833.4 files/sec
```

### 4. Search and Query
```bash
# Full-text search
llmwikify search "gold mining" -l 10

# Query page references
llmwikify references "Company Name"

# Get smart recommendations
llmwikify recommend
```

---

## 💻 Python API

```python
from llmwikify import Wiki, create_wiki
from pathlib import Path

# Create/open a wiki
wiki = create_wiki("/path/to/wiki")

# Initialize
wiki.init(agent="claude")

# Ingest source
result = wiki.ingest_source("document.pdf")
print(f"Ingested: {result['title']}")

# Write page
wiki.write_page("Test Page", "# Test\n\nContent with [[Link]]")

# Search
results = wiki.search("gold mining", limit=10)
for r in results:
    print(f"{r['page_name']}: {r['snippet']}")

# Get references
inbound = wiki.get_inbound_links("Company Page")
outbound = wiki.get_outbound_links("Company Page")

# Get recommendations
recs = wiki.recommend()
print(f"Missing pages: {recs['missing_pages']}")
print(f"Orphan pages: {recs['orphan_pages']}")
```

---

## ⚙️ Configuration

### .wiki-config.yaml

```yaml
# Wiki configuration
# Pure tool design - you decide what to exclude

orphan_pages:
  # Regex patterns for page names to exclude
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Date format (2025-07-31)
    - '^meeting-.*'          # Meeting notes
    - '^book-note-.*'        # Book notes
  
  # Frontmatter keys that indicate exclusion
  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages
    - 'template: true'       # Template pages
  
  # Directory names that indicate archived content
  archive_directories:
    - 'daily'                # Daily summaries
    - 'journal'              # Personal journal
    - 'meetings'             # Meeting notes
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
| `init` | Initialize wiki | `wiki init --agent claude` |
| `ingest` | Ingest PDF/URL/YouTube | `wiki ingest doc.pdf` |
| `write_page` | Create/update page | `wiki write_page Test -c "..."` |
| `read_page` | Read page | `wiki read_page Test` |
| `search` | Full-text search | `wiki search "gold" -l 10` |
| `lint` | Health check | `wiki lint` |
| `status` | Status overview | `wiki status` |
| `log` | Record log entry | `wiki log ingest doc.pdf` |
| `references` | Show references | `wiki references "Agnico"` |
| `build-index` | Build index | `wiki build-index` |
| `export-index` | Export JSON | `wiki export-index -o out.json` |
| `batch` | Batch ingest | `wiki batch raw/pdfs/ -l 10` |
| `hint` | Smart suggestions | `wiki hint` |
| `recommend` | Recommendations | `wiki recommend` |
| `serve` | Start MCP server | `wiki serve` |

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
pytest tests/test_core.py -v

# Run and generate HTML report
pytest --cov=src/llmwikify --cov-report=html
```

**Test Coverage**: 48 tests, >85% coverage

---

## 📚 Use Cases

### 1. Mining News Wiki (Current Project)
```yaml
# .wiki-config.yaml
orphan_pages:
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
orphan_pages:
  exclude_patterns:
    - '^book-note-.*'        # Book notes
    - '^course-.*'           # Course notes
  archive_directories:
    - 'journal'
    - 'notes'
```

### 3. Project Documentation
```yaml
orphan_pages:
  exclude_patterns:
    - '^release-.*'          # Release notes
    - '^meeting-.*'          # Meeting notes
    - '^rfc-.*'              # RFC documents
  archive_directories:
    - 'releases'
    - 'meetings'
    - 'rfcs'
```

### 4. Research Wiki
```yaml
orphan_pages:
  exclude_patterns:
    - '^experiment-.*'       # Experiment logs
    - '^paper-note-.*'       # Paper notes
  archive_directories:
    - 'experiments'
    - 'papers'
    - 'data'
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
│  1. Data Layer (95 lines)                                   │
│     ExtractedContent, Link, Issue, PageMeta                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Extraction Layer (296 lines)                            │
│     PDF, URL, YouTube, HTML, Text extraction                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Index Layer (401 lines)                                 │
│     WikiIndex: SQLite FTS5 + Reference Tracking             │
│     Optimized: batch inserts, PRAGMA tuning                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Core Layer (565 lines)                                  │
│     Wiki: Business logic, Configuration, Orphan exclusion   │
│     Zero domain assumptions                                 │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌────────────────────────┐        ┌────────────────────────┐
│  5. MCP Server (71)    │        │  6. CLI (376 lines)    │
│     8 MCP tools        │        │     15 commands        │
└────────────────────────┘        └────────────────────────┘
```

---

## 📖 Documentation

- **[Configuration Guide](docs/CONFIG_GUIDE.md)** - Detailed configuration options
- **[LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)** - Karpathy's original vision
- **[Reference Tracking Guide](docs/REFERENCE_TRACKING_GUIDE.md)** - How references work

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Report bugs** - [GitHub Issues](https://github.com/sn0wfree/llmwikify/issues)
2. **Fix bugs** - Submit a PR
3. **Add features** - Open an issue first to discuss
4. **Improve docs** - PRs welcome
5. **Share use cases** - Add your `.wiki-config.yaml` to examples/

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

### v0.10.x (Current)
- ✅ Modular package structure
- ✅ PyPI release
- ✅ Comprehensive documentation
- ✅ CI/CD pipeline

### v0.11.0 (Planned)
- [ ] Web UI (optional)
- [ ] Graph visualization (graphviz/Mermaid)
- [ ] Incremental index updates
- [ ] More extractors (Word, Excel)

### v0.12.0 (Future)
- [ ] MCP server authentication (API key / token)
- [ ] Obsidian plugin (read JSON index)
- [ ] VS Code extension
- [ ] LLM Agent integrations (Claude Code, Cursor)

---

## 🙏 Acknowledgments

- **Andrej Karpathy** - [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- **llm-wiki-kit** - Original inspiration
- **Obsidian** - Markdown wiki platform
- **MCP (Model Context Protocol)** - LLM integration standard

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

---

## 📬 Contact

- **GitHub**: [@sn0wfree](https://github.com/sn0wfree)
- **Email**: linlu1234567@sina.com
- **Discussions**: [GitHub Discussions](https://github.com/sn0wfree/llmwikify/discussions)

---

*Built with ❤️ based on Karpathy's LLM Wiki Principles*
