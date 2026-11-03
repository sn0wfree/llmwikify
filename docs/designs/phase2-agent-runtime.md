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

## 未做（Stage 3）

- **ChatPlan**：`runner_v2.ChatRunnerV2` 迁到共享运行时（生产影响最大的一步）
- **SubagentPlan**：`subagent_worker` 的工具循环
- 删除死代码 `base.aask_with_tools`（生产零调用者）
- `kernel/agent/loop.py` 的 `UnifiedAgentLoop` 与新运行时二者的关系（前者只有
  codegen 一条腿在用，且那条腿自身无生产入口）
