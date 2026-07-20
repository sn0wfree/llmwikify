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

  # v0.40.1+ — FTS5 tokenizer (CJK-friendly default)
  tokenize: "unicode61 categories 'L* N* Co Mn' tokenchars '_'"
  # - "porter unicode61" → 旧 schema (英文 porter + 整段中文), 不推荐
  # - "unicode61" → 基础 unicode, 无 categories
  # - "unicode61 categories 'L* N* Co Mn' tokenchars '_'" → 中文单字 + 英文单词, 推荐

  qmd:
    host: "127.0.0.1"
    port: 8181
    auto_start: false
```

**首次启动**检测到旧 `tokenize` 参数 → 自动 `DROP TABLE pages_fts` → 用新
tokenize 重建 → 从 `pages` metadata 表回填。**完全自动，无需手动**。

详见 [QMD Setup Guide](./QMD_SETUP.md)、[v0.40.1 release notes](./releases/v0.40.1-search-cjk.md)。

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

## 🌐 Global LLM Config (`~/.llmwikify/llmwikify.json`)

The CLI reads LLM settings from `~/.llmwikify/llmwikify.json`. This is **separate** from
`.wiki-config.yaml` (which is per-wiki). LLM features (`analyze-source`, `synthesize`,
`--self-create`, `chat`, `reproduce`) require this file.

**Config priority** (highest → lowest):
1. Programmatic config (Python API)
2. `~/.llmwikify/llmwikify.json` (global, CLI reads this)
3. Built-in defaults

### Minimum config

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "sk-your-key-here"
  }
}
```

### Supported providers

| Provider | `provider` value | Default `base_url` | Env var for `api_key` |
|----------|-----------------|---------------------|----------------------|
| OpenAI | `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` |
| Minimax | `minimax` | `https://api.minimaxi.com/v1` | `MINIMAX_API_KEY` |
| Xiaomi | `xiaomi` | `https://api.xiaomi.com/v1` | — |

### OpenAI example

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "sk-proj-...",
    "base_url": "https://api.openai.com/v1",
    "timeout": 600
  }
}
```

### Anthropic example

```json
{
  "llm": {
    "enabled": true,
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "api_key": "sk-ant-...",
    "base_url": "https://api.anthropic.com/v1"
  }
}
```

### Minimax example

```json
{
  "llm": {
    "enabled": true,
    "provider": "minimax",
    "model": "minimax-M3",
    "api_key": "eyJ...",
    "base_url": "https://api.minimaxi.com/v1"
  }
}
```

### OpenAI-compatible / custom endpoint

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "deepseek-chat",
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com/v1"
  }
}
```

### Offline mode (no LLM)

Simply don't create the config file, or set `enabled` to `false`:

```json
{
  "llm": {
    "enabled": false
  }
}
```

Features that work without LLM: `init`, `write_page`, `read_page`, `search`,
`build-index`, `references`, `status`, `lint`, `fix-wikilinks`, `graph-analyze`,
`export-graph`, `community-detect`, `serve` (REST + MCP, no chat).

### Quick setup

```bash
# Option 1: One-shot during wiki init
export OPENAI_API_KEY=sk-...
llmwikify init --llm

# Option 2: Standalone (auto-detects from env vars)
llmwikify init-llm

# Option 3: Explicit
llmwikify init-llm --provider openai --api-key sk-...

# Option 4: Interactive (init prompts you)
llmwikify init
# No config detected. Set one up now? [y/N]: y

# Option 5: Manual
mkdir -p ~/.llmwikify
cat > ~/.llmwikify/llmwikify.json << 'EOF'
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "sk-your-key-here"
  }
}
EOF
```

### Verify config

```bash
llmwikify doctor    # Check config, deps, LLM, wiki, server
llmwikify --help    # Confirm CLI is working
```

---

## 🩺 Doctor — Health Check

The `llmwikify doctor` command validates your installation and reports issues
before you hit them in production.

