# MCP Server Setup Guide

**llmwikify** provides an MCP (Model Context Protocol) server that exposes wiki operations as tools for LLMs.

**Current**: 20 tools available (v0.30.1)

---

## 🚀 Quick Start

### 1. Basic Usage (Default Configuration)

```python
from llmwikify import Wiki, MCPServer

# Open wiki
wiki = Wiki("/path/to/wiki")

# Create and start server
# Auto-reads config from wiki.config["mcp"] if no explicit config
server = MCPServer(wiki)
server.serve()
```

**Output**:
```
Starting MCP server with STDIO transport...
```

---

## ⚙️ Configuration

### Option 1: Auto-Read from Wiki Config (Recommended)

```python
from llmwikify import Wiki, MCPServer

wiki = Wiki("/path/to/wiki")  # Loads .wiki-config.yaml automatically
server = MCPServer(wiki)      # Reads mcp settings from wiki.config["mcp"]
server.serve()
```

### Option 2: Programmatic Configuration

```python
from llmwikify import Wiki, MCPServer

wiki = Wiki("/path/to/wiki")

# Custom configuration
config = {
    "host": "0.0.0.0",
    "port": 8765,
    "transport": "http",
}

server = MCPServer(wiki, config=config)
server.serve()
```

**Output**:
```
Starting MCP server on 0.0.0.0:8765 with HTTP transport...
```

### Option 3: Override at Runtime

```python
server = MCPServer(wiki)

# Override host/port/transport when starting
server.serve(
    transport="http",
    host="127.0.0.1",
    port=9000
)
```

### Option 4: Configuration File

Create `.wiki-config.yaml` in wiki root:

```yaml
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"  # or "http" or "sse"
```

Then:

```python
from llmwikify import Wiki, MCPServer

wiki = Wiki("/path/to/wiki")  # Auto-loads .wiki-config.yaml
server = MCPServer(wiki)      # Reads mcp section
server.serve()
```

**Configuration Priority**:
1. Explicit `config` parameter to `MCPServer()`
2. `wiki.config["mcp"]` (from `.wiki-config.yaml`)
3. `DEFAULT_CONFIG` (stdio, 127.0.0.1:8765)

---

## 🔌 Transport Protocols

### STDIO (Default)

**Best for**: LLM integration (Claude, Cursor, etc.)

```python
server.serve(transport="stdio")
```

- Uses standard input/output
- No network exposure
- Secure by default

### HTTP

**Best for**: Web APIs, remote access

```python
server.serve(
    transport="http",
    host="127.0.0.1",
    port=8765
)
```

- Exposes HTTP endpoint
- Can be accessed remotely
- Requires firewall configuration

### SSE (Server-Sent Events)

**Best for**: Streaming responses

```python
server.serve(
    transport="sse",
    host="127.0.0.1",
    port=8765
)
```

- Event-based communication
- Good for real-time updates
- Unidirectional (server → client)

---

## 🔒 Security Considerations

### Local Only (Recommended)

```yaml
# .wiki-config.yaml
mcp:
  host: "127.0.0.1"  # Localhost only
  port: 8765
  transport: "stdio"
```

### Expose to Network

```yaml
# .wiki-config.yaml
mcp:
  host: "0.0.0.0"  # All interfaces
  port: 8765
  transport: "http"
```

**⚠️ Warning**: Only expose to network if:
- You have firewall rules configured
- You trust all clients on the network
- You've reviewed security implications

---

## 📋 Available Tools (20 Total)

