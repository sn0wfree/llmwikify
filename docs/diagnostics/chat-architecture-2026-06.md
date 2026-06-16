# Chat 模块架构诊断报告

> 日期: 2026-06-16
> 范围: `src/llmwikify/apps/chat/` 全模块 + `interfaces/server/http/chat_sse.py` + 共享 DB `/home/ll/.llmwikify/agent/.llmwiki_agent.db`
> 数据: 115 个 Python 文件 / ~23,500 行代码 / 21 张 DB 表 / 2 套并行 chat 引擎
> 状态: 报告 + Phase 1（归档旧层）已交付；Phase 2-4 待下个 sprint

---

## 1. TL;DR

Chat 模块同时存在**两套并行的主循环**（v0.41 的 `ResearchEngine` 与 v0.42+ 的 `ChatOrchestrator` + `ReActEngine`），**共享同一份 DB**，且**都没有明确的弃用路径**。同时 skill action 膨胀到 27 个独立文件，DB 里塞了 PPT / Research / Reproduction 等异质子系统的表，**职责边界已经模糊到"不伦不类"的程度**。

清理目标: **1 个主循环 + 3 张独立 DB + 5–8 个 skill action 类别**。

---

## 2. 当前架构地图

### 2.1 模块物理布局

```
src/llmwikify/apps/chat/                   115 个 .py, ~23,500 行
├── 旧层 (v0.41, 仍在被 7 个文件依赖) — Phase 1 已归档
│   ├── engine.py                  405 行   ResearchEngine
│   ├── actions.py                 872 行   8 个 free-function action_*
│   ├── observer.py                212 行   ResearchObserver
│   ├── gates.py                   ~200 行  ResearchGates
│   ├── reasoner.py                ~150 行  ResearchReasoner
│   ├── report.py                  288 行   ReportGenerator
│   ├── llm_step.py                ~100 行  run_prompt helper
│   ├── resume.py                  ~100 行  ResearchResumeLoader
│   ├── routes.py                  311 行   /api/autoresearch/*
│   ├── prompts.py                 414 行
│   ├── gatherer.py                426 行   SourceGatherer
│   └── state.py                   281 行   ResearchState
│
├── 新层 (v0.42+, 路由已切到 /api/agent/*)
│   └── agent/
│       ├── orchestrator.py        664 行   ChatOrchestrator
│       ├── react_engine.py        687 行   ReActEngine
│       ├── chat_react.py          711 行   ChatReActBridge
│       ├── react_loop.py          ~200 行  loop runner
│       ├── research_bridge.py     ~150 行  translate_react_events
│       ├── tool_executor.py       ~250 行  ToolExecutor
│       ├── context_manager.py     314 行
│       └── agent_service.py       310 行   AgentService (composition root)
│
├── 通用层 (新旧都依赖)
│   ├── db.py                      926 行   ChatDatabase + AutoResearchDatabase
│   ├── base.py                    590 行
│   ├── db_migrations.py           ~150 行
│   ├── memory/__init__.py         473 行   MemoryManager
│   └── harness/                   ~1500 行 SourceFilter/Reviewer/Revisor/QualityGate
│
└── skills/                        40+ 文件
    ├── registry.py                317 行   SkillRegistry
    ├── service.py                 ~150 行  SkillService
    ├── base.py                    435 行   Skill/Action/Context/Result
    ├── runtime.py                 290 行
    ├── plugin_loader.py           ~150 行
    ├── actions/                   18 文件  18 个 *action.py
    ├── actions/detect/            9 文件   9 个 detect/*.py
    ├── pipelines/                 3 文件   report/gather/ingest
    ├── crud/                      4 文件   notify/dream/memory/scheduler
    ├── workflows/
    │   ├── executor.py            860 行
    │   ├── dag.py                 823 行
    │   ├── subagent_runner.py     550 行
    │   ├── subagent_worker.py     411 行
    │   ├── skill.py               318 行
    │   └── run_store.py           ~200 行
    ├── research_skill.py          703 行
    ├── wiki_query_skill.py        672 行
    └── autoresearch_compound_skill.py  327 行
```

### 2.2 路由挂载

```
src/llmwikify/interfaces/server/http/routes.py
  L524: app.include_router(agent_router)            # /api/agent/* (新)
  L525: app.include_router(autoresearch_router)     # /api/autoresearch/* (旧, Phase 1 已移除)
  L590-593: paper / factor / strategy / reproduction
```

**Phase 1 完成后**: `autoresearch_router` 已从 `routes.py:524-525` 移除。两条 router 不再共享同一份 DB 入口（旧 router 已弃）。

### 2.3 DB 现状 (21 张表)