```bash
# Full check (5s timeout for LLM API call)
llmwikify doctor

# Skip LLM API call (faster, ~1s)
llmwikify doctor --skip-llm

# Check a specific wiki directory (default: cwd)
llmwikify doctor --wiki-root /path/to/wiki

# JSON output for scripts/CI
llmwikify doctor --json
```

### What it checks

| # | Category | What it verifies | Fix command if it fails |
|---|----------|------------------|-------------------------|
| 1 | **Config** | `~/.llmwikify/llmwikify.json` exists, valid JSON, has `api_key` | `llmwikify init-llm` |
| 2 | **Python** | Version >= 3.10 | Upgrade Python |
| 3 | **Core deps** | llmwikify, yaml, duckdb, jinja2 | `pip install llmwikify` |
| 4 | **Optional extras** | fastapi, fastmcp, watchdog, networkx, markitdown, tiktoken, httpx | `pip install 'llmwikify[extractors,web,mcp]'` |
| 5 | **LLM connectivity** | **Actual API call** to provider with `"Say hi"`, 5s timeout | Re-check `api_key`, network, `base_url` |
| 6 | **Wiki directory** | wiki.md, .llmwikify.db, index.md, raw/ present | `llmwikify init` (in wiki dir) |
| 7 | **Permissions** | `~/.llmwikify/` and wiki root writable | `chmod 755 ~/.llmwikify/` |
| 8 | **WebUI bundle** | `ui/webui/dist/index.html` exists | `cd ui/webui && pnpm build` |
| 9 | **Server** | `GET /api/health` returns 200 | `llmwikify serve --web` (in another terminal) |

### Exit codes

| Code | Meaning | When |
|------|---------|------|
| 0 | All passed | Healthy install |
| 1 | One or more checks failed | Issues to fix |
| 2 | Config missing | First-time setup incomplete |

### CI / Scripting

```bash
# Fail the script if doctor finds issues
llmwikify doctor --json --skip-llm | jq -e '.summary.failed == 0'

# Pretty output with errors highlighted
llmwikify doctor 2>&1 | grep -E "❌|error"
```

### Example output

```
🔍 llmwikify doctor

Config file:
  ✅ ~/.llmwikify/llmwikify.json — provider=minimax, model=minimax-M3

Python:
  ✅ Python 3.11.15 — requires >= 3.10

Core dependencies:
  ✅ llmwikify
  ✅ yaml
  ✅ duckdb
  ✅ jinja2

Optional extras:
  ✅ fastapi — web
  ✅ fastmcp — mcp
  ✅ watchdog — watch
  ✅ networkx — graph
  ✅ markitdown — extractors
  ✅ tiktoken — llm
  ✅ httpx — http

LLM connectivity:
  ✅ minimax/minimax-M3 — responded in 1.2s

Wiki directory (/home/user/my-wiki):
  ✅ /home/user/my-wiki — 4 files present

Permissions:
  ✅ ~/.llmwikify/ — writable
  ✅ /home/user/my-wiki/ — writable

WebUI bundle:
  ✅ ui/webui/dist/ — found

Server (http://localhost:8765):
  ✅ Server reachable — status=ok

✅ All checks passed.
```

---

## 📚 Related

