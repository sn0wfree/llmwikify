# llmwikify Agent 升级评估 (Phase 3 输出: apply-plan.md)

> 输入: `compare.md` (Phase 1) + `nanobot-framework.md` (Phase 2) + 本文件
> 目的: 基于框架对比, 给出 llmwikify agent 升级的**具体实施计划** (含风险/优先级/验收)
> 时间: 2026-06-17

---

## 1. llmwikify chat+agent 当前框架

### 1.1 顶层架构 (5+1 service composition)

**设计哲学**: composition-over-inheritance — 5 个核心服务 + 1 个 MemoryManager 聚合, AgentService 作为 composition root.

```
┌────────────────────────────────────────────────────────────────────┐
│  AgentService (310 LOC, composition root)                           │
│  ├─ app_db: AppDatabase (3-facade aggregate)                       │
│  ├─ wiki_service: WikiService (multi-wiki + dream/notify/scheduler)│
│  ├─ chat_service: ChatOrchestrator (SSE chat)                       │
│  ├─ skill_service: SkillService (81 actions registry)              │
│  ├─ harness_service: HarnessService (6 eval primitives)            │
│  └─ memory_manager: MemoryManager (6 memory stores)                 │
└────────────────────────────────────────────────────────────────────┘
```

### 1.2 chat/agent/ 子模块 (15 文件 / 3,912 LOC)

```
chat/agent/ (3,912 LOC 总)
├── agent_service.py           310  Composition root
├── orchestrator.py            664  ChatOrchestrator 主循环 + ChatEvent SSE factory
├── chat_react.py              711  ChatReActBridge: ReActEngine ↔ ChatService glue
├── react_engine.py            687  通用 ReAct 引擎 (Thought→Action→Observation)
├── tool_executor.py           205  工具执行 + DB 持久化
├── context_manager.py         314  AgentContext (in-memory state) + 截断/压缩
├── text_mode_tool.py          252  [TOOL_CALL] 文本模式解析
├── prompt_builder.py          150  System prompt 组装
├── bridge_backend.py          149  Bridge backend adapter
├── context_store.py           109  LRU + TTL eviction
├── event_log.py                88  事件日志
├── research_bridge.py          77  Research 模块桥接
├── react_loop.py               51  简版 react loop
├── _error_logging.py          123  错误日志工具
├── __init__.py                 22  Re-exports
└── agent/                   3,912  子目录 (15 文件)
    └── (具体子模块略)
```

### 1.3 关键组件拆解

#### ChatOrchestrator (664 LOC)

**职责**:
- SSE 事件流 (ChatEvent factory, 7 种 event types)
- Session 创建/恢复
- Abort/status 管理
- Event translation (ReActEngine → frontend vocabulary)

**主循环** (扁平方法, 非状态机):
```python
async def chat(self, session_id, message, ...) -> AsyncIterator[dict]:
    # 1. 加载/创建 session
    # 2. PromptBuilder.build_system_prompt
    # 3. ContextManager.get_messages (含截断)
    # 4. ChatReActBridge.build_config
    # 5. ReActEngine.run (yield SSE events)
    # 6. 流式 yield 给 HTTP handler
    pass

# 隐含状态:
# - 当前 session
# - 当前 wiki
# - abort flag
# - tool_call_id ↔ tool_name 映射
```

**ChatEvent 事件类型** (frontend SSE contract):
- `message_delta` — LLM 流式输出
- `thinking` — 思考过程
- `tool_call_start` / `tool_call_end` / `tool_call_error`
- `confirmation_required` — 需要用户确认
- `save_warning` — 保存警告 (`ui/webui/src/api.ts:34`)
- `done` / `error`

#### ReActEngine (687 LOC)

**职责**: 通用 ReAct 循环 (与 chat 解耦, 可复用)

**核心**:
- `ReActConfig` dataclass
- `ReActEngine(config).run(skill_ctx)` async iterator
- 状态机简化版: THOUGHT → ACTION → OBSERVATION → (loop or DONE)

#### ChatReActBridge (711 LOC)

**职责**: 把 ReActEngine 接入 ChatService 特有逻辑

**注入依赖**:
- LLM 流式调用 (含重试)
- Tool execution (含 DB 持久化)
- Confirmation flow
- Text-mode `[TOOL_CALL]` 解析
- Observation aggregation

#### AgentContext (314 LOC, dataclass)

**职责**: 单 session 内存状态

```python
@dataclass
class AgentContext:
    session_id: str = ""
    wiki_id: str | None = None
    messages: list[dict[str, str]]
    recent_wiki_id: str | None = None
    _tool_calls: dict[str, Any]
    
    # ReAct 状态
    react_observations: list[str]
    react_thoughts: list[str]
    react_round: int
    _thinking: str
    
    # 限制
    _observation_limit: int = 10
    _observation_summary_limit: int = 5
```

