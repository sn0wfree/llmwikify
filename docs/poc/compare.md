# compare.md — llmwikify chat vs nanobot 深度对比

> Date: 2026-06-17
> nanobot tag: v0.2.1 (`f309982 chore(release): update version to 0.2.1`)
> nanobot source: `/tmp/nanobot/nanobot/`
> llmwikify source: `/home/ll/llmwikify/src/llmwikify/`

---

## 0. TL;DR

- **nanobot** = 完整 agent runtime (channels + agent + providers + webui)
- **llmwikify** = wiki 研究工具 + 简单 chat (apps/chat + foundation/llm + interfaces/server)
- **总 LOC**: nanobot 57,266 vs llmwikify chat ~26,500 (2.2x)
- **核心差异**: nanobot 是"通用代理", llmwikify 是"专业工具"
- **直接 import 整个 nanobot 不合理**, 但 **借模式 + 补缺失功能** 价值高

---

## 1. nanobot 全量结构 (22 子模块, 57,266 LOC)

| Submodule | Files | LOC | 内容 |
|---|---|---|---|
| **channels** | 19 | **16,475** | 9 channel 适配器 (websocket, telegram, discord, slack, email, wecom, weixin, feishu, signal, msteams, dingtalk, qq, matrix, whatsapp, mochat) |
| **agent** | 35 | **13,333** | loop.py (1724) + runner + context + autocompact + subagent + skills + tools/ + memory + hook |
| **providers** | 16 | **8,050** | 6 backend + 30+ ProviderSpec + retry machinery |
| **webui** | 11 | **4,723** | 内置 WebUI |
| **cli** | 5 | **3,535** | 命令行入口 + service |
| **utils** | 19 | **3,597** | helpers + runtime + document + llm_runtime |
| **session** | 5 | **1,483** | SessionManager + goal_state + turn_continuation + webui_turns |
| **config** | 4 | **810** | TOML schema + loader + paths |
| **cron** | 3 | **765** | 定时任务 |
| **command** | 3 | **745** | CommandRouter + builtin commands |
| **skills** | 3 | **743** | skill 插件框架 (框架代码, 插件本身在仓根 `skills/`) |
| **security** | 4 | **675** | workspace_access + workspace_policy + network |
| **bus** | 3 | **103** | 极简事件总线 (events + queue) |
| **api** | 2 | **400** | OpenAI-compatible server |
| **web** | 1 | 8 | web 入口 |
| **其他 (apps, pairing, etc.)** | 4+ | ~5,000 | cron/apps/web/nanobot.py 等 |

**关键观察**:
- 主体代码 **60%+** 在 `channels (29%) + agent (23%) + providers (14%)`
- `bus/` 仅 103 LOC — 极简 pub/sub
- `api/` 仅 400 LOC — OpenAI-compat server 实现紧凑
- `skills/` 框架代码只 743 LOC, 实际 skill 插件 (weather/cron/tmux/github...) 在仓库根目录 `skills/` 而非包内

---

## 2. llmwikify chat 结构 (~26,500 LOC)

