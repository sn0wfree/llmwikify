# MCP Server Setup Guide

**llmwikify** provides an MCP (Model Context Protocol) server that exposes wiki operations as tools for LLMs.

---

## 🚀 Quick Start

### 1. Basic Usage (Default Configuration)

```python
from llmwikify import Wiki, MCPServer

# Open wiki
wiki = Wiki("/path/to/wiki")

# Create and start server (uses defaults: stdio transport)
server = MCPServer(wiki)
server.serve()
```

**Output**:
```
Starting MCP server with STDIO transport...
```

---

## ⚙️ Configuration

### Option 1: Programmatic Configuration

```python
from llmwikify import Wiki, MCPServer

wiki = Wiki("/path/to/wiki")

# Custom configuration
config = {
    "host": "0.0.0.0",  # Allow external connections
    "port": 8765,
    "transport": "http",  # Use HTTP instead of stdio
}

server = MCPServer(wiki, config=config)
server.serve()
```

**Output**:
```
Starting MCP server on 0.0.0.0:8765 with HTTP transport...
```

### Option 2: Override at Runtime

```python
server = MCPServer(wiki)

# Override host/port/transport when starting
server.serve(
    transport="http",
    host="127.0.0.1",
    port=9000
)
```

### Option 3: Configuration File

Create `.wiki-config.yaml` in wiki root:

```yaml
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"  # or "http" or "sse"
```

Then use in code:

```python
from llmwikify import Wiki, MCPServer, load_config
from pathlib import Path

wiki_root = Path("/path/to/wiki")
config = load_config(wiki_root)

wiki = Wiki(wiki_root, config=config)
server = MCPServer(wiki, config=config.get('mcp'))
server.serve()
```

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

## 📋 Available Tools

The MCP server exposes these 8 wiki tools:

| Tool | Description |
|------|-------------|
| `wiki_init` | Initialize a wiki |
| `wiki_ingest` | Ingest a source file |
| `wiki_write_page` | Write a wiki page |
| `wiki_read_page` | Read a wiki page |
| `wiki_search` | Search the wiki |
| `wiki_lint` | Health-check the wiki |
| `wiki_status` | Get wiki status |
| `wiki_log` | Append entry to wiki log |

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
server.serve(port=8766)  # Use different port
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

### Example 3: Development Setup

```yaml
# .wiki-config.yaml
mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "sse"  # For real-time updates
```

---

## 🎯 Best Practices

1. **Use STDIO by default** - Most secure, works with LLMs
2. **Change port if conflict** - Default is 8765
3. **Don't expose to network** unless necessary
4. **Use configuration file** for consistency
5. **Test locally first** before exposing

---

## 📖 Related

- [Configuration Guide](./CONFIGURATION_GUIDE.md)
- [MCP Documentation](https://modelcontextprotocol.io/)
- [Wiki API](../README.md#python-api)

---

*Last updated: 2026-04-10 | Version: 0.11.0*
