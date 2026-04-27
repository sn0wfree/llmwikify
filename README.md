# llmwikify

> **Build persistent, LLM-maintained knowledge bases** — Based on Karpathy's LLM Wiki Principles

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 1008+ passing](https://img.shields.io/badge/tests-1008%2B%20passing-brightgreen.svg)](https://github.com/sn0wfree/llmwikify)

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

### Agent Layer (v0.30.0+) ⚠️ DEPRECATED
**Built-in Agent has moved to an independent project.** Use external AI agents with the MCP protocol:
- `llmwikify mcp` — Start MCP server for Agent integration
- All 20+ wiki tools are available via standard MCP protocol

*Legacy Agent is kept for backward compatibility only and will be removed in a future version.*
- **Autonomous Wiki Maintenance** — 8 sub-systems: WikiAgent, AgentRunner, TaskScheduler, MemoryManager, NotificationManager, HooksSystem, ToolsRegistry, DreamEditor
- **Dream Confirmation Flow** — Agent proposes changes, human confirms (respects "stay involved" principle)
- **Scheduled Tasks** — Cron-based periodic lint, source analysis, knowledge gap detection
- **Hook System** — Pre/post operation callbacks for custom workflows

### Web UI (v0.30.0+)
- **React + TypeScript SPA** — 18 components, Vitest tested
- **Markdown Editor** — Real-time preview, front matter panel
- **Interactive Graph View** — D3.js visualization with PageRank sizing, community coloring, bridge node highlighting
- **Insights Dashboard** — Cross-source synthesis, knowledge gaps, graph analysis
- **Agent Interface** ⚠️ DEPRECATED — Legacy agent UI (removed, use external agents via MCP)
- **Project Metadata** — `llmwikify · project-name` display, version number indicator

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

## 🔍 QMD Hybrid Search (Optional)

For larger wikis (1000+ pages), enable QMD for semantic search with LLM reranking:

- **Hybrid**: BM25 keyword + vector embeddings
- **Query Expansion**: LLM generates semantic variants
- **LLM Reranking**: Cross-encoder reorders results
- **Auto Recommendation**: Prompts to enable at scale

```bash
# Check status and recommendations
llmwikify qmd status

# Start QMD MCP server (separate process)
qmd mcp --http --port 8181

# Use QMD backend
llmwikify search "your query" --backend qmd
llmwikify qmd search "your query"
```

See [QMD Setup Guide](docs/QMD_SETUP.md) for installation instructions.

---

## 🐍 Python Usage

Use llmwikify as a library in your Python projects:

```python
from llmwikify import Wiki, create_wiki

# Create or open a wiki
wiki = create_wiki("./my-wiki")

# Write a page
wiki.write_page("Python/Patterns/Singleton", """
# Singleton Pattern

Ensures a class has only one instance...
""")

# Read a page
content = wiki.read_page("Python/Patterns/Singleton")

# Search (supports FTS5 and QMD backends)
results = wiki.search("singleton", limit=10, backend="fts5")

# Get inbound/outbound links
inbound_links = wiki.get_inbound_links("Python/Patterns/Singleton")

# Get wiki status
status = wiki.status()

# Health check
lint_result = wiki.lint(format="brief")

# Cleanup
wiki.close()
```

### Running Web Server Programmatically

```python
from llmwikify import Wiki
from llmwikify.server import WikiServer

wiki = Wiki("./my-wiki")
server = WikiServer(
    wiki,
    api_key="optional-secret",  # Optional: enable auth
    enable_mcp=True,            # Enable MCP protocol
    enable_rest=True,           # Enable REST API
    enable_webui=True,          # Enable React Web UI
)
server.run(host="0.0.0.0", port=8765)
```

### MCP Integration (for AI Agents)

```python
from llmwikify import Wiki
from llmwikify.mcp import create_mcp_server

wiki = Wiki("./knowledge-base")
mcp = create_mcp_server(wiki, name="my-wiki")
mcp.run(transport="stdio")  # Connects to Claude Desktop, etc.
```

**Full examples:** See [examples/](examples/) directory for Django, Flask, Docker, and more.

---

## 🔌 Integration Guide

### Django Integration

```python
# settings.py
LLMWIKIFY_ROOT = BASE_DIR / "data" / "wiki"

# views.py
from llmwikify import create_wiki

wiki = create_wiki(settings.LLMWIKIFY_ROOT)

def search(request):
    results = wiki.search(request.GET["q"])
    return JsonResponse({"results": results})
```

See full example: [examples/integrate_with_django.py](examples/integrate_with_django.py)

### Flask Integration

```python
from flask import Flask
from llmwikify import create_wiki

app = Flask(__name__)
wiki = create_wiki("./data/wiki")

@app.route("/search")
def search():
    return jsonify(wiki.search(request.args["q"]))
```

See full example: [examples/integrate_with_flask.py](examples/integrate_with_flask.py)

### Docker Deployment

```dockerfile
FROM python:3.11-slim
RUN pip install llmwikify[web]
VOLUME /data
EXPOSE 8765
CMD ["llmwikify", "serve", "--web", "--host", "0.0.0.0"]
```

See Docker Compose: [examples/docker-compose.yml.example](examples/docker-compose.yml.example)

---

## 🖥️ Web UI

Start the unified **FastAPI** web server:

```bash
llmwikify serve --web                  # Starts MCP + Web UI + REST API on http://localhost:8765
llmwikify serve --web --auth-token=key # With optional API key authentication
```

**Architecture** (FastAPI):
- 🔄 **MCP Protocol** — `/mcp` endpoint for AI agent integration
- 🌐 **REST API** — `/api/wiki/*` endpoints with auto-generated docs at `/docs`
- 🖥️ **Web UI** — React SPA static file serving

**Features**:
- 📝 **Markdown Editor** — Live preview, front matter support, wikilink autocomplete
- 🌐 **Graph View** — D3.js interactive visualization, PageRank sizing, community colors
- 📊 **Insights Panel** — Cross-source synthesis, knowledge gaps, graph analysis
- 🤖 **Agent Console** — Chat interface, scheduled tasks, dream proposals & confirmations
- 📈 **Health Dashboard** — Broken links, orphans, stale pages, knowledge growth
- 🔍 **Full-text Search** — FTS5-powered search with snippets
- 🔑 **Optional Auth** — API key authentication for production deployments

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
pytest                           # All 879+ Python tests
pytest --cov=src/llmwikify       # With coverage
pytest tests/test_p1_features.py # Specific module

# Frontend tests
cd src/llmwikify/web/webui && npm test
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
