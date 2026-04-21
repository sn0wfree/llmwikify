# llmwikify

> **Build persistent, LLM-maintained knowledge bases** — Based on Karpathy's LLM Wiki Principles

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 879+ passing](https://img.shields.io/badge/tests-879%2B%20passing-brightgreen.svg)](https://github.com/sn0wfree/llmwikify)

---

> ⚠️ **Beta Release** — You may encounter bugs or breaking changes. Please report issues on [GitHub](https://github.com/sn0wfree/llmwikify/issues).

---

## 🎯 What is llmwikify?

**llmwikify** is a general-purpose LLM-Wiki management tool that helps you build and maintain a persistent knowledge base. Unlike RAG systems that rediscover knowledge from scratch on every query, llmwikify incrementally builds and maintains a structured, interlinked wiki that compounds over time.

### Core Philosophy

> **The wiki is a persistent, compounding artifact.** The cross-references are already there. The contradictions have already been flagged. The synthesis already reflects everything you've read.

Based on [Karpathy's LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md):
- 📚 **Raw sources** — Your immutable source documents in `raw/`
- 📝 **The wiki** — LLM-maintained markdown pages with cross-references
- ⚙️ **The schema** — `wiki.md` that tells the LLM how to maintain the wiki

---

## ✨ Features

### Core
- **SQLite FTS5 search** — Porter stemmer, BM25 ranking, 0.06s for 157 pages
- **Bidirectional references** — Automatic `[[wikilink]]` detection with section-level granularity
- **Query compounding** — Save query answers as persistent wiki pages (`wiki_synthesize`)
- **Query sink** — Buffer pending updates for later review with urgency tracking

### Source Analysis (v0.26.0+)
- `analyze-source` CLI with `--all` and `--force` support
- Caches LLM extraction results (entities, relations, suggested pages)
- Powers schema-aware lint gap detection

### Cross-Source Synthesis (v0.28.0+)
- Detects reinforced claims, contradictions, knowledge gaps across sources
- Returns suggestions only — human decides what to do with them
- CLI: `llmwikify suggest-synthesis [source]`

### Smart Lint 2.0 (v0.28.0+)
- Detects broken links, orphan pages, contradictions, data gaps
- New: outdated pages, knowledge gaps, redundancy alerts
- CLI: `llmwikify lint [--format=full|brief|recommendations|json]`
- CLI: `llmwikify knowledge-gaps`

### Knowledge Graph (v0.22.0+)
- LLM auto-extracts concept relationships (8 relation types, 3 confidence levels)
- Graph queries: neighbors, shortest path, statistics, context
- Community detection via Leiden/Louvain algorithms
- Surprise Score reports for unexpected connections

### Graph Analyzer (v0.28.0+)
- PageRank centrality scoring — identify core concepts
- Hub/Authority analysis — find highly connected pages
- Community auto-labeling and bridge node detection
- Suggested page generation for orphan concepts
- CLI: `llmwikify graph-analyze [--json] [--report]`

### Graph Visualization (v0.23.0+)
- Interactive HTML (pyvis), SVG (graphviz), GraphML (Gephi)

### Additional
- **File extraction** — PDF, Word, Excel, PowerPoint, images, audio, YouTube, web URLs via MarkItDown
- **File watcher** — Watch `raw/` for new files, optional auto-ingest
- **MCP server** — 20 tools for LLM/Agent integration
- **Performance** — Batch inserts, PRAGMA optimizations, 10-20x faster than naive implementation

---

## 📦 Installation

```bash
# Basic (zero dependencies)
pip install llmwikify

# Full (all features)
pip install llmwikify[all]

# Development
git clone https://github.com/sn0wfree/llmwikify.git
cd llmwikify
pip install -e ".[dev]"
```

### Optional Extras

| Extra | Purpose |
|-------|---------|
| `extractors` | Enhanced file extraction (PDF, Office, images, audio) |
| `mcp` | MCP server support |
| `watch` | File system watching |
| `graph` | Graph visualization + community detection |
| `web` | Web UI support |
| `all` | Everything above |

---

## 🚀 Quick Start

### 1. Initialize
```bash
llmwikify init
# Creates: raw/, wiki/, wiki.md, .llmwikify.db
```

### 2. Ingest Sources
```bash
llmwikify ingest document.pdf           # Extract content
llmwikify ingest document.pdf --self-create  # Auto-create wiki pages
llmwikify ingest https://example.com/article
llmwikify ingest https://youtube.com/watch?v=abc123
llmwikify batch raw/pdfs/ --self-create  # Batch ingest
```

### 3. Search and Query
```bash
llmwikify search "topic" -l 10
llmwikify references "Page Name" --detail
llmwikify lint --format=brief
```

### 4. Analyze Knowledge Graph
```bash
llmwikify graph-analyze              # PageRank, communities, suggestions
llmwikify graph-analyze --json       # Programmatic output
llmwikify graph-analyze --report     # Detailed suggested pages report
llmwikify suggest-synthesis          # Cross-source synthesis suggestions
llmwikify knowledge-gaps             # Knowledge gap analysis
```

### 5. MCP Server for Agents
```bash
llmwikify mcp                        # STDIO (default)
llmwikify mcp --transport http       # HTTP
llmwikify serve --web                # MCP + Web UI
```

---

## 💻 Python API

```python
from llmwikify import Wiki
from pathlib import Path

wiki = Wiki(Path("/path/to/wiki"))
wiki.init()

# Ingest source
result = wiki.ingest_source("document.pdf")

# Create pages
wiki.write_page("Test Page", "# Title\n\nContent with [[Link]]", page_type="Concept")

# Search
results = wiki.search("topic", limit=10)

# Synthesize query answers (knowledge compounding)
wiki.synthesize_query(query="Q?", answer="A...", source_pages=["Page1", "Page2"])

# Knowledge graph
engine = wiki.get_relation_engine()
engine.get_neighbors("Concept")
engine.get_path("A", "B")

# Health check
lint_result = wiki.lint(generate_investigations=True)

# Cross-source synthesis
wiki.suggest_synthesis()

# Graph analysis
graph_result = wiki.graph_analyze()
```

---

## 🗄️ MCP Server (20 Tools)

| Tool | Description |
|------|-------------|
| `wiki_init` | Initialize wiki structure |
| `wiki_ingest` | Ingest a source file |
| `wiki_write_page` | Write/update a wiki page |
| `wiki_read_page` | Read a wiki page |
| `wiki_search` | Full-text search with snippets |
| `wiki_lint` | Health check |
| `wiki_status` | Status overview |
| `wiki_log` | Append log entry |
| `wiki_recommend` | Get recommendations |
| `wiki_build_index` | Build reference index |
| `wiki_read_schema` | Read wiki.md (schema) |
| `wiki_update_schema` | Update wiki.md |
| `wiki_synthesize` | Save query answer as wiki page |
| `wiki_sink_status` | Sink buffer overview |
| `wiki_references` | Page references |
| `wiki_graph` | Graph query/modify |
| `wiki_graph_analyze` | Graph export/detect/report/analyze |
| `wiki_analyze_source` | Analyze raw source file |
| `wiki_suggest_synthesis` | Cross-source synthesis suggestions |
| `wiki_knowledge_gaps` | Knowledge gap + outdated + redundancy |

---

## ⚙️ Configuration

Create `.wiki-config.yaml` in your wiki root:

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Date pages
    - '^meeting-.*'           # Meeting notes
  archive_directories:
    - 'archive'
    - 'logs'

llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "env:OPENAI_API_KEY"

mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"
```

See [Configuration Guide](docs/CONFIGURATION_GUIDE.md) for full options.

---

## 📊 CLI Commands

| Command | Description | Command | Description |
|---------|-------------|---------|-------------|
| `init` | Initialize wiki | `lint` | Health check |
| `ingest` | Ingest source | `status` | Status overview |
| `analyze-source` | Analyze source file | `log` | Record log |
| `write_page` | Create page | `references` | Show references |
| `read_page` | Read page | `build-index` | Build index |
| `search` | Full-text search | `batch` | Batch ingest |
| `synthesize` | Save query as page | `suggest-synthesis` | Cross-source analysis |
| `sink-status` | Sink overview | `knowledge-gaps` | Gap analysis |
| `watch` | Watch for files | `graph-query` | Graph queries |
| `graph-analyze` | Graph analysis | `export-graph` | Export visualization |
| `community-detect` | Detect communities | `report` | Surprise report |
| `mcp` | Start MCP server | `serve` | MCP + Web UI |

---

## 📖 Documentation

- **[Architecture](ARCHITECTURE.md)** — Technical architecture, data flows, components
- **[Configuration Guide](docs/CONFIGURATION_GUIDE.md)** — Detailed config options
- **[LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)** — Karpathy's original vision
- **[Migration Guide](MIGRATION.md)** — Version migration notes
- **[Contributing](CONTRIBUTING.md)** — Development workflow
- **[Known Issues](docs/KNOWN_ISSUES.md)** — Known issues and planned fixes

---

## 🧪 Testing

```bash
pytest                           # All 879 Python tests
pytest --cov=src/llmwikify       # With coverage
pytest tests/test_p1_features.py # Specific module
```

---

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and contribution workflow.

---

## 🙏 Acknowledgments

- **[llm-wiki-kit](https://github.com/iamsashank09/llm-wiki-kit)** — Original inspiration
- **Andrej Karpathy** — [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- **Obsidian** — Markdown wiki platform
- **MCP** — Model Context Protocol

---

## 📄 License

MIT License — See [LICENSE](LICENSE) file.

## 📬 Contact

- **GitHub**: [@sn0wfree](https://github.com/sn0wfree)
- **Email**: linlu1234567@sina.com
- **Discussions**: [GitHub Discussions](https://github.com/sn0wfree/llmwikify/discussions)
