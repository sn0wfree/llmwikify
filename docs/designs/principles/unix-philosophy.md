# Unix 哲学原则

> **v0.32 skill 重构的核心指导思想之一。**
> 适用于 llmwikify 的 skill 体系设计，以及任何"工具 + 业务流程"分层场景。

## 核心 3 条原则

### 原则 1：底层 = 工具（单一职责、纯数据操作）

**底层 skill 只做单一简单事件**，与具体业务无关。

- 每个底层 skill 暴露 **1 个 action**（或最多 2-3 个高度内聚的）
- 底层 skill **不调用其他 skill**（避免循环依赖）
- 底层 skill 直接操作 kernel/foundation 资源（DB、文件、LLM）
- 命名以"动词"为主：`search`、`read`、`write`、`extract`、`score`、`filter`...

**llmwikify 落地**：12 个底层 skill（search/extract/read/write/lint/plan/analyze/summarize/score/revise/filter/graph）

### 原则 2：上层 = 业务流程（编排底层完成业务目标）

**上层 skill 内部组合多个底层 skill** 完成业务流。

- 每个上层 skill 暴露 **1 个主 action**（业务入口），可能带 2-3 个辅助 action
- 上层 skill **内部直接调底层 skill 的 handler**（Python 函数调用，**不通过 LLM**）
- 上层 skill 体现"业务知识"——哪几步、按什么顺序、什么条件下调哪个底层
- 命名以"业务目标"为主：`gather`、`research`、`wiki_query`、`report`、`ingest`...

**llmwikify 落地**：9 个上层 skill（gather/ingest/report/wiki_query/research/memory/notify/dream/scheduler）

### 原则 3：简单 CRUD 不拆（已经是 Unix 风格）

**不是所有 skill 都该按 Unix 哲学拆**。简单 CRUD 工具本身就是 Unix 风格（`ls`/`cat`/`rm`），再拆底层是过度设计。

- **判断标准**：这个 skill 的 actions 是不是每个都是独立的"原语"（没有"先做 X 再做 Y"的组合）？
- **是 → 保持现状**（不要强行拆）
- **否 → 按原则 1+2 拆**

**llmwikify 落地**：
- `scheduler_skill`（CRUD：add_job / list_jobs / remove_job / trigger）— **保持现状**（本身就是 cron / at 的等价物）
- `memory_skill` / `notify_skill`（CRUD：append/query/clear / list/mark/subscribe）— **保持 4 actions 形状，但内部复用底层 skill 实现**

## 不适用边界

Unix 哲学**不**适用于以下场景：

| 场景 | 原因 |
|---|---|
| **纯数据 schema**（Pydantic model、ORM table）| 不是 skill，无业务入口 |
| **单点 LLM 抽象**（如 `llm_step.run_prompt`）| 属于 kernel/foundation 基础设施 |
| **状态机本身**（orchestrator 6 步）| 持久化 + 异常恢复，单独设计 |
| **纯业务数据访问**（如 `ppt_schema.py`）| 模式固定，不涉及工具组合 |

## 在 llmwikify 中的具体体现

### ✅ 正确的拆分

```python
# 底层 skill：纯工具
class SearchSkill(Skill):
    name = "search"
    actions = {"search": SkillAction(handler=search, ...)}

# 上层 skill：业务流程
class GatherSkill(Skill):
    name = "gather"
    actions = {"gather_for_research": SkillAction(handler=gather_for_research, ...)}

async def gather_for_research(args, ctx):
    # 1. 调底层 search
    search_result = await search_skill.actions["search"].handler(args, ctx)
    # 2. 调底层 filter
    filter_result = await filter_skill.actions["filter"].handler(..., ctx)
    # 3. 调底层 extract
    sources = []
    for s in filter_result.data["filtered"]:
        extract = await extract_skill.actions["extract"].handler(..., ctx)
        sources.append(...)
    return SkillResult(status="ok", data={"sources": sources})
```

