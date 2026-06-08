# Skill 分类法：action / pipeline / skill

> **v0.32 skill 重构的核心概念框架。**
> 配套 `docs/designs/principles/unix-philosophy.md` 使用——后者讲"如何拆分"，本文讲"如何区分"。
>
> 适用于 llmwikify 的 skill 体系设计，以及任何"工具 + 业务流程"分层场景。

## 1. 一句话定义

| 类别 | 一句话 | 命名风格 |
|---|---|---|
| **action** | **单一原子操作**（不可再分的工具）| 动词（search, read, write）|
| **pipeline** | **多步骤业务流程**（编排多个 action 完成业务目标）| 业务目标（gather, research）|
| **skill** | **完成特定功能的能力**（独立概念，与 action/pipeline 平级）| 能力名（memory, notify, scheduler）|

**关键洞察**：3 类是**独立的概念维度**，不是"层级"或"子类"关系。

## 2. 3 类核心差异

| 维度 | action | pipeline | skill |
|---|---|---|---|
| **本质** | 原子操作 | 业务流程 | 独立功能 |
| **暴露 action 数** | 1 | 1（主入口）| N（CRUD 工具集）|
| **内部调其他** | 否 | 是（编排）| 否（独立实现）|
| **state 生命周期** | 无 | 有（持久化/resume/cancel）| 有（CRUD 状态）|
| **复用方式** | 被 pipeline/skill 调 | 被 LLM 一键调 | 被 LLM 一键调 |
| **数量（v0.32）** | 14 | 4 | 5 |

## 3. 4 个核心判断问题

新能力 X 进来时，按顺序问 4 个问题：

| # | 判断问题 | 答案 → 类别 |
|---|---|---|
| 1 | X 是单一原子操作，不可再分？ | **是 → action** |
| 2 | X 是多步编排（有顺序/分支/state）？ | **是 → pipeline** |
| 3 | X 是独立功能（如 CRUD 工具集）？ | **是 → skill** |
| 4 | X 不是以上任何？ | ❓ 再评估（可能需要拆）|

**判定优先级**：Q1 → Q2 → Q3，互斥（一个 X 只能归一类）。

## 4. 概念特征对比

### 4.1 实现差异

| 维度 | action | pipeline | skill |
|---|---|---|---|
| **handler 实现** | 直接调 kernel/foundation | 编排其他 action | 独立实现（不调 action）|
| **state 管理** | 无状态 | 完整 state 生命周期 | 局部 state（CRUD 状态）|
| **DB 依赖** | 通常只读 | 写 DB（业务进度）| 写 DB（CRUD 状态）|
| **失败处理** | 返回 error | 内部 retry / 持久化 | 内部事务性 |
| **LLM 依赖** | 大多数无 | 可能有（reason/orchestrator）| 通常无 |
| **测试方式** | 纯函数单测 | 集成测试 + mock 持久化 | 集成测试 |

### 4.2 LLM 视角

| 维度 | action | pipeline | skill |
|---|---|---|---|
| **LLM 看到描述** | "我能做**这个具体动作**" | "我能**达成这个业务目标**" | "我能**完成这个功能**" |
| **典型 tool name** | `search_skill.search` | `research_skill.run_research` | `memory_skill.append` |
| **典型 tool 描述** | "Search across wiki + web" | "Run a 6-step research session" | "Append to conversation history" |
| **LLM 选择粒度** | 细（拼装组合）| 粗（一键）| 粗（一键 CRUD）|

### 4.3 命名风格

| 类别 | 命名 | 例子 |
|---|---|---|
| **action** | 动词 | `search`, `read`, `write`, `score`, `extract`, `reason`, `observe` |
| **pipeline** | 业务目标 | `gather`, `research`, `report`, `ingest` |
| **skill** | 能力名 | `memory`, `notify`, `scheduler`, `wiki_query`, `dream` |

## 5. v0.32 实际分类（23 个）

### 5.1 action（14 个，工具池）

每个 action 是单一原子操作，1 个 skill 暴露 1 个 action：

| action | 类别 | 命名 |
|---|---|---|
| `search_skill.search` | action | 动词 |
| `extract_skill.extract` | action | 动词 |
| `read_skill.read` | action | 动词 |
| `write_skill.write` | action | 动词 |
| `lint_skill.lint` | action | 动词 |
| `plan_skill.plan` | action | 动词 |
| `analyze_skill.analyze` | action | 动词 |
| `summarize_skill.summarize` | action | 动词 |
| `score_skill.score` | action | 动词 |
| `revise_skill.revise` | action | 动词 |
| `filter_skill.filter` | action | 动词 |
| `graph_skill.graph` | action | 动词 |
| `reason_skill.reason_research` | action | 动词（ReAct 通用）|
| `observe_skill.observe_research_state` | action | 动词（ReAct 通用）|

**共同特征**：14 个全部都是 1 个 action、纯动词、不调其他、不持久化。

### 5.2 pipeline（4 个，业务流程）

每个 pipeline 编排多个 action：

