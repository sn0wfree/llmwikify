# Skill 分类法：底层 vs 上层

> **v0.32 skill 重构的辅助原则。**
> 配套 `docs/designs/principles/unix-philosophy.md` 使用——后者讲"如何拆分"，本文讲"如何区分"。
>
> 适用于 llmwikify 的 skill 体系设计，以及任何"工具 + 业务流程"分层场景。

## 1. 一句话定义

| 类别 | 一句话 | 调用方 |
|---|---|---|
| **底层 skill** | **纯工具**，单一能力、纯数据操作、无业务流 | 上层 skill 调 / LLM 细粒度调 |
| **上层 skill** | **业务流程**，编排底层 skill 完成业务目标 | LLM 高层调用（"一键"）|

## 2. 4 个核心判断维度

判断一个新能力该归为底层还是上层，问以下 4 个问题：

| # | 判断问题 | 是 → | 否 → |
|---|---|---|---|
| 1 | 这个 skill 调其他 skill 吗？ | **上层** | 可能是底层 |
| 2 | 这个 skill 有完整 state 生命周期（持久化/恢复/cancel/pause）？ | **上层** | 可能是底层 |
| 3 | 这个 skill 暴露几个 action？ | 单 action 倾向底层；多 action 看语义 | — |
| 4 | 这个 skill 的 action 涉及"业务目标"吗？ | **上层** | 可能是底层 |

**强信号（任一为是 → 上层）**：
- ✅ Q1 是（编排其他 skill）
- ✅ Q2 是（有 state 生命周期）

**弱信号（综合判断）**：
- Q3 单 action 但 Q4 是业务 → 上层
- Q3 多 action 但全是 CRUD → 可能是底层（但已 Unix 哲学化为"工具集"）

## 3. 概念特征对比

### 3.1 本质差异

| 维度 | 底层 skill | 上层 skill |
|---|---|---|
| **本质** | 工具（Tool） | 业务流程（Workflow） |
| **作用域** | 单一能力 | 多步骤业务目标 |
| **抽象层次** | 操作动词 | 业务目标名词 |
| **命名风格** | `search`, `read`, `write`, `score` | `gather`, `research`, `report`, `wiki_query` |
| **调用方** | 上层 skill 调 + LLM 细粒度调 | LLM 一键调用 |
| **数量比例** | 多（通用工具池）| 少（具体业务流程）|

### 3.2 实现差异

| 维度 | 底层 skill | 上层 skill |
|---|---|---|
| **handler 实现** | 直接调 kernel/foundation | 编排其他 skill 的 handler |
| **state 管理** | 无状态或仅短暂状态 | 完整 state 生命周期（持久化）|
| **DB 依赖** | 通常只读 DB | 通常写 DB（业务进度）|
| **失败处理** | 返回 error，调用方决定 | 内部 retry / 持久化 / 报告 |
| **LLM 依赖** | 大多数无（部分用 LLM 评分/总结）| 可能有（reason/orchestrator）|
| **测试方式** | 纯函数单元测试 | 集成测试 + mock 持久化 |

### 3.3 LLM 视角

| 维度 | 底层 skill | 上层 skill |
|---|---|---|
| **LLM 看到的描述** | "我能用这个做**这个具体动作**" | "我能用这个**达成这个业务目标**" |
| **LLM 选择粒度** | 细（拼装组合）| 粗（一键）|
| **典型 tool name** | `search_skill.search` | `research_skill.run_research` |
| **典型 tool 描述** | "Search across wiki + web" | "Run a 6-step research session" |

## 4. v0.32 实际分类（19 skill + 2 alias）

### 4.1 底层 skill（14 个，工具池）

