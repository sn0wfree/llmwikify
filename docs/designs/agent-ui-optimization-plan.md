# Agent UI 优化讨论记录

> 创建时间：2025-05-26
> 最后更新：2025-05-26（Phase 1-5 全部完成）
> 状态：Phase 5 完成，所有优化迭代完毕

---

## 一、初始评估（第一轮）

### 当时判断

Agent UI 缺少：
- Toast 反馈系统
- WikiSelector 多 wiki 上下文切换
- 侧边栏 Pending 数量徽章
- Markdown 渲染
- 键盘快捷键
- 空状态美化

结论：功能完整，体验残缺。只加 Toast 即可。

### Less is More 原则

> "不是把所有功能做到完美——而是只做必要的功能，必要的功能要做到位。"

---

## 二、重新评估（发现关键 Bug）

### 发现：Chat 功能完全损坏

前端 `api.agent.chat()` 期望同步 JSON：
```typescript
chat: (message, sessionId?, wikiId?) =>
  request<{ response: string; actions: unknown[] }>('/agent/chat', {...}),
```

后端 `/agent/chat` 返回 SSE 流：
```
event: message
data: {"type": "message_delta", "content": "Hello"}
event: message
data: {"type": "done", "final_response": "...", "actions": []}
```

前端对 SSE stream 调用 `.json()` 会失败或解析出乱码。

### 架构一致性问题

| 层级 | 期望 | 实际 |
|------|------|------|
| 后端 `/agent/chat` | SSE 流 | ✅ EventSourceResponse |
| 后端 `service.chat()` | AsyncIterator | ✅ 正确 yield 事件 |
| 后端 `stream_chat()` | SSE 解析 | ✅ 正确解析 |
| **前端 api.ts** | JSON 响应 | ❌ 期望同步 JSON |
| **前端 AgentChat.tsx** | 完整响应 | ❌ `await result.response` |

### 各视图状态重新评估

| 视图 | 功能 | 结论 |
|------|------|------|
| **AgentChat** | ❌ SSE 不兼容，无法工作 | **P0 修复** |
| Confirmations | ✅ 功能 OK，无 Toast | P2 加 Toast |
| DreamProposals | ✅ 功能 OK，无 Toast | P2 加 Toast |
| TaskMonitor | ✅ 能用 | 不动 |
| DreamLog | ✅ 能用 | 不动 |
| IngestLog | ✅ 能用 | 不动 |
| EditHistory | ✅ 能用 | 不动 |

---

## 三、相关设计文档

| 文档 | 内容 |
|------|------|
| `docs/agent-framework-design.md` | 完整架构设计，含 Chat SSE、Quick Research、评分系统 |
| `docs/agent-backend-implementation-plan.md` | 后端实现计划，含 DB Schema、per-wiki 缓存 |

---

## 四、修正后的最小迭代计划

### Phase 1：修复 Chat SSE（唯一 P0）

**目标**：让 Chat 功能可工作

| 文件 | 改动 |
|------|------|
| `api.ts` | 新增 `chatStream()` 使用 `fetch` + `ReadableStream` 消费 SSE |
| `AgentChat.tsx` | 重构 `sendMessage()` 流式消费，逐字渲染 `message_delta` |
| `Toast.tsx` + `hooks/useToast.ts` | 从 webui 复制，Chat 错误处理需要 |
| `main.tsx` | 包裹 `<ToastProvider>` |

**验收标准**：
- 发送消息后，助手回复**流式逐字显示**
- 工具调用（wiki_search 等）有卡片展示
- 网络错误时右下角 Toast 提示

### Phase 2：Confirmations/Proposals 操作反馈 ✅ 已完成

| 视图 | 改动 |
|------|------|
| Confirmations.tsx | ✅ Toast on approve/reject individual and batch, actionLoading state |
| DreamProposals.tsx | ✅ Toast on approve/apply, "Apply All Approved" now shows confirmation dialog |

### Phase 3：WikiSelector（多 wiki 环境需要）✅ 已完成

| 文件 | 改动 |
|------|------|
| `agentWikiStore.ts` | ✅ Zustand store，`WikiInfo` 接口，`loadWikis()`, `switchWiki()` |
| `WikiSelector.tsx` | ✅ 从 webui 简化复制，支持单 wiki 只读 / 多 wiki 下拉切换 |
| `App.tsx` | ✅ 渲染 WikiSelector，`loadWikis()` on mount |
| `AgentChat.tsx` | ✅ `chatStream()` 传入 `currentWikiId` |
| `package.json` | ✅ 添加 `zustand` 依赖 |

