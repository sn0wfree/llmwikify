# compare.md — llmwikify chat vs nanobot 深度对比

> Date: 2026-06-19 (updated Phase 5 god class split)
> Original: 2026-06-17
> nanobot tag: v0.2.1 (`f309982 chore(release): update version to 0.2.1`)
> nanobot source: `/tmp/nanobot/nanobot/`
> llmwikify source: `/home/ll/llmwikify/src/llmwikify/`
> llmwikify HEAD: `793cf1b` (Phase 5 D5)

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

---

## 10. Phase 5 — God Class Split (2026-06-19)

> Phase 5 是 Plan B (5 步状态机) 之后的内部架构清理, **与 nanobot 借鉴无关**。
> 目标: 拆解 chat 子系统内的 4 个 god class, 借鉴 nanobot 的"小而专"模块化思路。

### 10.1 拆解目标 (4 个 god class)

| God class (前) | 形态 | LOC | 触发问题 |
|---|---|---:|---|
| `ChatOrchestrator` | 720 LOC 混合 5 职责 (chat loop + confirmation + session + executor wiring + DB) | 720 | 12 方法可独立, 单测困难 |
| `ChatDatabase` (`db.py`) | 926 LOC 混 21 表 + 27 research_delegate + 17 wiki_delegate | 926 | 单文件过大, schema 演变风险 |
| `apps/chat/chat_legacy/*` | 9 文件共 ~2,800 LOC 在 archive 但 live import 路径 | 2,800 | archive 不应被 import |
| `service.py` | 1,236 LOC 已被 B-7 删除, 3 tests 残留 | 1,236 | uncollectable tests |

### 10.2 拆解结果 (4 + 1 阶段)

#### D1: `ConfirmationManager` + `SessionManager` (`da870d9`)

从 `ChatOrchestrator` 抽出 2 个 manager, dict-by-reference 共享状态:

```python
# 前: ChatOrchestrator 12 个方法 + 散落状态
# 后: 3 文件各司其职
agent/orchestrator.py       720 LOC (chat loop only)
agent/confirmation_manager.py 86 LOC (5 confirm/reject method)
agent/session_manager.py      80 LOC (5 session lifecycle method)
```

**保留 11 个 public method 作为 1-line 委托** — 调用方零迁移, 公共 API 完全不变。

**新增测试**: `test_confirmation_manager.py` (25) + `test_session_manager.py` (13) = **38 新 cases**。

#### D3: `ChatDatabase` 拆 7 repository (`f771c0a`, **高风险**)

926 LOC god class → 7 个 repository + 1 thin facade:

```
apps/chat/db/
├── __init__.py            50 LOC (re-exports)
├── _facade.py            608 LOC (ChatDatabase thin facade, 99 methods 1-line 委托)
├── base.py                79 LOC (ChatDBBase 抽象)
├── chat_session_repo.py  166 LOC (chat_sessions 表, 8 methods)
├── chat_message_repo.py  227 LOC (chat_messages + revert_to_message 回调)
├── tool_call_repo.py     138 LOC (tool_calls + delete_after_rowid 回调)
├── permission_repo.py     90 LOC (chat_permissions 表)
├── research_delegate.py  216 LOC (27 delegates → ResearchDatabase)
├── wiki_delegate.py      133 LOC (17 delegates → WikiDatabase)
└── admin_stats_repo.py   155 LOC (5 cross-table stats)
```

**架构选择**: facade 模式, 99 个 method 都是 1-line 委托 → 调用方零迁移 (123 调用方)。
**跨表事务**: `delete_chat_session` + `revert_to_message` 在 facade 协调, 用 `tool_call_delete_after_rowid` 回调跨 repo 共享同一 SQLite connection。
**module/package 冲突解决**: `db.py` (file) + `db/` (package) 共存时 Python 优先 package, 故 facade 移入 `db/_facade.py`。

**新增测试**: 7 test files + 106 cases (session 18 / message 16 / tool 16 / permission 10 / admin 10 / research 17 / wiki 19)。

#### D4: inline `chat_legacy/` → `research_engine/` (`4c469fe`)

把 v0.41 6-step framework 从 `archive/llmwikify_v0_41_legacy/chat_legacy/` (9 文件) git mv 到 `apps/chat/research_engine/`:

```
research_engine/
├── __init__.py     44 LOC (re-exports + back-compat aliases)
├── engine.py      410 LOC (ResearchEngine)
├── actions.py     877 LOC (8 action functions + ActionContext)
├── gates.py       274 LOC (ResearchGates)
├── llm_step.py    237 LOC (run_prompt)
├── observer.py    135 LOC (ResearchObserver)
├── reasoner.py    239 LOC (ResearchReasoner)
├── report.py      289 LOC (ReportGenerator)
├── resume.py      185 LOC (ResearchResumeLoader)
└── routes.py      312 LOC (legacy autoresearch FastAPI router)
```

**back-compat**: `apps/chat/__init__.py` 末段 `sys.modules` 注入 9 aliases (`llmwikify.apps.chat.{engine,actions,gates,...}`) — 旧调用 `from llmwikify.apps.chat import engine` 仍可用。
**修复**: `actions.py` 用 `TYPE_CHECKING` 懒导入 `ResearchClarifier` (原循环 import)。
**archive 真正冻结**: `archive/chat_legacy/` 删除空目录, `git grep` 验证 0 live imports。

#### D5: 3 dead archive tests 清理 (`793cf1b`)

B-7 (`98a47bd`) 已删除 `service.py` (1,236 LOC), 但 3 tests 因 `from llmwikify.apps.chat.agent.service import` (无 archive 前缀) 残留, pytest collection error。

**迁移 18 个 uncovered scenario** → `tests/test_apps_chat_agent_context_manager.py`:
- `TestAgentContext` (5): state mgmt + copy semantics
- `TestCompaction` (5): disabled / too-few / below-threshold / reduces / fail-fallback
- `TestTruncation` (7): short / long / system-preserved / fallback / empty / single / override
- `TestPrepareMessages` (1): compact + truncate 集成

**净 diff**: -1,742 (3 dead tests) + 264 (新 test) = -1,478 LOC。

### 10.3 借鉴的 nanobot 模式 (Phase 5 副产品)

| 模式 | nanobot 来源 | llmwikify 实施 | LOC |
|---|---|---|---:|
| **State Trace** | `nanobot.agent.observability.StateTraceEntry` | `apps/chat/agent/runner_v2.py:60` `_StateTraceEntry` + `_StateTrace` CM + `self._current_ctx` | 85 |
| **Microcompact** | `nanobot.agent.autocompact._COMPACTABLE_TOOLS` | `apps/chat/agent/microcompact.py` (默认 ON, keep_chars=1000) | 85 |
| **13 钩子点 CompositeHook** | `nanobot.agent.hook.Hook` (8 态 lifecycle) | `foundation/callback/composite.py` 13 钩子点 + `CompositeHook` fan-out + `_maybe_await` | 170 |

**State Trace 设计要点** (借鉴 nanobot 而非 vendor):
- `_StateTraceEntry` 5 字段 (step / status / elapsed_ms / iteration / message_count)
- `_StateTrace` CM 包裹主循环 5 步, 失败仍记录
- `ChatRunResult.state_trace` 默认空 list, runner_v2 通过 `self._current_ctx` 传递

**Microcompact 借鉴清单** (`apply-plan.md:§5.1`):
- 7 compactable tools: `read_file / exec / grep / find_files / web_search / web_fetch / list_dir`
- marker 格式: `[Tool result compacted] Tool: ... Original: N chars Kept: M chars ID: ...`
- `spec._compacted_results[call_id]` per-run 内存缓存, run 结束 GC
- DB 持久化与 observation 生成仍用原 result, 仅 `conversation_messages.append` 用 marker

**CompositeHook 13 钩子点** (来自 `plan-b-refactor.md:§2.5`):
- `wants_streaming` / `before_iteration` / `on_stream` / `on_stream_end`
- `emit_reasoning` / `emit_reasoning_end`
- `before_execute_tools` / `after_tool_executed` / `on_tool_error`
- `on_confirmation`
- `after_iteration` / `finalize_content` / `on_error`

**fan-out 错误隔离**: `CompositeHook` 的 async 方法自动 try/except log warning, 仅 `finalize_content` 透传异常。
**业务 hook 放 `integrations/` 子包**: `WikiHook` / `DreamSyncHook` / `AutoIngestHook` (3 个, 共 113 LOC)。

### 10.4 决策记录 (Plan B → Phase 5)