#### ToolExecutor (205 LOC)

**职责**: 工具调用 + DB 持久化

**关键能力**:
- 异步执行 (`tool_registry.execute`)
- DB 状态机: `pending` → `executed` / `confirmation_required`
- Posthoc-confirmation 工具的 ingest 日志
- DBRetryManager (3 次重试)

### 1.4 Skills 系统 (10,185 LOC / 81 actions)

**与 nanobot 完全不同的概念**:

| 维度 | llmwikify skills | nanobot skills |
|------|------------------|----------------|
| 本质 | Python 业务函数 | Prompt 文档 |
| 数量 | 81 actions | 10 内置 + 用户扩展 |
| 注册 | `skills/base.py` (SkillAction ABC) | YAML frontmatter |
| 调用 | `await skill.execute(ctx)` | LLM 读 SKILL.md |

**SkillAction ABC**:
```python
class SkillAction(ABC):
    name: str
    description: str
    requires_confirmation: Literal["none", "pre", "posthoc"]
    
    async def execute(self, ctx: SkillContext) -> SkillResult: ...
```

---

## 2. 与 nanobot 框架的逐项对比 (升级视角)

### 2.1 入口层

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| Composition root | `AgentService` (5+1 service) | `Nanobot` (单 mega-loop + channels) | llmwikify 更清晰 |
| 依赖数 | 7 | 23+ | llmwikify 更简洁 |
| 渠道抽象 | 无 (HTTP only) | Channels layer (19f/16kL) | **llmwikify 缺多渠道** |

**结论**: llmwikify composition 优于 nanobot (更模块化). **不要 vendor Nanobot**.

### 2.2 主循环层

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 主循环 | `ChatOrchestrator` (扁平 28 方法) | `AgentLoop` (TurnState 状态机) | **llmwikify 缺显式状态** |
| 执行循环 | `ChatReActBridge` + `ReActEngine` (内嵌) | `AgentRunner.run` (独立 dataclass API) | **llmwikify 可借鉴独立化** |
| 状态恢复 | Session reload in Orchestrator | Session 在 RESTORE 阶段 | 类似 |
| 子代理 | 无 | `SubagentManager` (392 LOC) | **llmwikify 缺** |

**核心差距**: llmwikify ChatOrchestrator 28 方法, 隐式状态转换; nanobot 8 状态显式. **可借鉴独立化思路**.

### 2.3 Context 组装

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 组装器 | `PromptBuilder` (150 LOC, 内嵌于 Orchestrator) | `ContextBuilder` (266 LOC, 独立类) | **llmwikify 缺独立抽象** |
| Bootstrap | 无 | AGENTS.md / SOUL.md / USER.md | llmwikify 可借鉴 (复用现有 AGENTS.md) |
| ReAct prompt | `REACT_SYSTEM_PROMPT` 字符串 (chat_react.py:67) | Tool contract template | 类似 |
| 截断 | `token_estimator.count_messages` + AgentContext | `_MAX_RECENT_HISTORY = 50` + `_MAX_HISTORY_CHARS = 32_000` | 类似 |

**结论**: llmwikify PromptBuilder 应**抽取为独立类** (参考 nanobot), 不必 vendor.

### 2.4 LLM 调用

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 抽象 | `StreamableLLMClient` Protocol (1509 LOC) | `LLMProvider` ABC (843 LOC) | **llmwikify 更成熟** |
| 4 模式借用 | ✅ M1 commit `2c59227` | ✅ nanobot 原本 | **已对齐** |
| Thinking | `build_thinking_extra_body` (M1 借) | `thinking_style` map | 类似 |

**结论**: llmwikify LLM 层**已优于** nanobot (更成熟, 已借 4 模式). **无升级需求**.

### 2.5 消息总线

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 总线 | 无 (Orchestrator 直接调) | `MessageBus` (103 LOC) | **llmwikify 缺** |
| 事件 schema | `ChatEvent` (SSE events, 7 types) | `InboundMessage` / `OutboundMessage` | 不同 (SSE vs 跨渠道) |
| 多渠道 | HTTP/SSE only | Telegram/Discord/Slack/WhatsApp/WebSocket | **llmwikify 缺多渠道** |

**结论**: MessageBus 对 llmwikify **价值低** (单进程 HTTP 已够). 但**多渠道价值高** (WebSocket 是 P1 候选).

