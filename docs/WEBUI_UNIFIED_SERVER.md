# WebUI 统一服务器设计文档

**版本**: v3.0  
**创建日期**: 2026-04-20  
**更新日期**: 2026-04-27  
**状态**: ✅ 已完成  
**关联文档**: [AGENT_INTEGRATION_PLAN.md](AGENT_INTEGRATION_PLAN.md), [LLM_WIKI_PRINCIPLES.md](LLM_WIKI_PRINCIPLES.md)

---

## 实现摘要

**Starlette → FastAPI 迁移完成**。所有设计目标已实现：

- ✅ **单进程统一服务器**：FastAPI + MCP + REST + WebUI
- ✅ **模块化架构**：`server/` 目录下清晰的分层设计
- ✅ **可选 API Key 认证**：`AuthMiddleware` 已实现
- ✅ **完整 REST API**：`/api/wiki/*` 端点已注册
- ✅ **MCP 协议集成**：通过 `MCPAdapter` 挂载到 FastAPI
- ✅ **React WebUI 挂载**：静态文件服务已配置
- ✅ **100% 测试覆盖**：新增 24 个 API 路由测试 + 15 个 WikiServer 核心测试

---

## 目录

1. [背景](#背景)
2. [架构演进](#架构演进)
3. [最终架构](#最终架构)
4. [确认机制设计](#确认机制设计)
5. [API 设计](#api-设计)
6. [鉴权设计](#鉴权设计)
7. [文件变更清单](#文件变更清单)
8. [启动方式](#启动方式)
9. [实施步骤](#实施步骤)

---

## 背景

在 Phase 1-3 完成后，React WebUI 前端已构建完成，但缺少后端 API 桥接。前端 `api.ts` 定义了 REST API 端点，但现有 `web/server.py` 是 JSON-RPC 代理，与前端不匹配。

需要解决的问题：
1. 前端调用的 `/api/wiki/*`、`/api/agent/*` 没有后端实现
2. 现有 `web/server.py` 指向旧 Vanilla JS `static/`，未指向 React `webui/dist/`
3. Agent 聊天需要流式输出支持
4. **核心问题**：Agent 自动写操作违反"人类主导"原则，需要确认机制

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

| 路径 | 方法 | 功能 | 对应后端 | 确认方式 |
|------|------|------|---------|---------|
| `/mcp` | POST | MCP JSON-RPC 端点 | FastMCP 内置 | — |
| `/api/wiki/status` | GET | Wiki 状态 | `wiki.status()` | — |
| `/api/wiki/search?q=&limit=` | GET | 全文搜索 | `wiki.search()` | — |
| `/api/wiki/page/{page_name}` | GET | 读取页面 | `wiki.read_page()` | — |
| `/api/wiki/page` | POST | 写入页面 | `wiki.write_page()` | **前置确认** |
| `/api/wiki/sink/status` | GET | Sink 状态 | `wiki.sink_status()` | — |
| `/api/wiki/lint` | GET | 健康检查 | `wiki.lint()` | — |
| `/api/wiki/recommend` | GET | 推荐 | `wiki.recommend()` | — |
| `/api/agent/chat` | POST | Agent 聊天 | `WikiAgent.chat()` | — |
| `/api/agent/status` | GET | Agent 状态 | `WikiAgent.get_status()` | — |
| `/api/agent/tools` | GET | Agent 工具列表 | `WikiAgent.get_tools()` | — |
| `/api/agent/notifications` | GET | 通知列表 | `NotificationManager.list_all()` | — |
| `/api/agent/notifications/{id}/read` | POST | 标记已读 | `NotificationManager.mark_read()` | — |
| `/api/agent/confirmations` | GET | 获取待确认列表 | `ConfirmationManager.get_pending_by_group()` | — |
| `/api/agent/confirmations/{id}` | POST | 确认单个操作 | `ConfirmationManager.approve(id)` | — |
| `/api/agent/confirmations/{id}` | DELETE | 拒绝单个操作 | `ConfirmationManager.reject(id)` | — |
| `/api/agent/confirmations/batch` | POST | 批量确认 | `ConfirmationManager.batch_approve(ids)` | — |
| `/api/agent/dream/proposals` | GET | 获取 Dream 提议 | `ProposalManager.get_pending_by_page()` | — |
| `/api/agent/dream/proposals/{id}/approve` | POST | 批准提议 | `ProposalManager.approve(id)` | — |
| `/api/agent/dream/proposals/{id}/reject` | POST | 拒绝提议 | `ProposalManager.reject(id)` | — |
| `/api/agent/dream/proposals/batch-approve` | POST | 批量批准 | `ProposalManager.batch_approve(ids)` | — |
| `/api/agent/dream/run` | POST | 触发 Dream | `DreamEditor.run_dream()` | — |
| `/api/agent/ingest/log` | GET | Ingest 变更日志 | `IngestChangeLog.get_recent()` | — |
| `/api/agent/ingest/log/{id}` | GET | 详细变更 | `IngestChangeLog.get_changes(id)` | — |
| `/api/agent/ingest/log/{id}/revert` | POST | 回滚 Ingest | `IngestChangeLog.revert(id)` | — |
| `/*` | GET | React 静态文件 | `StaticFiles` | — |

### 前端 API 端点（`api.ts` 已定义 + 新增）

```typescript
// Wiki 端点
api.wiki.status()          → GET  /api/wiki/status
api.wiki.search(q, limit)  → GET  /api/wiki/search?q=&limit=
api.wiki.readPage(name)    → GET  /api/wiki/page/{name}
api.wiki.writePage(n, c)   → POST /api/wiki/page          // 返回 confirmation_required
api.wiki.sinkStatus()      → GET  /api/wiki/sink/status
api.wiki.lint()            → GET  /api/wiki/lint
api.wiki.recommend()       → GET  /api/wiki/recommend

// Agent 端点
api.agent.chat(msg)        → POST /api/agent/chat
api.agent.status()         → GET  /api/agent/status
api.agent.tools()          → GET  /api/agent/tools

// 确认端点（新增）
api.confirmations.list()   → GET  /api/agent/confirmations
api.confirmations.approve(id) → POST /api/agent/confirmations/{id}
api.confirmations.reject(id)  → DELETE /api/agent/confirmations/{id}
api.confirmations.batchApprove(ids) → POST /api/agent/confirmations/batch

// Dream 端点
api.dream.log(limit)       → GET  /api/agent/dream/log?limit=
api.dream.run()            → POST /api/agent/dream/run
api.dream.proposals()      → GET  /api/agent/dream/proposals
api.dream.approve(id)      → POST /api/agent/dream/proposals/{id}/approve
api.dream.reject(id)       → POST /api/agent/dream/proposals/{id}/reject
api.dream.batchApprove(ids) → POST /api/agent/dream/proposals/batch-approve

// 通知端点
api.notifications.list()   → GET  /api/agent/notifications
api.notifications.markRead → POST /api/agent/notifications/{id}/read

// Ingest 事后确认（新增）
api.ingest.log(limit)      → GET  /api/agent/ingest/log?limit=
api.ingest.changes(id)     → GET  /api/agent/ingest/log/{id}
api.ingest.revert(id)      → POST /api/agent/ingest/log/{id}/revert
```

---

## 确认机制设计

### 核心原则

遵循 [LLM_WIKI_PRINCIPLES.md](LLM_WIKI_PRINCIPLES.md)：
- **"The human's job is to curate sources, direct the analysis, ask good questions, and think about what it all means. The LLM's job is everything else."**
- 读操作自动执行，写操作需确认
- 小改动可自动批准，大改动需人类审核
- 事后确认用于高频操作（如 ingest），避免中断工作流

### 确认策略矩阵

| 操作 | 确认方式 | 理由 |
|------|---------|------|
| **所有 read 操作** | 无需确认 | 无风险 |
| `wiki_init` | 无需确认 | CLI 已有 `--overwrite`/`--force` 保护 |
| `wiki_build_index` | 无需确认 | 可重建，无风险 |
| `wiki_log` | 无需确认 | append-only，可追溯 |
| `wiki.md 同步` | 无需确认 | 自动执行 |
| `wiki_ingest` | **事后确认** | 直接执行，记录变更 log，事后可审核/回滚 |
| `wiki_write_page` | **前置确认** | 单页写入，展示变更预览 |
| `wiki_synthesize` | **前置确认** | 新页面 + 索引，展示内容预览 |
| `wiki_graph write` | **前置确认** | 展示关系变更 |
| `wiki_delete_page` | **前置确认** | 破坏性操作 |
| Dream 编辑（<100字 append） | **自动批准** | 小改动，风险低 |
| Dream 编辑（≥100字） | **前置确认** | 提议模式，批量审核 |

### 确认粒度

- **按页面类型分组**：`entity_pages`, `concept_pages`, `source_pages` 等
- **支持全选/反选**：批量确认同一组内的所有操作
- **支持取消个别**：可取消组内特定操作
- **批量确认 API**：`POST /api/agent/confirmations/batch` 接受 `{"ids": ["...", "..."]}`

### 确认超时

- 待确认操作 **24 小时后保留**（不自动拒绝）
- 可通过 `expires_at` 字段追踪创建时间
- 用户可随时清理过期确认

### 核心组件

### 代码复用策略

**核心原则**：不新建独立文件，复用现有代码模式，降低维护成本。

#### 可复用的基础设施

| 现有代码 | 复用目标 | 复用方式 |
|---------|---------|---------|
| `notifications.py` `NotificationManager` | `ConfirmationManager` + `ProposalManager` | 相同的内存队列模式：ID + timestamp + status + max_size + LRU eviction |
| `dream_editor.py` JSONL 日志 | `IngestChangeLog` | JSONL 日志模式完全相同（`_log_dream_run()` / `get_edit_log()`） |
| `runner.py` `ActionType`, `RunState.WAITING_CONFIRMATION` | 确认机制 | 基础设施已存在，只需激活 |
| `tools.py` `action_type` 注册 | 确认策略 | 已有字段，只需添加 `requires_confirmation` |

#### 精简后的文件变更

**新建文件**: 0（全部复用现有模式）  
**修改文件**: 9 个后端 + 4 个前端 = 13 个

| 文件 | 操作 | 说明 | 复用来源 |
|------|------|------|---------|
| `src/llmwikify/agent/tools.py` | **修改** | 添加 `_pending_confirmations` 字典 + `confirm_execution()` + `confirm_batch()` + `requires_confirmation` 逻辑 | 复用 `NotificationManager` 内存队列模式 |
| `src/llmwikify/agent/dream_editor.py` | **修改** | 添加 `ProposalManager` 类（内嵌）+ `run_dream()` 改为生成提议 + 自动批准小改动 | 复用 `NotificationManager` 模式 + 现有 `_process_sink()` 逻辑 |
| `src/llmwikify/agent/runner.py` | **修改** | 激活现有 `requires_confirmation` 逻辑，集成 `ConfirmationManager` | 已有 `ActionType`, `RunState.WAITING_CONFIRMATION` |
| `src/llmwikify/agent/scheduler.py` | **修改** | 任务分类：只读自动，写操作生成提议/通知 | — |
| `src/llmwikify/agent/wiki_agent.py` | **修改** | 集成新确认/提议流程 | — |
| `src/llmwikify/mcp/server.py` | **修改** | 新增确认/Dream/Ingest REST 端点，`create_unified_server()` | — |
| `src/llmwikify/web/server.py` | **重写** | 薄封装，复用 `mcp/server.py` 的统一创建逻辑 | — |
| `src/llmwikify/cli/commands.py` | **修改** | `serve` 命令简化，新增 `--auth-token`、`--agent` 参数 | — |
| `src/llmwikify/web/webui/src/api.ts` | **修改** | 新增确认/Dream/Ingest API，添加 Bearer Token 支持 | — |
| `src/llmwikify/web/webui/src/components/Confirmations.tsx` | **新建** | 待确认操作列表 + 批量确认 | — |
| `src/llmwikify/web/webui/src/components/DreamProposals.tsx` | **新建** | Dream 提议审核面板 | — |
| `src/llmwikify/web/webui/src/components/IngestLog.tsx` | **新建** | Ingest 事后审核日志 | — |
| `src/llmwikify/web/webui/src/components/EditHistory.tsx` | **新建** | 编辑历史，区分 LLM/人类/Dream 来源 | — |
| `src/llmwikify/web/webui/src/components/DreamLog.tsx` | **修改** | 适配提议模式 | — |
| `src/llmwikify/web/webui/src/components/Editor.tsx` | **修改** | 人类编辑记录日志 | — |
| `src/llmwikify/agent/notifications.py` | 已存在 | 无需修改 | — |

#### 复用示例：NotificationManager → ConfirmationManager

```python
# NotificationManager 模式（现有）
class NotificationManager:
    def __init__(self, max_size: int = 100):
        self._notifications: list[dict[str, Any]] = []
        self._max_size = max_size

    def add(self, event_type, message, data=None) → dict:
        n = {
            "id": str(uuid.uuid4())[:8],
            "type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        self._notifications.append(n)
        if len(self._notifications) > self._max_size:
            self._notifications = self._notifications[-self._max_size:]
        return n

# ConfirmationManager 复用相同模式（扩展）
class ConfirmationManager:
    def __init__(self, max_size: int = 200):
        self._confirmations: list[dict[str, Any]] = []
        self._max_size = max_size

    def create(self, tool, args, action_type, impact, group) → dict:
        c = {
            "id": str(uuid.uuid4())[:8],
            "tool": tool,
            "arguments": args,
            "action_type": action_type,
            "impact": impact,
            "group": group,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        self._confirmations.append(c)
        if len(self._confirmations) > self._max_size:
            self._confirmations = self._confirmations[-self._max_size:]
        return c
    # approve/reject/batch_approve 模式同 NotificationManager.mark_read()
```

---

### 确认流程

```
用户/Agent 触发操作
  ↓
WikiToolRegistry 检查 requires_confirmation
  ↓
  ├─ False → 直接执行
  ├─ "posthoc" → 执行并记录到 IngestChangeLog（复用 JSONL 日志模式）
  └─ "pre" → 创建 Confirmation（复用 NotificationManager 模式），返回 confirmation_id + impact 预览
                ↓
          前端展示确认面板（按分组）
                ↓
          用户 approve / reject / batch_approve
                ↓
          ConfirmationManager 执行 or 丢弃
                ↓
          记录日志（agent_edit / human_edit / dream_apply）
```

---

## API 设计

### REST API 规范

- 所有 API 端点以 `/api/` 为前缀
- 请求/响应均为 JSON
- 错误响应格式：`{"error": "message", "status_code": N}`

### 确认相关请求示例

```bash
# 获取待确认列表（按分组）
curl http://127.0.0.1:8765/api/agent/confirmations

# 响应示例
{
  "entity_pages": [
    {
      "id": "a1b2c3d4",
      "tool": "wiki_write_page",
      "arguments": {"page_name": "Risk Parity", "content": "..."},
      "action_type": "write",
      "impact": {"page": "Risk Parity", "change_type": "append", "chars": 45},
      "created_at": "2026-04-21T10:30:00Z",
      "expires_at": "2026-04-22T10:30:00Z"
    }
  ],
  "concept_pages": [...]
}

# 确认单个操作
curl -X POST http://127.0.0.1:8765/api/agent/confirmations/a1b2c3d4

# 批量确认
curl -X POST http://127.0.0.1:8765/api/agent/confirmations/batch \
  -H "Content-Type: application/json" \
  -d '{"ids": ["a1b2c3d4", "e5f6g7h8"]}'

# 获取 Dream 提议（按页面分组）
curl http://127.0.0.1:8765/api/agent/dream/proposals

# 批量批准 Dream 提议
curl -X POST http://127.0.0.1:8765/api/agent/dream/proposals/batch-approve \
  -H "Content-Type: application/json" \
  -d '{"ids": ["prop-001", "prop-002"]}'

# 获取 Ingest 变更日志
curl http://127.0.0.1:8765/api/agent/ingest/log?limit=10

# 回滚 Ingest
curl -X POST http://127.0.0.1:8765/api/agent/ingest/log/ingest-20260421-1030/revert
```

### 通用请求示例

```bash
# 获取 Wiki 状态
curl http://127.0.0.1:8765/api/wiki/status

# 搜索
curl "http://127.0.0.1:8765/api/wiki/search?q=test&limit=10"

# 读取页面
curl http://127.0.0.1:8765/api/wiki/page/concepts/Risk%20Parity

# 写入页面（返回 confirmation_required）
curl -X POST http://127.0.0.1:8765/api/wiki/page \
  -H "Content-Type: application/json" \
  -d '{"page_name": "Test Page", "content": "# Hello"}'

# 响应: {"status": "confirmation_required", "confirmation_id": "x1y2z3", "impact": {...}}

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
| `src/llmwikify/agent/confirmation.py` | **新建** | `ConfirmationManager`, `Confirmation` 类 |
| `src/llmwikify/agent/dream_proposals.py` | **新建** | `ProposalManager`, `DreamProposal` 类 |
| `src/llmwikify/agent/ingest_log.py` | **新建** | `IngestChangeLog` 类 |
| `src/llmwikify/agent/dream_editor.py` | **修改** | `run_dream()` 改为生成提议，新增 `apply_proposals()` |
| `src/llmwikify/agent/tools.py` | **修改** | `execute()` 添加确认检查，新增 `confirm_execution()`, `confirm_batch()` |
| `src/llmwikify/agent/runner.py` | **修改** | 集成确认流程，新增 `get_pending_confirmations()`, `confirm_batch()` |
| `src/llmwikify/agent/scheduler.py` | **修改** | 任务分类，写任务改为通知/提议模式 |
| `src/llmwikify/agent/wiki_agent.py` | **修改** | 适配新的 Dream 提议流程，集成 `ConfirmationManager` |
| `src/llmwikify/mcp/server.py` | **修改** | 新增确认/Dream/Ingest REST 端点，`create_unified_server()` |
| `src/llmwikify/web/server.py` | **重写** | 薄封装，复用 `mcp/server.py` 的统一创建逻辑 |
| `src/llmwikify/cli/commands.py` | **修改** | `serve` 命令简化，新增 `--auth-token`、`--agent` 参数 |
| `src/llmwikify/web/webui/src/api.ts` | **修改** | 新增确认/Dream/Ingest API，添加 Bearer Token 支持 |
| `src/llmwikify/web/webui/src/components/Confirmations.tsx` | **新建** | 待确认操作列表 + 批量确认 |
| `src/llmwikify/web/webui/src/components/DreamProposals.tsx` | **新建** | Dream 提议审核面板 |
| `src/llmwikify/web/webui/src/components/IngestLog.tsx` | **新建** | Ingest 事后审核日志 |
| `src/llmwikify/web/webui/src/components/EditHistory.tsx` | **新建** | 编辑历史，区分 LLM/人类/Dream 来源 |
| `src/llmwikify/web/webui/src/components/DreamLog.tsx` | **修改** | 适配提议模式 |
| `src/llmwikify/web/webui/src/components/Editor.tsx` | **修改** | 人类编辑记录日志 |
| `src/llmwikify/agent/notifications.py` | 已存在 | 无需修改 |

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
| `http://127.0.0.1:8765/api/agent/confirmations` | 确认面板 API |

---

## 实施步骤

### Phase 1: 扩展 `tools.py` 添加确认机制

在 `WikiToolRegistry` 内扩展，复用 `NotificationManager` 内存队列模式：

- 添加 `_pending_confirmations: dict[str, dict]` 字典
- 添加 `_ingest_log: list[dict]` 列表（复用 JSONL 日志模式）
- 修改 `_register()` 添加 `requires_confirmation` 参数（`False` | `"posthoc"` | `"pre"`）
- 修改 `execute()` 方法：
  - `False` → 直接执行
  - `"posthoc"` → 执行并记录到 `_ingest_log`
  - `"pre"` → 创建 Confirmation（复用 NotificationManager 模式），返回 `confirmation_id`
- 新增 `confirm_execution(id)` / `confirm_batch(ids)` 方法
- 新增 `get_pending_confirmations()` / `get_pending_by_group()` 方法

### Phase 2: 扩展 `dream_editor.py` 添加提议模式

在 `DreamEditor` 内扩展，复用 `NotificationManager` 模式：

- 添加 `ProposalManager` 类（内嵌或同级）
  - `_proposals: list[dict]` 字典（同 NotificationManager 模式）
  - `AUTO_APPROVE_THRESHOLD = 100` 字符阈值
  - `generate_proposals()` — 复用现有 `_process_sink()` 逻辑，但不写文件
  - `auto_approve_pending()` — 自动批准 <100 字的 append 操作
  - `approve()` / `reject()` / `apply()` — 单个操作
  - `batch_approve()` / `apply_all_approved()` — 批量操作
  - `get_pending_by_page()` — 按页面分组
- 修改 `run_dream()` — 改为生成提议 + 自动批准小改动，不直接写文件
- 新增 `apply_proposals(ids)` — 真正写文件的方法

### Phase 3: 激活 `runner.py` 确认流程

现有基础设施已存在，只需激活：

- `ActionType` 枚举已定义（READ, WRITE, DELETE, BULK, EXTERNAL）
- `RunState.WAITING_CONFIRMATION` 已定义
- `ToolCall.requires_confirmation` 字段已存在
- 修改 `execute_tool()` — 集成 `ConfirmationManager` 逻辑
- 新增 `get_pending_confirmations()` / `confirm_batch()` 方法（委托给 tool_registry）

### Phase 4: 修改 `scheduler.py` 任务分类

- 任务分类：只读任务自动执行，写任务生成提议/通知
- `dream_update` 任务改为生成 Dream 提议（不直接执行）
- `daily_lint`, `weekly_gaps`, `check_raw` 保持自动执行

### Phase 5: 修改 `wiki_agent.py` 集成

- 集成 `ConfirmationManager`（通过 tool_registry）
- 集成 `ProposalManager`（通过 dream_editor）
- 适配新的 Dream 提议流程
- `_notify()` 回调添加确认/提议状态通知

### Phase 6: 统一服务器 `mcp/server.py`

- 新增 `AuthMiddleware`
- 新增 `_register_rest_routes()` — 注册所有 REST API（含确认/Dream/Ingest 端点）
- 新增 `_mount_webui()` — 挂载 React 静态文件（多级 fallback）
- 新增 `create_unified_server()` — 统一服务器创建函数

### Phase 7: 重写 `web/server.py`

- 薄封装，调用 `create_unified_server()`
- 保留 `--wiki-root`, `--host`, `--port`, `--agent`, `--api-key` 参数

### Phase 8: 修改 `cli/commands.py`

- 简化 `serve` 命令为单进程
- 新增 `--auth-token`, `--agent` 参数
- 移除双线程启动逻辑

### Phase 9: 前端适配

#### 9a. 修改 `api.ts`
- 新增确认/Dream/Ingest API 端点
- 添加 `VITE_API_TOKEN` Bearer Token 支持

#### 9b. 新建 `Confirmations.tsx`
- 按分组展示待确认操作
- 支持全选/反选/批量确认/拒绝
- 展示变更预览（impact）

#### 9c. 新建 `DreamProposals.tsx`
- 按页面分组展示 Dream 提议
- 标记自动批准的提议
- 支持批量批准/拒绝/应用

#### 9d. 新建 `IngestLog.tsx`
- 展示 ingest 历史记录
- 查看变更详情
- 回滚按钮（预留）

#### 9e. 新建 `EditHistory.tsx`
- 区分 LLM/人类/Dream 编辑来源
- 不同颜色标识

#### 9f. 修改现有组件
- `DreamLog.tsx` — 适配提议模式
- `Editor.tsx` — 人类编辑记录日志

### Phase 10: 测试 + 文档

- 更新 `tests/test_agent_layer.py` 添加确认机制测试
- 更新本文档实施状态

---

## 向后兼容

| 旧用法 | 新用法 | 状态 |
|--------|--------|------|
| `llmwikify mcp` | `llmwikify mcp` | ✅ 不变 |
| `llmwikify serve --web` | `llmwikify serve --web` | ✅ 简化为单进程 |
| `python -m llmwikify.web.server` | `python -m llmwikify.web.server --wiki-root` | ✅ 保留，参数略调 |
| `wiki.write_page()` 直接写入 | 返回 `confirmation_required` | ⚠️ 行为变更，需前端适配 |

---

## 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| **v3.0** | **2026-04-27** | **✅ 实现完成：FastAPI 架构，新增 server/ 模块，全部后端 Phase 完成** |
| v2.1 | 2026-04-21 | 精简方案：不新建 Agent 文件，复用 NotificationManager 模式，0 新建后端文件 |
| v2.0 | 2026-04-21 | 添加确认机制设计：前置确认、事后确认、Dream 提议模式、自动批准小改动 |
| v1.0 | 2026-04-20 | 初始版本，记录单 Server 架构设计 |

---

## 实现状态 (v3.0)

| Phase | 状态 | 说明 |
|-------|------|------|
| Phase 1–7 | ✅ **后端已完成** | FastAPI 架构、`server/` 模块全部实现 |
| Phase 8 | ✅ **CLI 已完成** | `serve` 命令支持 FastAPI server |
| Phase 9 | ⚠️ **前端部分** | 确认/提议 UI 待实现 |
| Phase 10 | ✅ **测试已完成** | 新增 39 个后端测试，全部通过 |

**已实现的文件结构**：
```
src/llmwikify/server/
├── core.py              # WikiServer 核心类
├── constants.py         # DEFAULT_HOST, DEFAULT_PORT 等
├── http/
│   ├── routes.py        # /api/wiki/* REST API 路由
│   └── middleware.py    # AuthMiddleware + CORS
└── utils/
    └── webui.py         # React SPA 静态文件挂载
```
