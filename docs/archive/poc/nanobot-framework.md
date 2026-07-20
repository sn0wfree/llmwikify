# nanobot 框架深度分析 (Phase 2 产出)

> 输入: nanobot v0.2.1 `/tmp/nanobot/`
> 对照: llmwikify `src/llmwikify/apps/chat/`
> 目的: 为 Phase 3 的 `apply-plan.md` (A1-A6 实施顺序) 提供框架级理解

---

## 1. nanobot 顶层架构

### 1.1 包结构 (22 子模块)

```
nanobot/
├── nanobot.py            # 主入口: Nanobot 类, 串联所有组件
├── __main__.py           # CLI 入口
├── agent/                # Agent 核心 (35 文件 / 13,333 LOC)
│   ├── loop.py           # TurnState 状态机 (1724 LOC)
│   ├── runner.py         # 共享执行循环 (1348 LOC)
│   ├── context.py        # System prompt 组装器 (266 LOC)
│   ├── memory.py         # MemoryStore + Consolidator + Dream (1161 LOC)
│   ├── skills.py         # SkillsLoader (242 LOC, markdown 插件)
│   ├── hook.py           # AgentHook 生命周期钩子 (141 LOC)
│   ├── subagent.py       # SubagentManager (392 LOC)
│   └── tools/            # ToolRegistry / ToolLoader / MCP
├── api/server.py         # OpenAI-compat HTTP API (399 LOC)
├── apps/
│   └── cli/              # CLI 应用入口
├── bus/                  # 事件总线 (103+53 LOC)
│   ├── queue.py          # MessageBus pub/sub
│   └── events.py         # InboundMessage / OutboundMessage
├── channels/             # 多渠道接入 (19 文件 / 16,475 LOC)
│   ├── websocket.py      # WebSocket (1907 LOC) ← A1
│   ├── telegram.py / discord.py / slack.py / whatsapp.py
│   └── web.py
├── command/router.py     # CommandRouter (88 LOC)
├── config/               # 配置文件 schema (4 文件 / 810 LOC)
├── cron/                 # 定时任务 (3 文件 / 765 LOC)
├── pairing/              # 配对授权
├── providers/            # LLM 适配 (16 文件 / 8,050 LOC)
│   ├── base.py           # LLMProvider ABC (843 LOC) ← M1 跳过 vendor
│   ├── openai_provider.py / anthropic_provider.py
│   ├── minimax.py / xiaomi.py
│   └── spec.py           # 30+ 模型 spec
├── security/             # Workspace 沙箱 (4 文件 / 675 LOC)
├── session/              # 会话管理 (5 文件 / 1,483 LOC)
│   ├── manager.py        # SessionManager (740 LOC)
│   └── goal_state.py
├── skills/               # 内置 SKILL.md 插件 (10 目录)
├── templates/            # Prompt 模板
├── utils/                # 工具函数 (19 文件 / 3,597 LOC)
├── web/                  # Web 配置 (待补充)
└── webui/                # 内置 WebUI (11 文件 / 4,723 LOC)
```

### 1.2 整体数据流

```
┌─────────────────────────────────────────────────────────────────┐
│  Channels (Telegram/Discord/Slack/WebSocket/Web/CLI)             │
│      ↓ publish InboundMessage                                    │
│  MessageBus.queue                                                │
│      ↓ subscribe                                                 │
│  Nanobot._run()                                                  │
│      ↓                                                           │
│  CommandRouter.dispatch (priority/exact/prefix)                  │
│      ↓ (if not handled)                                          │
│  AgentLoop.process_direct(msg)                                   │
│      ↓                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  TurnState 状态机 (loop.py)                               │    │
│  │  RESTORE → COMPACT → COMMAND → BUILD → RUN →             │    │
│  │  SAVE → RESPOND → DONE                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│      ↓ (BUILD / RUN 阶段)                                        │
│  ContextBuilder.build_system_prompt                              │
│      ↓ (Memory + Skills + Bootstrap + Identity)                  │
│  AgentRunner.run (共享执行循环)                                  │
│      ↓ for iteration in max_iterations:                          │
│      ↓   LLMProvider.chat(messages, tools)                       │
│      ↓   if tool_calls: execute tools → add results              │
│      ↓   else: break                                             │
│  SessionManager.save (JSON file)                                 │
│      ↓                                                           │
│  MessageBus.publish OutboundMessage                              │
│      ↓                                                           │
│  Channels (回写到对应渠道)                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心组件拆解

### 2.1 Nanobot 入口类 (`nanobot.py`)

**职责**: 串联所有组件, 是 application-level composition root

**关键依赖** (从 AgentLoop 构造函数推断):
- `MessageBus` (publish/subscribe)
- `SessionManager` (会话存储)
- `LLMProvider` (LLM 调用)
- `SkillsLoader` (技能加载)
- `ContextBuilder` (prompt 构造)
- `SubagentManager` (子代理)
- `ChannelsConfig` (多渠道配置)
- `MCPServersConfig` (MCP 协议)
- `Hooks` 列表 (生命周期钩子)
- `Workspace` Path

**对外暴露**:
- `process_direct(content, ...)` — 同步处理入口
- `process_streaming(...)` — 流式处理入口
- `run_forever()` — 启动 bus consumer

### 2.2 AgentLoop 状态机 (`agent/loop.py`, 1724 LOC)

**核心抽象**:

```python
class TurnState(Enum):
    RESTORE = "restore"        # 加载 session
    COMPACT = "compact"        # 上下文压缩 (如有需要)
    COMMAND = "command"        # slash command 拦截
    BUILD = "build"            # 组装 messages
    RUN = "run"                # 调用 AgentRunner.run
    SAVE = "save"              # 持久化 session
    RESPOND = "respond"        # 发送 OutboundMessage
    DONE = "done"              # 结束