### 2.6 会话管理

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 存储 | SQLite (`sessions` + `messages` 表) | JSON 文件 (per-session) | **llmwikify 更优** (查询/事务) |
| 压缩 | 简单 token 截断 (`token_estimator`) | `Consolidator` (LLM-driven) + `Dream` | **llmwikify 缺深度压缩** |
| 摘要 | 无 | `[Archived Context Summary]` 注入 | **llmwikify 可借鉴** |

**结论**: Storage 保持 SQLite. **可借鉴 Consolidator 设计** (P3 候选).

### 2.7 钩子系统

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 钩子 | callback 链 (无显式抽象) | `AgentHook` (141 LOC, 9 钩子点) | **llmwikify 缺** |
| 错误隔离 | 无 (一个 callback 抛错整链挂) | `CompositeHook` (fan-out + 隔离) | **llmwikify 缺** |

**结论**: **`CompositeHook` 是 P0 候选** — 141 LOC, 解决现有 callback 链脆弱问题.

### 2.8 Command Router

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| Router | 无 (slash cmd 内联 Orchestrator) | `CommandRouter` (88 LOC, 3-tier) | **llmwikify 缺** |
| Lock | 无 | priority 外锁 / exact+prefix 内锁 | llmwikify 也不需要 (单用户) |

**结论**: `CommandRouter` 88 LOC, **P1 候选** (清理 slash cmd 内联).

### 2.9 Skills

| 维度 | llmwikify | nanobot | 结论 |
|------|-----------|---------|------|
| 概念 | Python 业务函数 (81 actions) | Prompt 文档 (markdown) | **不可移植** |
| Loader | `SkillService` registry (dict-based) | `SkillsLoader` (filesystem scan) | llmwikify 更强 |

**结论**: **不借鉴 nanobot skills** (概念不同). llmwikify skills 81 actions 已是核心资产.

### 2.10 HTTP API

| 维度 | llmwikify | nanobot | 差距 |
|------|-----------|---------|------|
| 框架 | FastAPI (sync wrapper) | aiohttp (async native) | nanobot 更原生 |
| OpenAI 兼容 | ❌ (自定义 `/api/chat/stream`) | ✅ (`/v1/chat/completions`, `/v1/models`) | **llmwikify 缺** |
| SSE | 自定义 (`type: save_warning`) | 标准 OpenAI chunk 格式 | **llmwikify 缺 OpenAI 生态** |
| LOC | 588 (routes) + 479 (chat_sse) | 399 (api/server.py) | nanobot 更紧凑 |

**结论**: **`api/server.py` 是 P0 vendor 候选** — 399 LOC, 立即获得 OpenAI 生态接入.

---

## 3. 升级评估总览

### 3.1 风险/价值矩阵

| 升级项 | 复杂度 | 风险 | 价值 | 推荐度 |
|--------|--------|------|------|--------|
| **P0-1** CompositeHook 抽象 | 低 | 低 | **高** | ✅ **立即做** |
| **P0-2** AgentRunner 独立化 (借鉴 nanobot 思路) | 中 | 低 | **高** | ✅ **立即做** |
| **P1-1** vendor api/server.py | 低 | 低 | **高** | ✅ 推荐 |
| **P1-2** CommandRouter 引入 (88 LOC) | 低 | 低 | 中 | ✅ 推荐 |
| **P1-3** PromptBuilder 抽取独立类 | 低 | 低 | 中 | ✅ 推荐 |
| **P2-1** WebSocket vendor (`channels/websocket.py`) | 中 | 中 | 中 | ⏸ 评估需求 |
| **P2-2** Anthropic native vendor | 中 | 低 | 中 | ⏸ 评估需求 |
| **P3-1** AgentLoop 状态机重写 | 高 | 高 | 中 | ⚠ 谨慎 |
| **P3-2** Consolidator (LLM 压缩) | 高 | 中 | 中 | ⚠ 评估 |
| **P3-3** MessageBus 引入 | 中 | 中 | 低 | ❌ 价值低 |
| ❌ Skills 借鉴 | — | — | — | 不做 (概念不同) |
| ❌ Session 改 JSON 文件 | — | — | — | 不做 (SQLite 更优) |
| ❌ vendor Nanobot 整体 | 高 | 高 | 低 | 不做 |

### 3.2 三大升级类别

#### 类别 A: 借鉴设计模式 (不 vendor 代码)
- **A-1**: CompositeHook (callback chain + 错误隔离)
- **A-2**: AgentRunner dataclass API (Runner 独立化)
- **A-3**: ContextBuilder 独立类

**优点**: 借鉴 nanobot 设计哲学, 不引入耦合, 风险极低.

#### 类别 B: Vendor 小模块
- **B-1**: `api/server.py` (399 LOC, OpenAI 兼容)
- **B-2**: `command/router.py` (88 LOC)
- **B-3**: `agent/hook.py` (141 LOC, CompositeHook 基础)