**Plan B (5 步状态机, 2026-06-18)**:
- ✅ B-1 到 B-7 完成, 19 commits, 868 tests, 0 archive deps
- ✅ 选择性借鉴 nanobot TurnState 8 态 → 我们 5 步域特化
- ✅ 不 vendor nanobot `agent/loop.py` (1,724 LOC, 改写成本 > 收益)

**Phase 5 (god class split, 2026-06-19)**:
- ✅ D1 + D3 + D4 + D5 (D2 是设计阶段, 无独立 commit)
- ✅ 4 god class → 11 + 9 + 10 + 0 = 30 个小文件
- ✅ 调用方零迁移 (123 + 3 production + 14 test), facade 模式保留公共 API
- ✅ 借鉴 nanobot 3 模式 (state trace / microcompact / 13 hooks)

### 10.5 数据对比 (前 vs 后)

| 维度 | Phase 5 前 (god class 状态) | Phase 5 后 (D5 终点) | Δ |
|---|---:|---:|---:|
| `apps/chat/db/` LOC | 926 (单 `db.py`) | 1,862 (10 文件) | +936 (拆分 overhead) |
| `apps/chat/research_engine/` LOC | 0 (在 archive) | 3,002 (10 文件) | +3,002 (净增) |
| `archive/llmwikify_v0_41_legacy/` LOC | ~5,500 | ~28 (仅 README + 空 `__init__.py`) | **-5,472** (冻结) |
| 测试 cases (Phase 5 新增) | 0 | 38 (managers) + 106 (db repos) + 18 (ctx) = **+162** | +162 |
| Public API 迁移成本 | — | 0 (facade/manager 透明) | — |
| 拆分后最大单文件 LOC | 1,236 (`service.py`, B-7 已删) | 877 (`research_engine/actions.py`) | — |

**结论**: Phase 5 把 4 个 god class 拆成 30+ 个小文件, 调用方零迁移, 测试覆盖 +162 cases,
archive 目录 -5,472 LOC。代码 LOC 净增 (~+3,938) 是拆分 overhead, 但单文件最大 < 900 LOC。

### 10.6 与 nanobot 模块化对比

| 维度 | nanobot | llmwikify Phase 5 后 |
|---|---|---|
| 平均单文件 LOC | 60 (22 子模块 / 1.3k 文件) | ~250 (chat 子系统) |
| 最大单文件 LOC | `loop.py` 1,724 (历史包袱) | `research_engine/actions.py` 877 |
| God class 数 | 1 (`AgentLoop`) | 0 (已全部拆) |
| Facade 模式 | 无 | `_facade.py` (ChatDatabase 99 委托) |
| Delegate 模式 | `factory.make_provider()` | `research_delegate.py` 27 委托 + `wiki_delegate.py` 17 委托 |

**借鉴点**: nanobot 没有 facade 模式, 我们新增 `_facade.py` 是从 `db.py` god class 拆分中自然产生的设计。
**未借鉴**: nanobot `agent/loop.py` 1,724 LOC 仍是单文件 — 我们选择拆为 10 个 < 900 LOC 文件。

### 10.7 后续 (Phase 6+)

- **Phase 6**: Memory consolidation pipeline (借鉴 nanobot Consolidator + Dream, 见 §10.8)
- **Phase 7**: microcompact metrics 暴露 (`/api/llm/metrics` HTTP endpoint + frontend panel, P3-1 推迟)
- **v0.5 cleanup** (2026-06-19): `git rm -r archive/llmwikify_v0_41_legacy/` (仅剩 README + 空 __init__.py, ~28 LOC)
- **未来若补 nanobot 全模块**: 见 `apply-plan.md:§4 Phase C/D/E`, 仍锁定 P3-3 MessageBus 否决

---

## 10.8 Phase 6 — Memory Consolidation Pipeline (2026-06-19, 借鉴 nanobot memory.py)

> Phase 6 解决 `apps/chat/memory/__init__.py` 与 nanobot `agent/memory.py`
> 的关键差距: **长期记忆 + 后台 consolidation + Dream 处理器**。
> 不是"chat + reproduction memory 合并" (它们是 peer, 详见 `apply-plan.md:§6`)。

### 10.8.1 nanobot memory.py 设计 vs 我们的差距

nanobot 单文件 `agent/memory.py` (1,161 LOC) 有 3 个独立组件协作:

| 组件 | LOC | 职责 | nanobot 实施 |
|---|---:|---|---|
| **MemoryStore** | 403 | 纯文件 I/O | `MEMORY.md` (facts) + `history.jsonl` (events) + `SOUL.md` (identity) + `USER.md` (user info) + `GitStore` 版本控制 |
| **Consolidator** | 415 | 短期 → 长期桥 | Per-turn 检查, session eviction + LLM summarize → 写 `MEMORY.md` |
| **Dream** | 302 | 后台记忆处理 | 2-phase: Phase 1 analyze history; Phase 2 edit files via `AgentRunner` (file tools) |

我们 `apps/chat/memory/__init__.py` (473 LOC) **缺** Consolidator 和 Dream, 只有 MemoryManager (6-store facade)。microcompact 是 per-tool-result (短周期), 不持久化, 不能替代 Consolidator (per-session eviction + 持久化总结)。

### 10.8.2 Phase 6 实施: 加 Consolidator + Dream

借鉴 nanobot 但**适配 llmwikify 架构** (后端差异):

| 维度 | nanobot | Phase 6 后 llmwikify |
|---|---|---|
| **存储后端** | 纯文件 (md + jsonl) | **双写**: SQLite 2 表 + 文件系统 `~/.llmwikify/memory/*.md` |
| **触发方式** | per-turn (Consolidator) + cron/command (Dream) | per-turn via `after_iteration` 钩子 (复用 13 钩子点) + `/dream` slash + APScheduler daily 03:00 |
| **长期记忆存储** | `MEMORY.md` (单文件, Git 版本) | `memory_consolidations` (SQLite, per-session summary) + `memory_facts` (SQLite, long-term facts) + `~/.llmwikify/memory/sessions/{id}.md` + `~/.llmwikify/memory/facts/{id}.md` (human-readable) |
| **跨平台 cron** | apscheduler (Linux/macOS) | **APScheduler** (与 nanobot 一致, 为跨平台准备) |

**为什么双写 (SQLite + markdown) 不只用 SQLite**:
- SQLite 高效 query (供 MemoryIndex search)
- markdown human-readable (供用户 `cat ~/.llmwikify/memory/facts/index.md`)
- 不进 wiki 系统 (wiki 是研究内容, memory 是系统状态)

### 10.8.3 文件清单

**新增 (7 文件, ~830 LOC)**:
```
apps/chat/memory/
├── consolidator.py          ~250 LOC  # Consolidator class + ConsolidatorConfig
├── dream.py                 ~300 LOC  # Dream class + DreamConfig
├── consolidation_store.py   ~80 LOC   # SQLite CRUD
├── facts_store.py           ~80 LOC   # SQLite CRUD
├── tables.py                ~50 LOC   # SQL DDL
└── dream_scheduler.py       ~70 LOC   # APScheduler wrapper

apps/chat/skills/crud/
└── dream_skill.py           ~80 LOC   # /dream slash command
```

**修改 (6 文件)**:
- `apps/chat/db/_facade.py` — `_init_db()` 加 2 表
- `apps/chat/memory/__init__.py` — MemoryManager: provider 参数 + `consolidator`/`dream` 属性 + 2 method
- `apps/chat/agent/runner_v2.py` — `after_iteration` 钩子触发 consolidate
- `apps/chat/command_router.py` — register `/dream`
- `interfaces/server/http/routes.py` — FastAPI lifespan: scheduler start/stop
- `pyproject.toml` — `apscheduler>=3.10,<4`

### 10.8.4 Option 7a 决策: 与 MemoryManager 关系

我们 3 种候选:

| 选项 | 描述 | 选? |
|---|---|---|
| 7a | Consolidator/Dream 是 MemoryManager 的 method + 属性 | ✅ **选** |
| 7b | 新建 `ChatMemory` 容器 (MemoryManager 是其属性), 9 caller 改 | ❌ 破坏性 |
| 7c | Consolidator 取代 MemoryManager | ❌ 语义混乱 |

**7a 优势**:
- 9 个现有 caller (`chat_sse.py`, `agent_service.py`, `prompt_builder.py`, `memory_skill.py`, `skills/service.py` 等) 零迁移
- MemoryManager 仍是 facade, 只是转发到内部 consolidator/dream
- 渐进式扩展, 未来可升级到 7b