| Tool | Description | Added |
|------|-------------|-------|
| `wiki_init` | Initialize wiki directory structure | v0.9.0 |
| `wiki_ingest` | Ingest source (auto-collects to raw/) | v0.9.0 |
| `wiki_write_page` | Write/update a wiki page | v0.9.0 |
| `wiki_read_page` | Read a wiki page | v0.9.0 |
| `wiki_search` | Full-text search with snippets | v0.9.0 |
| `wiki_lint` | Health check (broken links, orphans) | v0.9.0 |
| `wiki_status` | Get wiki status overview | v0.9.0 |
| `wiki_log` | Append entry to wiki log | v0.9.0 |
| `wiki_recommend` | Missing pages and orphan detection | v0.12.0 |
| `wiki_build_index` | Build reference index from all pages | v0.12.0 |
| `wiki_read_schema` | Read wiki.md (schema/conventions) | v0.12.4 |
| `wiki_update_schema` | Update wiki.md with new conventions | v0.12.4 |
| `wiki_synthesize` | Save query answer as wiki page | v0.12.6 |
| `wiki_sink_status` | Query sink buffer overview | v0.22.0 |
| `wiki_references` | Page backlink/forward references | v0.22.0 |
| `wiki_graph` | Graph query: neighbors, path, stats, write | v0.22.0 |
| `wiki_graph_analyze` | Export, community detect, report, analyze | v0.28.0 |
| `wiki_analyze_source` | Analyze raw source file (entities, relations) | v0.28.0 |
| `wiki_suggest_synthesis` | Cross-source synthesis suggestions | v0.28.0 |
| `wiki_knowledge_gaps` | Knowledge gap + outdated + redundancy detection | v0.28.0 |

### wiki_synthesize (v0.12.6+)

The key tool for the Query compounding cycle. Saves LLM-generated answers as persistent wiki pages.

```json
{
  "query": "Compare gold and copper mining",
  "answer": "# Mining Comparison\n\n...",
  "source_pages": ["Gold Mining", "Copper Mining"],
  "raw_sources": ["raw/report.pdf"],
  "page_name": "Query: Mining Comparison",
  "auto_link": true,
  "auto_log": true,
  "update_existing": false
}
```

**Returns**:
```json
{
  "status": "created",
  "page_name": "Query: Mining Comparison",
  "page_path": "wiki/Query: Mining Comparison.md",
  "source_pages": ["Gold Mining", "Copper Mining"],
  "raw_sources": ["raw/report.pdf"],
  "logged": true,
  "hint": "A similar query page already exists..."
}
```

---

## 🧪 Testing

### Test STDIO Transport

```bash
python3 -c "
from llmwikify import Wiki, MCPServer
wiki = Wiki('/tmp/test-wiki')
wiki.init()
server = MCPServer(wiki)
server.serve()
"
```

### Test HTTP Transport

```bash
python3 -c "
from llmwikify import Wiki, MCPServer
wiki = Wiki('/tmp/test-wiki')
wiki.init()
server = MCPServer(wiki, config={'transport': 'http', 'port': 8765})
server.serve()
" &

# Test connection
curl http://localhost:8765
```

---

## 🔧 Troubleshooting

### Port Already in Use

**Error**: `Address already in use`

**Solution**: Use a different port
```python
server.serve(port=8766)
```

### Connection Refused

**Check**:
1. Server is running
2. Correct host/port
3. Firewall allows connection
4. Transport protocol matches client

### Import Error

**Error**: `MCP server requires 'mcp' package`

**Solution**:
```bash
pip install mcp
```

---

## 📚 Examples

### Example 1: Claude Code Integration

```yaml
# .wiki-config.yaml
mcp:
  transport: "stdio"  # Default, perfect for Claude
```

```python
# claude_wiki.py
from llmwikify import Wiki, MCPServer

wiki = Wiki("~/knowledge-base")
server = MCPServer(wiki)
server.serve()  # STDIO transport
```

Run with Claude:
```bash
claude --mcp-file claude_wiki.py
```

### Example 2: Web API

```yaml
# .wiki-config.yaml
mcp:
  host: "0.0.0.0"
  port: 8765
  transport: "http"
```

```python
# web_wiki.py
from llmwikify import Wiki, MCPServer

wiki = Wiki("~/knowledge-base")
server = MCPServer(wiki)
server.serve()  # HTTP on 0.0.0.0:8765
```

Access from other machines:
```bash
curl http://your-server-ip:8765
```

---

## 🎯 Best Practices

1. **Use STDIO by default** — Most secure, works with LLMs
2. **Auto-read config** — Don't pass config explicitly unless needed
3. **Change port if conflict** — Default is 8765
4. **Don't expose to network** unless necessary
5. **Test locally first** before exposing

---

## 📖 Related

- [Configuration Guide](./CONFIGURATION_GUIDE.md)
- [MCP Documentation](https://modelcontextprotocol.io/)
- [Wiki API](../README.md#python-api)

---

*Last updated: 2026-04-27 | Version: 0.30.1 | 20 tools*
