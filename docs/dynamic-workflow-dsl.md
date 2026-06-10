# llmwikify Dynamic Workflow DSL v1

> **Status**: Draft v1 (2026-06-10)
> **Inspired by**: [Claude Code Dynamic Workflows](https://code.claude.com/docs/en/workflows) — 5 篇 Anthropic 工程博客、3 个官方 plugins (code-review/feature-dev/ralph-wiggum) 的设计哲学
> **Goal**: 让 `llmwikify` 的 chat agent 能像 Claude Code 一样"按任务动态生成多 agent 编排脚本"，但用 YAML + Python 解释器实现，与现有 ReAct 引擎、Skill 框架、Token 预算、Wiki 子系统无缝集成
> **Audience**: workflow authors. For end-to-end usage, see [`dynamic-workflows-guide.md`](./dynamic-workflows-guide.md). For runtime internals, see [`dynamic-workflow-impl.md`](./dynamic-workflow-impl.md). For background, see [`dynamic-workflows-research.md`](./dynamic-workflows-research.md).

---

## 0. 设计原则

1. **LLM 安全第一** — 描述用结构化 YAML，**不**让 LLM 生成 Python/JS 代码。LLM 只能"挑选 + 填参数"。
2. **与现有架构共存** — workflow 是 `dynamic_workflow` skill 的一个 action，**不是** ReAct 引擎的替代。
3. **可静态校验** — schema 用 Pydantic；YAML 加载时即拒绝非法 workflow。
4. **dry-run 友好** — 不调 LLM 也能验证拓扑（phase 数、依赖图、actor 数量上限）。
5. **可恢复 + 可中断** — 进度写 SQLite；中断后从最后完成 phase 续跑。

---

## 1. 顶层结构

一个 workflow 是一个 YAML 文件：

```yaml
version: 1                              # 必填，当前固定为 1
workflow:                               # 必填
  name: llmwikify-research              # 唯一标识，会成为 /<name> 命令
  description: "..."                    # 一句话描述
  triggers:                             # 触发方式（可选）
    keywords: ["research", "ultracode"]  # 关键词触发（任意一个）
    command: "/llmwikify-research"      # 命令触发
  inputs:                               # 入参 schema（JSON Schema Draft 7 子集）
    type: object
    properties:
      question: { type: string }
    required: [question]
  budget:                               # token 预算（可选，强烈建议）
    max_total_tokens: 200000
    max_concurrent_agents: 8
    on_exceed: halt                     # halt | continue
  actors:                               # 角色定义（subagent 类）
    planner:
      prompt_file: wikify-research-planner.md
      model: opus
      tools: [Read, Grep, Glob]
    researcher:
      prompt_file: wikify-phase-researcher.md
      model: sonnet
      isolation: worktree               # worktree | none
      tools: [Read, Grep, Glob, WebFetch, WebSearch]
    verifier:
      prompt_file: wikify-adversarial-verifier.md
      model: sonnet
      tools: [Read, WebFetch]
    synthesizer:
      prompt_file: wikify-synthesizer.md
      model: opus
      permission_mode: acceptEdits      # acceptEdits | default | dontAsk
      tools: [Read, Grep, Glob, Write, Edit, Bash]
  phases:                               # 执行阶段（DAG）
    - id: plan
      actor: planner
      inputs:
        question: $inputs.question
      outputs: plan
    - id: gather
      actor: researcher
      parallel: true                    # 与下列同 parallel 标记的 phase 并行
      needs: [plan]                     # 依赖
      count: 4                          # parallel: true 时，fan-out 实例数
      fan_out:                          # count > 1 时使用
        from: $plan.phases              # 列表的来源（$引用 inputs/outputs）
        per_item:
          id_prefix: gather_
          actor: researcher
          inputs:
            phase: $item
      outputs: gather_results
    - id: verify
      actor: verifier
      needs: [gather]
      inputs:
        question: $inputs.question
        claims: $gather_results.findings
      outputs: review
    - id: synthesize
      actor: synthesizer
      needs: [verify]
      inputs:
        question: $inputs.question
        plan: $plan
        filtered_findings: $gather_results.filtered
        review_summary: $review.summary
      outputs: final_report
  limits:                               # 运行时硬上限（防 runaway）
    max_total_agents: 100
    max_phase_timeout_seconds: 1800
    max_wallclock_seconds: 14400        # 4 小时
  events:                               # 可选：发往外部的进度事件
    on_phase_complete: log
    on_workflow_complete: notify
```

---

## 2. 关键概念

### 2.1 Actor（角色）

一个 actor = 一个 subagent 配置。

| 字段 | 类型 | 说明 |
|---|---|---|
| `prompt_file` | string | 相对路径；指向 `.md` 文件（与 Claude Code agents/*.md 同款 YAML frontmatter） |
| `model` | string | opus / sonnet / haiku / 完整 model id / `inherit`（从主 session 继承） |
| `tools` | list[str] | 允许的工具集（白名单）。`Read, Grep, Glob, WebFetch, WebSearch, Write, Edit, Bash` |
| `isolation` | string | `worktree`（隔离 git worktree）/`none`（默认） |
| `permission_mode` | string | Claude Code 同款：default / acceptEdits / auto / dontAsk / bypassPermissions / plan |
| `system_prompt` | string | 内联 prompt（与 prompt_file 二选一） |

### 2.2 Phase（阶段）

DAG 中的一个节点。**一个 phase = 一次 subagent 调用**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | DAG 内唯一 |
| `actor` | string | 引用 actors 中的角色 |
| `needs` | list[str] | 依赖的 phase id 列表 |
| `inputs` | dict | subagent 入参；值支持 `$` 引用 |
| `parallel` | bool | 与其他 `parallel: true` 同级 phase 并行（needs 仍生效） |
| `count` | int | 显式 fan-out 数 |
| `fan_out` | object | 数据驱动的 fan-out |
| `outputs` | string | 该 phase 输出在 DAG context 里的变量名（供后续 `$` 引用） |
| `retry` | object | 重试策略 |
| `timeout_seconds` | int | 单 phase 超时 |
| `skip_if` | string | 表达式；为 true 时跳过（语法见 §3） |

### 2.3 Fan-out（数据驱动并行）

```yaml
- id: gather
  needs: [plan]
  fan_out:
    from: $plan.phases            # 引用 plan phase 的 outputs.phases 字段
    per_item:                     # 对每个 item 创建一个 phase 实例
      id_prefix: gather_          # 实例 id = gather_<index>
      actor: researcher
      inputs:
        phase: $item
```

效果：若 `$plan.phases` 长度为 4，则自动创建 `gather_0`, `gather_1`, `gather_2`, `gather_3` 4 个 phase，全部并行。

### 2.4 $ 引用语法

| 形式 | 含义 |
|---|---|
| `$inputs.x` | 整个 workflow 的输入参数 `x` |
| `$plan` | 引用 `id=plan` 的 phase 输出（整个 dict） |
| `$plan.phases` | 嵌套访问 |
| `$item` | fan-out 内部，引用当前 item |
| `$env.HOME` | 环境变量（仅在 system_prompt 中可引用） |

引用解析发生在 runtime，**不**在加载时。

### 2.5 Skip-if 表达式

极小子集（白名单，避免 prompt injection）：

| 操作符 | 含义 |
|---|---|
| `$x == y` | 等值 |
| `$x != y` | 不等 |
| `$x > n` / `$x < n` / `$x >= n` / `$x <= n` | 数值比较 |
| `$x && $y` | 与 |
| `$x || $y` | 或 |
| `!$x` | 非 |
| `len($x) <op> n` | 长度比较 |

> **不做**：函数调用、方法调用、属性访问任意字段。**只**白名单字段。

---

## 3. 运行时模型

### 3.1 进程模型

```
[llmwikify chat process]
    │
    │ workflow.run()
    ▼
[WorkflowRunner (in-process)]
    │ parse YAML → WorkflowDAG
    │ validate (schema + DAG + limits)
    │ check budget gates
    │
    │ spawn subagents via SubagentRunner
    ▼
[SubagentRunner] ──── per subagent ────> [subprocess (python -m ...)]
    │                                          │
    │                                          │ 独立 context / 独立 LlmClient
    │                                          │ 独立 token budget bucket
    │                                          ▼
    │                                     [LLM API call(s)]
    │                                          │
    │ ◄───────── SkillResult via stdout JSON ──┘
    ▼
[DAG runner: store outputs, mark phases complete, fire events]
```

**为什么用 subprocess 而不是 asyncio task**：

- Claude Code 的 subagent 文档明确："Subagents cannot spawn other subagents" —— 用独立进程避免 GIL 共享，context 真正隔离
- 单 subagent 崩溃不会拖垮主进程
- 进程级 LlmClient 隔离 → token 计量更准确
- 与 `apps/agent/scheduler/` 现有的多进程模型一致

### 3.2 进度持久化

每个 workflow run 的状态写入 `~/.llmwikify/workflows/runs/{run_id}.json`：

```json
{
  "run_id": "wf_2026-06-10T14-30-22_abc123",
  "workflow_name": "llmwikify-research",
  "started_at": 1718026222.123,
  "status": "running",
  "phases": {
    "plan": {"status": "complete", "output": {...}, "tokens_used": 1234},
    "gather_0": {"status": "running", "started_at": 1718026225.0, "tokens_used": 5678},
    "gather_1": {"status": "complete", "output": {...}, "tokens_used": 5432},
    "verify": {"status": "pending"},
    "synthesize": {"status": "pending"}
  },
  "total_tokens_used": 12344,
  "total_agents_spawned": 5
}
```

中断后 `WorkflowRunner.resume(run_id)` 从 `pending`/`running` phase 续跑，已 `complete` 的 phase 直接复用缓存。

### 3.3 预算与限制

| 限制 | 默认 | 来源 |
|---|---|---|
| `max_total_agents` | 100 | workflow.budget 或 runtime 默认 |
| `max_concurrent_agents` | 8 | 同上 |
| `max_total_tokens` | 200000 | 同上 |
| `max_phase_timeout_seconds` | 1800 (30min) | workflow.limits |
| `max_wallclock_seconds` | 14400 (4hr) | 同上 |
| `on_exceed: halt` | halt | 中断整个 run；保留已完成 phase |
| `on_exceed: continue` | - | 标记超预算 phase 为 failed，继续后续 |

`on_exceed: halt` 时，已 `complete` 的 phase 保留在 `runs/{run_id}.json` 里，可手动 `resume`。

---

## 4. 4 个内置工作流

落地时随 PoC 一起交付：

1. **`llmwikify-research`** — 7 步研究流水线（plan→gather×N→verify→synthesize）
2. **`llmwikify-lint-parallel`** — 8 条 lint 规则并行扫描
3. **`llmwikify-factcheck`** — 跨页矛盾核查
4. **`llmwikify-batch-ingest`** — 大规模批量 ingest

存放在 `src/llmwikify/apps/chat/skills/workflows/builtins/*.yaml`。

---

## 5. Skill 集成

`dynamic_workflow` skill 暴露 4 个 action：

| Action | 作用 |
|---|---|
| `run` | `args = {name, inputs}` → 启动一个 workflow run |
| `status` | `args = {run_id}` → 查询 run 状态 |
| `resume` | `args = {run_id}` → 续跑中断的 run |
| `list` | `args = {}` → 列出所有内置 workflow |

LLM 触发方式（参见 `docs/dynamic-workflows-research.md` §1.4）：

- 用户说 "research X" → LLM 看到 `dynamic_workflow.run` 这个 tool → 调用 `args={"name": "llmwikify-research", "inputs": {"question": "X"}}`
- 不需要用户知道 ultracode 关键词
- LLM 不需要"写"workflow，只"选" workflow

### 5.1 与 `wiki_query_skill` 的 28 个 wiki_* tool 共存

`dynamic_workflow` 是一个独立 skill，**不**合并到 `wiki_query_skill`：

- `wiki_query_skill` 是 wiki CRUD 的 1:1 镜像（28 个 action）
- `dynamic_workflow` 是**编排层**（4 个 action，调用上面那 28 个 + 自定义 actor）
- 类比：wiki_query_skill 是 SQL，dynamic_workflow 是 stored procedure

---

## 6. 错误处理

| 错误 | 处理 |
|---|---|
| YAML 解析失败 | 立即抛 `WorkflowParseError`，不进入 runtime |
| schema 校验失败 | 同上，列出所有违规字段 |
| DAG 有环 | `WorkflowValidationError` |
| 单 phase 失败（retry 用尽） | 标记 `failed`；其他 phase 继续；最后整体状态 `partial` |
| 单 phase 超时 | 同上 |
| 整个 run 超时 | `halt`；保留 progress |
| 进程崩溃 / kill | progress 写 SQLite；下次启动可 `resume` |
| 预算耗尽 | 按 `on_exceed` 处理 |
| 16 并发上限 | runtime 内部 semaphore，超出的 phase 等候 |

---

## 7. 演进路线

| 版本 | 范围 |
|---|---|
| v1（当前） | YAML DSL + 进程级 subagent + 4 个内置 workflow + dynamic_workflow skill |
| v1.1 | 进度 UI（CLI `llmwikify workflow status <run_id>`） + Slack 通知 |
| v1.2 | 与 ReActEngine 集成（让 ReAct 可以在 tool 调用中触发 workflow） |
| v2.0 | 编译器：`LLM 自然语言 → workflow YAML`（取代 LLM "挑选 workflow"） |
| v3.0 | 跨语言 subagent（Node.js / Bun 子进程跑 Claude Code workflow JS） |

---

## 8. 与 Claude Code 概念的对照

| Claude Code 概念 | llmwikify DSL 等价 | 差异 |
|---|---|---|
| Subagent frontmatter | `actors.<name>.prompt_file` | 同 |
| `.claude/agents/*.md` | `src/.../workflows/actors/*.md` | 路径不同 |
| `/deep-research` JS workflow | `builtins/llmwikify-research.yaml` | YAML 而非 JS |
| `ultracode` 触发词 | `dynamic_workflow` skill 的 tool 描述 | LLM 主动选择而非关键词 |
| `/workflows` 菜单 | `dynamic_workflow.status` action | 通过 skill 暴露 |
| Runtime 16-concurrent 上限 | `runtime.max_concurrent_agents` (可调) | llmwikify 进程级调度 |
| `~/.claude/projects/` 脚本落地 | `~/.llmwikify/workflows/runs/{id}.json` | JSON 状态而非 JS 源 |

---

## 9. 完整示例

见 `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml`。