```python
# apps/chat/memory/__init__.py
class MemoryManager:
    def __init__(self, app_db, wiki=None, data_dir=None, provider=None):
        # ... existing 6 stores ...
        # NEW (optional, may be None in tests):
        self.consolidator = Consolidator(self, db=app_db.chat, provider=provider, data_dir=data_dir) if provider else None
        self.dream = Dream(self, db=app_db.chat, provider=provider, data_dir=data_dir) if provider else None
    
    async def consolidate_session(self, session_id, messages, session_tokens):
        return await self.consolidator.maybe_consolidate(...) if self.consolidator else None
    
    async def dream_run(self):
        return await self.dream.run() if self.dream else None
```

### 10.8.5 数据 schema (新增 2 表)

```sql
-- 在 apps/chat/db/_facade.py:_init_db() 加 IF NOT EXISTS

CREATE TABLE memory_consolidations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    start_msg_idx INTEGER NOT NULL,
    end_msg_idx INTEGER NOT NULL,
    summary TEXT NOT NULL,
    md_file_path TEXT,
    tokens_before INTEGER,
    tokens_after INTEGER,
    created_at REAL NOT NULL,
    INDEX idx_mem_cons_session (session_id, created_at)
);

CREATE TABLE memory_facts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source_session_id TEXT,
    source_type TEXT NOT NULL,        -- 'consolidation' | 'dream_extraction' | 'manual'
    confidence REAL DEFAULT 1.0,
    last_referenced_at REAL,
    created_at REAL NOT NULL,
    INDEX idx_mem_facts_source (source_type),
    INDEX idx_mem_facts_created (created_at)
);
```

### 10.8.6 与 reproduction/sessions.py 关系

**关键澄清**: Phase 6 **不**合并 chat memory 与 reproduction memory。它们是 sibling (同层 peer), 不是 parent-child:

```
apps/chat/memory/          (chat 域 - session 内对话 + 长期 facts)
  ├── MemoryManager
  ├── Consolidator (NEW)
  └── Dream (NEW)

apps/reproduction/sessions.py  (reproduction 域 - paper reproduction 流程)
  └── ReproductionDatabase
```

未来如果需要跨域查询 (e.g., "找 paper X 的 chat conversations + backtest results"), 应新建 `apps/memory_facade/` 协调者, **不**把 ReproductionDatabase 塞进 MemoryManager。这是 peer-to-peer 协调, 不是 parent-child 嵌套。

### 10.8.7 测试覆盖

新增 5 文件, ~50 cases:

| 文件 | 测什么 | cases |
|---|---|---|
| `test_apps_chat_memory_consolidation_store.py` | SQLite CRUD | 6 |
| `test_apps_chat_memory_facts_store.py` | SQLite CRUD | 6 |
| `test_apps_chat_memory_consolidator.py` | 阈值触发 / evict 范围 / 双写 / throttling | 15 |
| `test_apps_chat_memory_dream.py` | 增量 cursor / fact extraction / 双写 | 12 |
| `test_apps_chat_skill_dream.py` + `test_command_router.py` +1 | `/dream` slash | 5 + 1 |

Mock 策略: LLM (`AsyncMock`), filesystem (`tmp_path`), APScheduler (lifespan test 不启 scheduler, 直接调 `dream.run()`)。

### 10.8.8 数据对比 (Phase 6 前 vs 后)

| 维度 | Phase 6 前 | Phase 6 后 | Δ |
|---|---:|---:|---:|
| `apps/chat/memory/` LOC | 473 (单文件) | ~1,300 (7 文件) | +830 |
| SQLite 表数 (chat DB) | 21 | 23 (+ 2 memory 表) | +2 |
| Markdown 文件位置 | 无 | `~/.llmwikify/memory/` 新目录 | +新 |
| Tests (memory 子系统) | 19 | ~70 | +50 |
| Phase 6 vs nanobot 差距 | 缺 Consolidator + Dream | 全补齐 | — |
| 9 个 caller 迁移成本 | — | 0 (Option 7a) | — |
| 外部依赖新增 | — | apscheduler | +1 |

### 10.8.9 后续 (Phase 7+)

- **Phase 7**: microcompact metrics 暴露 (`/api/llm/metrics` HTTP endpoint + frontend panel)
- **Phase 8**: Memory consolidation 与 reproduction cross-system query (`apps/memory_facade/` 协调者)
- **Phase 9**: Multi-modal memory (image/audio via foundation/extractors)
- **v0.5 release**: CHANGELOG + version bump (Phase 5+6 累计)
