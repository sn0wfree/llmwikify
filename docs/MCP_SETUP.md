# MCP Server Setup Guide

**llmwikify** 通过统一的 `llmwikify serve` CLI 暴露 **26 个 wiki 工具**
（MCP stdio / HTTP / SSE 三种 transport），同时承载 REST API 和 Web UI。

**Current**: 26 tools (v0.38.0)

> **v0.30+ 破坏性变更**：旧 `MCPServer(wiki).serve()` Python API 已废弃。
> 统一由 `llmwikify.interfaces.server.WikiServer` 替代，由 `llmwikify serve`
> CLI 调度。配置入口见 [CONFIGURATION_GUIDE.md §server](./CONFIGURATION_GUIDE.md#7-server-unified-server--mcp--rest--webui)。

---

## 🚀 Quick Start

### CLI 模式（推荐）

```bash
# 单 wiki，stdio transport（最常用 — Claude Desktop / opencode / Cursor）
llmwikify serve
# → 启动 MCP stdio，绑定到当前进程 stdin/stdout

# 统一 server（MCP HTTP + REST + WebUI）
llmwikify serve --web --port 8765 --host 0.0.0.0

# 携带 API Key 鉴权
llmwikify serve --web --auth-token mysecret

# 多 wiki 注册表模式
llmwikify serve --web --multi-wiki --port 8765
```

健康检查：

```bash
curl http://localhost:8765/api/health
# {"status": "ok", "version": "0.38.0", "wikis": 1}
```

### Python 模式（嵌入到自己的应用）

```python
from llmwikify import Wiki
from llmwikify.interfaces.server import WikiServer

wiki = Wiki("/path/to/wiki")
server = WikiServer(
    wiki,
    api_key="optional-secret",       # Bearer auth
    enable_mcp=True,
    enable_rest=True,
    enable_webui=True,
)
server.run(host="0.0.0.0", port=8765)
# → FastAPI ASGI app: server.app
# → OpenAPI: http://localhost:8765/docs
```

---

## ⚙️ Configuration

### 方式 1：CLI 参数（最简）

```bash
llmwikify serve \
    --transport http \
    --host 127.0.0.1 \
    --port 8765 \
    --web
```

### 方式 2：`.wiki-config.yaml`（推荐）

```yaml
server:
  host: "127.0.0.1"
  port: 8765
  auth_token: null         # 设为非空字符串启用 Bearer auth
  enable_mcp: true
  enable_rest: true
  enable_webui: true
  multi_wiki: false

mcp:                       # 兼容：serve 启动时也会读这里
  transport: "http"        # stdio / http / sse
  port: 8765
```

**Config priority**（高 → 低）：

1. 显式 CLI flag (`--port`, `--transport`, ...)
2. `wiki.config["server"]` (from `.wiki-config.yaml`)
3. `wiki.config["mcp"]` (legacy 兼容)
4. `DEFAULT_CONFIG` (127.0.0.1:8765, stdio)

---

## 🔌 Transport Protocols

### stdio（默认）

适合 LLM 集成（Claude Desktop / opencode / Cursor），无需网络暴露：

```bash
llmwikify serve --transport stdio
```

### http

Web API + 远程访问。`llmwikify serve --web` 默认就是 http：

```bash
llmwikify serve --transport http --host 127.0.0.1 --port 8765
```

### sse（Server-Sent Events）

流式响应场景（chat agent）：

```bash
llmwikify serve --transport sse --port 8765
```

> **注意**：SSE 模式下 MCP 工具仍可用，但 Web UI 不工作；要 Web UI 须
> `--web`（= http + WebUI bundle）。

---

## 🔒 Security Considerations

### 本地默认（推荐）

```yaml
server:
  host: "127.0.0.1"
  port: 8765
  auth_token: null
```

### 暴露到网络 + Bearer auth

```bash
llmwikify serve --web \
    --host 0.0.0.0 \
    --port 8765 \
    --auth-token "$(openssl rand -hex 32)"
```

调用时所有 `/api/*` 需带：

```bash
curl -H "Authorization: Bearer <your-token>" http://server:8765/api/wiki/status
```

### 接入 MCP 客户端（Claude Desktop 配置示例）

```json
{
  "mcpServers": {
    "llmwikify": {
      "command": "llmwikify",
      "args": ["serve", "--transport", "stdio"],
      "cwd": "/path/to/your/wiki"
    }
  }
}
```

接入 opencode 见 [docs/MCPORTER_DEPLOYMENT.md](./MCPORTER_DEPLOYMENT.md)。

---

## 📋 Available Tools (26 Total)

> 数字 = 实际注册到 FastMCP 的工具数（v0.38.0）。每个工具的"Added"列表示
> 引入版本。

### Wiki 核心（20）

| Tool | Description | Added |
|------|-------------|-------|
| `wiki_init` | 初始化 wiki 目录结构 | v0.9.0 |
| `wiki_ingest` | 摄取源（自动收 raw/） | v0.9.0 |
| `wiki_write_page` | 写/更新 wiki 页面 | v0.9.0 |
| `wiki_read_page` | 读 wiki 页面 | v0.9.0 |
| `wiki_search` | FTS5/QMD 全文检索 + snippet | v0.9.0 |
| `wiki_lint` | 健康检查（broken links、orphans、contradictions） | v0.9.0 |
| `wiki_status` | wiki 状态总览 | v0.9.0 |
| `wiki_log` | 追加 log 条目 | v0.9.0 |
| `wiki_recommend` | 缺失页面 / orphan 检测 | v0.12.0 |
| `wiki_build_index` | 重建引用索引 | v0.12.0 |
| `wiki_read_schema` | 读 `wiki.md` schema | v0.12.4 |
| `wiki_update_schema` | 更新 `wiki.md` schema | v0.12.4 |
| `wiki_synthesize` | 查询结果落盘为新页面 | v0.12.6 |
| `wiki_sink_status` | query sink buffer 状态 | v0.22.0 |
| `wiki_references` | 页面双向引用 | v0.22.0 |
| `wiki_graph` | 知识图谱 query/modify | v0.22.0 |
| `wiki_graph_analyze` | 导出/社区检测/分析 | v0.28.0 |
| `wiki_analyze_source` | LLM 提取 raw 源（实体/关系/建议页面） | v0.28.0 |
| `wiki_suggest_synthesis` | 跨源综合建议 | v0.28.0 |
| `wiki_knowledge_gaps` | 知识缺口 / 过时 / 冗余 | v0.28.0 |

### Multi-Wiki（6，v0.31+）

| Tool | Description |
|------|-------------|
| `wiki_list` | 列出已注册 wikis |
| `wiki_switch` | 切换 active wiki |
| `wiki_register` | 注册新 wiki（local 或 remote） |
| `wiki_unregister` | 注销 wiki |
| `wiki_search_cross` | 跨多 wiki 检索 |
| `wiki_scan` | 扫描目录自动发现 wiki |

### Scoped variants

`wiki_status` 和 `wiki_search` 都接受可选 `wiki_id` 参数，把请求限定到注册
表中特定 wiki。

---

### `wiki_synthesize`（v0.12.6+）

Query compounding 循环的关键工具。把 LLM 生成的答案落盘为持久页面：

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

返回：

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

### Smoke test（stdio）

```bash
python3 - <<'PY'
from llmwikify import Wiki
from llmwikify.interfaces.mcp import create_mcp_server

wiki = Wiki("/tmp/test-wiki")
wiki.init()
mcp = create_mcp_server(wiki, name="test-wiki")
# 列工具
print([t.name for t in mcp.list_tools()])
PY
```

### Smoke test（HTTP）

```bash
llmwikify serve --web --port 8765 &
curl -s http://localhost:8765/api/health
curl -s http://localhost:8765/api/wiki/status | head -50
```

---

## 🔧 Troubleshooting

### 端口占用

```text
OSError: [Errno 98] Address already in use
```

```bash
llmwikify serve --web --port 8766
# 或 fuser -k 8765/tcp
```

### 客户端连接被拒

逐项检查：

1. 服务进程是否在跑 (`ps aux | grep llmwikify`)
2. host/port 是否与客户端匹配
3. 防火墙是否放行（暴露到 0.0.0.0 时）
4. transport 协议是否对得上（stdio vs http）

### `ImportError: mcp package not found`

```bash
pip install 'llmwikify[mcp]'   # 或 pip install fastmcp
```

### 401 Unauthorized

说明 server 启用了 `auth_token`（或 `server.auth_token`），需带 Bearer：

```bash
curl -H "Authorization: Bearer mysecret" http://localhost:8765/api/wiki/status
```

---

## 📚 Examples

### Claude Desktop 集成

`~/.config/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "llmwikify": {
      "command": "llmwikify",
      "args": ["serve", "--transport", "stdio"],
      "cwd": "/home/you/knowledge-base"
    }
  }
}
```

### opencode / Cursor（stdio）

同上：把 `llmwikify serve --transport stdio` 配到 MCP client。

### 多客户端通过 MCPorter Bridge

详见 [docs/MCPORTER_DEPLOYMENT.md](./MCPORTER_DEPLOYMENT.md) — 把多个
MCP 服务（含 llmwikify）聚合到一个 stdio 端点。

---

## 🎯 Best Practices

1. **stdio 优先** — 与 LLM 客户端集成最安全
2. **暴露网络时必须开 auth_token** — 别裸奔
3. **端口冲突 → 改 `--port`** — 默认 8765
4. **生产跑 systemd / docker** — 不要 `nohup` 起
5. **多 wiki 用 `--multi-wiki`** — 比手挂多个 server 简单

---

## 📖 Related

- [Configuration Guide](./CONFIGURATION_GUIDE.md) — `server.*` / `mcp.*` / `wikis.*` 全配置项
- [MCPorter Deployment](./MCPORTER_DEPLOYMENT.md) — 多 MCP 聚合
- [TUTORIAL.md](./TUTORIAL.md) — 5 个端到端场景（含 Chat SSE）
- [MCP 协议](https://modelcontextprotocol.io/)

---

*Last updated: 2026-06-30 | Version: 0.38.0 | 26 tools*