- [MCP Setup Guide](./MCP_SETUP.md)
- [Configuration System Design](../ARCHITECTURE.md#configuration)
- [Zero Domain Assumption](../README.md#design-principle-zero-domain-assumptions)

---

## 🆕 v0.41: 配置分层 + 自动迁移

### 三层配置架构

v0.41 引入三层配置架构：

| 层级 | 文件 | 作用域 | 可修改 |
|------|------|--------|--------|
| **全局** | `~/.llmwikify/llmwikify.json` | 所有 wiki | ✅ LLM / Research / MCP / Chat mutable |
| **Wiki** | `<wiki_root>/.wiki-config.yaml` | 单个 wiki | ✅ directories / database / wikis / orphan_detection |
| **默认** | `foundation/templates/llmwikify.default.json` | 兜底 | ❌ 只读 |

### 迁移段映射

`.wiki-config.yaml` 中以下段会自动迁移到全局配置：

| Wiki 段 | 迁移到 | 说明 |
|---------|--------|------|
| `llm` | `llmwikify.json:llm` | LLM provider / model / api_key |
| `research_mutable` | `llmwikify.json:research_mutable` | Research 可修改参数 |
| `chat_mutable` | `llmwikify.json:chat_mutable` | Chat 可修改参数 |
| `mcp` | `llmwikify.json:mcp` | MCP 服务器配置 |
| `prompts` | `llmwikify.json:prompts` | Prompt 模板目录 |

`.wiki-config.yaml` 中保留的段（不迁移）：

| Wiki 段 | 说明 |
|---------|------|
| `directories` | 目录结构（raw / wiki） |
| `database` | 数据库文件名 |
| `wikis` | 多 wiki 注册 |
| `orphan_detection` | 孤立页面检测 |
| `performance` | 性能参数 |
| `reference_index` | 引用索引 |

### 自动迁移机制

启动时 (`llmwikify serve` / `llmwikify chat`)，系统会自动检测旧版配置：

1. **检测版本**：读取 `.wiki-config.yaml` 的 `version` 字段
   - 缺失或 `< 0.41` → 需要迁移
   - `>= 0.41` → 跳过

2. **备份原文件**：`.wiki-config.yaml.bak.<timestamp>`（永久保留）

3. **合并到全局**：将 llm/research_mutable/chat_mutable/mcp/prompts 段合并到 `~/.llmwikify/llmwikify.json`

4. **冲突处理**（如果全局已有相同 key）：
   - **交互式（TTY）**：询问用户 `[g]lobal / [w]iki / [s]kip`，默认 `g`
   - **非交互式**：使用 `--auto-global`（默认）/ `--auto-wiki` / `--strict`

5. **更新 wiki 配置**：删除已迁移段，添加 `version: "0.41"`

### 手动迁移

```bash
# 默认行为：自动迁移（启动时 + 手动）
llmwikify migrate-config

# 只显示迁移计划，不写文件
llmwikify migrate-config --dry-run

# 冲突时严格失败（要求手动处理）
llmwikify migrate-config --strict

# 自动处理冲突（默认全局优先）
llmwikify migrate-config --auto-global
llmwikify migrate-config --auto-wiki

# 指定 wiki 目录
llmwikify migrate-config --wiki-root /path/to/wiki

# 跳过自动迁移（紧急情况）
llmwikify serve --no-migrate
```

### 备份管理

迁移会创建 `.wiki-config.yaml.bak.<timestamp>` 文件，**永久保留**：

- 文件名格式：`.wiki-config.yaml.bak.1721245678`
- 时间戳是 Unix epoch（秒）
- 多次迁移会创建多个备份
- 用户可手动删除不再需要的备份

### 手动编辑示例

如果你想手动迁移（跳过自动机制）：

```bash
# 1. 备份原文件
cp .wiki-config.yaml .wiki-config.yaml.bak.manual

# 2. 编辑全局配置
vim ~/.llmwikify/llmwikify.json

# 3. 从 .wiki-config.yaml 删除 llm/research_mutable/chat_mutable/mcp/prompts 段

# 4. 添加 version 字段
echo "version: \"0.41\"" >> .wiki-config.yaml
```

### 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| 启动时 WARNING | 检测到旧配置 | 等待自动迁移完成，或运行 `migrate-config` |
| 迁移后启动失败 | YAML 解析错误 | 手动修复 `.wiki-config.yaml` 或恢复 `.bak.<ts>` |
| 冲突未解决 | 非 TTY 环境 | 用 `--auto-global` / `--auto-wiki` / `--strict` |
| 备份太多 | 多次迁移 | 手动清理 `.bak.<timestamp>` 文件 |

---

*Last updated: 2026-07-20 | Version: 0.41.0*
