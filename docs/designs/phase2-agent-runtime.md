# Phase 2 / 方案 1（第一阶段） — 统一运行时 + research 迁移

日期: 2026-11-02 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 先更正两处判断

架构评审说「5 套 Agent 循环」。实测后：

| 原判断 | 实测 |
|--------|------|
| `apps/research/engine.py` 是一套循环 | **不是**——它是接线层，真正的循环在 `research_runner.ReActLoop` |
| `apps/chat/base.py::aask_with_tools` 是一套循环 | 是循环，但**生产零调用者**（只有测试用）——事实死代码 |

真实的循环是 4 处：

| # | 循环 | 性质 |
|---|------|------|
| 1 | `apps/chat/agent/runner_v2.py`（ChatRunnerV2） | LLM 驱动 ReAct，**生产在用** |
| 2 | `apps/chat/agent/research_runner.py`（ReactLoop） | 规则驱动状态机，**生产在用** |
| 3 | `apps/chat/base.py::aask_with_tools` | LLM 工具循环，**生产零调用者** |
| 4 | `apps/chat/skills/workflows/subagent_worker.py` | LLM 工具循环（子进程），**生产在用** |

其中 1 与 2 **结构完全同源**——`research_runner.py` 自己的 docstring 就写着
"mirrors Plan B runner_v2 5-step state machine"。差异只在两条正交轴：

- **REASON 策略**：LLM 流 vs 注入的 callable
- **状态载体**：消息列表 vs 单一 state 对象

## 设计：统一骨架 + Plan 插槽

关键取舍：**只搬驱动、保留语义**。

`kernel/agent/runtime.py` 提供唯一的执行骨架：

```
for iteration in range(plan.max_iterations):
    before_iteration
    PRECHECK             → stop?
    REASON               → ctx.decision
    DECIDE after_reason  → stop?
    ACT                  → ctx.result
    DECIDE after_act     → stop?
    OBSERVE
    DECIDE after_observe → stop?
    after_iteration
FINALIZE
```

`AgentPlan` 是声明式配置——每个 stage 都有默认空实现，plan 只写自己做的事；
**plan 不控制流程，只控制步骤**。

stage 契约：

| stage | 契约 |
|-------|------|
| `reason` | 必须设 `ctx.decision`；留 `None` = 失败（已发错误事件），循环停止 |
| `act` | 必须设 `ctx.result`；留 `None` = 失败（已发错误事件），循环**继续**下一轮 |
| `precheck` / `decide` | 设 `ctx.stop = True` 停止；可产出事件 |

所有 stage 都是异步生成器 —— plan 产出的事件原样透传给调用方。

## Stage 2：research 迁移（已完成）

`research_runner.ReActLoop.run()` 的公开 API 不变（`ReactLoop(config).run(ctx, emit)`），
内部改为 `_ResearchPlan` + 共享运行时。

**事件顺序逐条保持**：我把旧循环体一比一搬进 plan 的各个 stage ——
PRECHECK 的 timeout/done、REASON 的签名适配与强制下一动作、ACT 的未知动作与异常、
OBSERVE 的三个 hook、PERSIST、round_complete、尾部终态 phase。

途中发现并修正的**真实行为差异**：旧循环在 reason 失败时 `return`（**不发**尾部
`phase=done`），而运行时一定会调 `finalize`。用 `_ended_early` 标志还原：
终态阶段一旦发生（timeout / done 条件 / reason 说 done / cancelled / paused /
reason 失败），就不再补「完成」事件。

## 回归网

| 文件 | 项 | 内容 |
|------|----|------|
| `tests/kernel/agent/test_runtime.py` | 17 | 骨架契约：stage 顺序、三个停止点、失败路径、迭代上界、事件透传 |
| `tests/test_research_runner_plan.py` | 19 | **差分守卫**：正常轮的完整事件序列、hook 调用顺序、5 条错误路径、6 条终态路径、强制动作、嵌套事件、dataclass 状态载体 |

`test_research_runner_plan.py` 是真正的差分守卫：它把旧循环的可观测行为
（事件序列 + hook 顺序）逐条钉死，迁移后行为一旦漂移就红。

## 验证

```
pytest tests/kernel/agent/test_runtime.py tests/test_research_runner_plan.py → 36 passed
pytest -k "research or autoresearch or react or engine"
  → 失败清单与基线逐条一致（8 项预存）
全量 pytest → 58 failed（基线 58），无新增
ruff check → clean
```

## Stage 3：chat 迁移（已完成）

`runner_v2.ChatRunnerV2` 是生产影响最大的一处——它跑在 orchestrator 的每一次对话里。

### 结构拆分

| 改动 | 内容 |
|------|------|
| `apps/chat/agent/chat_plan.py`（新） | `ChatPlan` —— 纯粹的**适配器**：每个 stage 调 runner 现有的 step 方法 |
| `apps/chat/agent/state_trace.py`（新） | `_StateTrace` / `_StateTraceEntry` 从 runner_v2 移出（plan 需要它，又不能循环 import） |
| `runner_v2.run_stream` | 循环体换成 `RUNTIME.run_stream(runtime_ctx, ChatPlan(...))` |
| `runner_v2._consolidate_memory`（新方法） | 记忆合并从循环体里抽出（原本 30 行内联在 `for` 里） |

