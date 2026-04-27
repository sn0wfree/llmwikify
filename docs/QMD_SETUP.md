# QMD Hybrid Search Setup Guide

QMD (Query Markdown Documents) is a local hybrid search engine that combines
full-text search (BM25) with semantic vector search and LLM reranking.

---

## Overview

QMD provides significantly better search quality by understanding the semantic
meaning of queries, at the cost of slightly higher latency and memory usage.

| Feature | FTS5 (Default) | QMD (Hybrid) |
|---------|-----------------|---------------|
| **Speed** | Instant (~ms) | Slow (~seconds) |
| **Keyword Match** | ✅ Excellent | ✅ Excellent |
| **Semantic Match** | ❌ None | ✅ Excellent |
| **Query Expansion** | ❌ No | ✅ LLM-powered |
| **LLM Reranking** | ❌ No | ✅ Cross-encoder |
| **Memory Usage** | Negligible | ~2GB (3 GGUF models) |
| **Setup** | Built-in | Requires npm install |

---

## Installation

### 1. Install QMD CLI

```bash
npm install -g @tobilu/qmd
```

### 2. Initialize in your wiki root

```bash
cd /path/to/wiki
qmd init
```

This creates a `qmd.yaml` configuration file.

### 3. Index your wiki pages

```bash
qmd add wiki/
```

### 4. Generate embeddings

First run downloads ~2GB of GGUF models:

```bash
qmd embed
```

### 5. Start MCP server

```bash
qmd mcp --http --port 8181
```

---

## Usage with llmwikify

### CLI

```bash
# Check QMD status and recommendations
llmwikify qmd status

# QMD hybrid search
llmwikify qmd search "your query"

# Standard search with QMD backend
llmwikify search "your query" --backend qmd
```

### REST API

```bash
curl "http://localhost:8765/api/wiki/search?q=your%20query&backend=qmd"
```

### MCP Tools

```python
wiki_search("your query", limit=10, backend="qmd")
```

---

## Configuration

### llmwikify config

Add to your `.wiki-config.yaml`:

```yaml
search:
  # Default backend: "fts5" or "qmd"
  backend: "fts5"

  # QMD server connection settings
  qmd:
    host: "127.0.0.1"
    port: 8181
    auto_start: false  # Not implemented yet
```

### QMD config

See `qmd.yaml` in your wiki root for search-specific configuration:

```yaml
# QMD configuration
collections:
  wiki:
    path: wiki/
    pattern: "**/*.md"

# Model configuration (defaults)
models:
  embed: "Xenova/all-MiniLM-L6-v2"
  rerank: "Xenova/bge-reranker-base"
  generate: "llama.cpp compatible model"
```

---

## Automatic Recommendation

QMD is automatically recommended when your wiki reaches 1000+ pages,
at which point semantic search provides significant benefit over
pure keyword matching.

Check status:
```bash
llmwikify qmd status
```

---

## Running as a Service

To run QMD MCP server in the background:

```bash
# Using systemd (Linux)
cat > /etc/systemd/system/qmd.service << EOF
[Unit]
Description=QMD MCP Server
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/wiki
ExecStart=/usr/local/bin/qmd mcp --http --port 8181
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable qmd
sudo systemctl start qmd
```

---

## Troubleshooting

### QMD server not available

```
llmwikify qmd status
# Check if port 8181 is open
lsof -i :8181

# Start the server
qmd mcp --http --port 8181
```

### Model download issues

First embedding run downloads models to `~/.cache/qmd/`. If download fails:

```bash
# Clear cache and retry
rm -rf ~/.cache/qmd/
qmd embed
```

### High memory usage

QMD runs 3 GGUF models. For systems with limited RAM:

```bash
# Use smaller models in qmd.yaml
models:
  embed: "Xenova/all-MiniLM-L6-v2"  # ~80MB
  rerank: "Xenova/bge-reranker-base"  # ~180MB
  generate: "Xenova/gemma-2b-it"  # ~2GB (only needed for query expansion)
```

---

## Related Resources

- QMD GitHub: https://github.com/tobilu/qmd
- GGUF Format: https://github.com/ggerganov/ggml
- MCP Protocol: https://modelcontextprotocol.io/