| skill | 命名 | Q1 调其他 skill？ | Q2 state 生命周期？ | 类别判定 |
|---|---|---|---|---|
| `search_skill` | 动词 search | 否 | 否 | ✅ 底层 |
| `extract_skill` | 动词 extract | 否 | 否 | ✅ 底层 |
| `read_skill` | 动词 read | 否 | 否 | ✅ 底层 |
| `write_skill` | 动词 write | 否 | 否 | ✅ 底层 |
| `lint_skill` | 动词 lint | 否 | 否 | ✅ 底层 |
| `plan_skill` | 动词 plan | 否 | 否 | ✅ 底层 |
| `analyze_skill` | 动词 analyze | 否 | 否 | ✅ 底层 |
| `summarize_skill` | 动词 summarize | 否 | 否 | ✅ 底层 |
| `score_skill` | 动词 score | 否 | 否 | ✅ 底层 |
| `revise_skill` | 动词 revise | 否 | 否 | ✅ 底层 |
| `filter_skill` | 动词 filter | 否 | 否 | ✅ 底层 |
| `graph_skill` | 动词 graph | 否 | 否 | ✅ 底层 |
| `reason_skill` | 动词 reason | 否 | 否 | ✅ 底层（ReAct 通用）|
| `observe_skill` | 动词 observe | 否 | 否 | ✅ 底层（ReAct 通用）|

**共同特征**：14 个全部都是 1 个 action、纯动词、不调其他 skill、无 state 生命周期。

### 4.2 上层 skill（9 个，业务流程）

| skill | 命名 | Q1 调其他 skill？ | Q2 state 生命周期？ | 类别判定 |
|---|---|---|---|---|
| `gather_skill` | 业务目标 gather | ✅ 调 search+filter+extract | 否（无状态）| ✅ 上层 |
| `ingest_skill` | 业务目标 ingest | ✅ 调 extract+write+read | 否 | ✅ 上层 |
| `report_skill` | 业务目标 report | ✅ 调 summarize+write+score | 否 | ✅ 上层 |
| `wiki_query_skill` | 业务目标 wiki_query | ✅ 调 read+write+search+lint+graph | 否 | ✅ 上层 |
| `research_skill` | 业务目标 research | ✅ 调 plan+gather+analyze+summarize+score+revise+write | **是**（ReAct 循环 + 持久化）| ✅ 上层 |
| `memory_skill` | 业务目标 memory | ✅ 调 write+search+summarize | 是（持久化对话历史）| ✅ 上层 |
| `notify_skill` | 业务目标 notify | ✅ 调 read+write | 是（持久化通知）| ✅ 上层 |
| `dream_skill` | 业务目标 dream | ✅ 调 read+write+score | 是（增量编辑计划）| ✅ 上层 |
| `scheduler_skill` | 业务目标 scheduler | ❌ 独立实现（cron）| 是（cron schedule 持久化）| ✅ 上层（CRUD 工具集，Unix 哲学下不拆）|

**共同特征**：9 个都涉及业务目标（即使 memory/notify 看似"工具"，因为有 state 生命周期）。

### 4.3 orchestrator alias（2 个，不重复实现）

| alias | 对应 skill | 区别 |
|---|---|---|
| `research_orchestrator` | `research_skill` 别名 | LLM 视角换名字（"研究编排"语义）|
| `wiki_orchestrator` | `wiki_query_skill` 别名 | LLM 视角换名字（"wiki 编排"语义）|

**关键**：orchestrator 不是新 skill，是已有上层 skill 的 alias——**不增加新的实现**。

## 5. 命名约定

### 5.1 底层 skill 命名规则

- **动词**或**动作名词**：`search`, `read`, `write`, `extract`, `score`, `filter`, `summarize`, `analyze`, `revise`, `plan`, `lint`, `graph`, `reason`, `observe`
- **一个文件 = 一个 skill**：`search_skill.py` → `SearchSkill` class
- **一个 skill = 一个主 action**：`search_skill.search`（1 对 1）

**避免的命名**：
- ❌ `tool_search`（"tool_" 是冗余前缀）
- ❌ `SearchTool`（class 名字带 "Tool"）
- ❌ `search_skill_v2`（版本后缀）

### 5.2 上层 skill 命名规则

- **业务目标**或**领域名词**：`gather`, `ingest`, `report`, `wiki_query`, `research`, `memory`, `notify`, `dream`, `scheduler`
- **一个文件 = 一个 skill**：`research_skill.py` → `ResearchSkill` class
- **一个 skill = 一个或多个 action**：
  - `research_skill.run_research`（1 个主入口）
  - `memory_skill.{append,query,summarize,clear}`（4 个 CRUD actions，Unix 哲学下不拆）