```
.llmwiki_agent.db (实际位于 /home/ll/.llmwikify/agent/)
├── chat_*  (3 表)              ─ 当前主对话核心
├── autoresearch_* (3 表)        ─ 旧 v0.41 研究
├── research_* (4 表)            ─ 新研究
├── ppt_* (3 表)                 ─ PPT 混入!
├── confirmations (1 表)         ─ confirmation dialog
├── context_entries (1 表)       ─ RAG-style memory
├── dream_proposals (1 表)       ─ dream review queue
├── event_log (1 表)             ─ SSE 审计
├── tool_calls (1 表)            ─ tool 审计
├── notifications (1 表)
├── ingest_log (1 表)
└── sqlite_sequence (1 表)
```

---

## 3. 五个核心问题

### 问题 1: 两套并行 Chat 引擎 (最严重) — **Phase 1 已修**

**证据**:
- `engine.py:53` `class ResearchEngine` 仍在 (Phase 1 已 git mv 到 archive)
- `apps/research/__init__.py:3` 注释 "legacy ResearchEngine / ResearchSessionManager were removed in 4fd128b" — 但 `engine.py` 还在，注释与代码不一致
- `engine.py` 被 **7 个文件** import: `observer.py / resume.py / routes.py / reasoner.py / gates.py / report.py / llm_step.py`
- `ReActEngine` 被 **8 个文件** import: `engine.py / skills/research_skill.py / agent/research_bridge.py / agent/react_loop.py / agent/orchestrator.py / agent/__init__.py / agent/react_engine.py / agent/chat_react.py`
- 两个 router 同时挂载在 `routes.py:524-525`

**Phase 1 修复**:
- 9 个 v0.41 文件已 `git mv` 到 `archive/llmwikify_v0_41_legacy/chat_legacy/`
- `/api/autoresearch/*` 路由已移除
- 9 文件内部 import 改为绝对 archive 路径

### 问题 2: DB 职责混合 — **Phase 2 待做**

**证据**: 21 张表混合 4 个独立子系统的数据:
- `ppt_*` (PPT 子系统) 与 `chat_*` (对话) 共用一份 DB
- `autoresearch_*` 与 `research_*` 重复 (前者 v0.41, 后者 v0.42+, 可合并)
- `context_entries` 17 rows 与 `memory/__init__.py` 473 行 双重实现

**Phase 2 计划**:
1. **新 DB**: `.llmwiki_chat.db` — 只装 chat_messages / chat_sessions / chat_permissions / confirmations / event_log / tool_calls / context_entries / dream_proposals
2. **新 DB**: `.llmwiki_research.db` — research_* + autoresearch_* 合并
3. **新 DB**: `.llmwiki_ppt.db` — ppt_* 全部

### 问题 3: 3 个"主循环"语义重叠 — **Phase 1 已隐式修复**

| 类 | 角色 | 现状 |
|---|---|---|
| `ResearchEngine` (engine.py) | 旧 ReAct 循环 | Phase 1 已归档 |
| `ChatOrchestrator` (agent/orchestrator.py) | 新 SSE 编排 | 当前主 |
| `ReActEngine` (agent/react_engine.py) | 新 ReAct 核心 | 通用 |
| `ChatReActBridge` (agent/chat_react.py) | 桥接 chat↔ReAct | 粘合 |

**清理后状态**: 单一职责:
- `ChatOrchestrator` = SSE 事件编排（消息进出、状态机）
- `ReActEngine` = 通用 ReAct 循环
- `ChatReActBridge` = 把 ReAct 状态翻译成 SSE

### 问题 4: Skill Action 数量爆炸 (27 个文件) — **Phase 3 待做**

**证据**:
- `skills/actions/` 18 个 `*_action.py` 文件
- `skills/actions/detect/` 9 个 `detect/*.py` 子检测

**Phase 3 计划 (用户已确认合并 5-8 大类)**:
```
skills/actions/
├── read/        search_action, read_action, observe_action
├── write/       write_action, revise_action, summarize_action
├── analyze/     analyze_action, score_action, reason_action, extract_action
├── detect/      detect/ 整个子目录 (9 个内部保持)
├── control/     plan_action, clarify_action, filter_action, lint_action
├── network/     web_search_action, graph_action
└── _common.py   _helpers.py
```

### 问题 5: 两个 Memory 系统 — **Phase 4 待做**

| 系统 | 实现 | 位置 |
|---|---|---|
| `MemoryManager` | 进程内状态 | `apps/chat/memory/__init__.py` (473 行) |
| `context_entries` | DB + embedding | DB (17 rows) |

**Phase 4 计划**: 决定哪个是「主」、哪个是「辅」或合并

---

## 4. 依赖图 (关键链)

```
前端 SSE
  ↓
chat_sse.py  (/api/agent/*)
  ↓
ChatOrchestrator  (orchestrator.py:75)
  ├→ AgentService  (agent_service.py:310)  composition root
  │    ├→ WikiService
  │    ├→ SkillService  (skills/service.py)
  │    │    └→ SkillRegistry  (registry.py:317)
  │    │         └→ Skill.base  (base.py:435)
  │    │              └→ SkillAction  → handler
  │    ├→ MemoryManager  (memory/__init__.py:473)
  │    └→ HarnessService
  └→ ReActEngine  (react_engine.py:687)
       └→ ChatReActBridge  (chat_react.py:711)
            └→ ToolExecutor
                 └→ db.save_chat_message
```