_TRANSITIONS: dict[TurnState, list[TurnState]] = {
    RESTORE: [COMPACT, COMMAND, BUILD],  # 视情况跳过
    COMPACT: [COMMAND, BUILD],
    COMMAND: [BUILD, DONE],               # /stop 直接 DONE
    BUILD: [RUN],
    RUN: [SAVE, RESPOND, DONE],
    SAVE: [RESPOND],
    RESPOND: [DONE],
    DONE: [],
}
```

**process_direct 流程**:
```python
async def process_direct(self, msg: InboundMessage) -> OutboundMessage | None:
    state = TurnState.RESTORE
    ctx = TurnContext(msg=msg, session=None, ...)

    while state != TurnState.DONE:
        next_states = _TRANSITIONS[state]
        # 执行当前 state 的 handler
        if state == TurnState.RESTORE:
            ctx.session = await self.session_manager.get_or_create(msg.session_key)
        elif state == TurnState.COMPACT:
            await self._maybe_compact(ctx)
        elif state == TurnState.COMMAND:
            result = await self.command_router.dispatch(CommandContext(msg, ctx.session, ...))
            if result is not None:
                return result  # 命令已处理, 跳过后续
        elif state == TurnState.BUILD:
            ctx.messages = await self.context_builder.build(ctx)
        elif state == TurnState.RUN:
            ctx.result = await self.runner.run(AgentRunSpec(messages=ctx.messages, ...))
        elif state == TurnState.SAVE:
            await self.session_manager.save(ctx.session, ctx.result.messages)
        elif state == TurnState.RESPOND:
            return OutboundMessage(content=ctx.result.final_content, ...)

        state = next(...)  # 推进状态
```

### 2.3 AgentRunner 共享执行循环 (`agent/runner.py`, 1348 LOC)

**职责**: 纯函数式的 LLM + tools 循环, 与状态机解耦, 可独立复用

**核心 dataclass**:

```python
@dataclass(slots=True)
class AgentRunSpec:
    initial_messages: list[dict]
    tools: ToolRegistry
    model: str
    max_iterations: int = 40
    max_tool_result_chars: int = 50000
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    hook: AgentHook | None = None
    error_message: str | None = None
    workspace: Path | None = None
    session_key: str | None = None
    context_window_tokens: int | None = None
    context_block_limit: int | None = None
    provider_retry_mode: str = "standard"
    progress_callback: Any | None = None
    stream_progress_deltas: bool = True
    llm_timeout_s: float | None = None
    goal_active_predicate: Callable[[], bool] | None = None
    # ... 25+ 字段

@dataclass(slots=True)
class AgentRunResult:
    final_content: str | None
    messages: list[dict]
    tools_used: list[str]
    usage: dict[str, int]
    stop_reason: str = "completed"
    error: str | None = None