| pipeline | 编排的 actions | Q1 调其他？ | Q2 state 生命周期？ |
|---|---|---|---|
| `gather_skill.gather_for_research` | search + filter + extract | ✅ | 否（无状态编排）|
| `ingest_skill.ingest_content` | extract + write + read | ✅ | 否 |
| `report_skill.generate_report` | summarize + write + score | ✅ | 否 |
| `research_skill.run_research` | plan + gather + analyze + summarize + score + revise + write（7 步 ReAct 循环）| ✅ | **是**（持久化 15+ 字段）|

**共同特征**：都是"多步编排"，但 state 复杂度不同（gather/ingest/report 无状态，research 有完整 ReAct state）。

### 5.3 skill（5 个，独立功能）

每个 skill 是独立功能（不调 action，独立实现），暴露 N 个 CRUD-style actions：

| skill | 暴露的 actions | 命名 | 独立实现 |
|---|---|---|---|
| `memory_skill` | append / query / summarize / clear | 能力名 | 持久化对话历史（JSONL）|
| `notify_skill` | list / mark_read / subscribe | 能力名 | 通知订阅 + 标记已读 |
| `scheduler_skill` | add_job / list_jobs / remove_job / trigger | 能力名 | cron 周期任务（独立）|
| `wiki_query_skill` | 28 actions（read/write/search/lint/graph/...）| 能力名 | 多 wiki 业务入口集 |
| `dream_skill` | run / get_proposals / approve / reject | 能力名 | 增量 wiki 编辑（独立）|

**共同特征**：都不调 action，**独立实现**自己的功能。CRUD 风格的 N actions。

### 5.4 orchestrator alias（2 个，pipeline 的别名）

| alias | 对应 pipeline | 区别 |
|---|---|---|
| `research_orchestrator` | `research_skill` 的别名 | LLM 视角换名字（"研究编排"语义）|
| `wiki_orchestrator` | `wiki_query_skill` 的别名 | LLM 视角换名字（"wiki 编排"语义）|

**关键**：orchestrator 不是新概念，是 pipeline 的 alias——**不增加新的实现**。

## 6. 决策树（快速判断）

```
新能力 X 进来
  │
  ├─ Q1: X 是单一原子操作？
  │   ├─ 是 → ✅ action (1 action, 纯函数)
  │   └─ 否 → Q2
  │
  ├─ Q2: X 是多步编排（有顺序/分支/state）？
  │   ├─ 是 → ✅ pipeline (1 主入口, 内部编排 action)
  │   └─ 否 → Q3
  │
  ├─ Q3: X 是独立功能（不调 action，独立实现）？
  │   ├─ 是 → ✅ skill (N actions, CRUD 工具集)
  │   └─ 否 → ❌ 重新评估（X 可能要拆）
```

## 7. 4 个常见混淆 FAQ

### 7.1 混淆 1：`report_skill` 应该是 pipeline 还是 action？

**答**：**pipeline**。它内部调 summarize + write + score 3 个 action，**多步编排**生成报告。
单 `summarize` 或 `write` 是 action，组合是 pipeline。

### 7.2 混淆 2：`wiki_query_skill` 有 28 actions 应该是 skill 还是 pipeline？

**答**：**skill**。它**不调其他 action**——每个 action 内部是直接的 read/write/search 调用，**不是"先 A 再 B" 的流程**。
判定要点：
- 不是 1 action → 不是 action
- 不编排 action（每个 action 是独立的 wiki 入口）→ 不是 pipeline
- 是 CRUD 工具集（28 个 wiki 业务入口）→ **skill**

### 7.3 混淆 3：`memory_skill` / `notify_skill` 看起来像"工具集"——是 skill 还是 pipeline？

**答**：**skill**。它们：
- 不调 action（独立实现）
- 有 CRUD 风格的 N actions
- 是独立功能（对话历史管理、通知管理）

**vs pipeline** 的关键区别：pipeline 是"多步编排"（一个 action 完成后做下一个），skill 是"独立功能"（每个 action 是独立的 CRUD 入口）。

### 7.4 混淆 4：orchestrator 是 action / pipeline / skill 哪一类？

**答**：**都不算**。orchestrator 是已有 **pipeline** 的别名（`research_orchestrator` = `research_skill` 别名）。
- 它不引入新概念，只是给 pipeline 换 LLM 视角的名字
- 实现只有 1 份
- 命名规则：`<capability>_orchestrator` = `<capability>_skill` 的别名

## 8. 决策矩阵（速查表）

| 能力描述 | 判定 | 类别 |
|---|---|---|
| "搜索 wiki 页面" | Q1 是 → action | `search_skill.search` |
| "读一个 wiki 页面" | Q1 是 → action | `read_skill.read` |
| "收集多源信息" | Q2 是 → pipeline | `gather_skill.gather_for_research` |
| "完成一个研究" | Q2 是 → pipeline | `research_skill.run_research` |
| "管理对话历史"（CRUD）| Q3 是 → skill | `memory_skill.{append,query,...}` |
| "管理通知"（CRUD）| Q3 是 → skill | `notify_skill.{list,mark_read,...}` |
| "wiki 28 个操作"（CRUD 集）| Q3 是 → skill | `wiki_query_skill.{read_page,...}` |
| "编排研究" | 是 pipeline 的别名 | `research_orchestrator` |

