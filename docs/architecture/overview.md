# llmwikify 架构与流程总览（图解版）

> 面向开发者的图示文档。文字版见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。
> **版本:** 0.40.2 · **更新:** 2026-10-13 · **测试:** 4940 collected
> **验证:** `python scripts/check_architecture.py` → 0 violations

## 目录

- [1. 分层与依赖规则](#1-分层与依赖规则)
- [2. 整体架构图](#2-整体架构图)
- [3. Chat 主链路（SSE 时序）](#3-chat-主链路sse-时序)
- [4. ChatRunnerV2 状态机与 Hook](#4-chatrunnerv2-状态机与-hook)
- [5. 知识入库与查询复利](#5-知识入库与查询复利)
- [6. 自维护子系统（v0.41）](#6-自维护子系统v041)
- [7. `/study` 深度研究](#7-study-深度研究)
- [8. 入口层与运行时开关](#8-入口层与运行时开关)
- [9. 验证与维护](#9-验证与维护)

---

## 1. 分层与依赖规则

依赖方向严格单向，禁止反向（含 runtime lazy import）：

```
interfaces  →  apps, kernel, foundation
apps        →  foundation, kernel
kernel      →  foundation              ← 严格不依赖 apps
foundation  →  (self only)
```

backward-compat shim（保留旧导入路径，指向新家）：

| Shim | 指向 |
|------|------|
| `apps/chat/agent/unified/` | `kernel/agent/`（通用 agent 框架） |
| `apps/chat/agent/execution_context.py` | `kernel/agent/execution_context.py` |
| `apps/chat/engine.py`、`apps/chat/research_engine/` | `apps/research/`（研究引擎） |
| `kernel/quant/llm_client.py` | `foundation/llm/client.py` |

---

## 2. 整体架构图

```mermaid
flowchart TB
    subgraph L4["interfaces/ · 入口层"]
        direction LR
        CLI["CLI · 34 子命令"]
        MCP["MCP Adapter · 28 工具"]
        SRV["WikiServer (FastAPI)<br/>REST + SSE + WebSocket<br/>JWT + 限流中间件"]
        OAI["/v1/chat/completions<br/>OpenAI 兼容端点"]
    end

    subgraph L3["apps/ · 应用层"]
        direction LR
        AW["wiki · WikiService"]
        AC["chat<br/>AgentService → ChatOrchestrator → ChatRunnerV2<br/>Skills · Memory · Harness · Providers"]
        AR["research · ResearchEngine"]
        AA["agent<br/>MaintenanceManager · DreamEditor<br/>Scheduler · Notifications"]
    end

    subgraph L2["kernel/ · 核心引擎"]
        direction LR
        KW["wiki<br/>Wiki (13 mixins)<br/>engines · lint"]
        KMW["multi_wiki<br/>Registry · Remote"]
        KST["storage<br/>FTS5 · sink · watcher"]
        KS["search · QMD"]
        KG["graph"]
        KA["agent<br/>UnifiedAgentLoop · Hook"]
    end

    subgraph L1["foundation/ · 基础设施"]
        direction LR
        FL["llm<br/>client · spec · resolver<br/>streamable · token budget"]
        FP["prompts"]
        FE["extractors"]
        FC["callback<br/>AgentHook · CompositeHook"]
        FX["config · io · utils · auth · logging"]
    end

    CLI --> AC & AW & AR
    MCP --> KMW
    SRV --> AC & AW & AR & AA
    OAI --> AC
    L3 --> L2
    L3 --> L1
    L2 --> L1
```

规模：`src/llmwikify/` 约 400 个 py 文件 / 7.5 万行；`tests/` 约 236 个测试文件。

---

## 3. Chat 主链路（SSE 时序）

```mermaid
sequenceDiagram
    autonumber
    participant UI as WebUI
    participant API as FastAPI<br/>POST /api/agent/chat
    participant AS as AgentService
    participant CO as ChatOrchestrator
    participant RV as ChatRunnerV2
    participant TE as ToolExecutor
    participant LLM as foundation.llm

    UI->>API: {message, session_id, wiki_id}
    API->>AS: chat() → async iterator
    AS->>CO: chat()
    CO->>CO: 会话创建/恢复 · 斜杠命令拦截(CommandRouter)
    CO->>CO: PromptBuilder 组装 + ContextManager 裁剪
    CO->>RV: build runner → run_stream(ChatRunSpec)
    loop 每轮（≤ max_chat_rounds，默认 10）
        RV->>RV: PRECHECK（超时/取消/目标失效谓词）
        RV->>LLM: REASON（流式 + 重试 + text-mode 解析）
        LLM-->>UI: SSE message_delta / thinking
        alt 有 tool_calls
            RV->>TE: ACT（技能/工具执行）
            TE-->>RV: 结果（microcompact + DB 持久化）
            RV->>RV: OBSERVE 汇总
        else 无 tool_calls
            RV->>RV: final_content → FINALIZE
        end
    end
    RV-->>UI: done / error / save_warning / confirmation_required
    CO->>CO: 落库 assistant 消息（含 research_run_id）
```

关键代码路径：

| 步骤 | 位置 |
|------|------|
| HTTP 入口 | `interfaces/server/http/agent/sessions.py` (`POST /chat`) |
| 组合根 | `apps/chat/agent/agent_service.py` (`AgentService`) |
| Chat 编排 | `apps/chat/agent/orchestrator.py` (`ChatOrchestrator`) |
| Agent 循环 | `apps/chat/agent/runner_v2.py` (`ChatRunnerV2`) |
| 工具执行 | `apps/chat/agent/tool_executor.py` + `apps/agent/tools/skill_adapter.py` |
| LLM 客户端 | `foundation/llm/client.py` → `foundation/llm/streamable.py` |

每轮 chat 动态组装：`CompositeHook[WikiHook, _V2PersistenceHook]` +
`SubagentManager`（子代理不能再生成孙代理）。`ChatRunSpec` 承载
microcompact（默认 ON，保留 1000 字符）等约 20 个字段。

### SSE 事件表（`apps/chat/agent/events.py`）

| Event | 含义 |
|-------|------|
| `message_delta` | LLM 内容增量 |
| `thinking` | 思维链 / reasoning |
| `tool_call_start` / `tool_call_end` / `tool_call_error` | 工具轮次执行 |
| `confirmation_required` | 等待用户确认（危险操作） |
| `compacted` | 工具结果被 microcompact |
| `session_created` / `session_init` | 会话生命周期 |
| `command_done` | 斜杠命令完成（绕过 LLM 循环） |
| `research_run_started` | `/study` 研究已启动 |
| `save_warning` | DB 写失败但流继续（`{type, reason}`） |
| `done` / `error` | 终止事件 |
| `phase` | 研究引擎域标记（透传） |

---

## 4. ChatRunnerV2 状态机与 Hook

```mermaid
flowchart LR
    S((开始)) --> P["PRECHECK<br/>超时/取消/暂停/目标谓词"]
    P --> R["REASON<br/>LLM 流式 + retry<br/>text-mode 解析"]
    R -->|无工具调用| F["FINALIZE<br/>finalize_content 钩子管道<br/>emit done/error"]
    R -->|有工具调用| A["ACT<br/>before_execute_tools<br/>→ 执行 → after_tool_executed"]
    A -->|confirmation_required| F
    A --> O["OBSERVE<br/>轮次摘要 + 记忆整合"]
    O --> P
    F --> E((结束))
```

13 个 `AgentHook` 钩子点（`foundation/callback/composite.py`）：

```
wants_streaming · before_iteration · on_stream · on_stream_end ·
emit_reasoning · emit_reasoning_end · before_execute_tools ·
after_tool_executed · on_tool_error · on_confirmation ·
after_iteration · finalize_content · on_error
```

`CompositeHook` fan-out 错误隔离（async 钩子自动 try/except log warning），
仅 `finalize_content` 透传异常（pipeline 语义）。业务钩子位于
`foundation/callback/integrations/`：`WikiHook` / `WikiDreamSyncHook` /
`AutoIngestHook`。

---

## 5. 知识入库与查询复利

```mermaid
flowchart LR
    subgraph IN["入库"]
        SRC["源文件<br/>PDF/URL/YouTube/MD"] --> EX["foundation.extractors<br/>类型检测+提取"]
        EX --> IG["wiki.mixins.io.ingest<br/>raw/ 收集+日志"]
        IG --> SA["source_analysis<br/>LLM 提取（带缓存）"]
        SA --> SY["synthesis<br/>跨源对比（可选）"]
        SY --> PG["page_io<br/>写页面+关系"]
        PG --> LT["lint 健康检查<br/>（8 条规则）"]
    end
    subgraph Q["查询复利"]
        QQ["提问"] --> FTS["FTS5 检索<br/>kernel.storage.index"]
        FTS --> RD["read_page"]
        RD --> LL["LLM 综合"]
        LL --> QP["保存为 Query: 页面"]
    end
```

---

## 6. 自维护子系统（v0.41）

```mermaid
flowchart TB
    LIFE["WikiServer lifespan"] --> MM["MaintenanceManager<br/>覆盖所有 LOCAL wiki"]
    MM --> T1["Track A · AutoIngestService<br/>逐 wiki FileSystemWatcher<br/>新文件直写入库"]
    MM --> T2["Track B · GapFiller<br/>周期 gap 研究 → 提案制"]
    MM --> T3["Lint 周期检查<br/>健康历史持久化"]
    MM --> T4["DB 例行维护"]
    T1 & T2 & T3 --> TH["Semaphore(3) + 全局限流 ≤5 次/5s"]
    T2 --> PROP["WikiDreamProposalManager<br/>共享 .llmwiki_agent.db"]
    PROP --> UI["WebUI /insights/maintenance<br/>人工审核"]
```

同一 lifespan 还管理：

- **DreamScheduler**（cron，记忆梦境管线）
- **AutoCompact**（TTL 压缩，`memory_config.json` 可调）
- **ConfirmationsCleanup**（过期确认令牌清理）

全部走两级开关：服务构造开关 + 配置文件 `enabled` 标志。

---

## 7. `/study` 深度研究

```mermaid
sequenceDiagram
    participant U as 用户
    participant CH as ChatRunnerV2 主循环
    participant SK as autoresearch_compound skill<br/>triggers=["/study"]
    participant RE as ResearchEngine
    participant W as Wiki

    U->>CH: /study 问题文本
    CH->>SK: LLM 匹配触发器 → 调用 run 工具
    SK->>RE: 启动研究（plan→gather→analyze→synthesize→report→review）
    RE-->>CH: run_id（写入 assistant 消息）
    loop SSE /api/autoresearch/{id}/stream
        RE-->>U: phase / round / 事件
    end
    U->>RE: POST /save-to-wiki
    RE->>W: 报告落库为页面
```

要点：

- 触发条件只有显式 `/study` 前缀（`/api/health.features.research_trigger`）。
- 研究阶段由 `apps/research/gates.py` 质量门控制（源数量 / 类型多样性 / 可信度）。
- 长任务使用更长的 SSE 超时（研究 6 步流程默认超时不足）。

---

## 8. 入口层与运行时开关

### WebUI 路由（`ui/webui/src/App.tsx`）

```
/edit                     编辑器
/dashboard                知识增长
/insights                 洞察
/insights/dream           梦境提案
/insights/sink            Sink 队列
/insights/maintenance     自维护面板
/agent/chat               Agent 对话
/agent/autoresearch       深度研究
/agent/confirmations      确认中心
/agent/tasks              任务监控
/agent/settings           LLM 设置
/login                    JWT 认证
```

### `/api/health.features` 运行时开关

| Feature | 说明 |
|---------|------|
| `mcp` / `webui` / `auth` | 服务能力 |
| `multi_wiki` | 多 wiki 模式（>1 个注册 wiki 时为 true） |
| `dream_scheduler` / `auto_compact` | 后台任务运行状态 |
| `confirmations_cleanup` | 过期确认清理任务 |
| `maintenance` | 自维护管理器（v0.41） |
| `research_trigger` | 固定为 `/study` |

---

## 9. 验证与维护

```bash
python scripts/check_architecture.py     # 分层依赖检查：必须 0 violations
pytest --collect-only -q                 # 测试收集（4940，排除 tests/ab_testing）
pytest -m e2e                            # 端到端（需要真实服务）
curl http://localhost:8765/api/health    # 运行时健康检查
```

代码图谱（graphify）：

```bash
graphify update .    # 刷新 graphify-out/（无 API 成本）
```

> 维护约定：本文件是`ARCHITECTURE.md` 的图解伴生文档。
> 架构改动（新增/删除层内模块、改变主链路）时同步更新两处。