```

**关键常量**:
- `_MAX_EMPTY_RETRIES = 2`
- `_MAX_LENGTH_RECOVERIES = 3`
- `_MAX_INJECTIONS_PER_TURN = 3`
- `_MAX_INJECTION_CYCLES = 5`
- `_MICROCOMPACT_KEEP_RECENT = 10`
- `_MICROCOMPACT_MIN_CHARS = 500`
- `_COMPACTABLE_TOOLS = frozenset({"read_file", "exec", "grep", "find_files", ...})`

**Runner.run 流程** (简化):
```python
async def run(self, spec: AgentRunSpec) -> AgentRunResult:
    messages = list(spec.initial_messages)
    tools_used = []
    total_usage = {}
    stop_reason = "completed"
    
    for iteration in range(spec.max_iterations):
        # 1. Hook: before_iteration
        if spec.hook:
            await spec.hook.before_iteration(AgentHookContext(iteration=iteration, messages=messages))
        
        # 2. 调用 LLM
        response = await self.provider.chat(
            messages=messages,
            tools=spec.tools,
            model=spec.model,
            temperature=spec.temperature,
            ...
        )
        
        # 3. Hook: on_stream (流式回调)
        if spec.hook:
            await spec.hook.on_stream(...)
        
        # 4. 处理 tool_calls
        if response.tool_calls:
            # Hook: before_execute_tools
            results = await self._execute_tools(response.tool_calls, spec)
            messages.extend(self._format_tool_results(response.tool_calls, results))
            tools_used.extend([tc.name for tc in response.tool_calls])
            continue
        
        # 5. 无 tool_calls, 结束
        stop_reason = "completed"
        break
    
    return AgentRunResult(
        final_content=response.content,
        messages=messages,
        tools_used=tools_used,
        usage=total_usage,
        stop_reason=stop_reason,
    )
```

### 2.4 AgentHook 生命周期钩子 (`agent/hook.py`, 141 LOC)

**核心 dataclass**:
```python
@dataclass(slots=True)
class AgentHookContext:
    iteration: int
    messages: list[dict]
    response: LLMResponse | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    streamed_content: bool = False
    streamed_reasoning: bool = False
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None
```

**可重写方法** (默认空操作):
- `wants_streaming() -> bool`
- `before_iteration(context)`
- `on_stream(context, delta)`
- `on_stream_end(context, *, resuming)`
- `before_execute_tools(context)`
- `emit_reasoning(reasoning_content)`
- `emit_reasoning_end()`
- `after_iteration(context)`
- `finalize_content(context, content) -> str | None`

**CompositeHook**: fan-out, async 方法错误隔离 (一个 hook 抛错不影响其他).

### 2.5 ContextBuilder (`agent/context.py`, 266 LOC)

**职责**: 拼装 system prompt

**组装顺序** (`build_system_prompt`):
1. **Identity** (`identity.md` template + workspace path + OS)
2. **Bootstrap files** (`AGENTS.md` / `SOUL.md` / `USER.md`)
3. **Tool contract** (`tool_contract.md`)
4. **Memory** (`MEMORY.md`)
5. **Active skills** (always-loaded skills)
6. **Skills summary** (其他 skills 索引)
7. **Recent history** (last 50 entries, capped at 32k chars)
8. **Archived session summary** (来自 consolidation)

**关键常量**:
- `_MAX_RECENT_HISTORY = 50`
- `_MAX_HISTORY_CHARS = 32_000`

### 2.6 SkillsLoader (`agent/skills.py`, 242 LOC)

**职责**: 加载 skill 插件 (markdown + YAML frontmatter)

**Skill 文件格式**:
```
skills/weather/SKILL.md
---
name: weather
requires:
  bins: [curl]
  env: [OPENWEATHER_API_KEY]
---

# Weather skill instructions
...
```

**加载逻辑**:
1. 扫描 `workspace/skills/` (用户级) + `nanobot/skills/` (内置)
2. 解析 YAML frontmatter (用 `yaml` 库)
3. 过滤 `disabled_skills`
4. 过滤 `requires` 不满足的 skills
5. 支持 `get_always_skills()` 总是加载

### 2.7 MessageBus (`bus/queue.py` + `bus/events.py`, 156 LOC 总)

**职责**: 进程内异步消息总线 (替代 MQ)

**事件类型**:
```python
@dataclass
class InboundMessage:
    channel: str          # telegram/discord/slack/whatsapp
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{chat_id}"

