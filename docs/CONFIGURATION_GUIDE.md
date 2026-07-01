# Configuration Guide

**llmwikify** uses a flexible configuration system that allows you to customize behavior while maintaining zero core dependencies.

**Current**: v0.38.0 (2026-06-30) — 与最新 main 分支对齐

> **破坏性变更提示（v0.30+）**：Python API `MCPServer(wiki)` 已废弃，由
> `llmwikify.interfaces.server.WikiServer` + `llmwikify serve` CLI 统一替代。
> 本文中所有 `MCPServer` 引用改为 `WikiServer` / `serve`。

---

## 📋 Overview

Configuration is loaded in this priority order (highest to lowest):

1. **Programmatic config** — Dict passed to `Wiki()` or `create_wiki()`
2. **User config file** — `.wiki-config.yaml` in wiki root
3. **Built-in defaults** — Embedded in `config.py`

This design ensures:
- ✅ Zero dependencies (defaults are embedded)
- ✅ Easy customization (YAML file)
- ✅ Full control (programmatic API)

---

## 📁 Configuration Files

### .wiki-config.yaml.example

Located in the wiki root, this is a **template** with:
- All available configuration options
- Detailed comments
- Use case examples

**Copy and customize**:
```bash
cp .wiki-config.yaml.example .wiki-config.yaml
```

### .wiki-config.yaml

Your **actual configuration** (optional):
- Only include options you want to change
- Omitted options use defaults
- Fully documented in the example file

---

## ⚙️ Configuration Options

### 1. directories

Control the directory structure:

```yaml
directories:
  raw: "raw"   # Source files (PDFs, exports, etc.)
  wiki: "wiki" # Wiki pages (markdown files)
```

**Use case**: Organize sources differently
```yaml
directories:
  raw: "sources"
  wiki: "knowledge"
```

---

### 2. files

Configure file names:

```yaml
files:
  index: "index.md"  # Wiki index file
  log: "log.md"      # Activity log
```

---

### 3. database

Database configuration:

```yaml
database:
  name: ".llmwikify.db"
```

**Use case**: Multiple wikis with different databases
```yaml
database:
  name: ".research-notes.db"
```

---

### 4. reference_index

JSON export settings:

```yaml
reference_index:
  name: "reference_index.json"  # Export filename
  auto_export: true             # Auto-export after build
```

---

### 5. orphan_detection

Control which pages are excluded from orphan detection:

```yaml
orphan_detection:
  # Regex patterns for page names
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates (2025-07-31)
    - '^meeting-.*'          # Meeting notes

  # Frontmatter keys that mark exclusion
  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages
    - 'template: true'       # Template pages

  # Directory names that indicate archives
  archive_directories:
    - 'archive'
    - 'logs'
    - 'old'
```

**⚠️ Zero Domain Assumption**: By default, all exclusion lists are **empty**. You must explicitly configure what to exclude. No dates, no redirect_to, no archive directories are assumed.

---

### 6. performance

Performance tuning:

```yaml
performance:
  batch_size: 100      # Files per batch during index build
  cache_size: 64000    # SQLite cache size in KB
```

**Tips**:
- Higher `batch_size` = faster but more memory
- `cache_size`: -1000 = 1MB, -64000 = 64MB

---

### 7. server (unified server — MCP + REST + WebUI)

v0.33 起统一服务器（`llmwikify serve --web`）替代了独立的 `MCPServer` 类。
所有 `MCPServer(wiki)` 旧调用应改为：

```python
# 旧（已废弃）
from llmwikify import MCPServer
server = MCPServer(wiki)
server.serve()

# 新（推荐）
from llmwikify.interfaces.server import WikiServer
server = WikiServer(wiki, enable_mcp=True, enable_rest=True, enable_webui=True)
server.run(host="127.0.0.1", port=8765)

# 或 CLI
# llmwikify serve --web --port 8765 --host 0.0.0.0 --auth-token mysecret
```

```yaml
# .wiki-config.yaml
server:
  host: "127.0.0.1"        # 绑定地址
  port: 8765               # REST + WebUI + MCP HTTP 端口
  auth_token: null         # 设为非空字符串启用 Bearer auth
  enable_mcp: true
  enable_rest: true
  enable_webui: true
  multi_wiki: false        # 多 wiki 注册表模式

mcp:                       # 兼容旧 mcp.* 字段；serve 也会读取
  host: "127.0.0.1"
  port: 8765
  transport: "http"        # stdio / http / sse — stdio 时 server 不可用
```

**Config priority** in `WikiServer`:
1. 显式构造参数 `WikiServer(wiki, enable_mcp=...)` / CLI flag
2. `wiki.config["server"]` (from `.wiki-config.yaml`)
3. `wiki.config["mcp"]` (legacy 兼容)
4. `DEFAULT_CONFIG` (127.0.0.1:8765)

---

### 8. search (后端选择)

v0.22+ 支持 QMD 混合检索（BM25 + 向量 + LLM rerank）。FTS5 是默认，零额外依赖。

```yaml
search:
  backend: "fts5"          # "fts5" (default) | "qmd"
  qmd:
    host: "127.0.0.1"
    port: 8181
    auto_start: false
```