**Phase 1 之后**: 旧 `ResearchEngine` 路径已从路由层切断, 不再被新层调用链触及.

---

## 5. 迁移路线图 (4 阶段)

| 阶段 | 时间 | 风险 | 价值 | 状态 |
|---|---|---|---|---|
| Phase 1: 归档旧层 | 3-4 h | 中 (import 链) | 高 (删 ~2,500 行) | **已完成** |
| Phase 2: DB 拆分 | 1-2 d | 中 (数据迁移) | 中 (清晰职责) | P1, 下个 sprint |
| Phase 3: Skill Actions 重组 | 1 d | 低 | 中 (可读性) | P2 |
| Phase 4: Memory 合并 | 1-2 d | 中 (语义) | 中 (去重) | P3 |

---

## 6. Phase 1 执行记录

### 6.1 移动文件 (9 个)

`git mv` 到 `archive/llmwikify_v0_41_legacy/chat_legacy/`:

```
src/llmwikify/apps/chat/engine.py
src/llmwikify/apps/chat/actions.py
src/llmwikify/apps/chat/observer.py
src/llmwikify/apps/chat/gates.py
src/llmwikify/apps/chat/reasoner.py
src/llmwikify/apps/chat/report.py
src/llmwikify/apps/chat/llm_step.py
src/llmwikify/apps/chat/resume.py
src/llmwikify/apps/chat/routes.py
```

### 6.2 import 改写

9 文件内部互相 import 改为绝对 archive 路径:
- `from llmwikify.apps.chat.X import Y` → `from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.X import Y`

### 6.3 路由移除

`interfaces/server/http/routes.py:524-525` 移除 `autoresearch_router` 挂载.

### 6.4 验证

- `ruff check .` 干净
- `pytest tests/test_apps_chat_* tests/test_apps_agent_*` 全过
- `git log --diff-filter=R` 确认 9 文件为 R 状态 (rename)

---

## 7. Phase 2-4 详细计划 (待执行)

### Phase 2: DB 拆分 (1-2 天)

```python
# db.py 的 path resolution 不绑死文件名 — 修改 caller 即可分流
# 推荐结构:
.llmwiki_chat.db       chat + permissions + confirmations
.llmwiki_research.db   research + autoresearch (合并)
.llmwiki_ppt.db        PPT 独立
```

**风险**: 需要数据迁移脚本, PPT 子系统可能有自己的 DB opener 需要同步改.

### Phase 3: Skill Actions 重组 (1 天)

18 文件 → 6 文件夹 + 1 公共:
```
skills/actions/
├── read/        3
├── write/       3
├── analyze/     4
├── detect/      9 (保持)
├── control/     4
└── network/     2
```

**风险**: 要更新 `__init__.py` 导出列表和 `registry.py` 注册路径.

### Phase 4: Memory 合并 (1-2 天)

读 `memory/__init__.py` 的导出, 查 `context_entries` 表的 schema, 决定主/辅/合并.

---

## 8. 文件级建议 (Phase 1 完成态)

### 已归档到 `archive/llmwikify_v0_41_legacy/chat_legacy/`

```
engine.py            # ResearchEngine
actions.py           # 8 个 free-function action_*
observer.py          # ResearchObserver
gates.py             # ResearchGates
reasoner.py          # ResearchReasoner
report.py            # ReportGenerator
llm_step.py          # run_prompt helper
resume.py            # ResearchResumeLoader
routes.py            # /api/autoresearch/*
```

### 保留并整理

```
apps/chat/db.py                # ChatDatabase (核心 schema)
apps/chat/base.py              # 数据模型
apps/chat/db_migrations.py     # 迁移管理
apps/chat/memory/              # 需要先分析后决定
apps/chat/agent/               # 全部保留 (新主层)
apps/chat/skills/              # 全部保留
apps/chat/harness/             # 保留 (reviewer/revisor 等仍被用)
apps/chat/prompts.py           # 保留 (chat 路径用)
apps/chat/gatherer.py          # 保留 (research 路径用)
apps/chat/state.py             # 保留 (research 路径用)
```

---

## 9. 回滚路径

如果 Phase 1 出现意外问题:
```bash
git revert HEAD~1   # 撤销 1.2 (DEPRECATED 移除 + README)
git revert HEAD~1   # 撤销 1.1 (git mv + 内部 import 改写 + 路由移除)
```

9 个文件回到原位, 路由表恢复, 完整恢复.

---

## 10. 参考

- [Karpathy 4 原则](https://github.com/forrestchang/andrej-karpathy-skills) — 项目规约参考
- `AGENTS.md` — 项目级 agent 行为规约
- `archive/llmwikify_v0_41_legacy/README.md` — v0.41 上帝类归档说明
- `git log 4fd128b~1..4fd128b` — Agent 重构引入新层的提交
- `git log 2682ea2` — ChatService 上帝类归档
