# llmwikify

> **Build persistent, LLM-maintained knowledge bases — and reproduce quant research from papers.** Inspired by Karpathy's LLM Wiki Principles.

[![PyPI version](https://badge.fury.io/py/llmwikify.svg)](https://pypi.org/project/llmwikify/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 3100+ collected](https://img.shields.io/badge/tests-3100%2B%20collected-brightgreen.svg)](https://github.com/sn0wfree/llmwikify)
[![Version: 0.38.0](https://img.shields.io/badge/version-0.38.0-blue.svg)](pyproject.toml)

---

> ⚠️ **Beta Release** — APIs may shift between minor versions. Report issues on
> [GitHub](https://github.com/sn0wfree/llmwikify/issues).

---

## What is llmwikify?

**llmwikify** is a Python package and CLI for building **persistent,
LLM-maintained knowledge bases**, with a dedicated **quant research reproduction
pipeline** (Paper → 6-layer Factor → DuckDB → Backtest → L5 reflection).

It is organised as four cooperating layers plus a standalone `reproduction/`
module:

| Layer | Purpose |
|-------|---------|
| **kernel/** | Core engines — wiki, multi-wiki, search, knowledge graph, storage |
| **foundation/** | LLM client, prompt registry, extractors, configuration, IO |
| **apps/** | Application services — wiki, chat (ReAct + Skills), research, agent |
| **interfaces/** | CLI, MCP, HTTP/WebSocket server, Web UI |
| **reproduction/** | Paper → Factor → Strategy quant pipeline (independent) |

### Core Philosophy

> **The wiki is a persistent, compounding artifact.** Cross-references are
> already there. Contradictions have already been flagged. The synthesis
> already reflects everything you've read.

Based on [Karpathy's LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md):
- **Raw sources** — Immutable inputs in `raw/`
- **The wiki** — LLM-maintained markdown pages with cross-references
- **The schema** — `wiki.md` tells the LLM how to maintain the wiki
- **Quant repro** — Papers and factors live in `quant/`, separate from `wiki/`

---

## Features

### Wiki Core
- **SQLite FTS5 search** — Porter stemmer, BM25 ranking, sub-second queries
- **Bidirectional references** — Automatic `[[wikilink]]` detection with section-level granularity
- **Query compounding** — Save query answers as persistent wiki pages (`wiki_synthesize`)
- **Query sink** — Buffer pending updates with urgency tracking
- **Multi-Wiki Registry** (`kernel/multi_wiki/`) — Manage local + remote wikis through one server

### Smart Lint & Synthesis
- **Smart Lint 2.0** — Broken links, orphans, contradictions, outdated pages, knowledge gaps, redundancy alerts
- **Cross-Source Synthesis** — Reinforced claims, contradictions, knowledge gaps across sources
- **Source Analysis** — Cached LLM extraction (entities, relations, suggested pages)
- CLIs: `lint`, `suggest-synthesis`, `knowledge-gaps`, `analyze-source`

### Knowledge Graph
- **Relation engine** — 8 relation types × 3 confidence levels stored in SQLite
- **Graph queries** — Neighbours, shortest path, statistics, context, contradiction detection
- **Graph Analyzer** — PageRank centrality, hubs/authorities, community auto-labelling, bridge nodes
- **Visualisation** — Interactive HTML (pyvis), SVG (graphviz), GraphML (Gephi)

### Chat + Agent + Skills (`apps/chat/`, `apps/agent/`, `apps/research/`)
- **ChatService + ReActEngine (v0.37)** — Unified ReAct loop, up to 4 tool-call rounds, streaming events (`reasoning`, `phase`, `confirmation_required`, `save_warning`, `timeout`)
- **Skills system** (`apps/chat/skills/`) — `registry`, `pipelines`, `actions`, `workflows`, plugin loader, `wiki_query_skill`, `research_skill`, `autoresearch_compound_skill`
- **Research engine** (`apps/research/`) — Web search + structured reasoning + quality gate + harness eval
- **Dynamic Workflow DSL (LAL)** — Strict validation, alias rejection, subagent LLM inheritance, configurable retry/backoff
- **Agent runtime** (`apps/agent/`) — DreamEditor (async proposal + human confirmation), Scheduler (croniter), Hooks, Notifications

### Quant Reproduction (`reproduction/`) — first-class
- **Paper Extraction Pipeline** — Trigger via `POST /api/paper/start`; PDF/Markdown → structured JSON via `repro_extract.yaml`, `repro_factor.yaml`, `repro_factor_full.yaml` prompts
- **6-layer Factor YAML** — `quant/factors/{asset_type}/{category}/{slug}.yaml` covering L1 logic, L2 computation, L3 financial intuition, L4 hypotheses, L5 validation, L6 risk; see [docs/designs/factor_library_framework.md](docs/designs/factor_library_framework.md)
- **Factor library API** (`factor_library.py`) — Read/write YAML, rebuild `quant/factors/index.yaml`, list by category
- **Factor value store** (`factor_value_store.py`) — DuckDB long-table `factor_values(date, stock, factor_name, value)` at `quant/factor.duckdb`
- **Backtesting** (`factor_backtest.py`) — Single-stock + cross-sectional, IC/RankIC, quantile groups, long-short, tradability filter
- **L5 reflection** (`l5_orchestrator.py`, `l5_validation.py`) — Stability analysis, OOS K-fold, reflection-driven optimisation
- **Multi-factor / Parquet** — 101 Formulaic Alphas style multi-factor extraction; local Parquet ingestion + LLM-generated factor formula code

### Web UI
- **React + TypeScript SPA** (Vitest tested)
- **Markdown editor** — Live preview, front-matter panel, wikilink autocomplete
- **Interactive Graph View** — D3.js, PageRank sizing, community colours, bridge highlighting
- **Insights dashboard** — Cross-source synthesis, knowledge gaps, graph analysis
- **Chat console** — ReAct streaming, tool-call rounds, confirmations, regenerate, abort
- **Quant pages** — Paper extraction status, Factor library viewer/editor, backtest summary

### Extraction & Ingestion
- **MarkItDown unified extractor** — PDF, Word, Excel, PowerPoint, images, audio
- **Web / YouTube** — trafilatura + transcript API
- **File watcher** — Watch `raw/`, optional auto-ingest

### MCP Server
- **26 wiki tools** exposed over MCP (stdio + HTTP), incl. scoped variants for multi-wiki, cross-wiki search, and registry management

---

## Installation

```bash
# Basic (zero hard dependencies — only stdlib + jinja2 + pyyaml + requests)
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
| `extractors` | PDF / Office / images / audio / YouTube via MarkItDown |
| `mcp` | MCP server (`fastmcp`) |
| `watch` | Filesystem watching (`watchdog`) |
| `graph` | Graph visualisation + community detection |
| `web` | FastAPI / Starlette / Uvicorn for the unified server |
| `agent` | Scheduler + filelock + DuckDuckGo / Tavily search |
| `llm` | `tiktoken` for token counting |
| `all` | Everything above |

---

## Quick Start

### 1. Initialise a wiki
```bash
llmwikify init
# Creates: raw/, wiki/, wiki.md, .llmwikify.db
```

### 2. Ingest sources
```bash
llmwikify ingest document.pdf
llmwikify ingest document.pdf --self-create        # Auto-create wiki pages
llmwikify ingest https://example.com/article
llmwikify ingest https://youtube.com/watch?v=abc
llmwikify batch raw/pdfs/ --self-create            # Batch ingest
```

### 3. Search & query
```bash
llmwikify search "topic" -l 10
llmwikify references "Page Name" --detail
llmwikify lint --format=brief
```

### 4. Analyse the knowledge graph
```bash
llmwikify graph-analyze              # PageRank, communities, suggestions
llmwikify graph-analyze --json
llmwikify suggest-synthesis
llmwikify knowledge-gaps
```

### 5. Start the unified server (MCP + REST + Web UI)
```bash
llmwikify serve --web --port 8765 --host 0.0.0.0
curl http://localhost:8765/api/health
# OpenAPI docs: http://localhost:8765/docs
```

> Do not run with `--reload`; see `AGENTS.md` for project-specific server rules.

### 6. Quant reproduction (Paper → Factor → Backtest)
```bash
# Initialise quant/ scaffolding
llmwikify quant-init
# -> quant/{factors, papers, factorbacktest, strategies, datacache, factor.duckdb}

# Trigger paper extraction (POST or via Web UI)
curl -X POST http://localhost:8765/api/paper/start \
     -H "Content-Type: application/json" \
     -d '{"paper_id": "<id>", "source": "raw/<id>.pdf"}'

# Inspect generated 6-layer Factor YAMLs
ls quant/factors/stock/price/                       # e.g. momentum_20d.yaml
curl http://localhost:8765/api/factor/library/list
curl http://localhost:8765/api/factor/library/stock/price/momentum_20d

# Run a backtest, persisted to quant/factorbacktest/*.md and quant/factor.duckdb
curl -X POST http://localhost:8765/api/factor/momentum_20d/backtest
```

End-to-end design:
- [Paper extraction pipeline](docs/designs/paper_extraction_pipeline.md)
- [Factor library framework](docs/designs/factor_library_framework.md)
- [Factor reflection design](docs/designs/factor_reflection_design.md)

---

## MCP Server (26 Tools)

Wiki maintenance and query:

| Tool | Description |
|------|-------------|
| `wiki_init` | Initialise wiki structure |
| `wiki_ingest` | Ingest a source file |
| `wiki_write_page` | Write/update a wiki page |
| `wiki_read_page` | Read a wiki page |
| `wiki_search` | Full-text search (FTS5) |
| `wiki_lint` | Health check |
| `wiki_status` | Status overview |
| `wiki_log` | Append log entry |
| `wiki_recommend` | Get recommendations |
| `wiki_build_index` | Build reference index |
| `wiki_read_schema` | Read `wiki.md` |
| `wiki_update_schema` | Update `wiki.md` |
| `wiki_synthesize` | Save query answer as wiki page |
| `wiki_sink_status` | Sink buffer overview |
| `wiki_references` | Page references |
| `wiki_analyze_source` | Analyse raw source file |
| `wiki_suggest_synthesis` | Cross-source synthesis suggestions |
| `wiki_knowledge_gaps` | Knowledge gap + outdated + redundancy |
| `wiki_graph` | Graph query / modify |
| `wiki_graph_analyze` | Graph export / detect / report / analyse |

Multi-wiki management:

| Tool | Description |
|------|-------------|
| `wiki_list` | List all registered wikis |
| `wiki_switch` | Switch to a different wiki |
| `wiki_register` | Register a new wiki |
| `wiki_unregister` | Unregister a wiki |
| `wiki_search_cross` | Search across multiple wikis |
| `wiki_scan` | Scan directories for wikis |

> `wiki_status` and `wiki_search` accept an optional `wiki_id` to scope the
> request to a specific registered wiki.

---

## QMD Hybrid Search (Optional)

For larger wikis (1000+ pages), enable QMD for semantic search with LLM
reranking:

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

## Python Usage

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

# Inbound/outbound links
inbound_links = wiki.get_inbound_links("Python/Patterns/Singleton")

# Status / lint
status = wiki.status()
lint_result = wiki.lint(format="brief")

wiki.close()
```

### Run the unified server programmatically

```python
from llmwikify import Wiki
from llmwikify.interfaces.server import WikiServer

wiki = Wiki("./my-wiki")
server = WikiServer(
    wiki,
    api_key="optional-secret",
    enable_mcp=True,
    enable_rest=True,
    enable_webui=True,
)
server.run(host="0.0.0.0", port=8765)
```

### MCP integration

```python
from llmwikify import Wiki
from llmwikify.interfaces.mcp import create_mcp_server

wiki = Wiki("./knowledge-base")
mcp = create_mcp_server(wiki, name="my-wiki")
mcp.run(transport="stdio")
```

### Quant reproduction (Python)

```python
from llmwikify.reproduction.factor_library import (
    list_factors, read_factor_yaml, write_factor_yaml,
)
from llmwikify.reproduction.factor_value_store import (
    compute_and_store_factor, query_factor_values,
)
from llmwikify.reproduction.factor_backtest import run_factor_backtest

# Load a 6-layer factor definition
factor = read_factor_yaml("stock/price/momentum_20d")

# Compute and persist factor values to quant/factor.duckdb
compute_and_store_factor("momentum_20d", subcategory="momentum", window=20)

# Single-factor backtest (results land in quant/factorbacktest/)
result = run_factor_backtest(slug="momentum_20d")
```

**Full examples:** see [examples/](examples/) for Django, Flask, Docker, and more.

---

## Configuration

Project-wide config: `~/.llmwikify/llmwikify.json` (LLM, server defaults).

Per-wiki config: `.wiki-config.yaml` in the wiki root:

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

# Multi-Wiki (kernel/multi_wiki/)
wikis:
  default: "project-a"
  local:
    - id: "project-a"
      name: "Project A"
      path: "."
  remote:
    - id: "remote-docs"
      name: "Remote Docs"
      url: "http://wiki-server:8765"
      api_key: "${WIKI_DOCS_API_KEY}"
  discovery:
    enabled: true
    scan_paths: [".", "../", "~/wikis"]
    scan_depth: 2
```

See [Configuration Guide](docs/CONFIGURATION_GUIDE.md) for full options.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Initialise a wiki |
| `quant-init` | Scaffold `quant/` for the reproduction pipeline |
| `ingest` | Ingest a source file or URL |
| `batch` | Batch ingest a directory |
| `analyze-source` | Run LLM source analysis |
| `write_page` / `read_page` | Page CRUD |
| `search` | FTS5 / QMD search |
| `references` | Show inbound/outbound references |
| `build-index` | Rebuild the reference index |
| `fix-wikilinks` | Fix broken `[[wikilink]]` targets |
| `lint` | Health check |
| `status` | Status overview |
| `log` | Append log entry |
| `synthesize` | Save query answer as a wiki page |
| `sink-status` | Sink buffer overview |
| `suggest-synthesis` | Cross-source synthesis suggestions |
| `knowledge-gaps` | Knowledge-gap analysis |
| `graph-query` / `graph-analyze` | Graph queries + PageRank/community analysis |
| `export-graph` | Export visualisation (HTML/SVG/GraphML) |
| `community-detect` | Run Leiden/Louvain community detection |
| `report` | Surprise / connection report |
| `watch` | Watch `raw/` for new files |
| `qmd` | QMD hybrid search subcommands |
| `wikis` | Multi-wiki registry management |
| `serve` | Start MCP + REST + Web UI (unified server) |
| `db` | Low-level database utilities |
| `help` | Show CLI help (with `--aliases`) |

---

## REST API Surface

`llmwikify serve --web` exposes:

| Prefix | Purpose |
|--------|---------|
| `/api/wiki/*` | Page CRUD, search, lint, sink, recommend, graph |
| `/api/wikis/*` | Multi-wiki registry (list/register/scan/reload) |
| `/api/search/cross` | Cross-wiki search |
| `/api/agent/*` | Chat (SSE), sessions, dream, notifications, ingest log, confirmations, config, tools |
| `/api/paper/*` | Paper extraction pipeline (start, status, list, upload, artifacts) |
| `/api/factor/*` | Factor library list/read/update + backtest |
| `/api/strategy/*` | Strategy listing + backtest |
| `/api/reproduction/*` | Reproduction sessions |
| `/api/log/error` | Error log ingestion |
| `/docs`, `/redoc` | OpenAPI docs |

---

## Documentation

- [Architecture](ARCHITECTURE.md) — Layered architecture, modules, data flow
- [Configuration Guide](docs/CONFIGURATION_GUIDE.md)
- [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md) — Karpathy's original vision
- [Migration Guide](MIGRATION.md) — Version-by-version migration notes (v0.30 → v0.37)
- [Factor library framework](docs/designs/factor_library_framework.md) — 6-layer model
- [Paper extraction pipeline](docs/designs/paper_extraction_pipeline.md)
- [Factor reflection design](docs/designs/factor_reflection_design.md)
- [Dynamic workflows guide](docs/dynamic-workflows-guide.md)
- [LLM access layer](docs/designs/llm-access-layer.md)
- [Multi-wiki plan](docs/designs/MULTI_WIKI_PLAN.md)
- [WebUI unified server](docs/designs/WEBUI_UNIFIED_SERVER.md)
- [Known Issues](docs/KNOWN_ISSUES.md)
- [Contributing](CONTRIBUTING.md)

---

## Testing

```bash
pytest                                # 3100+ tests collected
pytest --cov=src/llmwikify             # With coverage
pytest tests/reproduction/             # Quant reproduction tests
pytest tests/test_apps_chat_agent_react_engine.py  # ReAct engine

# Frontend tests
cd src/llmwikify/web/webui && npm test
```

---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development
setup, coding standards, and the contribution workflow. Project-internal agent
rules live in [AGENTS.md](AGENTS.md).

---

## Acknowledgments

- **[llm-wiki-kit](https://github.com/iamsashank09/llm-wiki-kit)** — Original inspiration
- **Andrej Karpathy** — [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- **Obsidian** — Markdown wiki platform
- **MCP** — Model Context Protocol

---

## License

MIT License — see [LICENSE](LICENSE).

## Credits

- **PPT Generator theme system** is based on
  [html-ppt-skill](https://github.com/lewislulu/html-ppt-skill) (MIT, © 2026
  lewislulu). Theme tokens, category structure, and inspiration are adapted
  from their CSS-token design system.

## Contact

- **GitHub**: [@sn0wfree](https://github.com/sn0wfree)
- **Email**: linlu1234567@sina.com
- **Discussions**: [GitHub Discussions](https://github.com/sn0wfree/llmwikify/discussions)