@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    buttons: list[list[str]] = field(default_factory=list)
```

**特殊 metadata key**:
- `OUTBOUND_META_AGENT_UI = "_agent_ui"` (rich UI payload, JSON-serializable)
- `INBOUND_META_RUNTIME_CONTROL = "_runtime_control"` (内部 runtime 控制)
- `RUNTIME_CONTROL_MCP_RELOAD = "mcp_reload"` (MCP 重载命令)

### 2.8 CommandRouter (`command/router.py`, 88 LOC)

**职责**: 3-tier slash command dispatch

**3 个 tier**:
1. **priority** — 精确匹配, 在 lock 外执行 (如 `/stop`, `/restart`)
2. **exact** — 精确匹配, 在 lock 内执行
3. **prefix** — 前缀匹配, longest-first (如 `/team `)

**CommandContext**:
```python
@dataclass
class CommandContext:
    msg: InboundMessage
    session: Session | None
    key: str
    raw: str           # "/stop"
    args: str = ""     # "/stop arg1 arg2" → "arg1 arg2"
    loop: Any = None   # 注入 AgentLoop (供 /status 等查询用)
```

### 2.9 SessionManager (`session/manager.py`, 740 LOC)

**职责**: 会话持久化 (JSON 文件存储, **非 SQLite**)

**Session dataclass**:
```python
@dataclass
class Session:
    key: str                           # channel:chat_id
    messages: list[dict[str, Any]]     # 完整消息历史
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
    last_consolidated: int = 0         # 已 consolidate 的消息数
```

**关键常量**:
- `FILE_MAX_MESSAGES = 2000`
- `_SESSION_PREVIEW_MAX_CHARS = 120`

**Sanitize helpers**:
- `_MESSAGE_TIME_PREFIX_RE` — 去除 `[Message Time: ...]` 内部时间戳
- `_LOCAL_IMAGE_BREADCRUMB_RE` — 去除 `[image: /path]` 面包屑
- `_TOOL_CALL_ECHO_RE` — 去除 tool call echo (`generate_image(...)`)

### 2.10 MemoryStore (`agent/memory.py`, 1161 LOC)

**职责**: 长期记忆 (文件系统)

**文件**:
- `MEMORY.md` — 策划后的精华 (LLM 总结)
- `history.jsonl` — 原始历史 (JSONL, 增量写)
- `SOUL.md` / `USER.md` — bootstrap 文件
- `.cursor` / `.dream_cursor` — 处理游标

**子组件**:
- `Consolidator` — LLM 驱动的 history → MEMORY.md 压缩
- `Dream` — 后台进程, 离线深度整理
- `GitStore` — 关键文件 git 版本控制 (SOUL.md / USER.md / MEMORY.md)

### 2.11 API Server (`api/server.py`, 399 LOC)

**职责**: OpenAI-compat HTTP API (基于 aiohttp)

**端点**:
- `POST /v1/chat/completions` (含流式 SSE)
- `GET /v1/models`

**特性**:
- 单例 session (`API_SESSION_KEY = "api:default"`)
- 完整 OpenAI 兼容 chunk 格式
- 错误格式: `{"error": {"message": ..., "type": ..., "code": ...}}`
- 支持 base64 上传 (FILE_SIZE limit)
- `data: [DONE]` 标准结束符

### 2.12 LLMProvider ABC (`providers/base.py`, 843 LOC) ← M1 已跳过 vendor

**核心抽象**:
```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages, tools, model, ...) -> LLMResponse: ...
    
    @abstractmethod
    def get_context_window(self, model) -> int: ...
    
    @abstractmethod
    def supports_progress_deltas(self) -> bool: ...
    
    # 运行时切换
    def apply_snapshot(self, snapshot: dict) -> None: ...
    
    # factory
    @classmethod
    def from_config(cls, config) -> "LLMProvider": ...