**避免的命名**：
- ❌ `service_research`（"service_" 是 service 层概念）
- ❌ `ResearchManager`（"Manager" 是管理层概念）
- ❌ `research_app`（"app" 是应用层概念）

### 5.3 orchestrator 命名规则

- **复用已有上层 skill 的别名**：`research_orchestrator` = `research_skill` 别名
- **LLM 看到两个名字**（语义侧重不同）：
  - `research_skill.run_research` = "运行研究"（动作）
  - `research_orchestrator.run_research` = "编排研究"（编排视角）
- **实现只有一份**（不重复）

## 6. 决策树（快速判断）

```
新能力 X 进来
  │
  ├─ X 内部调其他 skill 吗？
  │   ├─ 是 → Q2 是否有 state 生命周期（持久化/恢复）？
  │   │       ├─ 是 → ✅ 上层（业务流程）
  │   │       └─ 否 → ⚠️ 可能是上层（无状态编排）
  │   │
  │   └─ 否（X 不调其他 skill）→ Q3 暴露几个 action？
  │           ├─ 1 个 action → Q4 涉及"业务目标"？
  │           │       ├─ 是 → ❌ 反例: 应该拆出更底层的工具
  │           │       └─ 否 → ✅ 底层（工具）
  │           │
  │           └─ N 个 action → Q2 是否有 state 生命周期？
  │                   ├─ 是 → ✅ 上层（业务管理）
  │                   └─ 否 → ⚠️ 检查: N 个 action 是否全是 CRUD？
  │                           ├─ 是 → ✅ 工具集（按 Unix 哲学不拆）
  │                           └─ 否 → ✅ 上层（多 action 业务流程）
```

## 7. 4 个常见混淆（FAQ）

### 7.1 混淆 1：为什么 `report_skill` 是上层不是底层？

**答**：`report_skill` 内部调 `summarize + write + score`（自检）3 个底层 skill。**它涉及"业务目标"（生成报告）**而非"工具能力"（总结或写）。单 `summarize` 或 `write` 是底层，组合是上层。

### 7.2 混淆 2：为什么 `wiki_query_skill` 有 28 actions 但仍是上层？

**答**：28 actions 中的每一个都是"读/写/搜索/lint"等底层调用的**薄包装**。它聚合了 12 个底层 skill 的能力，提供 28 个 wiki 业务入口。

判定要点：
- **Q1** = 是（内部调底层）
- **Q4** = 是（每个 action 都是 wiki 业务目标）

所以是上层。**action 数量不是分类标准**——action 数量只是表征"业务广度"。

### 7.3 混淆 3：`memory_skill` 和 `notify_skill` 看起来像"工具集"——它们是上层还是底层？

**答**：**上层**。判断依据：
- **Q2** = 是（有 state 生命周期：对话历史持久化、通知订阅状态）
- 即使 Q1 调底层（write/search/summarize），但因 state 生命周期是上层标志
- 内部 Q1=否 也可能是上层（scheduler_skill 是反例：完全独立实现但有 state）

### 7.4 混淆 4：orchestrator 是 skill 吗？

**答**：**不是新 skill，是已有上层 skill 的 alias**。

`research_orchestrator.run_research` 实际上等于 `research_skill.run_research`——LLM 看到不同名字，**实现只有一份**。这是为了 LLM 视角的语义清晰（"研究" vs "研究编排"），不是为了增加新功能。

## 8. 实际应用示例

### 8.1 新能力 X："把 wiki 页面导出为 PDF"

判断流程：
1. Q1 调其他 skill 吗？→ **是**（调 read_skill + extract_skill + write_skill 写文件）
2. Q2 state 生命周期？→ 否（单次操作）
3. 类别：**上层**（无状态编排）
4. 命名：`export_pdf_skill`（业务目标 "export"）
5. 文件：`apps/chat/skills/export_pdf_skill.py`

### 8.2 新能力 Y："给一段文本打分（1-10）"

判断流程：
1. Q1 调其他 skill 吗？→ 否（直接调 LLM）
2. Q2 state 生命周期？→ 否（纯函数）
3. Q3 几个 action？→ 1 个
4. Q4 业务目标？→ 否（通用打分）
5. 类别：**底层**（工具）
6. 命名：`score_skill`（动词 score）—— **但这与已有 score_skill 重复！**
7. 解决：合并到已有 `score_skill`，加 1 个新 action `score_text`

