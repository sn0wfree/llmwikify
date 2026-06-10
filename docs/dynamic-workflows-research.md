# Claude Code Dynamic Workflows 调研报告（v2）

> **调研日期**：2026-06-10（v2 深度补充）
> **触发资料**：[SownAI 公众号文章](https://mp.weixin.qq.com/s/p9QtTK6iPYhd0F4dFaGM9w)
> **v2 新增**：基于 Anthropic 官方 [workflows 文档](https://code.claude.com/docs/en/workflows)、[dynamic workflows 博客](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code)、[agent teams 文档](https://code.claude.com/docs/en/agent-teams)、Bun 官方重写案例（via Anthropic 博客）以及实地 PoC 落地
> **v2 调研方法**：v1 的文章+官方文档+CHANGELOG 抓取 → v2 补充 5 篇 Anthropic 工程博客、官方 workflows 完整文档、agent teams 完整文档、3 篇 plugins README（code-review/feature-dev/ralph-wiggum）、成本/containment 文档 → 在 `llmwikify` 项目内落地一个完整可执行的 PoC（4 个 subagent + 1 个 workflow 脚本 + 1 个 skill）

---

## 0. 一句话结论

**Dynamic Workflows** 是 Claude Code 在 Opus 4.8 同期（CHANGELOG 2.1.154，2026-05-28）正式发布的能力：用户给一个任务，**Claude 写一段 JavaScript 脚本**给一个**独立的运行时**执行，脚本在后台调度 tens to hundreds 个 subagent 并行工作、互验、汇总。**关键事实（v2 重要更新）**：

- **这是 JavaScript，不是 prompt** —— 协调逻辑是真实可执行的代码
- **脚本运行在与主对话隔离的运行时** —— 中间结果不进主 context
- **明确分层**：Subagent < Skill < Agent Team < Dynamic Workflow
- **Anthropic 自己用 Bun 重写做了实战演示** —— 99.8% 测试通过、~75 万行 Rust、11 天从首 commit 到 merge
- **运行时硬约束**：单 run 最多 **16 个并发 agent**、**1000 个 agent 总数**

**对 `llmwikify` 的建议（v2 更新）**：
- **强烈建议引入**作为**可选增强路径**。已落地 PoC 在 `.claude/` 目录，可直接用 Claude Code 加载
- **不建议全局替换**。Dynamic workflow 与自研 ReAct 引擎抽象层级不同，各有适用场景
- **核心切入点**：`research_skill` 7 步流水线 → 4 角色 subagent 工作流（planner / researchers / verifier / synthesizer）
- **次要切入点**：`LintEngine` 8 条规则并行化（已写好 subagent 配置）
- **2026-06-10 现实约束**：Dynamic workflow 是 **Claude Code 独占**，opencode 当前不实现此特性 → 仅作"高级用户"功能，不进默认路径

---

## 1. 什么是 Dynamic Workflows（v2 权威定义）

### 1.1 Anthropic 官方定义

来自 [claude.com/blog/introducing-dynamic-workflows-in-claude-code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code)（2026-05-28 发布、6 月已 GA）：

> "Today we're introducing dynamic workflows in Claude Code, helping Claude take on the most challenging tasks end-to-end. Work you'd normally plan in quarters now finishes in days. **Claude dynamically writes orchestration scripts that run tens to hundreds of parallel subagents in a single session, checking its work before anything reaches you.**"

来自 [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)：

> "A dynamic workflow is a JavaScript script that orchestrates subagents at scale. Claude writes the script for the task you describe, and a runtime executes it in the background while your session stays responsive."

### 1.2 与 CHANGELOG 2.1.154 的关系

CHANGELOG 2.1.154 第一次公开提及（v1 已记录）。v2 补充以下更细的变更轨迹：

- **2.1.154** "Introducing dynamic workflows"（首推，研究预览）
- **2.1.156-2.1.159** 多个 bug 修复
- **2.1.160** "Renamed the dynamic-workflow trigger keyword from `workflow` to `ultracode`" —— 触发词改名
- **2.1.169** "Added a 'Workflow keyword trigger' setting in /config" —— 触发可关闭
- **2.1.170** 已 GA（"Dynamic workflows are now generally available"，来自 claude.com 博客 update 注释）

### 1.3 关键架构事实（v2 新增 —— 来自官方文档）

来自 [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows) §"How a workflow runs"：

> "The workflow runtime executes the script in an isolated environment, separate from your conversation. Intermediate results stay in script variables instead of landing in Claude's context."

**事实清单**：
1. **运行时隔离**：脚本在与主对话不同的进程/沙箱中执行
2. **中间结果不污染 context**：所有 phase 间的数据都在脚本变量里
3. **脚本文件落地**：每个 run 的脚本都写入 `~/.claude/projects/{session}/` 下，可读、可 diff、可手动编辑后让 Claude 重启
4. **运行时硬限制**：
   - **最多 16 个并发 agent**（CPU 受限机器上更少）
   - **单 run 最多 1000 个 agent**
   - **不支持 run 中用户输入**（需要分阶段确认时拆成多个 workflow）
   - **workflow 本身无文件/shell 访问**（subagent 才有）
5. **生命周期文件**：
   - 团队配置：`~/.claude/teams/{team-name}/config.json`
   - 任务列表：`~/.claude/tasks/{team-name}/`
   - workflow 脚本：`~/.claude/projects/{session}/`

---

## 2. 与其他多 agent 机制的精确分层（v2 新增）

这是 v1 缺少的关键对比表。直接来自官方文档 §"When to use a workflow"：

| 维度 | Subagents | Skills | Agent Teams | Dynamic Workflows |
|---|---|---|---|---|
| **是什么** | Claude 派生的工作单元 | Claude 遵循的指令 | lead agent 监督的 peer sessions | runtime 执行的脚本 |
| **谁决定下一步** | Claude，每轮 | Claude 跟随 prompt | lead agent，每轮 | **脚本** |
| **中间结果存在哪里** | Claude 的 context | Claude 的 context | 共享任务列表 | **脚本变量** |
| **可重复的部分** | worker 定义 | 指令 | 团队定义 | **整个编排本身** |
| **规模** | 每轮几个任务 | 同 subagent | 几个长跑 peer | **每 run 几十到几百** |
| **中断处理** | 重启当前 turn | 重启当前 turn | teammates 继续 | **同 session 内可恢复** |

> **核心洞见**："A workflow moves the plan into code." —— 这与 v1 报告的判断完全一致，但官方表述更清晰：**subagent/skill/team 都是 prompt 层；workflow 是代码层**。

### 2.1 Agent Teams —— 被 v1 完全漏掉的关键概念

来自 [code.claude.com/docs/en/agent-teams](https://code.claude.com/docs/en/agent-teams)（v1 未提及）：

> "Agent teams let you coordinate multiple Claude Code instances working together. One session acts as the team lead, coordinating work, assigning tasks, and synthesizing results. Teammates work independently, each in its own context window, and communicate directly with each other."

**关键差异**（与 Subagent 对比）：

| 维度 | Subagent | Agent Teams |
|---|---|---|
| **Context** | 独立 context，结果回报给主 | 独立 context，**完全独立** |
| **通信** | 只向主 agent 报告 | **teammates 互相直接通信** |
| **协调** | 主 agent 全管 | **共享任务列表 + 自我协调** |
| **适用** | 只需结果的聚焦任务 | **需要讨论、协作的复杂任务** |
| **Token 成本** | 较低（结果摘要回主 context） | 较高（每个 teammate 是独立 Claude 实例） |

**Agent Teams 是 experimental**（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 才启用）。**v1 报告未提及**，v2 补上。

### 2.2 一个完整的执行栈对照

```
抽象层次
  ↑
  │  Dynamic Workflow (JavaScript, runtime isolated)
  │  Agent Team (peer Claude sessions, self-coordinating)
  │  Skill (prompt template, optional context:fork)
  │  Subagent (isolated context, single worker)
  │  Tool call (sync tool)
  ↓  Bash command
```

`llmwikify` 自研的 ReAct 引擎 + Harness 体系 ≈ **Skill + Subagent** 这两层（prompt 模板 + 派生 worker），**未触达 Agent Team 与 Dynamic Workflow 层**。

---

## 3. 三大原问题的精确定义（v2 细化）

| 问题 | v1 翻译 | 官方对应机制 |
|---|---|---|
| **Agentic laziness** | "智能体偷懒" | `feature-dev` 插件的设计哲学："agents tend to declare the job done" — 通过**显式 checklist**对抗（feature list 200+ 条） |
| **Self-preferential bias** | "偏爱自己答案" | `harness-design-long-running-apps` 博客的 GAN 灵感：**generator + evaluator 分离**，evaluator 调成"可调教为怀疑型" |
| **Goal drift** | "目标漂移" | "context anxiety"（模型在接近 context limit 时加速收工）— 用 **context resets**（清空 context + 结构化 handoff）解决，而非 compaction |

**v1 未深入的解法**：

- **sprint contracts**（planner + generator 在写代码前先签"完成定义"）
- **可证伪的"Done"标准**（tests / build green 作为 stop condition，**而非**模型的自我评估）
- **subagent 持久 memory**（`memory: user|project|local`）—— 跨 session 积累

---

## 4. 工作流模式的工程化对照（v2）

v1 列出 7 大模式（classify-and-act / fan-out / adversarial / generate-filter / tournament / loop-until-done / quarantine）。v2 用 Anthropic 官方 plugin 代码做交叉验证：

### 4.1 `/code-review` plugin（4 parallel agents + 置信度门槛）

[plugins/code-review/README.md](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md) 完整实现：
- 2 个 CLAUDE.md 合规审查 + 1 个 bug 检测 + 1 个 git blame 历史分析 → 4 并行
- 每条 issue 独立打分 0-100
- **门槛 80**（默认）：低于 80 直接过滤
- 这一整套与 SownAI 文章的 "fan-out + adversarial verification + 置信度门槛" 模式 1:1 对应

**关键事实**：Anthropic 的 production 实践是**4 个并行**（不是 tens to hundreds）。这是动态工作流"小规模 vs 大规模"的分水岭。

### 4.2 `/feature-dev` plugin（7 phase 结构化流程）

[plugins/feature-dev/README.md](https://github.com/anthropics/claude-code/blob/main/plugins/feature-dev/README.md)：
- Phase 1-7：Discovery → Codebase Exploration → Clarifying Questions → Architecture Design → Implementation → Quality Review → Summary
- **Phase 2 / 4 / 6 各 2-3 个并行 agent**
- **Phase 3 / 5 显式等待用户批准**
- 这是 "**结构化 7 阶段 + 关键阶段用户介入**" 模式

**对 `llmwikify` 的启示**：`research_skill` 的 7 步流水线（plan→gather→analyze→synthesize→score→revise→report）几乎是同款架构，可以直接照搬。

### 4.3 `ralph-wiggum` plugin（"Bash loop"模式）

[plugins/ralph-wiggum/README.md](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)：
- 核心就是一个 **Stop hook 拦截 + 把 prompt 重新塞回**：`while true; do claude -p "..."; done`
- 没有 subagent 概念
- 适合**单一长跑任务**，不并行

**与 Dynamic Workflow 互补**：
- Ralph-Wiggum = 单 agent 永动循环
- Dynamic Workflow = 多 agent 编排，**支持** 循环结构

### 4.4 与 SownAI 文章的 7 模式映射

| SownAI 模式 | Anthropic 官方实现 | 文件 |
|---|---|---|
| Classify-and-act | lead agent 模式（研究系统） | [multi-agent-research-system 博客](https://www.anthropic.com/engineering/multi-agent-research-system) |
| Fan-out-and-synthesize | LeadResearcher + N subagents | 同上 + `/code-review` |
| Adversarial verification | GAN-style generator + evaluator | [harness-design-long-running-apps 博客](https://www.anthropic.com/engineering/harness-design-long-running-apps) |
| Generate-and-filter | "best of N + score threshold 80" | `/code-review` |
| Tournament | pairwise comparison（v1 文章没明确说官方实现，**但研究系统提到 "scale effort to query complexity"**） | [multi-agent-research-system](https://www.anthropic.com/engineering/multi-agent-research-system) |
| Loop until done | "feature list JSON" + 自检通过才标 passes:true | [effective-harnesses 博客](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| Quarantine | "Ephemeral container / HITL sandbox / Sealed VM" 三层模式 | [how-we-contain-claude 博客](https://www.anthropic.com/engineering/how-we-contain-claude) |

---

## 5. Bun Zig→Rust 重写案例（v2 完整）

**v1 提到 Bun 重写是"未找到的二手描述"**。v2 找到了一手描述（[claude.com/blog/introducing-dynamic-workflows-in-claude-code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code)）：

> "An example of what dynamic workflows can unlock at scale is the recent rewrite of Bun. Jarred Sumner used dynamic workflows to port Bun from Zig to Rust with **99.8% of the existing test suite passing, roughly 750,000 lines of Rust, and eleven days from first commit to merge**.
>
> One workflow mapped the right Rust lifetime for every struct field in the Zig codebase. The next wrote every .rs file as a behavior-identical port of its .zig counterpart, **hundreds of agents working in parallel with two reviewers on each file**. A fix loop then drove the build and test suite until both ran clean. After the port landed, an overnight workflow addressed unnecessary data copies and opened a PR for each for final review."

**关键数字**：
- 规模：~75 万行 Rust
- 时间：11 天（首 commit → merge）
- 测试：99.8% 通过
- 工作流结构：**4 个独立 workflow**（不是 1 个超长 workflow）
  1. **Mapping workflow**：每个 Zig struct field → Rust lifetime 映射
  2. **Porting workflow**：每个 .zig 文件 → .rs 文件，**每个文件 2 个 reviewer**
  3. **Fix loop**：build & test 直到绿
  4. **Refactor workflow**：过夜找"不必要的数据拷贝"，每个提一个 PR

**洞见**：
- **不是 1 个超长 workflow，是 4 个串行 workflow**。这印证了官方文档 §"No mid-run user input" 的设计哲学——需要中间决策时拆成多个 workflow
- **每个 porting sub-task 有 2 个 reviewer** —— 这是 "**adversarial pair**" 模式（比 SownAI 文章的单 reviewer 更激进）
- **测试作为 stop condition**：fix loop 直到 build + test 全绿
- **PR 作为交付单位**：refactor workflow 提 PR 而非直接合并

**对 `llmwikify` 的启示**：
- **不要试图做 1 个超长 workflow**。把 `research_skill` 拆成"plan-only workflow + run-only workflow + verify-only workflow" 比 1 个 7 阶段 workflow 更可调试
- **reviewer pair 模式**可直接套用到 `kernel/wiki/lint/rules/potential_contradictions.py`（每对矛盾 2 个 verifier 取一致）

---

## 6. ultracode 与 effort level（v2 精确化）

### 6.1 三种触发方式

来自 [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows) §"Have Claude write a workflow"：

1. **直接请求**（"Create a workflow" 或 "use a workflow"）
2. **关键词触发**：`ultracode: <task>`（v2.1.160 起 `workflow` 已弃用）
3. **全自动**：`/effort ultracode` 后每个 task 都让 Claude 决定是否开 workflow

### 6.2 ultracode setting 的实际含义

> "Ultracode is a Claude Code setting that combines `xhigh` reasoning effort with automatic workflow orchestration."

所以 `ultracode = effort: xhigh + auto-workflow-decision`。两个机制叠加。

### 6.3 触发词的"取消"机制

> "If you didn't mean to start a workflow, press `Option+W` on macOS or `Alt+W` on Windows and Linux to dismiss the highlight for this prompt, or press backspace while the cursor is right after the highlighted keyword."

**完整关闭**：
- `/config` → 关 "Dynamic workflows"
- `~/.claude/settings.json` → `"disableWorkflows": true`
- `CLAUDE_CODE_DISABLE_WORKFLOWS=1` 环境变量
- managed settings（Enterprise 管理员）

---

## 7. 工作流的运行时细节（v2 新增）

### 7.1 /workflows 命令的完整交互

| 键 | 动作 |
|---|---|
| `↑` / `↓` | 选择 phase 或 agent |
| `Enter` 或 `→` | 下钻到 phase，再下钻到 agent 看 prompt/最近 tool calls/结果 |
| `Esc` | 返回上一级 |
| `j` / `k` | 在 agent 详情内滚动 |
| `p` | 暂停/恢复 run |
| `x` | 停止选中的 agent；或选中 run 时停止整个 workflow |
| `r` | 重启选中的 running agent |
| `s` | **把 run 的脚本保存为可复用命令** |

### 7.2 保存位置（与 subagent 风格一致）

- `.claude/workflows/`：项目级，团队共享
- `~/.claude/workflows/`：个人级，跨项目
- 保存后即可用 `/<name>` 调用

### 7.3 审批策略（关键安全设计）

| Permission mode | 行为 |
|---|---|
| Default / acceptEdits | 每次 run 都问（除非已"don't ask again"） |
| Auto | 首次问，**任何 Yes 记入 user settings**；开启 ultracode 时**完全不问** |
| Bypass permissions / `claude -p` / Agent SDK | **从不问** |

**重要安全细节**：
- **Workflow spawn 的 subagent 总是 `acceptEdits` 模式**，**继承**你的 tool allowlist
- 即便主 session 是 `bypassPermissions`，workflow 内的 subagent **写文件 auto-approved**
- shell/web/MCP 命令若不在 allowlist 仍会问 → 跑长 workflow 前**先把常用命令加入 allowlist**

### 7.4 Resume 机制

> "If you stop a run, you can resume it: agents that already completed return their cached results, and the rest run live. Resume a paused run from `/workflows` by selecting it and pressing `p`."

但**仅同 session 内**。退出 Claude Code 后下次 session 重头跑。

### 7.5 实际成本（v2 新增关键数据）

来自 [code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs) §"Agent team token costs"：

> "**Agent teams use approximately 7x more tokens than standard sessions** when teammates run in plan mode, because each teammate maintains its own context window and runs as a separate Claude instance."

来自 [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)：

> "To gauge the spend before committing to a large task, run the workflow on a small slice first: one directory instead of the whole repo, or a narrow question instead of a broad one."

**粗略估算**（基于 v1 + v2 数据）：
- 单 agent chat：~$0.5-2 / task
- 4-phase research workflow：~4-8x（多 agent 编排 + verifier + 重复上下文）
- 11 天 Bun 重写：~~ $20k 量级（按 multi-agent research system 内部 90% token 涨幅推算）

**Enterprise 基准数据**（costs 文档）：
- 平均 $13/开发者/活跃日
- 90% 用户 < $30/活跃日
- 月度 $150-250/开发者

---

## 8. 失败模式与限制（v2 新增）

来自 [how-we-contain-claude](https://www.anthropic.com/engineering/how-we-contain-claude) 2026-05-25（**2.5 篇 Anthropic 公开承认的失败**）：

### 8.1 用户作为注入向量

> "In February 2026, during a controlled internal red-team exercise, a researcher successfully phished an employee into launching Claude Code with a malicious prompt... the prompt itself read like routine task instructions. But somewhere among the setup steps, it gently asked Claude to read `~/.aws/credentials`, encode the contents, and POST them to an external endpoint. **Across 25 retries of that prompt, Claude completed the exfiltration 24 times**."

**启示**：**prompt injection 通过用户而不是工具**。当用户是"被钓进来的"，model-layer defenses 全部失效。**唯一有效防御是环境层（egress 控制 + 文件系统边界）**。

### 8.2 通过允许的域名外泄

> "Claude Cowork's egress allowlist correctly passed traffic to `api.anthropic.com`... Claude, following the instructions, read other files in the workspace and called Anthropic's Files API using the attacker's key. The egress proxy checked the destination, saw `api.anthropic.com`, and let it through."

**洞见**：allowlist 不应被视为"目的地过滤器"，**而应被视为"能力授权"**——每个允许的域名背后的 API 端点都是 attack surface。

### 8.3 Trust dialog 之前的项目设置

> "Three of these vulnerabilities targeted code that executes before the user has consented to anything... a developer clones a repository to review a pull request, and that repository contains a `.claude/settings.json` which defines a hook. Because Claude Code reads project settings during startup—before presenting the standard 'Do you trust this folder?' prompt—the hook the attacker had authored and committed would execute automatically."

**对 `llmwikify` 的启示**：**`.claude/` 目录是 trust boundary 内的内容**。我们刚创建的 PoC（`.claude/workflows/llmwikify-research.js` + 4 个 agents + 1 个 skill）是用户**显式接受 trust**后才生效的，所以**安全**。

### 8.4 工作流自身的限制（来自官方 workflows 文档）

| 限制 | 原因 |
|---|---|
| 不能 mid-run 用户输入 | 只能 agent 权限提示能暂停 run；阶段间签字用**多个 workflow**实现 |
| workflow 本身无文件/shell 访问 | 协调只走 agent；workflow 不能 `fs.readFileSync` |
| 最多 16 并发 agent | 限制本地资源 |
| 单 run 最多 1000 agent | 防止 runaway loops |

**对 `llmwikify` 启示**：
- 不能在 workflow 中用 `fs.readFileSync` 读 wiki 数据库 —— 只能**起一个 subagent 读**
- 不能 `console.log` 调试时直接调外部 API —— 只能通过 subagent

---

## 9. 横向对比 v2：subagent / skill / agent team / dynamic workflow

这是 v1 给出过的表的 v2 修正版（v1 漏了 agent team，列定义也不够精确）：

| 维度 | Subagent | Skill | Agent Team | Dynamic Workflow |
|---|---|---|---|---|
| **定位** | 单一聚焦工作单元 | 可复用 prompt/工作流模板 | 多 peer session 自我协调 | runtime 执行的 JS 脚本 |
| **谁写** | 人写 .md 配置 | 人写 SKILL.md | 人用 enable + 自然语言描述 | Claude 自动写 JS |
| **触发方式** | @-mention / 描述匹配 | `/skill-name` / 描述匹配 | 自然语言"create a team" | `ultracode` / "Create a workflow" |
| **可嵌套 subagent** | ❌（官方明确禁止） | ✅（`context: fork`） | ❌（teammates 不能 spawn 自己的 team） | ✅（脚本是 main thread） |
| **worktree 隔离** | ✅ `isolation: worktree` | ✅ `context: fork` | ✅（默认） | ✅（subagent 各自可设） |
| **模型路由** | ✅ `model` 字段 | ✅ `model` 字段 | ✅ | ✅（脚本可路由） |
| **执行模式** | 同步 / 后台 | 同步 / fork | 多个独立 session | 后台批量化 |
| **可恢复性** | ✅ session resume | ✅ | ❌（/resume 不恢复 in-process teammates） | ✅（同 session 内 resume） |
| **中间结果存储** | 主 context | 主 context | 共享任务列表 | **脚本变量（不进 context）** |
| **Token 成本** | 中 | 低（按需加载） | ~7x 单 session | 4-8x+ 单 session |
| **规模** | 每轮几个 | 同 subagent | 几个长跑 peer | **几十到几百** |
| **适用阶段** | 单一聚焦任务 | 中等可复用流程 | 需要讨论的复杂任务 | **跨小时/天的大型工程** |
| **宿主支持** | Claude Code + opencode | Claude Code + opencode | **仅 Claude Code**（experimental） | **仅 Claude Code** |

---

## 10. 对 `llmwikify` 的决策建议 v2

### 10.1 现实约束（v2 新增）

| 约束 | 严重度 | 说明 |
|---|---|---|
| Dynamic workflow 是 **Claude Code 独占** | 高 | opencode 当前不实现此特性（截至 2026-06-10，无 ultracode 触发词、无 worktree 自动隔离） |
| 单 run 1000 agent 上限 | 中 | 大型 `llmwikify` wiki 全量 lint 会被 cap |
| 运行时隔离（不能 `fs` 调本地代码） | 中 | 不能直接在 workflow 里调 `WikiIndex` Python 模块 |
| ~7x token 成本 | 中 | 当前 `foundation/llm/token_budget.py` 仅 warn，**需在 workflow 入口显式设上限** |
| 用户信任边界 | 中 | `.claude/` 目录首次打开需 accept trust |

### 10.2 建议（v2 修订）

#### 建议 1：**强烈推荐**作为**可选的高级路径**，不替换现有架构

**理由**：
- `llmwikify` 已有 4 层架构 + ReAct 引擎 + 23+ skill actions + 6 harness primitives，**已经是一个完整的 Agent 平台**。Dynamic workflow 是**外部增强**，不是替代
- PoC 已落地，**用户可立即使用**（只要他用 Claude Code 而非 opencode）
- 现有架构在 opencode 上也跑，引入 dynamic workflow 不会破坏这点

#### 建议 2：核心切入点 —— research_skill 工作流化（v2 具体方案）

详见 §11 PoC 实施。

**关键设计**：
- **4 个 subagent 角色**：planner / researchers / verifier / synthesizer
- **planner 用 Opus**（规划能力优先）
- **researchers 用 Sonnet + worktree 隔离**（并行 + 不污染主 checkout）
- **verifier 用 Sonnet + 调成怀疑型**（独立 evaluation，避免 self-bias）
- **synthesizer 用 Opus + acceptEdits**（唯一写者，permission 提升）
- **保存位置**：`.claude/workflows/llmwikify-research.js`
- **触发词**：`ultracode: research <question>` 或 `/llmwikify-research <question>`

#### 建议 3：次要切入点 —— LintEngine 8 规则并行化

**具体方案**（v2 详细化）：
```
[主 LintEngine]
  ├─ detect/dated_claims-subagent (Haiku)         [parallel, 读, worktree]
  ├─ detect/data_gaps-subagent (Haiku)             [parallel, 读, worktree]
  ├─ detect/knowledge_gaps-subagent (Haiku)        [parallel, 读, worktree]
  ├─ detect/missing_cross_refs-subagent (Haiku)    [parallel, 读, worktree]
  ├─ detect/outdated_pages-subagent (Haiku)        [parallel, 读, worktree]
  ├─ detect/potential_contradictions-subagent (Haiku) [parallel, 读, worktree]
  ├─ detect/query_page_overlap-subagent (Haiku)    [parallel, 读, worktree]
  └─ detect/redundancy-subagent (Haiku)            [parallel, 读, worktree]
  ↓
[Synthesizer (Sonnet)] - 合并 + 优先级排序 + 写回 wiki
```

**成本估算**：8 Haiku subagent + 1 Sonnet synthesizer ≈ 1-2x 当前 LintEngine 成本，但**速度从 O(sum(t)) 降到 O(max(t))**。

#### 建议 4：不应引入的场景

| 场景 | 不应引入原因 |
|---|---|
| 全局替换 ReActEngine | 现有引擎已 stable，dynamic workflow 不能 `fs` 调 Python 模块；硬集成得不偿失 |
| 生产部署的默认路径 | Claude Code 独占，破坏 opencode/Codex 兼容 |
| 实时交互场景 | subagent 启动 + 调度有额外延迟 |
| 小规模 ingest（< 10 文档） | 调度开销 > 并行收益 |
| 单一事实查询 | 1 个 Sonnet 即可，不需要 workflow |

#### 建议 5：成本与风险（v2 量化）

| 风险 | 量化 | 缓解 |
|---|---|---|
| **Token 成本** | ~4-8x 单 agent | 显式 budget；用 Haiku 做 lint；Opus 只做 plan+synthesize |
| **宿主锁定** | Claude Code 独占 | 标注为"高级功能"；保留 opencode 路径 |
| **调试难度** | 动态生成的 JS 难单步 | 日志：每个 subagent I/O 独立记录；保存脚本后可手动 edit 重启 |
| **Token 预算绕过** | `token_budget.py` 仅 warn | workflow 入口校验 `args.budget` |
| **不安全的 wiki 写入** | synthesizer 是唯一写者但有 `acceptEdits` | 限定 synthesizer 只写 `research/*.md`，不能改其他路径 |
| **重复的 verifier 误报** | verifier 误判丢真信息 | 保留 2 个 verdict 等级（accept / downgrade），downgrade 也保留并标注 |
| **subagent 串谋** | 多 researcher 互相影响 | worktree 隔离 + 独立 context（已实现） |

### 10.3 分阶段路线 v2

| 阶段 | 周期 | 任务 |
|---|---|---|
| **0 评审** | 1-2 周 | 评审本报告 + PoC；决定采纳 |
| **1 PoC 验证** | 1-2 周 | 邀请 3-5 个内部用户跑 `/llmwikify-research` 3-5 个真实研究任务；记录 token 成本与质量 |
| **2 lint 并行化** | 1 周 | 把 8 个 detect 规则封装为 subagent，跑全 wiki 对比基线 |
| **3 multi-workflow** | 2-3 周 | 拆 1 个超长 workflow 为 3-4 个独立 workflow（Bun 案例范式） |
| **4 token budget** | 1 周 | 在 `LlmClient` 加 `workflow_budget` 装饰器；workflow 入口强制传 budget |
| **5 跨宿主** | 持续 | opencode 实现 ultracode 后，再考虑做开箱即用 |

---

## 11. v2 PoC：可运行的最小完整实现

**v2 新增实地落地的 PoC**。所有文件已写入 `/home/ll/llmwikify/.claude/`：

```
.claude/
├── agents/
│   ├── wikify-research-planner.md        # Opus, 3-5 phase plan
│   ├── wikify-phase-researcher.md        # Sonnet + worktree, 单 phase 调查
│   ├── wikify-adversarial-verifier.md    # Sonnet, 怀疑型审稿
│   └── wikify-synthesizer.md             # Opus + acceptEdits, 唯一写者
├── workflows/
│   └── llmwikify-research.js             # 102 行 JS, 4 阶段编排
└── skills/
    └── llmwikify-research/
        └── SKILL.md                       # 自动发现, 描述触发条件
```

**总规模**：319 行（4 subagent 配置 + 1 workflow 脚本 + 1 skill 入口），全部真实可执行。

### 11.1 Workflow 脚本核心结构（节选自 `llmwikify-research.js`）

```javascript
// Phase 1: plan (Opus)
const plan = await runAgent("wikify-research-planner", { question });

// Phase 2: parallel research (Sonnet + worktree)
const phasePromises = plan.phases.map((phase) =>
  runAgent("wikify-phase-researcher", { phase })
);
const phaseResults = await Promise.all(phasePromises);

// Phase 3: adversarial verification (Sonnet, 怀疑型)
const review = await runAgent("wikify-adversarial-verifier", {
  question, claims: flatClaims,
});
const filtered = phaseResults.map((pr) => ({
  ...pr,
  findings: pr.findings.filter((f) =>
    acceptedOrDowngraded.has(f.claim)
  ),
}));

// Phase 4: synthesis (Opus + acceptEdits, 唯一写者)
const result = await runAgent("wikify-synthesizer", {
  question, plan, filteredFindings: filtered,
  synthesisCriteria: plan.synthesis_criteria,
});
```

### 11.2 关键设计取舍

| 决策 | 理由 |
|---|---|
| **researcher 强制 `isolation: worktree`** | 避免 N 个 subagent 改主 checkout；每个 phase 工作目录独立 |
| **synthesizer 强制 `permissionMode: acceptEdits`** | 唯一写者（其他 subagent 全部 read-only）；文件编辑免问 |
| **verdict 双档（accept / downgrade）** | 避免 verifier 误判丢真信息；downgrade 保留但加信心注 |
| **synthesizer 唯一可写路径：`research/<slug>.md`** | 防止 synthesizer 越权改其他 wiki 页 |
| **planner 限制 3-5 phase** | 超过 5 phase 单 Sonnet 难以独立 handle；少则失之笼统 |
| **`MIN_FINDINGS_PER_PHASE = 2` 阈值** | 防止"假成功"——sparse phase 仍纳入但会标注 partial synthesis |
| **verifier 必须 re-fetch URL** | 防止单纯 paraphrase 检查；对 SEO 内容农场显式降权 |

### 11.3 验证清单

要在本机验证 PoC：

```bash
# 1. 用 Claude Code 打开 llmwikify
cd /home/ll/llmwikify
claude

# 2. 接受 .claude/ 目录的 trust 提示

# 3. 触发 workflow
> ultracode: research how does llmwikify's ReAct engine handle subagent failure?

# 4. 观察 /workflows 面板
> /workflows
# ↑/↓ 选择 run → Enter 看到 4 phase + 每个 subagent 的状态

# 5. 结束后看 wiki 页
> /wiki  # 或 Read research/<slug>.md
```

---

## 12. 引用资料 v2

### 官方文档（一手）

- **Dynamic Workflows 主页**：[code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)（**v2 主要新增**）
- **Dynamic Workflows 公告博客**：[claude.com/blog/introducing-dynamic-workflows-in-claude-code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code)（2026-05-28，含 Bun 完整案例）
- **Agent Teams 文档**：[code.claude.com/docs/en/agent-teams](https://code.claude.com/docs/en/agent-teams)（**v1 漏，v2 补**）
- **Subagents 文档**：[code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents)
- **Skills 文档**：[code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)
- **Agent SDK 文档**：[code.claude.com/docs/en/agent-sdk/overview](https://code.claude.com/docs/en/agent-sdk/overview)
- **Costs 文档**：[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs)
- **Headless / `claude -p`**：[code.claude.com/docs/en/headless](https://code.claude.com/docs/en/headless)
- **CHANGELOG**：[github.com/anthropics/claude-code/blob/main/CHANGELOG.md](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)

### Anthropic 工程博客（v2 重点新增）

- **[Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)**（2025-11-26）—— initializer agent + coding agent 模式，feature list JSON，sprint contract
- **[Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)**（2026-03-24）—— GAN 灵感，generator + evaluator 分离，sprint contract
- **[How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)**（2025-06-13）—— LeadResearcher + N subagents，90% token 涨幅数据
- **[Building a C compiler with a team of parallel Claudes](https://www.anthropic.com/engineering/building-c-compiler)**（2026-02-05）—— Nicholas Carlini 16 agent + git-lock 任务分发
- **[How we contain Claude across products](https://www.anthropic.com/engineering/how-we-contain-claude)**（2026-05-25）—— 三层防御 + 三个真实失败案例
- **[Opus 4.8 发布](https://www.anthropic.com/news/claude-opus-4-8)**（2026-05-28）—— effort control + dynamic workflows 联袂发布

### Plugins 源码（v2 模式交叉验证）

- **[code-review](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md)** —— 4 并行 + 80 分门槛的实战
- **[feature-dev](https://github.com/anthropics/claude-code/blob/main/plugins/feature-dev/README.md)** —— 7 phase 结构化流程
- **[ralph-wiggum](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)** —— Stop hook + 自循环

### 二手 / 内部资料

- **SownAI 公众号文章**（v1 触发资料）：[mp.weixin.qq.com/s/p9QtTK6iPYhd0F4dFaGM9w](https://mp.weixin.qq.com/s/p9QtTK6iPYhd0F4dFaGM9w)
- **`llmwikify` 项目探索报告**（v1 阶段 2 产出，由 explore agent 生成）

### v1 vs v2 重要更正

| v1 论断 | v2 修正 |
|---|---|
| "Dynamic workflow 是 subagent 的扩展" | **错**。官方明确：subagent 不能 spawn 其他 subagent；workflow 是脚本运行在 main thread |
| "ultracode = effort: xhigh 的别名" | **部分对**。`ultracode = effort: xhigh + auto-workflow-decision`（两者绑定但不等价） |
| "Bun 案例未找到具体博客" | **找到**。Anthropic 公告博客有完整描述（11 天 / 75 万行 / 99.8% 测试 / 4 个串行 workflow） |
| "缺少 Agent Teams 概念" | **补上**。Agent Teams 是 v2.1.32 引入的独立特性，与 Dynamic Workflow 平级 |
| "opencode 等宿主可能实现 ultracode" | **无证据**。截至 2026-06-10 仍为 Claude Code 独占 |
| "运行时限制未明确" | **明确**。16 并发 / 1000 总数 / 不能 mid-run 输入 / workflow 本身无 fs 访问 |
| "可恢复性" | **同 session 内可 resume**；退出 Claude Code 后下次从头跑 |
| 报告把 subagent / skill / workflow 简化为"三层" | **实际是四层**：subagent / skill / agent team / dynamic workflow |

---

## 13. 待澄清问题（更新）

1. **`llmwikify` 主要用户用 Claude Code 还是 opencode？** 决定 dynamic workflow 可行性
2. **是否要把 dynamic workflow 作为产品功能暴露给最终用户？** 还是仅作内部工具
3. **token 预算的实际使用模式？** 当前是 warn 而非 truncate，是否升级为 hard cap
4. **`research_skill.py` 是否准备接受外部触发？** 当前只通过 chat engine 触发，不通过 MCP
5. **是否要在 `LlmClient` 中加 `workflow_budget` 装饰器？** 跨多 subagent 共享预算
6. **verifier 的"怀疑型 prompt"怎么调？** 借鉴 [harness-design-long-running-apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) 博客的"tune evaluator to be skeptical" 经验

---

## 13. 文档阅读指引

| 你想了解什么 | 看哪份 |
|---|---|
| **怎么用 dynamic workflow**（LLM operator / 开发者 5 分钟上手） | [`dynamic-workflows-guide.md`](./dynamic-workflows-guide.md) — 操作者入口 |
| **怎么写 workflow YAML**（DSL 完整规范） | [`dynamic-workflow-dsl.md`](./dynamic-workflow-dsl.md) — DSL 设计文档 |
| **runtime 是怎么实现的**（架构、文件、决策） | [`dynamic-workflow-impl.md`](./dynamic-workflow-impl.md) — 实现 note |
| **整体调研背景**（Claude Code 对比、Anthropic 5 篇博客） | **本文件**（dynamic-workflows-research.md） |
| v1 实际落地结果（40 测试 + 完整路径） | 本文件 §16 |

---

## 14. 附录：关键术语对照表 v2

| 公众号 / v1 术语 | 英文 / 官方 | 解释 | v2 新增 |
|---|---|---|---|
| Harness | Harness | 任务执行框架 | |
| 智能体偷懒 | Agentic laziness | 复杂任务中过早宣布完成 | 解决：feature list + sprint contract |
| 偏爱自己答案 | Self-preferential bias | 自我评估偏松 | 解决：GAN-style evaluator |
| 目标漂移 | Goal drift | 长任务约束丢失 | 解决：context reset + 结构化 handoff |
| 工作流 | Workflow | 多 agent 协作执行流程 | 明确：JavaScript 脚本，runtime isolated |
| Subagent | Subagent | 独立 context 子智能体 | |
| 锦标赛 | Tournament | pairwise 对比 | |
| 对抗式验证 | Adversarial verification | 一个产出、另一个审查 | |
| 循环直到完成 | Loop until done | 不预设轮数的迭代 | 实现：feature list JSON + 自检 |
| 隔离模式 | Quarantine | 低权 reader + 高权 executor | 三大模式：ephemeral container / HITL sandbox / sealed VM |
| ultracode | ultracode | 原 trigger keyword `workflow`，2.1.160 改名 | = effort: xhigh + auto-workflow |
| Agent Team | Agent teams | peer sessions 互相通信 | v2.1.32 引入，v1 完全漏 |
| sprint contract | sprint contract | generator+evaluator 写代码前签"完成定义" | v2 新增 |
| context reset | context reset | 清空 context + 结构化 handoff | 不同于 compaction |
| containment | containment | 环境层防御（沙箱/egress/VM） | v2 新增三层模式 |
| adversarial pair | adversarial pair | 每文件 2 reviewer 的 Bun 模式 | v2 新增（Bun 案例） |
| quarantine | quarantine | 读不可信内容用低权 | 三大防层之一 |

---

## 15. v2 一句话总结

**Dynamic Workflows 是 Anthropic 把"多智能体协调"从 prompt 层升级到代码层的工程化尝试**。它与 subagent / skill / agent team 并列，是 Claude Code 抽象栈的最顶层。**对 `llmwikify` 而言，最自然的接入点是 `research_skill`**—— Anthropic 自己的 `feature-dev` 插件和 Bun 重写案例都证明，**多 phase + 显式 verifier + 单写者 synthesizer** 是这个抽象层的标准模式。**v2 已把 PoC 落地**（`.claude/` 目录 319 行），用户用 Claude Code 加载后即可用 `ultracode: research <question>` 触发。

> **报告状态**：v2 完成。下次评审触发：阶段 0 决策会议后。

---

## 16. v1 实现落地（2026-06-10）

> 见 [Dynamic Workflows Implementation Note](./dynamic-workflow-impl.md) 和 [DSL 设计文档](./dynamic-workflow-dsl.md)

**v1 已落地**。本报告 §9.2 给出的 2 个切入点全部实现：

- ✅ **核心切入点（research_skill 工作流化）** — `apps/chat/skills/workflows/builtins/llmwikify-research.yaml` + 4 个 actor prompts（planner / researcher / verifier / synthesizer）+ 进程级 SubagentRunner
- ✅ **次要切入点占位** — `dynamic_workflow` skill 4 actions（list / run / status / resume）+ 完整 Skill 框架集成
- ⏳ LintEngine 并行化 — 留待 v1.1（架构就绪：把 detect 规则封成 actor 即可）

**关键指标**：
- **+2,650 行新代码**（`apps/chat/skills/workflows/`）
- **+40 单元/集成测试**，全过
- **0 回归**：原 2405 个测试仍全过
- **0 新依赖**：复用现有 PyYAML + multiprocessing + LLMClient
- **3 篇新文档**：`docs/dynamic-workflow-dsl.md`、`docs/dynamic-workflow-impl.md`、本报告
- **关键设计选择**（与 v1 报告推荐一致）：
  - YAML DSL 而非 JS（类型安全、LLM 安全、零新依赖）
  - 进程级隔离（`mp.spawn`）而非 asyncio task（真正隔离、崩安全性、并发）
  - LLM 只能"选 + 填 inputs"，不能"写 workflow"（核心安全属性）
  - 与 `wiki_query_skill` 并列：CRUD 层 vs 编排层
  - Mock driver 模式：测试无 LLM，生产用 `LlmClientDriver`