**关键设计点**：
- 上层 skill 调底层 skill **通过 Python 函数调用**（不经过 LLM 重入）
- 上层 skill **可选地被 LLM 直接调用**（细粒度）
- LLM 可选粒度：高层一键 vs 底层组合

### ❌ 过度拆分的反例

```python
# ❌ 把 memory_skill 拆成 4 个底层 skill
class MemoryStoreSkill(Skill): ...   # 写
class MemoryQuerySkill(Skill): ...   # 读
class MemorySummarizeSkill(Skill): ... # 总结
class MemoryClearSkill(Skill): ...  # 清

# ❌ 然后又叠一个 memory_skill 上层
class MemorySkill(Skill):
    actions = {
        "append": 调用 MemoryStoreSkill,
        "query": 调用 MemoryQuerySkill,
        "summarize": 调用 MemorySummarizeSkill,
        "clear": 调用 MemoryClearSkill,
    }
```

**为什么是反例**：
- 4 个"底层" actions（store/query/summarize/clear）每个都是**原语**，无业务流程
- LLM 看到的 action 数翻倍（从 4 → 8）
- 增加了间接层，调试复杂度上升
- memory 本身**已经是 Unix 风格**（CRUD）

✅ **正确做法**：memory_skill 保持 4 actions，**内部实现**调其他底层 skill（write/search/summarize）来复用通用能力，但 LLM 视角仍是 1 个 skill 4 个 actions。

## 与"Unix 哲学 vs Unix 工具"的对比

| 维度 | Unix 工具 | llmwikify skill |
|---|---|---|
| 工具 | `ls / cat / grep / awk` | 12 个底层 skill |
| 复合 | `ls \| grep foo \| xargs rm` | 9 个上层 skill |
| 管道 | `cmd1 \| cmd2` | Python 函数调用（同进程）|
| 脚本 | `bash script.sh` | orchestrator 状态机（持久化）|
| 进程边界 | 独立进程 | 同一 Python 进程（同步）|
| 退出码 | 0/非 0 | `SkillResult(status="ok"/"error", ...)` |

## 适用时机判断流程

遇到新能力要设计为 skill 时，按以下流程判断：

```
新能力 X
  │
  ├─ X 是纯数据操作（DB/文件读写）？ ─→ 放入"底层 skill"池
  │
  ├─ X 是业务流程（多步、有顺序、有条件）？ ─→ 放入"上层 skill"池
  │   │
  │   └─ X 内部需要哪些步骤？ → 拆出对应底层 skill，复用
  │
  ├─ X 是简单 CRUD（add/list/remove/get）？ ─→ 保持 1 个 skill 多 actions
  │   │
  │   └─ X 内部能否复用已有底层 skill（write/search）？ → 复用
  │
  └─ X 跨 5+ 步骤且需状态持久化？ ─→ 设计为 orchestrator
      │
      └─ orchestrator 是否要 LLM 选粒度？ → 拆上层 + 底层
```

## 总结

| 原则 | 适用 | 不适用 |
|---|---|---|
| **底层 = 工具** | 跨业务复用的基础操作 | 仅在一个 skill 中用的特殊操作 |
| **上层 = 业务流程** | 多步骤、有顺序的业务流 | 单步、一次性的操作 |
| **简单 CRUD 不拆** | 已经是 Unix 风格的 CRUD | 复杂的、可拆的业务流 |

**总原则**：**让 LLM 看到的 skill 池 = 业务词汇**（research/gather/wiki_query），**不让 LLM 看到工具实现细节**（filter/score/extract）。这样 LLM 决策更准确，代码复用度更高。

---

## 相关文档

- `docs/designs/principles/skill-taxonomy.md`：skill 分类法（如何区分底层 vs 上层）
- `docs/designs/v0.32-skill-restructure.md`：本原则在 v0.32 重构中的具体落地
- `docs/designs/refactor-4layer-architecture.md`：4 层技术架构（D1-D14 决策）
- `docs/LLM_WIKI_PRINCIPLES.md`：Karpathy LLM Wiki 原始原则