### 8.3 新能力 Z："客户支持工单自动分类"

判断流程：
1. Q1 调其他 skill 吗？→ 可能（read_skill 读工单 + score_skill 评分）
2. Q2 state 生命周期？→ 是（工单持久化 + 状态机）
3. 类别：**上层**（业务流程）
4. 命名：`ticket_classify_skill` 或 `support_skill`
5. 未来扩展：可复用 ReactLoop 框架

## 9. 反模式（不要做）

### 9.1 反模式 1：底层 skill 调用上层 skill

```python
# ❌ 禁止: 底层 skill 不应该编排
class SearchSkill(Skill):
    async def handle(self, args, ctx):
        result = await search_db(args)  # OK
        result.update(await gather_skill.execute(...))  # ❌ 底层不应调上层
        return result
```

**为什么禁止**：底层 skill 应该是纯工具，被上层调用。如果底层调上层，会形成循环依赖（gather → search → gather → ...）。

### 9.2 反模式 2：上层 skill 直接实现底层操作

```python
# ❌ 避免: 上层 skill 应调底层，不应直接实现
class ResearchSkill(Skill):
    async def run_research(self, args, ctx):
        # 直接调 DB，不通过 read_skill
        sources = db.get_sources(args["session_id"])  # ❌ 应调底层
        # 自己写 LLM prompt
        response = llm_client.chat(messages)  # ❌ 应调 summarize_skill
```

**为什么避免**：上层 skill 应是"编排者"，不应自己实现工具。这导致代码重复（多个上层 skill 重复实现同一工具）和测试困难（不能独立测试工具）。

### 9.3 反模式 3：skill 名带"Tool"或"Service"或"Manager"

```python
# ❌ 禁止命名
class SearchTool(Skill): ...      # "Tool" 冗余
class ResearchService(Skill): ... # "Service" 是 service 层
class NotificationManager: ...    # "Manager" 是管理层
```

**为什么禁止**：skill 不是 tool（tool 是 LLM 视角），不是 service（service 是后端概念），不是 manager（manager 是管理层）。skill = skill。

## 10. 与 Unix 哲学的关系

`docs/designs/principles/unix-philosophy.md` 3 条原则 + 本文 4 个判断维度 = 完整的 skill 设计方法论：

| Unix 哲学（如何拆）| Skill 分类（如何区分）|
|---|---|
| 原则 1：底层 = 工具 | 维度 1+3+4：判定为"工具" |
| 原则 2：上层 = 业务流程 | 维度 1+2：判定为"业务" |
| 原则 3：简单 CRUD 不拆 | 维度 3：CRUD 工具集归上层（不拆）|

两者结合：
- Unix 哲学给"如何拆"
- 分类法给"拆完后归哪"

## 11. 总结

| 类别 | 一句话 | 命名风格 | 调用方 |
|---|---|---|---|
| **底层 skill** | 纯工具，单一动作 | 动词（search, read, write）| 上层 / LLM 细粒度 |
| **上层 skill** | 业务流程，多步编排 | 业务目标（gather, research, report）| LLM 高层 |
| **orchestrator alias** | 已存在 skill 的别名 | 编排视角（research_orchestrator）| LLM 高层 |

**核心心法**：
- 看到动词 → 想到底层
- 看到业务目标 → 想到上层
- 看到别名 → 想到已有 skill
- 看到"Tool/Service/Manager" → 想到这是命名错误

---

## 12. 相关文档

- `docs/designs/principles/unix-philosophy.md`：3 条 Unix 哲学原则（如何拆）
- `docs/designs/v0.32-skill-restructure.md`：v0.32 skill 重构（具体落地）
- `docs/designs/refactor-4layer-architecture.md`：4 层技术架构（D1-D14 决策）

---

## 13. 变更日志

| 日期 | 变更 | 作者 |
|---|---|---|
| 2026-06-08 | 初始 skill 分类法（4 维度 + 4 FAQ + 10 反模式）| Refactor session |