**优点**: 小模块 vendor, 即时获得 nanobot 能力.

#### 类别 C: Vendor 大模块 (谨慎)
- **C-1**: `channels/websocket.py` (1907 LOC)
- **C-2**: `agent/loop.py` (1724 LOC, 状态机)
- **C-3**: `agent/memory.py` (1161 LOC, Consolidator+Dream)

**缺点**: 大模块 vendor 风险高, loguru 依赖, shape 不匹配.

---

## 4. 渐进式升级路径 (3 阶段)

### Phase A: P0 借鉴 (1 周)

**目标**: 解决 callback 链脆弱 + 引入 Runner 独立化

**步骤**:
1. **A-1 CompositeHook** (2 天)
   - 新建 `src/llmwikify/foundation/callback/composite.py` (~80 LOC)
   - 9 个钩子点: `before_iteration`, `on_stream`, `on_stream_end`, `before_execute_tools`, `after_iteration`, `finalize_content`, `emit_reasoning`, `emit_reasoning_end`, `wants_streaming`
   - 错误隔离: async 方法 try/except, 错误日志记录
   - 测试: `tests/test_foundation_callback_composite.py` (10 cases)

2. **A-2 AgentRunner 独立化** (3 天)
   - 新建 `src/llmwikify/apps/chat/agent/runner.py` (~150 LOC)
   - 抽取 `ReActEngine.run()` 为 `ChatRunner.run(spec: ChatRunSpec) -> ChatRunResult`
   - `ChatRunSpec` dataclass: messages, tools, model, max_iterations, hook, etc.
   - `ChatRunResult` dataclass: final_content, messages, tools_used, usage, stop_reason, error
   - 重构 `ChatReActBridge` 调用 Runner (替换 ReActEngine 内嵌循环)
   - 测试: `tests/test_apps_chat_agent_runner.py` (15 cases)

**验收**:
- [x] 现有 711 LOC chat_react.py 减少 ~200 LOC
- [x] callback 链抛错不影响其他 callback
- [x] Runner 可独立单元测试 (不依赖 FastAPI / SSE)
- [x] ruff clean, pytest all green

### Phase B: P1 vendor (1-2 周)

**目标**: 引入 OpenAI 兼容 API + Command Router

**步骤**:
1. **B-1 vendor api/server.py** (3 天)
   - 复制 `nanobot/api/server.py` 到 `src/llmwikify/apps/api/openai_server.py`
   - 替换依赖: `aiohttp` → `FastAPI` (or 保留 aiohttp?)
   - 替换依赖: `nanobot.process_direct` → `ChatOrchestrator.chat`
   - 替换 SSE 格式: `OutboundMessage` → `ChatEvent` translation layer
   - 测试: `tests/test_apps_api_openai.py` (10 cases, OpenAI SDK 兼容)
   - 文档: `docs/api/openai-compat.md`

2. **B-2 CommandRouter** (1 天)
   - 复制 `nanobot/command/router.py` 到 `src/llmwikify/apps/chat/command_router.py`
   - 接入: Orchestrator 在 ReAct 循环前先 dispatch command
   - 测试: `tests/test_apps_chat_command_router.py` (5 cases)

3. **B-3 PromptBuilder 独立化** (2 天)
   - 抽取 `PromptBuilder.build_system_prompt()` 为独立类
   - 路径: `src/llmwikify/apps/chat/agent/prompt_builder.py` (现有 150 LOC → 独立 300 LOC)
   - 加入 bootstrap 文件读取 (复用现有 AGENTS.md)
   - 测试: 现有测试 + 新增 `tests/test_apps_chat_prompt_builder.py` (8 cases)

**验收**:
- [x] OpenAI Python SDK 可直接调用 llmwikify
- [x] `/v1/models` 返回真实模型列表
- [x] slash command 从 Orchestrator 内联移除
- [x] PromptBuilder 可独立测试

### Phase B 实现笔记 (P1-1, P1-2, P1-3, 2026-06-18 完成)

P1-1/P1-2/P1-3 全部已 vendor + 测试通过。Phase A 的 3 步 (P0-1 CompositeHook / P0-2 ChatRunner 独立化 / microcompact) 加上 Phase B 的 3 步 (P1-1 OpenAI API / P1-2 CommandRouter / P1-3 PromptBuilder 独立化) 形成"借鉴 nanobot" 核心的完整闭环。Phase C / Phase D / Phase E 全部缓办 (P2-2 Anthropic 用户暂缓; P3-1/P3-2 谨慎; P3-3 不做)。

#### P1-1 OpenAI 兼容 API (`src/llmwikify/apps/api/openai_server.py`, commit `8ba4a00`)