## 9. 反模式（不要做）

### 9.1 反模式 1：action 调用 pipeline

```python
# ❌ 禁止: action 不应编排
class SearchSkill(Skill):
    async def handle(self, args, ctx):
        result = await search_db(args)  # OK
        result.update(await gather_skill.execute(...))  # ❌ action 不应调 pipeline
        return result
```

**为什么禁止**：action 是纯工具，被 pipeline 调用。如果 action 调 pipeline，会形成循环依赖。

### 9.2 反模式 2：pipeline 直接实现底层操作

```python
# ❌ 避免: pipeline 应编排 action，不应直接实现
class ResearchSkill(Skill):
    async def run_research(self, args, ctx):
        # 直接调 DB，不通过 read_skill
        sources = db.get_sources(args["session_id"])  # ❌ 应调 action
        # 自己写 LLM prompt
        response = llm_client.chat(messages)  # ❌ 应调 action
```

**为什么避免**：pipeline 是"编排者"，不应自己实现工具。这导致代码重复（多个 pipeline 重复实现同一工具）和测试困难。

### 9.3 反模式 3：skill 命名带 "Tool" / "Service" / "Manager"

```python
# ❌ 禁止命名
class SearchTool(Skill): ...      # "Tool" 冗余
class ResearchService(Skill): ... # "Service" 是 service 层概念
class NotificationManager: ...    # "Manager" 是管理层概念
```

**为什么禁止**：skill / action / pipeline 是抽象概念，不是 tool（LLM 视角）、service（后端概念）、manager（管理层）。

### 9.4 反模式 4：3 类概念混淆（pipeline 当 action 用）

```python
# ❌ 禁止: 1 个 pipeline 调另一个 pipeline 整个跑一遍
class GatherSkill(Skill):
    async def gather_for_research(self, args, ctx):
        # ❌ 不应调整个 research pipeline
        result = await research_skill.run_research(args, ctx)
        return result
```

**为什么禁止**：pipeline 是"业务目标入口"，不是"可嵌套的子流程"。要复用 pipeline 的步骤，应拆出可重用的 action。

## 10. 与 Unix 哲学的关系

`docs/designs/principles/unix-philosophy.md` 3 条原则 + 本文 3 类概念 = 完整 skill 设计方法论：

| Unix 哲学（如何拆）| Skill 分类（如何区分）|
|---|---|
| 原则 1：底层 = 工具 | Q1：是 → action |
| 原则 2：上层 = 业务流程 | Q2：是 → pipeline |
| 原则 3：简单 CRUD 不拆 | Q3：是 → skill（不拆为 N 个 action）|

两者结合：
- Unix 哲学给"如何拆"
- 分类法给"拆完后归哪一类"

## 11. 总结

| 类别 | 一句话 | 命名 | 例子 | 数量 |
|---|---|---|---|---|
| **action** | 单一原子操作 | 动词 | `search`, `read`, `write` | 14 |
| **pipeline** | 多步编排 | 业务目标 | `gather`, `research`, `report` | 4 |
| **skill** | 独立功能 | 能力名 | `memory`, `notify`, `wiki_query` | 5 |
| **orchestrator alias** | pipeline 别名 | 编排视角 | `research_orchestrator` | 2 |

**核心心法**：
- 看到动词 → action
- 看到业务流程 → pipeline
- 看到独立功能名 → skill
- 看到别名 → 已有 pipeline

## 12. 决策记录

本次术语重构由用户提出（2026-06-08）：
- 之前："底层 skill" / "上层 skill"（按层级划分）
- 现在："action" / "pipeline" / "skill"（按概念性质划分，3 个独立概念）

**变更原因**：
- "底层/上层" 过于工程化，混淆"层级"和"概念"
- action / pipeline / skill 三个词更精确（各自一个概念维度）
- 简化了心智模型（3 类 vs 2 类 + 隐含的"业务 vs 工具" 二分）

**保留的概念**：
- Unix 哲学 3 原则（如何拆）
- 4 个判断问题（如何区分）
- 决策树（快速判断）
- 4 个 FAQ（常见混淆）
- 4 个反模式

---

## 13. 相关文档

- `docs/designs/principles/unix-philosophy.md`：3 条 Unix 哲学原则（如何拆）
- `docs/designs/v0.32-skill-restructure.md`：v0.32 skill 重构（具体落地）
- `docs/designs/refactor-4layer-architecture.md`：4 层技术架构（D1-D14 决策）
- `docs/LLM_WIKI_PRINCIPLES.md`：Karpathy LLM Wiki 原始原则

---

## 14. 变更日志

| 日期 | 变更 | 作者 |
|---|---|---|
| 2026-06-08 | 初始 skill 分类法（"底层 vs 上层"，4 维度 + 4 FAQ + 10 反模式）| Refactor session |
| 2026-06-08 | **重构为 action / pipeline / skill 3 独立概念**（用户提议）| Refactor session |