```

**LLMResponse dataclass**: content + tool_calls + usage + stop_reason + reasoning

---

## 3. 与 llmwikify 的逐项对比

### 3.1 顶层入口

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 入口类 | `Nanobot` | `AgentService` (composition root) |
| 依赖数 | 23+ | 7 |
| LOC | (跨多个文件) | 310 LOC (agent_service.py) |
| 服务模型 | 单 mega-loop + 多 channel | 5+1 service composition |

### 3.2 Agent 循环

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 主循环 | `AgentLoop` (TurnState 状态机, 1724 LOC) | `ChatOrchestrator` (664 LOC, 28 方法, 扁平) |
| 执行循环 | `AgentRunner.run()` (独立 1348 LOC, 可复用) | `ChatReactAgent.run()` (711 LOC, 嵌入 orchestrator) |
| 子代理 | `SubagentManager` (392 LOC, async 后台) | 无 (m3 阶段重构) |
| 状态恢复 | 从 Session reload | 无 (session 隔离) |

### 3.3 Context 组装

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 组装器 | `ContextBuilder` (266 LOC, 独立类) | 内联在 orchestrator (`build_messages`) |
| Bootstrap 文件 | AGENTS.md / SOUL.md / USER.md | 无 |
| Skills | markdown + YAML frontmatter | Python 业务代码 (81 actions) |
| Memory | file I/O + GitStore + Consolidator + Dream | SQLite (`research_*` 表) |

### 3.4 LLM 调用

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 抽象 | `LLMProvider` ABC + `from_config()` | `StreamableLLMClient` Protocol (1509 LOC) |
| 提供商 | OpenAI / Anthropic / MiniMax / Xiaomi | MiniMax / Xiaomi |
| 重试 | 标准 / 429 fine classification / 欠费检测 | M1 已借 4 模式 (commit 2c59227) |
| Thinking 风格 | `thinking_style` map (10+ 风格) | M1 已借 (`build_thinking_extra_body`) |

### 3.5 消息总线

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 总线 | `MessageBus` (103 LOC, 进程内 pub/sub) | 无 (直接调用) |
| 事件 schema | `InboundMessage` / `OutboundMessage` (dataclass) | `RunState` (sqlite row) |
| 多渠道 | channels/ 19f/16475L (Telegram/Discord/Slack/WhatsApp/WebSocket/Web) | HTTP/SSE only (chat_sse.py 479 LOC) |
| WebSocket | `channels/websocket.py` (1907 LOC, 完整双向) | 无 |

### 3.6 会话管理

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 存储 | JSON 文件 (per-session) | SQLite (`sessions` + `messages` 表) |
| 压缩 | `Consolidator` (LLM-driven) + `Dream` (后台) | 无 |
| 文件格式 | 1 file per session | 1 row per message (查询友好) |
| 上限 | `FILE_MAX_MESSAGES = 2000` | 无显式上限 |

### 3.7 命令路由

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 路由 | `CommandRouter` (88 LOC, priority/exact/prefix 3-tier) | 无 (slash command 内联在 orchestrator) |
| Lock | priority 外锁 / exact+prefix 内锁 | 无并发控制 |

### 3.8 钩子系统

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 钩子 | `AgentHook` (141 LOC, 9 钩子点) | 无显式钩子 (通过 callback) |
| 隔离 | `CompositeHook` (fan-out + 错误隔离) | 无 |

### 3.9 Skills

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| **概念** | **prompt 文档** (SKILL.md, markdown) | **Python 业务函数** (skill_adapter.py, 81 actions) |
| 数量 | 内置 10 + 用户扩展 | 81 actions (10,185 LOC) |
| 加载 | YAML frontmatter + requires 检查 | 注册表 (dict) |
| 路径 | workspace/skills/ + nanobot/skills/ | apps/chat/skills/ |

> ⚠️ **关键发现**: nanobot 的 skills 是 markdown prompt 文档 (教 LLM 怎么用工具), 而 llmwikify 的 skills 是 Python 函数 (实际业务逻辑). 两者**完全不同的概念**, 不能直接 vendor. A6 候选需要重新设计: 是借 loader (YAML frontmatter), 还是 vendor markdown skill 模式到 Python skill?

### 3.10 HTTP API

| 维度 | nanobot | llmwikify |
|------|---------|-----------|
| 框架 | aiohttp (async native) | FastAPI (sync wrapper) |
| OpenAI 兼容 | ✅ (`/v1/chat/completions`, `/v1/models`) | ❌ (自定义 `/api/chat/stream`) |
| SSE | 标准 OpenAI chunk 格式 | 自定义 (`type: save_warning`) |
| LOC | 399 | 588 (routes.py) + 479 (chat_sse.py) |

---

## 4. 关键技术洞察

### 4.1 范式差异: 状态机 vs 扁平方法

**nanobot**: AgentLoop 是显式 TurnState 状态机
- 优点: 状态转换明确, 易追踪, 易测试, 易插入新 state
- 优点: 与外部事件 (bus) 解耦
- 缺点: 8 个 state 各自有 handler, 代码量大 (1724 LOC)

**llmwikify**: ChatOrchestrator 是扁平 28 方法
- 优点: 简单直接, 一目了然
- 缺点: 状态转换隐式, 难追踪 (看 `process()` 才知道流程)
- 缺点: 子代理、并发、cancel 等扩展困难

**借鉴建议**: A3 (重写 agent/loop.py) 不应盲目 vendor, 应先抽取 llmwikify 隐式状态为 TurnState, 然后评估是否需要 8 个 state (可能 5 个就够).

### 4.2 解耦策略: AgentRunner 独立化

**nanobot** 最值得借鉴的设计: `AgentRunner.run()` 是**纯函数式**的执行循环, 与 AgentLoop 完全解耦. 任何模块 (含 SubagentManager) 都可复用 Runner.

**llmwikify 现状**: `ChatReactAgent.run()` 嵌入 orchestrator, 难以独立测试和复用.

**借鉴建议**: 即使不 vendor nanobot Runner, 至少应将 llmwikify 的 React 循环抽成独立 dataclass-based API. 这比 A3 风险小.

### 4.3 错误隔离: CompositeHook 模式

**nanobot** 的 CompositeHook 模式 (fan-out + 错误隔离) 解决了多 hook 互不干扰的问题. 一个 hook 抛错, 其他照常工作.

**llmwikify 现状**: callback 链式调用, 一个 callback 抛错整链挂掉.

**借鉴建议**: 抽取 `CallbackChain` 工具类 (M2 之后).

### 4.4 Skills 概念不可移植

**nanobot skills**: prompt 文档, 教 LLM 怎么用
**llmwikify skills**: Python 业务函数, 实际执行

**结论**: A6 (skills plugin loader) 应**只借 loader 的 YAML frontmatter 模式** (用于插件元数据声明), 不能借 skill 本身. llmwikify 的 Python 业务函数需要其他方案 (entry_points? dynamic import?).

### 4.5 Session 存储选择

**nanobot**: JSON 文件 (per-session, 1 file)
- 优点: 简单, 易备份, 易 git
- 缺点: 大 session 加载慢, 无事务

**llmwikify**: SQLite (1 row per message)
- 优点: 查询快, 事务安全
- 缺点: 复杂查询需要 SQL

**结论**: llmwikify 不应改用文件存储. A4 (bus + session) 应**只借 Session dataclass 设计**, 保留 SQLite 后端.

### 4.6 Thinking 风格 vs Thinking 类型

**nanobot**: `thinking_style` (语义化字符串, 如 "reasoning_split", "budget_tokens")
**llmwikify**: `reasoning_split` (单一字段, 兼容多个 LLM)

**M1 决策已部分借鉴**: `build_thinking_extra_body(style, on)` 已支持多种 style. 但**仅借鉴 4 模式**, 未完整 vendor 10+ 风格.

**后续**: 如需更多风格, 直接扩展 `_THINKING_STYLE_BUILDERS` 字典.

---

## 5. Phase 3 输入: A1-A6 实施优先级建议

基于本章框架理解, 重新排序 A1-A6 候选:

| 优先级 | 候选 | 复杂度 | 风险 | 价值 | 决策 |
|--------|------|--------|------|------|------|
| **P0** | **A2** OpenAI-compat API vendor | 低 | 低 | 高 | ✅ 推荐 |
| **P1** | A1 WebSocket vendor | 中 | 中 | 中 | ⏸ 评估需求 |
| **P2** | A5 Anthropic native vendor | 中 | 低 | 中 | ⏸ 评估需求 |
| **P3** | **A3' Runner 独立化** (非 vendor) | 中 | 低 | **高** | ✅ 推荐 |
| **P4** | A4 bus + session (只借设计) | 高 | 高 | 中 | ⚠ 谨慎 |
| **P5** | A6 skills plugin loader (只借 frontmatter) | 中 | 中 | 低 | ⚠ 重新评估 |

**核心建议**:
- **P0 (A2)**: nanobot api/server.py 仅 399 LOC, vendor 风险最低, 立即获得 OpenAI 生态接入.
- **P3 (A3')**: 不 vendor nanobot runner, 而是**重构 llmwikify ChatReactAgent 为 dataclass-based 独立 API**. 这是最小风险最大价值的借鉴.
- **A1/A5**: 仅在用户明确需要 WebSocket / Anthropic 时再做.
- **A4/A6**: 风险高, 先做小 POC 验证.

---

## 6. 待补 / 未读文件

为完整覆盖, 以下文件未在 Phase 2 阅读 (优先级低):

- `nanobot.py` 主类 (只看了入口推断)
- `nanobot/__main__.py` CLI 入口
- `nanobot/cron/` 定时任务
- `nanobot/pairing/` 配对授权
- `nanobot/security/` workspace 沙箱
- `nanobot/web/` web 配置
- `nanobot/utils/` 19 文件 (helpers.py 已读过, 其余略)

Phase 3 (apply-plan.md) 不需要这些, 跳过.