- **vendored from**: `nanobot/api/server.py` (399 LOC, MIT)
- **实际 LOC**: 508 (含 docstring + 适配层)
- **路由**:
  - `POST /v1/chat/completions` (流式 SSE + 非流式)
  - `GET /v1/models`
  - `GET /v1/health`
- **适配点**:
  - `aiohttp.web.Application` → FastAPI `APIRouter` (前缀 `/v1`)
  - `aiohttp.web.StreamResponse` → FastAPI `StreamingResponse`
  - `agent_loop.process_direct(...)` → `AgentService.chat(...)` (复用 Plan B 完成的 ChatRunnerV2)
  - 简化: 删除 multipart 上传 (llmwikify 走 wiki API), 加 vision-format text 提取
  - `app["session_locks"]` → 模块级 `_SessionLockRegistry` (per-session `asyncio.Lock`)
- **事件翻译**: `OpenAIStreamTranslator` 将 llmwikify `message_delta`/`done`/`error` → OpenAI content/stop chunks; 忽略 `thinking`/`tool_call_*`/`save_warning` (OpenAI 协议无对应通道)。
- **路由接入**: `interfaces/server/http/routes.py:_register_agent_routes` 调用 `create_openai_router(model=...)`, 从 `get_default_provider().model` 推断 model_name, 失败回退 `"llmwikify-chat"`。
- **测试**: `tests/test_apps_api_openai.py` (35 cases) — 包含响应形态 / 事件翻译 / 请求解析 / 路由工厂 / FastAPI TestClient E2E (流式 + 非流式 + 错误路径 + session 转发)。
- **server smoke**: 用 `WikiServer(wiki)` + `TestClient` 实际跑通, 所有 3 路由可达; 流式 SSE content-type 正确; 错误模型返回标准 OpenAI 错误 JSON。

#### P1-2 CommandRouter (`src/llmwikify/apps/chat/command_router.py`, commit `9e43835`)

- **vendored from**: `nanobot/command/router.py` (88 LOC, MIT)
- **实际 LOC**: 215 (含 docstring + 适配层)
- **3 层 dispatch**:
  - **priority** — 锁外执行 (e.g. `/stop` 设 `abort_event`)
  - **exact** — 锁内精确匹配 (e.g. `/help`, `/clear`, `/status`)
  - **prefix** — 最长前缀优先 (e.g. `/title <text>`, `/model <name>`)
- **适配点**:
  - `InboundMessage` / `OutboundMessage` → `CommandContext.text: str` + handlers 返回 `list[dict]` SSE events
  - 加 `Awaitable[dict]` 自动 await (handler 可 `async def`)
  - 加 `is_command()` 公共方法 (合并 priority+exact+prefix 分类)
  - prefix 派发用 `ctx.text` (原大小写) 提取 args, 保留 user 大小写
- **集成**: `ChatOrchestrator` 在 `parse_wiki_prefix` 之后、`add_user_message` 之前调 `_dispatch_command`; 匹配后 yield `command_done` 事件短路返回 (不进 LLM loop)。
- **5 个内建命令**: `/stop` (priority) / `/help` / `/clear` / `/status` (exact) / `/title <text>` (prefix)
- **可扩展性**: `self.command_router` 是可替换实例, 业务模块可调 `orch.command_router.exact("/foo", handler)` 注入新命令。
- **测试**: `tests/test_apps_chat_command_router.py` (35 cases) — 注册 / 分类 / dispatch / handler 形态 (None/dict/list/async iter) / 大小写保留 / priority vs exact 语义 / orchestrator 集成。

#### P1-3 PromptBuilder 独立化 (`src/llmwikify/apps/chat/agent/prompt_builder.py`, commit `52d23bf`)

- 早于 P1-1/P1-2 完成 (Plan B 期间)。150 → 300 LOC, 7 sections + BuildContext + mtime cache + 内联 `REACT_SYSTEM_PROMPT`。
- 测试: 现有 + `tests/test_apps_chat_agent_prompt_builder.py` (15 cases)。

#### 累计数据

- **总 LOC 新增**: ~1,030 (508 + 215 + 300 + 一些 docstring)
- **测试新增**: 70 (35 OpenAI + 35 CommandRouter) + 15 PromptBuilder = 85
- **总测试套件**: 968 passed (P1-1 + P1-2 + P1-3 + Plan B 全套)

#### 待审批 (Phase C/D/E, 缓办)