详见 [QMD Setup Guide](./QMD_SETUP.md)。

---

### 9. wikis (multi-wiki 注册表 — v0.31+)

统一管理本地 + 远程 wiki。`llmwikify wikis` 子命令 / `/api/wikis/*` REST 端点
都从这一节读取。

```yaml
wikis:
  default: "project-a"

  local:
    - id: "project-a"
      name: "Project A"
      path: "."
    - id: "research-notes"
      name: "Research Notes"
      path: "~/wikis/research"

  remote:
    - id: "team-docs"
      name: "Team Docs"
      url: "http://wiki-server:8765"
      api_key: "${WIKI_DOCS_API_KEY}"   # 支持 env 引用

  discovery:
    enabled: true
    scan_paths: [".", "../", "~/wikis"]
    scan_depth: 2
```

启动多 wiki 模式：

```bash
llmwikify serve --web --multi-wiki --port 8765
# Wikis: 3 registered
# Transport: http
```

---

### 10. llm (LLM provider 配置 — v0.33+)

wiki/chat 路径下需要 LLM 调用（analyze-source、synthesize、chat）时从此处
读取。CLI 子命令 `llmwikify` 启动时也会读 `~/.llmwikify/llmwikify.json` 中的
全局配置。

```yaml
llm:
  provider: "openai"                    # openai | anthropic | minimax | custom
  model: "gpt-4o"
  api_key: "env:OPENAI_API_KEY"         # 显式 env: 前缀
  base_url: null                        # 留空走 provider 默认
  max_retries: 3
  timeout_seconds: 60
```

---

## 🎯 Use Case Examples

### Example 1: Personal Knowledge Base

```yaml
database:
  name: ".personal-wiki.db"

orphan_detection:
  exclude_patterns:
    - '^journal-.*'
    - '^daily-.*'
    - '^book-note-.*'
  archive_directories:
    - 'archive'
    - 'old'

server:
  transport: "stdio"     # MCP stdio 模式
```

---

### Example 2: Project Documentation

```yaml
database:
  name: ".project-docs.db"

orphan_detection:
  exclude_patterns:
    - '^release-.*'
    - '^changelog-.*'
    - '^meeting-.*'
  archive_directories:
    - 'releases'
    - 'meetings'
    - 'rfcs'
```

---

### Example 3: Research Wiki

```yaml
database:
  name: ".research-notes.db"

directories:
  raw: "papers"
  wiki: "notes"

orphan_detection:
  exclude_patterns:
    - '^experiment-.*'
    - '^paper-note-.*'
  archive_directories:
    - 'experiments'
    - 'papers'
    - 'data'
```

---

### Example 4: Team Wiki

```yaml
database:
  name: ".team-wiki.db"

orphan_detection:
  exclude_patterns:
    - '^meeting-.*'
    - '^decision-.*'
    - '^rfc-.*'
  archive_directories:
    - 'meetings'
    - 'decisions'
    - 'archive'

mcp:
  host: "127.0.0.1"
  port: 8765
  transport: "stdio"

wikis:
  default: "team-wiki"
  local:
    - id: "team-wiki"
      name: "Team Wiki"
      path: "."
```

---

## 💻 Programmatic Configuration

For full control, pass config dict directly:

```python
from llmwikify import create_wiki

custom_config = {
    "database": {
        "name": ".custom.db"
    },
    "directories": {
        "raw": "sources",
        "wiki": "pages"
    },
    "orphan_detection": {
        "exclude_patterns": ["^draft-.*"]
    },
    "server": {
        "host": "0.0.0.0",
        "port": 9000,
        "auth_token": "mysecret",
    },
    "search": {
        "backend": "fts5",
    },
}

wiki = create_wiki("/path/to/wiki", config=custom_config)
```

---

## 🔍 Configuration Helpers

Use helper functions to work with configuration:

```python
from llmwikify import get_default_config, load_config
from pathlib import Path

# Get default config
default = get_default_config()
print(default['database']['name'])  # .llmwikify.db

# Load user config (merged with defaults)
wiki_root = Path("/path/to/wiki")
config = load_config(wiki_root)
print(config['database']['name'])  # From .wiki-config.yaml or default
```

---

## ⚠️ Troubleshooting

### Config file not loading?

**Check**:
1. File is named `.wiki-config.yaml` (not `.wiki-config.yml`)
2. File is in wiki root directory
3. YAML syntax is valid
4. PyYAML is installed: `pip install pyyaml`

### Changes not taking effect?

**Try**:
1. Restart Python interpreter
2. Check config priority (programmatic > file > defaults)
3. Verify YAML indentation
4. Use `get_default_config()` to see defaults

### Database name not changing?

**Check**:
1. Config is loaded **before** `Wiki()` initialization
2. `database.name` key is correct
3. No typos in YAML

---

## 📚 Related

- [MCP Setup Guide](./MCP_SETUP.md)
- [Configuration System Design](../ARCHITECTURE.md#configuration)
- [Zero Domain Assumption](../README.md#design-principle-zero-domain-assumptions)

---

*Last updated: 2026-06-30 | Version: 0.38.0*