`runner_v2` 里原来的私有名 `_StateTrace` / `_StateTraceEntry` 仍可导入（别名），
现有测试不受影响。

### stage 映射

| runtime stage | runner 方法 |
|---------------|-------------|
| before_iteration | `hook.before_iteration` |
| precheck | `_precheck`（超时 / goal 谓词 / cancelled / paused） |
| reason | `_reason`（LLM 流 + tool-call 解析） |
| decide after_reason | tool-call 记账 + 「无 tool_calls → 收敛」 |
| act | `_act`（工具执行 + microcompact） |
| decide after_act | confirmation → 停 |
| observe | `_observe`（截断的 thinking 记录） |
| after_iteration | `hook.after_iteration` + 记忆合并 |
| finalize | `_emit_done` |

### 途中踩到的两个坑

1. **`async def` 里没有 `yield` 就不是异步生成器**。`ChatPlan.decide` 起初写成
   纯协程，运行时 `async for` 直接抛 `TypeError` → 373 个测试变红。
   修法：函数体末尾留一个不可达的 `yield {}` 标记。
2. **不可达的 `yield {}` 标记不能放在会 fall-through 的位置**。它一度被实际
   执行，产出一个没有 `type` 的事件 → 39 个测试变红（`KeyError: 'type'`）。
   修法：`yield {}` 之前加 `return`，保证不可达。

### 回归网

| 文件 | 项 | 内容 |
|------|----|------|
| `tests/test_chat_plan.py` | 13 | plan↔runtime 边界：stage 映射顺序、四个停止路径、runner 确实走共享运行时、state_trace 五态仍在、旧私有名仍可导入 |
| `tests/test_apps_chat_agent_runner_v2.py` | 627 | 既有覆盖（本次只更新了 runner 的导入契约白名单——新增 runtime 依赖） |

## 验证

```
pytest tests/test_chat_plan.py + test_apps_chat_agent_runner_v2.py
  + test_runtime.py + test_research_runner_plan.py  → 675 passed
pytest -k "chat or agent or runner or orchestrator" → 失败项均为基线已有
全量 pytest → 58 failed（基线 58）
ruff check → clean
```

> 唯一「新增」的失败 `test_autoresearch.py::TestEventsCursor::test_get_events_since_returns_only_newer`
> 经 stash 对照确认为**预存的时间戳精度 flaky**（两次 append 落在同一毫秒 →
> 游标不前进），与本次改动无关：改动前后单跑都是 3/3 失败。

## Stage 4：subagent 迁移 + 删死代码（已完成）

### SubagentPlan

`subagent_worker` 的工具循环也搬到共享运行时。它的**上下文是同步的**（跑在子进程里），
所以加了一个同步桥接：

```python
# kernel/agent/runtime.py
def run_sync(coro):
    """Run a coroutine from synchronous code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
```

`SubagentPlan` 保持旧循环的契约：迭代上限 5、非致命错误退回普通 chat、
致命状态码（401/403/429/5xx）直接抛、消息记账（assistant + tool）不变。

### 删死代码：`apps/chat/base.py::aask_with_tools`

**生产零调用者**（只有 `tests/test_apps_chat_base.py` 引用）——180 行死代码
+ 169 行测试一并删除。

删掉后，生产里跑的循环从 4 处降到 **3 处**（chat / research / subagent），
而这 3 处现在共用同一个骨架。

## 收敛结果

| 循环 | 位置 | 状态 |
|------|------|------|
| chat ReAct | `runner_v2.py` | ✅ `ChatPlan` |
| research 管线 | `research_runner.py` | ✅ `_ResearchPlan` |
| subagent 工具循环 | `subagent_worker.py` | ✅ `SubagentPlan` |
| `base.py::aask_with_tools` | — | 🗑️ 已删（生产零调用） |

**「改一处语义」的改动点：从 4 处降到 1 处**（`AgentRuntime`）。

## 回归网（累计 66 项）

| 文件 | 项 | 内容 |
|------|----|------|
| `tests/kernel/agent/test_runtime.py` | 17 | 骨架契约 |
| `tests/test_research_runner_plan.py` | 19 | research 差分守卫 |
| `tests/test_chat_plan.py` | 13 | chat plan↔runtime 边界 |
| `tests/test_subagent_plan.py` | 8 | subagent plan 边界 |

## 验证

```
pytest 四份守卫 + chat runner + subagent       → 全部通过
pytest -k "chat or agent or runner or ..."     → 失败项均为基线已有
全量 pytest → 58 failed（基线 58，逐条一致）
ruff check src/llmwikify                        → clean
```

## 未做

- `kernel/agent/loop.py` 的 `UnifiedAgentLoop` 与新运行时的关系：它只有 codegen
  一条腿在用，而那条腿自身没有生产入口。待确认是「并入新运行时」还是「删」。