- **P2-1 WebSocket vendor** (1907 LOC) — 按需, 评估实时双向通信需求
- **P2-2 Anthropic native vendor** (~400 LOC) — **用户 2026-06-18 暂缓**, 当前 focus 是核心功能稳定
- **P3-1 AgentLoop 状态机重写** — 谨慎, 我们通过 Plan B 写了自己的 5 步状态机 (PRECHECK/REASON/ACT/OBSERVE/COMPLETE), 不需要 vendor nanobot 1724 LOC
- **P3-2 Consolidator** — 评估, microcompact 已覆盖多数 LLM 压缩场景
- **P3-3 MessageBus** — ❌ 不做 (单进程 HTTP 已够, apply-plan §5 决策记录)

### Phase C: P2 评估 (按需)

**目标**: 多渠道接入 (WebSocket / Anthropic native)

**仅在用户明确需求时启动**:
- WebSocket: 1907 LOC vendor, 评估是否需要实时双向通信
- Anthropic: ~400 LOC vendor, 评估是否启用 Claude 系列模型

---

## 5. 不升级项 (决策记录)

| 项 | 不升级理由 | 锁定日期 |
|----|-----------|----------|
| Vendor `Nanobot` 整体 | 23 依赖 + loguru + 多渠道耦合, 与 llmwikify 5+1 service 冲突 | 初始 |
| Skills 概念迁移 | llmwikify 81 actions 是 Python 业务, nanobot 是 prompt 文档, 不可移植 | 初始 |
| Session 改 JSON 文件 | SQLite 查询/事务优势 > JSON 简单性 | 初始 |
| **`MessageBus` 引入** | **重新评估 (2026-06-19): bus/queue.py 仅 44 LOC `asyncio.Queue` 包装, 用于解耦多 channel (Slack/Discord). 我们是单进程 HTTP, request-response 模式. MessageBus 唯一适用场景: WebSocket 长连接 (P2-1, vendor 1907 LOC). 引入 MessageBus 收益边际. 锁定否决.** | **2026-06-19** |
| Vendor `agent/loop.py` 状态机 | 1724 LOC, 隐式 8 state, llmwikify 扁平 28 方法已可读 | 初始 |
| Vendor `agent/memory.py` 整体 | 1,161 LOC 文件级 vendor 适配成本高, **改为选择性借鉴 Consolidator + Dream** (Phase 6) | 2026-06-19 |
| Vendor `providers/base.py` | M1 已分析, shape 不兼容 + loguru 依赖 | 初始 |
| **合并 `chat memory` 与 `reproduction memory`** | 它们是 peer (同层 sibling), 不是 parent-child. 合并会强制单向耦合. 未来如需跨域查询, 新建 `apps/memory_facade/` 协调者. | **2026-06-19** |

### 5.1 已实施的可借鉴改进

| 项 | 状态 | 实施位置 |
|----|------|---------|
| 借鉴 `StateTraceEntry` 加显式 state trace | ✅ 完成 (2026-06-19) | `apps/chat/agent/runner_v2.py` (`_StateTraceEntry` + `_StateTrace` CM) + 10 tests |
| microcompact (借鉴 `_COMPACTABLE_TOOLS`) | ✅ 完成 (2026-06-17) | `apps/chat/agent/microcompact.py` |
| 13 钩子点 (借鉴 `agent/hook.py` 设计) | ✅ 完成 (2026-06-17) | `foundation/callback/composite.py` |
| **Consolidator (借鉴 `nanobot/agent/memory.py:444`)** | ✅ 完成 (Phase 6, 2026-06-19) | `apps/chat/memory/consolidator.py` (per-session evict + LLM summarize + 双写 SQLite+md) |
| **Dream (借鉴 `nanobot/agent/memory.py:859`)** | ✅ 完成 (Phase 6, 2026-06-19) | `apps/chat/memory/dream.py` (2-phase fact extraction + 双写 + /dream slash + APScheduler) |

---

## 6. Phase 6 实施笔记 (2026-06-19, Consolidator + Dream)

### 6.1 启动动机

Phase 5 完成后 (D1-D5), `apps/chat/memory/__init__.py` (473 LOC) 与 nanobot `agent/memory.py` (1,161 LOC) 仍差 2 个核心组件:
- **Consolidator**: per-turn session eviction + LLM summarize → 长期记忆
- **Dream**: 后台 fact extraction + 长期记忆维护

microcompact (借鉴 nanobot `_COMPACTABLE_TOOLS`) 解决了 per-tool-result compaction, 但**不持久化**, 不能替代 Consolidator 的 per-session eviction + 总结。

