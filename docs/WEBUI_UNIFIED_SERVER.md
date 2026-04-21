# WebUI 统一服务器设计文档

**版本**: v1.0  
**创建日期**: 2026-04-20  
**状态**: 待实施  
**关联文档**: [AGENT_INTEGRATION_PLAN.md](AGENT_INTEGRATION_PLAN.md)

---

## 目录

1. [背景](#背景)
2. [架构演进](#架构演进)
3. [最终架构](#最终架构)
4. [API 设计](#api-设计)
5. [鉴权设计](#鉴权设计)
6. [文件变更清单](#文件变更清单)
7. [启动方式](#启动方式)
8. [实施步骤](#实施步骤)

---

## 背景

在 Phase 1-3 完成后，React WebUI 前端已构建完成，但缺少后端 API 桥接。前端 `api.ts` 定义了 REST API 端点，但现有 `web/server.py` 是 JSON-RPC 代理，与前端不匹配。

需要解决的问题：
1. 前端调用的 `/api/wiki/*`、`/api/agent/*` 没有后端实现
2. 现有 `web/server.py` 指向旧 Vanilla JS `static/`，未指向 React `webui/dist/`
3. Agent 聊天需要流式输出支持

---

## 架构演进

### 方案 A：双 Server（初始想法，已废弃）

```
MCP Server (8765)  ← 提供 wiki 工具
     ↑ JSON-RPC
Web Server (8766)  ← 代理 + 静态文件
```

**问题**：
- 两个进程，两个端口
- Web Server 到 MCP Server 多一次 HTTP 往返，延迟高
- 部署复杂度高
- 功能重复实现

### 方案 B：单 Server（最终方案）

```
┌─────────────────────────────────────────────────────────┐
│              统一 Server (Starlette)                      │
│                                                         │
│  认证中间件 (预留)                                        │
│  ├── Bearer Token (API Key)                              │
│  └── 可扩展：OAuth / JWT / Basic Auth                    │
│                                                         │
│  /mcp          → MCP JSON-RPC 端点                       │
│  /api/wiki/*   → REST API (直接调用 Wiki)                 │
│  /api/agent/*  → REST API (直接调用 Agent)                │
│  /*            → React 静态文件 (fallback: 旧 static/)     │
└─────────────────────────────────────────────────────────┘
```

**优势**：
- 单进程，单端口
- 进程内直接调用，零网络延迟
- 部署简单
- 功能不重复

**技术依据**：
- FastMCP 底层是 Starlette
- FastMCP 提供 `custom_route` 装饰器添加自定义 HTTP 路由
- FastMCP 的 `_additional_http_routes` 支持直接注入 `Route`/`Mount`
- `mcp.http_app()` 返回 Starlette 应用，可进一步包装中间件

---

## 最终架构

### 路由表

| 路径 | 方法 | 功能 | 对应后端 |
|------|------|------|---------|
| `/mcp` | POST | MCP JSON-RPC 端点 | FastMCP 内置 |
| `/api/wiki/status` | GET | Wiki 状态 | `wiki.status()` |
| `/api/wiki/search?q=&limit=` | GET | 全文搜索 | `wiki.search()` |
| `/api/wiki/page/{page_name}` | GET | 读取页面 | `wiki.read_page()` |
| `/api/wiki/page` | POST | 写入页面 | `wiki.write_page()` |
| `/api/wiki/sink/status` | GET | Sink 状态 | `wiki.sink_status()` |
| `/api/wiki/lint` | GET | 健康检查 | `wiki.lint()` |
| `/api/wiki/recommend` | GET | 推荐 | `wiki.recommend()` |
| `/api/agent/chat` | POST | Agent 聊天 | `WikiAgent.chat()` |
| `/api/agent/status` | GET | Agent 状态 | `WikiAgent.get_status()` |
| `/api/agent/tools` | GET | Agent 工具列表 | `WikiAgent.get_tools()` |
| `/api/agent/notifications` | GET | 通知列表 | `NotificationManager.list_all()` |
| `/api/agent/notifications/{id}/read` | POST | 标记已读 | `NotificationManager.mark_read()` |
| `/api/agent/dream/log` | GET | Dream 日志 | `DreamEditor.get_edit_log()` |
| `/api/agent/dream/run` | POST | 手动触发 Dream | `DreamEditor.run_dream()` |
| `/*` | GET | React 静态文件 | `StaticFiles` |

### 前端 API 端点（`api.ts` 已定义）

```typescript
// Wiki 端点
api.wiki.status()          → GET  /api/wiki/status
api.wiki.search(q, limit)  → GET  /api/wiki/search?q=&limit=
api.wiki.readPage(name)    → GET  /api/wiki/page/{name}
api.wiki.writePage(n, c)   → POST /api/wiki/page
api.wiki.sinkStatus()      → GET  /api/wiki/sink/status
api.wiki.lint()            → GET  /api/wiki/lint
api.wiki.recommend()       → GET  /api/wiki/recommend

// Agent 端点
api.agent.chat(msg)        → POST /api/agent/chat
api.agent.status()         → GET  /api/agent/status
api.agent.tools()          → GET  /api/agent/tools

// Dream 端点
api.dream.log(limit)       → GET  /api/agent/dream/log?limit=
api.dream.run()            → POST /api/agent/dream/run

// 通知端点
api.notifications.list()   → GET  /api/agent/notifications
api.notifications.markRead → POST /api/agent/notifications/{id}/read
```

---

## API 设计

### REST API 规范

- 所有 API 端点以 `/api/` 为前缀
- 请求/响应均为 JSON
- 错误响应格式：`{"error": "message", "status_code": N}`

### 请求示例

```bash
# 获取 Wiki 状态
curl http://127.0.0.1:8765/api/wiki/status

# 搜索
curl "http://127.0.0.1:8765/api/wiki/search?q=test&limit=10"

# 读取页面
curl http://127.0.0.1:8765/api/wiki/page/concepts/Risk%20Parity

# 写入页面
curl -X POST http://127.0.0.1:8765/api/wiki/page \
  -H "Content-Type: application/json" \
  -d '{"page_name": "Test Page", "content": "# Hello"}'

# Agent 聊天
curl -X POST http://127.0.0.1:8765/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我分析这个文件"}'
```

---

## 鉴权设计

### 当前实现：Bearer Token (API Key)

```python
class AuthMiddleware(BaseHTTPMiddleware):
    """Simple API Key authentication middleware.

    验证方式（优先级）:
    1. Header: Authorization: Bearer <token>
    2. Query param: ?token=<token> (fallback)

    排除路径（无需鉴权）:
    - / (首页)
    - /mcp (MCP 端点)
    - /api/health (健康检查)
    - /assets/ (静态资源)
    - /favicon.ico
    """
```

### 鉴权使用方式

```bash
# 启动带鉴权的服务器
llmwikify serve --web --auth-token mysecret123

# 请求携带 token (Header)
curl -H "Authorization: Bearer mysecret123" \
  http://127.0.0.1:8765/api/wiki/status

# 请求携带 token (Query param fallback)
curl "http://127.0.0.1:8765/api/wiki/status?token=mysecret123"

# MCP 端点不受影响
curl -X POST http://127.0.0.1:8765/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 预留扩展点

| 扩展 | 说明 | 实现位置 |
|------|------|---------|
| JWT 验证 | 支持 JWT token 验证 | `AuthMiddleware` 添加 JWT 解码逻辑 |
| OAuth2 | 对接第三方 OAuth | 新增 OAuth2 中间件 |
| Basic Auth | HTTP Basic 认证 | `AuthMiddleware` 添加 Basic 解析 |
| 多 API Key | 配置文件管理多个 Key | 将 `api_key: str` 改为 `api_keys: list[str]` |
| RBAC | 角色权限控制 | 在中间件中添加权限检查逻辑 |
| 速率限制 | 请求频率限制 | 新增 RateLimitMiddleware |

### 前端适配

```typescript
// api.ts
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (API_TOKEN) {
    headers['Authorization'] = `Bearer ${API_TOKEN}`;
  }
  const res = await fetch(`${API_BASE}${endpoint}`, { headers, ...options });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llmwikify/mcp/server.py` | **修改** | 新增 `_register_rest_routes()`, `_mount_webui()`, `_register_agent_tools()`, `create_unified_server()`, `AuthMiddleware` |
| `src/llmwikify/web/server.py` | **重写** | 薄封装，复用 `mcp/server.py` 的统一创建逻辑，保留 `--wiki-root` 参数 |
| `src/llmwikify/cli/commands.py` | **修改** | `serve` 命令简化为单进程，新增 `--auth-token`、`--agent` 参数 |
| `src/llmwikify/agent/notifications.py` | **新建** | 内存通知队列 `NotificationManager` |
| `src/llmwikify/agent/wiki_agent.py` | **修改** | 集成 `NotificationManager`，`_on_notify` 回调写入通知 |

---

## 启动方式

### CLI 命令

| 场景 | 命令 | 说明 |
|------|------|------|
| 开发模式 | `python -m llmwikify.web.server --wiki-root ~/wiki --port 8765` | 独立入口，指定 wiki 路径 |
| 开发 + Agent | `python -m llmwikify.web.server --wiki-root ~/wiki --port 8765 --agent` | 启用 Agent |
| 开发 + 鉴权 | `python -m llmwikify.web.server --wiki-root ~/wiki --port 8765 --api-key mysecret` | API Key 鉴权 |
| CLI 推荐 | `llmwikify serve --web --agent --port 8765` | 自动检测当前目录 |
| CLI + 鉴权 | `llmwikify serve --web --agent --auth-token mysecret` | API Key 鉴权 |
| 仅 MCP | `llmwikify mcp --transport http --port 8765` | 旧行为不变 |

### 访问地址

| 路径 | 内容 |
|------|------|
| `http://127.0.0.1:8765/` | React WebUI |
| `http://127.0.0.1:8765/mcp` | MCP JSON-RPC 端点 |
| `http://127.0.0.1:8765/api/wiki/status` | REST API |

---

## 实施步骤

### Step 1: 新建 `src/llmwikify/agent/notifications.py`

新建内存通知队列模块，提供：
- `add()` — 添加通知
- `list_all()` / `list_unread()` — 获取通知列表
- `mark_read()` / `mark_all_read()` — 标记已读
- `unread_count()` — 未读计数
- 自动限制最大容量（默认 100 条）

### Step 2: 修改 `src/llmwikify/agent/wiki_agent.py`

在 `WikiAgent.__init__` 中：
- 实例化 `NotificationManager`
- 注册 `_on_notify` 回调，将 Agent 事件写入通知队列
- 事件类型映射：`task_completed→success`, `task_failed→error`, `new_files_detected→info`, `dream_completed→success`

### Step 3: 修改 `src/llmwikify/mcp/server.py`

#### 3a. 新增 `AuthMiddleware`

Bearer Token 认证中间件，支持 Header 和 Query param 两种方式，可配置排除路径。

#### 3b. 新增 `_register_rest_routes()`

注册所有 REST API 路由到 FastMCP，Wiki 端点直接调用 `wiki.*` 方法，Agent 端点（当 agent 启用时）调用 `agent.*` 方法。

#### 3c. 新增 `_register_agent_tools()`

注册 Agent MCP 工具供外部 MCP Client（如 Claude Desktop）调用：
- `agent_chat` — 与 Agent 对话
- `agent_status` — 查看 Agent 状态
- `agent_dream_run` — 手动触发 Dream
- `agent_dream_log` — 查看 Dream 日志
- `agent_notifications` — 获取通知

#### 3d. 新增 `_mount_webui()`

挂载 React 静态文件，多级 fallback：
1. `web/webui/dist/`（安装模式）
2. `../../web/webui/dist/`（开发模式）
3. `web/static/`（旧静态目录，兜底）

#### 3e. 新增 `create_unified_server()`

统一服务器创建函数，接受 `wiki`, `agent`, `api_key` 参数，返回 Starlette 应用。

### Step 4: 重写 `src/llmwikify/web/server.py`

保留为独立入口，参数：
- `--wiki-root`（必需）— Wiki 根目录路径
- `--host`（默认 `127.0.0.1`）— 绑定地址
- `--port`（默认 `8765`）— 端口号
- `--agent` — 启用 Agent 功能
- `--api-key` — API Key 鉴权

内部调用 `mcp/server.py` 的 `create_unified_server()` 创建应用。

### Step 5: 修改 `src/llmwikify/cli/commands.py`

简化 `serve` 命令：
- 新增 `--auth-token` 参数
- 新增 `--agent` 参数
- 移除双线程启动逻辑（不再需要后台 MCP 线程 + 前台 Web 线程）
- `--web` 模式下调用 `create_unified_server()` 单进程启动
- 非 `--web` 模式保持旧行为（仅 MCP）

### Step 6: 前端适配

修改 `web/webui/src/api.ts`：
- 读取 `VITE_API_TOKEN` 环境变量
- 在所有请求中自动添加 `Authorization: Bearer` Header

---

## 向后兼容

| 旧用法 | 新用法 | 状态 |
|--------|--------|------|
| `llmwikify mcp` | `llmwikify mcp` | ✅ 不变 |
| `llmwikify serve --web` | `llmwikify serve --web` | ✅ 简化为单进程 |
| `python -m llmwikify.web.server` | `python -m llmwikify.web.server --wiki-root` | ✅ 保留，参数略调 |

---

## 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-20 | 初始版本，记录单 Server 架构设计 |