### Phase 4：Sidebar 增强 ✅ 已完成

| 改动 | 说明 |
|------|------|
| Badge 徽章 | NavButton 显示红色徽章，confirmations/proposals 有 pending 数量 |
| 活跃指示器 | 左侧 `w-0.5` 蓝色竖条 |
| 自动刷新 | 每 30s 轮询 `/agent/status` 更新 badge 数量 |

### Phase 5：空状态 + 视觉统一 ✅ 已完成

| 改动 | 说明 |
|------|------|
| `StateViews.tsx` | 新增 `EmptyState` + `LoadingState` 组件 |
| 所有 7 个视图 | 统一使用 EmptyState，每个有独特图标/标题/描述 |
| `index.css` | 添加 `:focus-visible` 全局样式（键盘导航可访问性） |

---

## 五、Less is More 核心原则（修订版）

### 原表述（过于乐观）

> "只需要加一样东西：Toast 系统"

### 修订后表述

**Agent UI 当前真正的问题是 Chat 完全不可用**，不是体验问题，是功能问题。

核心问题只有一个：**前端 SSE 消费能力缺失**。解决这个问题后，Agent UI 才能从"不能用"升到"能用"。

### Phase 触发条件

| 用户反馈 | 才做 |
|---------|------|
| "Chat 消息格式太丑了" | Phase 3 加 react-markdown |
| "我在多 wiki 环境分不清在哪个 wiki" | Phase 4 加 WikiSelector |
| "dream 怎么手动跑" | TaskMonitor 加 Run 按钮 |
| "审批操作后不知道成功没有" | Phase 2 加 Toast |
| "空状态就一行文字看不懂" | Phase 5 加 EmptyState |

---

## 六、架构设计参考（来自 docs/）

### Chat SSE 事件类型

```typescript
ChatStreamEvent = (
  | { type: "message_delta", content: string }
  | { type: "tool_call_start", tool: string, args: dict }
  | { type: "tool_call_end", tool: string, result: dict }
  | { type: "tool_call_error", tool: string, error: string }
  | { type: "done", final_response: string, actions: list }
  | { type: "confirmation_required", confirmation_id: string, details: dict }
)
```

### DreamProposals 状态机

```
pending → approved → applied
    └→ rejected
    └→ auto_approved → applied
```

### Per-wiki 架构（service.py）

```
AgentService
├── _dream_editors: dict[wiki_id, DreamEditor]
├── _notification_managers: dict[wiki_id, NotificationManager]
├── _schedulers: dict[wiki_id, WikiScheduler]
└── _tool_registries: dict[wiki_id, WikiToolRegistry]
```

---

## 七、已确认的技术决策

| 决策 | 选择 |
|------|------|
| SSE 传输 | WebSocket 后续扩展，先用 SSE |
| 前端依赖 | 零新依赖，原生 `fetch` + `ReadableStream` |
| Toast 共享 | 方案 A（复制到 webui-agent），暂不建共享包 |
| WikiSelector | 确认需要后（多 wiki 用户）再加入 |

---

## 八、文件变更记录

### 已完成

| 提交 | 内容 |
|------|-------|
| `3f4dcce` | fix(agent): pass wiki_root to load_config in _get_llm |
| `95f6c80` | feat(agent-ui): add Toast system and fix SSE chat streaming |
| `6c7b146` | feat(agent-ui): add Toast feedback to Confirmations and DreamProposals |
| `9d311a5` | feat(agent-ui): add WikiSelector and agentWikiStore for multi-wiki support |
| `f96594f` | feat(agent-ui): add sidebar badges and active indicator |
| `8954b7f` | feat(agent-ui): add EmptyState component and unify all empty/loading states |

### Phase 1 产物（已实施）

| 文件 | 变更 |
|------|------|
| `webui-agent/src/api.ts` | ✅ `chatStream()` SSE 客户端 |
| `webui-agent/src/components/AgentChat.tsx` | ✅ 重构流式消费 + ToolCallCard + 键盘支持 |
| `webui-agent/src/components/Toast.tsx` | ✅ 从 webui 复制 |
| `webui-agent/src/main.tsx` | ✅ + ToastProvider |

### 待实施

| 文件 | 变更 |
|------|------|
| `Confirmations.tsx` | + Toast on approve/reject |
| `DreamProposals.tsx` | + Toast on approve/apply + 二次确认 |
| `stores/agentStore.ts` | Zustand store，管理 `currentWikiId` |
| `components/WikiSelector.tsx` | 从 webui 复制或重写 |
| `api.ts` | 所有方法自动注入 `wikiId` |