### 6.2 关键决策 (7 项)

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | 范围 | Consolidator + Dream (借鉴 nanobot memory.py) | 真正空缺, 不是"合并 chat+reproduction" |
| 2 | 数据后端 | **双写: SQLite 2 表 + `~/.llmwikify/memory/*.md`** | SQLite 高效 query, markdown human-readable, 不进 wiki |
| 3 | Cron library | **APScheduler** | 与 nanobot 一致, 为跨平台准备 (Linux/macOS/Windows) |
| 4 | LLM summarization prompt | **新写** | microcompact 是 per-tool, summarization 是 per-session, 语义不同 |
| 5 | Dream 周期 | **Daily 03:00** | nanobot 默认 |
| 6 | Fact extraction 范围 | **增量 (since-last-run via `.dream_cursor`)** | 借鉴 nanobot cursor 机制 |
| 7 | 与 MemoryManager 关系 | **Option 7a**: MemoryManager 加 2 method | 9 caller 零迁移, 渐进式扩展 |

### 6.3 数据后端 (Both: SQLite + 文件系统)

```
~/.llmwikify/
├── agent/.llmwiki_agent.db         # 现有 chat DB, 加 2 表
└── memory/                         NEW filesystem tree
    ├── sessions/{session_id}.md     # Consolidator per-session 总结
    ├── facts/index.md              # Dream 聚合 index
    ├── facts/{fact_id}.md          # Dream per-fact 详情
    └── .dream_cursor               # Dream 增量 cursor
```

**为什么不进 wiki 系统**: wiki 是研究内容 (用户浏览/搜索), memory 是系统状态 (自动生成, 不应污染 wiki)。借鉴 nanobot `workspace/memory/MEMORY.md` 文件系统模式。

### 6.4 与 reproduction/sessions.py 关系 (明确)

`apps/reproduction/sessions.py` (564 LOC) **不是** chat memory 的子集, 是 **peer (sibling)**:
- chat memory: 追踪 session 内对话 + 长期 facts (chat 域)
- reproduction: 追踪 paper reproduction 流程 (reproduction 域)

**未来跨域查询** (Phase 8+): 新建 `apps/memory_facade/` 协调者, 同时持 `ChatMemoryManager` + `ReproductionDatabase`, 提供 schema-aware cross-system search API. **不**把 ReproductionDatabase 塞进 MemoryManager (peer-to-peer 协调, 不是 parent-child 嵌套)。

### 6.5 实施步骤 (4 步 + 验证)

| Step | 内容 | 估时 | Commits |
|---|---|---|---|
| 1 | Tables + stores + apscheduler dep | 45 min | 1 |
| 2 | Consolidator + MemoryManager attr + runner_v2 hook | 60 min | 2 |
| 3 | Dream + /dream skill + command_router register | 75 min | 3 |
| 4 | APScheduler lifespan + memory_config.json | 45 min | 4 |
| 5 | Full regression + ruff + docs | 30 min | 5 |

### 6.6 关键集成点

**Runner_v2 `after_iteration` 钩子** (复用 13 钩子点):
```python
# apps/chat/agent/runner_v2.py
async def _run_iteration(self, ctx):
    # ... 5 步 (PRECHECK/REASON/ACT/OBSERVE/COMPLETE) ...
    
    # Phase 6 NEW: 每次迭代后检查 consolidation
    if self._memory_manager and self._memory_manager.consolidator:
        try:
            result = await self._memory_manager.consolidate_session(
                session_id=ctx.session_id,
                messages=list(ctx.messages),
                session_tokens=ctx.total_tokens,
            )
            if result:
                ctx.compacted_count += 1  # 复用现有字段
        except Exception:
            logger.warning("consolidation failed", exc_info=True)
```

**MemoryManager 扩展** (Option 7a, 9 caller 零迁移):
```python
# apps/chat/memory/__init__.py
class MemoryManager:
    def __init__(self, app_db, wiki=None, data_dir=None, provider=None):
        # ... existing 6 stores ...
        # NEW (optional, None if no provider):
        self.consolidator = Consolidator(self, app_db.chat, provider, data_dir or app_db.data_dir) if provider else None
        self.dream = Dream(self, app_db.chat, provider, data_dir or app_db.data_dir) if provider else None
    
    async def consolidate_session(self, session_id, messages, session_tokens):
        return await self.consolidator.maybe_consolidate(...) if self.consolidator else None
    
    async def dream_run(self):
        return await self.dream.run() if self.dream else None
```

**APScheduler lifespan** (FastAPI context manager):
```python
# interfaces/server/http/routes.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _dream_scheduler
    if config.get("dream.enabled", True):
        _dream_scheduler = DreamScheduler(dream=app.state.memory_manager.dream, ...)
        await _dream_scheduler.start()
    yield
    if _dream_scheduler:
        await _dream_scheduler.stop()
```

### 6.7 数据对比