| Submodule | Files | LOC | 内容 |
|---|---|---|---|
| **apps/chat/skills/** | 55 | **10,185** | 81 actions + CRUD + pipelines + workflows + service (**业务核心 39%**) |
| **apps/chat/** (root) | 18 | ~7,000 | agent_service.py + db.py (926) + state.py + research_agent.py + prompts.py |
| **apps/chat/agent/** | 15 | **3,912** | orchestrator (664) + chat_react (711) + react_engine + react_loop + tool_executor + context_manager + bridge_backend + research_bridge |
| **apps/chat/harness/** | 7 | 1,100 | eval framework |
| **apps/chat/memory/** | 1 | 473 | memory.py |
| **apps/chat/providers/** | 5 | 321 | 2 providers (MiniMax, Xiaomi) + registry + base |
| **foundation/llm/** | 10 | **2,688** | streamable.py (1509) + spec + resolver + budget + context_windows |
| **interfaces/server/http/** | 9 | **2,875** | chat_sse (479) + routes (588) + factor (576) + paper (761) + reproduction + middleware |

**关键观察**:
- **skills/ 占 llmwikify 39%** — 业务核心, nanobot 没有对应物
- agent/ 模块化更细 (15 文件, 单文件 <800 LOC), nanobot 反之 (35 文件, 单文件更小)
- **没有 event bus** — llmwikify 直接函数调用, 无 pub/sub
- **没有 session 抽象** — 用 db.py + state.py + session.py 拼凑
- **没有 channel 多端** — 仅 HTTP/SSE
- **没有 OpenAI-compat API endpoint** — 仅内部 HTTP

---

## 3. 架构差异 (5 个关键点)

### 3.1 "Skill" 含义完全不同

| | nanobot | llmwikify |
|---|---|---|
| **"skill" 是什么** | **外部插件** (weather/cron/github/tmux/summarize), 每个 skill 是目录 + SKILL.md + scripts/ | **业务动作** (81 个 wiki/research/synthesis 操作), 注册到 skill registry |
| **skill 数量** | 12 (clawhub, cron, github, weather, image-generation, memory, my, skill-creator, summarize, tmux, update-setup, long-goal) | **81 actions + CRUD + workflows** |
| **可重用性** | 跨项目通用 (天气/GitHub/tmux 之类) | llmwikify 专属业务 (wiki 查询/research 流程) |
| **结论** | ❌ 不能直接 import skill 框架 (语义不同) | ✅ llmwikify 自身比 nanobot 更"重" |

### 3.2 Event Bus 有无

| | nanobot | llmwikify |
|---|---|---|
| **架构** | `bus/queue.py` (pub/sub, 103 LOC) | ❌ 无 — 直接函数调用 |
| **优势** | channel/agent/UI 完全解耦 | 简单直接 |
| **改架构成本** | 高 | 高 |
| **结论** | 🟡 借鉴模式, 但**不要**全盘改写 | 改写成本 > 收益 |

### 3.3 Session 模型

| | nanobot | llmwikify |
|---|---|---|
| **抽象** | `SessionManager` (1.5k LOC) + `Session` 类 + `goal_state` + `turn_continuation` | `db.py` + `state.py` + `session.py` (拼凑) |
| **持久化** | 内部 JSON 文件 (`sessions/`) | SQLite (21 tables, 308 orphan rows) |
| **目标不同** | 多 channel 共享 session | 单 chat UI, session 绑 assistant message |
| **结论** | ❌ storage 不同, 不能直接 import | 借鉴 `SessionManager` 思路重写 |

### 3.4 Provider 抽象

| | nanobot | llmwikify |
|---|---|---|
| **抽象** | ABC `LLMProvider` + 30+ `ProviderSpec` + 6 backend (8k LOC) | Protocol `LLMProvider` + 2 concrete + `BaseLLMProvider` helpers (321 LOC) |
| **能力** | Anthropic/OpenAI/Azure/Bedrock/Codex/Copilot + 30+ spec | 仅 MiniMax + Xiaomi |
| **结论** | 🟢 借: 补 Anthropic/Bedrock/etc. | 实施 F2 (Anthropic native) |

### 3.5 Agent Loop 抽象

| | nanobot | llmwikify |
|---|---|---|
| **状态机** | `TurnState` 8 态: RESTORE → COMPACT → COMMAND → BUILD → RUN → SAVE → RESPOND → DONE | `ReActEngine` + `Orchestrator` + `ToolExecutor` 多模块分散 |
| **代码量** | 13,333 LOC (含 tools/, subagent, memory, hooks) | 3,912 LOC (更聚焦) |
| **复用潜力** | ⭐⭐⭐ 高 — 用户主痛 | — |
| **结论** | 🟡 整体迁移成本高, **思路可借鉴** | 实施: 借鉴 TurnState 状态机, 重写 agent/ 子模块 |

---

## 4. 全局统计对比

| 维度 | nanobot | llmwikify | 比值 |
|---|---|---|---|
| 总 LOC | 57,266 | 26,500 | **2.2x** |
| 文件数 (估) | ~250 | 106 | 2.4x |
| 外部依赖 | 多 (anthropic/openai/loguru/...) | 少 | — |
| Agent 抽象 | 13k LOC, 状态机 8 态 | 4k LOC, 多模块分散 | 3.3x |
| Provider 数 | 30+ | 2 | **15x** |
| Channel 数 | 9 (websocket/telegram/discord/...) | 0 | ∞ |
| Skills/Plugins | 12 + 框架 743 LOC | 81 actions + 框架 10k LOC | 业务深度: llmwikify 胜 |

**结论**: nanobot 是个 **完整 agent runtime**, llmwikify 是 **wiki 研究工具 + 简单 chat**. 两者目标不同.

---

## 5. 模块级深度对比

### 5.1 `providers/` (nanobot 8,050 LOC vs llmwikify 321 LOC)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 抽象 | ABC `LLMProvider` (843 LOC) + 数据类 (LLMResponse/ToolCallRequest) | Protocol `LLMProvider` (64 LOC) + 2 helper |
| 注册 | `ProviderSpec` dataclass + `factory.make_provider()` 派发 | 装饰器 `register_provider` + dict |
| Retry | `_run_with_retry` (500 LOC) + 429 分类 + arrearage | `_compute_backoff` + `_is_retryable_status` (streamable.py 1509 LOC) |
| Backend 数 | 6 (openai_compat/anthropic/azure/codex/copilot/bedrock) | 0 (用 OpenAI-compat 协议) |
| Provider 数 | 30+ (含 MiniMax/xiaomi_mimo) | 2 (MiniMax + Xiaomi) |

**已有借鉴 (M1 commit `2c59227`)**: 4 patterns 已搬到 `streamable.py` (429 分类 / arrearage / thinking style map / role alternation).

**继续借鉴候选**:
- 30+ `ProviderSpec` 元组 → 可直接搬过来作为新 provider 候选清单
- `_THINKING_STYLE_BUILDERS` map → 已借, 待集成到 retry 路径
- 6 backend 抽象 → 可选 vendor (优先级低, 仅当补 provider 时)

### 5.2 `agent/` (nanobot 13,333 LOC vs llmwikify 3,912 LOC)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 入口 | `nanobot.py:Nanobot` (104 LOC) + `agent/loop.py:AgentLoop` (1724 LOC) | `apps/chat/agent/agent_service.py` (估 600+) |
| 状态机 | `TurnState` 8 态 (RESTORE→COMPACT→COMMAND→BUILD→RUN→SAVE→RESPOND→DONE) | 隐式 — orchestrator.py 28 methods 散落各处 |
| Subagent | `subagent.py` (支持嵌套 agent) | 无 |
| Memory | `memory.py` (Dream/Consolidator) | `apps/chat/memory/` (1 文件 473 LOC, 简单) |
| Hook | `hook.py` (lifecycle 拦截) | 无 |
| AutoCompact | `autocompact.py` (上下文自动压缩) | 无 |
| Progress | `progress_hook.py` | `event_log.py` (轻量) |
| Runner | `runner.py` (消息累积+turn 切片) | `chat_react.py` (ReAct 风格) |
| Skills integration | `skills.py` (加载 skill 插件) | `skills/service.py` (注册 81 actions) |
| Tools | `tools/` (registry, file_state, context, message) | `tool_executor.py` (单文件) |

**借鉴方向**:
- ✅ **TurnState 状态机**: 直接借鉴思路, 重写 `orchestrator.py` 为状态机
- ✅ **AutoCompact**: 用户长对话时 context 爆炸, 这是真实痛点
- ✅ **Hook 系统**: 借 lifecycle 拦截, 现有 `_error_logging.py` 可扩展
- 🟡 Subagent / Memory: 优先级中, 现有 memory.py 简化版可用

### 5.3 `session/` (nanobot 1,483 LOC vs llmwikify 散落)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 核心 | `SessionManager` + `Session` 类 | 无单一管理器 |
| 状态 | `goal_state.py` (sustained goal tracking) | `state.py` (ResearchState 单一 case) |
| 持续化 | JSON 文件 | SQLite |
| Turn 切片 | `turn_continuation.py` | `agent_service.py` 内隐式 |
| WebUI 协调 | `webui_turns.py` | `event_log.py` |
| LOC 估算 | ~1,500 | ~500 (state.py + session.py + 部分 db.py) |

**借鉴方向**:
- 🟡 SessionManager 抽象: 价值中, llmwikify 现有 state.py 已覆盖核心场景
- 🟢 `turn_continuation.py`: **可直接借鉴** (multi-turn continuation 思路)

### 5.4 `bus/` (nanobot 103 LOC vs llmwikify 无)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 模块 | `events.py` (InboundMessage/OutboundMessage) + `queue.py` (MessageBus) | 无 |
| LOC | 103 | 0 |

**借鉴方向**:
- 🟡 **不直接 vendor**: llmwikify 当前架构是直接函数调用, 引入 bus 改造成本高
- 🟢 **借鉴模式**: 未来如要解耦 channel, 可借鉴 `events.py` 模式 (Message dataclass + 字段)

### 5.5 `channels/websocket.py` (nanobot 1,907 LOC vs llmwikify 无)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 协议 | WebSocket (port 8765) | 仅 SSE (port 8765) |
| 集成 | 9 channel 都通过统一 channel manager 注册 | — |

**借鉴方向**:
- 🟢 **Vendor 整个文件** (1,907 LOC): port 8765 已有, 直接套用
- 🟡 与现有 chat_sse.py (479 LOC) 并存, 路由分发

### 5.6 `api/` (nanobot 400 LOC vs llmwikify 无)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 模块 | `server.py` (OpenAI-compatible `/v1/chat/completions`) | 无 |
| LOC | 400 | 0 |

**借鉴方向**:
- 🟢 **Vendor + 适配** (400 LOC): 高价值, 任何 OpenAI 客户端可接入 llmwikify
- 🟢 集成到 `interfaces/server/http/routes.py` (588 LOC)

### 5.7 `command/` (nanobot 745 LOC vs llmwikify skills)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 模块 | `router.py` (CommandRouter) + `builtin.py` | `apps/chat/skills/registry.py` |
| 命令数 | 10+  builtin | 81 actions |
| LOC | 745 | 228 (registry.py) + service.py + runtime.py |

**借鉴方向**:
- 🟡 思路类似 (slash command → handler), 不需直接 vendor
- 🟢 如未来加 slash command (`/study` 已是), 可借鉴 `router.py` 模式

### 5.8 `security/` (nanobot 675 LOC vs llmwikify 无)

| 维度 | nanobot | llmwikify |
|---|---|---|
| 模块 | workspace_access + workspace_policy + network | 无 |
| LOC | 675 | 0 |

**借鉴方向**:
- 🟡 **低优先级**: llmwikify 当前不暴露 file system 操作给 LLM, 风险低
- 🟢 如未来加 file/skills tools, 必借鉴

### 5.9 `webui/` (nanobot 4,723 LOC)

**结论**: 跳过 (Tier 3). llmwikify 已有 `ui/webui/` 外部 UI.

---

## 6. 应用方向 (6 个候选, 价值/成本排序)

| # | 来源 | 目标 | 价值 | 成本 | 策略 | 推荐顺序 |
|---|---|---|---|---|---|---|
| **A1** | `channels/websocket.py` (1907 LOC) | llmwikify WebSocket (port 8765) | 🟢 中 | 🟡 3-5 天 | **Vendor** | 🥇 #1 |
| **A5** | `providers/anthropic_provider.py` (~400 LOC) | llmwikify Anthropic 原生 | 🟢 高 | 🟡 3-5 天 | **Vendor + 包装** | 🥈 #2 |
| **A2** | `api/server.py` (400 LOC) | OpenAI-compatible `/v1/chat/completions` | 🟢 高 | 🟡 1 周 | **Vendor + 适配** | 🥉 #3 |
| **A3** | `agent/loop.py` TurnState (8 态状态机) | agent/ 重构 (主痛) | 🟢 高 | 🔴 2-3 周 | **借鉴思路 + 重写** | #4 |
| **A4** | `bus/` + `session/manager.py` | 事件解耦 + session 管理 | 🟡 中 | 🟡 1 周 | **借鉴模式 + 重写** | #5 |
| **A6** | `skills.py` plugin loader | plugin 加载 | 🟡 中 | 🟡 3 天 | **借鉴思路** | #6 |

**建议执行顺序**: A1 → A5 → A2 → A3 → A4 → A6

---

## 7. 数据来源

### nanobot (v0.2.1)
- 克隆: `git clone --depth=1 --branch v0.2.1 https://github.com/HKUDS/nanobot.git /tmp/nanobot`
- HEAD: `f309982 chore(release): update version to 0.2.1`
- LOC 统计: `find /tmp/nanobot/nanobot -name "*.py" | xargs wc -l`
- 模块清单: `ls /tmp/nanobot/nanobot/`

### llmwikify (current HEAD: 2c59227)
- 路径: `/home/ll/llmwikify/src/llmwikify/`
- apps/chat LOC: 10185 (skills) + 7000 (root) + 3912 (agent) + 1100 (harness) + 473 (memory) + 321 (providers) ≈ 23,000
- foundation/llm LOC: 2,688
- interfaces/server/http LOC: 2,875
- 总计: ~28,500 LOC (chat 子系统)

---

## 8. 后续阶段

- **阶段 2**: 读 nanobot 关键模块 (`agent/loop.py` 1724 LOC + runner + context + subagent + memory + session/manager + command/router + bus/events), 出 `nanobot-framework.md`
- **阶段 3**: 基于框架理解, 出 `apply-plan.md` (模块级决策 + 实施顺序 + 风险矩阵)

---

## 9. 不在本范围

- ❌ 直接 import 整个 nanobot 子模块 (违反架构原则)
- ❌ 改写 llmwikify 现有架构 (event bus, session manager 等)
- ❌ 改写 ui/webui/ (Tier 3)
- ❌ 处理 Unstaged 10 文件 (用户确认先不管)
- ❌ M1 已 commit (2c59227), 不重做