| 维度 | Phase 6 前 | Phase 6 后 | Δ |
|---|---:|---:|---:|
| `apps/chat/memory/` LOC | 473 (单文件) | ~1,300 (7 文件) | +830 |
| SQLite 表数 (chat DB) | 21 | 23 | +2 |
| Tests (memory 子系统) | 19 | ~70 | +50 |
| 9 caller 迁移成本 | — | 0 | — |
| 与 nanobot memory.py 差距 | 缺 Consolidator+Dream | 全补齐 | — |

### 6.8 测试覆盖 (5 文件, ~50 cases)

| 文件 | 测什么 | cases |
|---|---|---|
| `test_apps_chat_memory_consolidation_store.py` | SQLite CRUD (add/get/list by session_id) | 6 |
| `test_apps_chat_memory_facts_store.py` | SQLite CRUD (add/get/list by source_type) | 6 |
| `test_apps_chat_memory_consolidator.py` | 阈值触发 / evict 范围 / 双写 / throttling | 15 |
| `test_apps_chat_memory_dream.py` | 增量 cursor / fact extraction / 双写 | 12 |
| `test_apps_chat_skill_dream.py` + `test_command_router.py` +1 | `/dream` slash | 5 + 1 |

Mock 策略: LLM (`AsyncMock`), filesystem (`tmp_path`), APScheduler (lifespan test 不启 scheduler, 直接 `dream.run()`)。

### 6.9 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| Consolidator 频繁触发 → LLM cost | `min_consolidation_interval_sec=60` throttle per session |
| Markdown 文件累积过多 | `stale_threshold_days=14` 自动 archive (可选) |
| Dream LLM call 超时 | `max_iterations=10` cap + `asyncio.wait_for(timeout=300)` |
| Table migration 失败 | `IF NOT EXISTS` 幂等, 失败不阻塞启动 |
| 与 microcompact 冲突 | microcompact 仍 per-tool-result; consolidate 是 per-session eviction (不同语义) |

### 6.10 验收标准

- [ ] 4 commits (Step 1-4) + 1 docs commit (Step 5)
- [ ] 2 新表 + 2 新 store + 2 新 memory 类 + 1 slash command + 1 scheduler
- [ ] ~50 新 test cases
- [ ] 0 regression (基线 2578 pass / 0 fail → 完成后 ~2628 pass / 0 fail)
- [ ] ruff clean on new files
- [ ] 9 个 MemoryManager caller 零迁移 (Option 7a 验证)

### 6.11 累计数据 (Plan A + B + Phase 5 + 6)

| 维度 | Phase 6 后 |
|---|---:|
| 总 commit (Plan B 起) | ~30 |
| 总新增 LOC | ~5,000 |
| 总新增 test cases | ~700 |
| 测试基线 | 2578 pass / 47 skipped / 0 fail (D7 后) |
| Phase 6 后基线 | ~2628 pass / 47 skipped / 0 fail |
| archive 清理 | -7,771 LOC (累计 D2-D6-3) |
| 外部依赖新增 | +1 (apscheduler) |
| 总 nanobot 借鉴组件 | 5 (state trace / microcompact / 13 hooks / Consolidator / Dream) |

---

按"风险最低 + 价值最高"排序, 推荐 **本周可完成**:

1. **P0-1 CompositeHook** (~80 LOC, 1-2 天)
   - 解决 callback 链脆弱问题
   - 立即改善 28 个 callback 调用点
   - 测试简单 (10 cases)

2. **P0-2 Runner 独立化** (~150 LOC, 3 天)
   - 借鉴 nanobot `AgentRunner.run(spec)` 模式
   - 让 ReActEngine 可独立测试
   - 为 Phase A-3 状态机重铺路

3. **P1-3 PromptBuilder 独立** (~300 LOC, 2 天)
   - 抽取现有 150 LOC + 扩展
   - 加入 bootstrap 文件读取
   - 为未来 SKILL.md 模式铺路

**总计**: ~530 LOC 新增, 1 周完成, 风险低, 价值高.

> ⚠ **微压缩默认 = ON** (2026-06-17 用户决定, 见 `phase-a-steps.md` §3.4)
> 详细进度追踪见 `docs/poc/phase-a-steps.md`.

---

## 7. 待用户决策

请确认:

1. **P0 升级路径**: 是否同意 Phase A (CompositeHook + Runner 独立化)?
2. **P1 vendor 路径**: 是否同意 Phase B (OpenAI API + Command Router + PromptBuilder)?
3. **P2 优先级**: WebSocket / Anthropic native 当前是否需要?
4. **Skills 决策**: 确认不借鉴 nanobot skills (保持 81 actions Python 函数)?

确认后我会:
- 创建详细 task list (todowrite)
- 启动 Phase A 第一步 (CompositeHook)
- 给出具体 commit 计划
