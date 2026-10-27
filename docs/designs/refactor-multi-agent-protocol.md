# 多 Agent 重构协作协议（llmwikify 专用版）

> **状态**：协议已落地，尚未有批次按本协议完整跑过一轮。
> 批次 0（FK profile / achat 契约 / 连接生命周期）是**手工**按等效纪律完成的
> ——无红提交逐个验证、每 commit 配自己的测试、方案先行——但没有经过本协议
> 的 handoff 校验门。
>
> **落盘位置**：
> - `.claude/agents/wikify-refactor-*.md` — 7 个角色提示词
> - `scripts/validate_handoff.py` — 交接校验器（唯一的门）
> - `tests/test_validate_handoff.py` — 校验器回归网（30 用例 + 4 处变异验证）
> - `docs/designs/refactor-multi-agent-protocol.md` — 本文档
> - `docs/designs/refactor-tasks.json` — 任务板（编排者唯一可写的状态文件）
> - `docs/designs/refactor-session-notes.md` — 决策 / 回滚点 / 未解决问题
> - `docs/designs/refactor-handoff/` — handoff artifact 目录
>   （**只放 artifact**，不放任务板，避免校验器每次都报一个「跳过」警告）
>
> **相关既有资产**（不要重复造轮子）：
> - `docs/designs/reuse-and-performance-isolation-plan.md` — 候选池 U1–U13 / P1–P16、批次 0–5
> - `docs/designs/codebase-survey.md` — 复用现状独立复核、克隆双口径数据
> - `docs/designs/code-reuse-optimization.md` — 批次 0 修订记录
> - `scripts/clone_survey.py` — AST 归一化克隆检测（本仓替代 CPD/jscpd）
> - `scripts/check_architecture.py` — 四层依赖方向守卫

---

## 1. 这份协议解决什么

一个大型重构里最容易失控的不是「改不动」，而是**上下文腐烂**：同一个 Agent
连做二十个任务后，前一个任务的上下文会污染后一个任务的判断；同时多个 Agent
并行改同一片代码会互相踩踏。

协议用两件事解决：

1. **Model Handshake** — 每个阶段的输出是下一个阶段的**已验证输入**。下游
   Agent 不需要读上游的推理过程，只需要读一份通过校验的 JSON。
2. **Orchestrator / Implementer 分离** — 规划与执行分离。编排者只做决策和
   分派，**不写业务代码**；实现者只按设计改，**不做决策**。

---

## 2. 角色与职责边界

| 角色 | Agent 文件 | 只读/只写 | 产出 |
|---|---|---|---|
| Orchestrator | `wikify-refactor-orchestrator.md` | 只写任务板 + handoff 目录 | `tasks.json`、`session_notes.md`、分派决策 |
| Recon | `wikify-refactor-recon.md` | 只读 | `<task_id>.recon.json` |
| Architect | `wikify-refactor-architect.md` | 只写设计文档 | `<task_id>.design.json` + `docs/designs/refactor-designs/<task_id>.md` |
| Implementer | `wikify-refactor-implementer.md` | 改业务代码 | `<task_id>.implement.json` |
| Reviewer | `wikify-refactor-reviewer.md` | 只读 | `<task_id>.review.json` |
| Benchmarker | `wikify-refactor-benchmarker.md` | 只写 handoff | `<task_id>.bench.json` |
| ReuseAuditor | `wikify-refactor-reuse-auditor.md` | 只读 | `<batch>.audit.json` |

**硬边界**：只有 Orchestrator 能改 `tasks.json` 和 handoff 目录的索引；只有
Implementer 能改 `src/` 下的业务代码；只有 Architect 能写设计文档。其余角色
越界即视为违规。

---

## 3. 交接契约

### 3.1 文件命名

```
docs/designs/refactor-handoff/<task_id>.<stage>.json
```

`<stage>` ∈ `recon` / `design` / `implement` / `review` / `bench` / `audit`。
文件名里的 stage 后缀是校验器的推断依据——**不要改名**。不是 handoff 形状的
JSON 在目录扫描时会被跳过并显式报告（不静默丢弃）。

### 3.2 各阶段 Schema

**recon** — 候选与证据，不含方案。

```json
{
  "scope": "src/llmwikify/kernel/graph",
  "candidates": [
    {
      "id": "C1",
      "kind": "performance|duplication|both",
      "location": "src/llmwikify/kernel/graph/cache.py:31-58",
      "evidence": "每次命中跑 3 次 COUNT/MAX 查询，无 memo；churn 22 次",
      "call_frequency": "high|medium|low",
      "test_coverage": "none|partial|full",
      "risk": "low|medium|high",
      "notes": ""
    }
  ],
  "unresolved": []
}
```

**design** — 决策、边界、接口、回滚、不做清单。

```json
{
  "task_id": "p3-graph-snapshot",
  "decision": "proceed",
  "boundary": "新增 kernel/wiki/snapshot.py；一次 lint 用一份页面快照",
  "interface": "def build_snapshot(conn, pages: list[Page]) -> Snapshot",
  "performance_constraints": {
    "complexity": "O(n) 单次遍历",
    "extra_copies": "禁止",
    "benchmark_command": "python scripts/repro_bench_graph.py"
  },
  "reuse_constraints": {
    "semantic_stability": "high",
    "max_params": 3,
    "side_effects": "none"
  },
  "rollback": "独立 commit，可直接 revert；默认实现 = 现状",
  "do_not": ["不引入 CommonUtils", "不改公开 API 契约"]
}
```

**implement** — 改了什么、测了什么、基准如何。

```json
{
  "task_id": "p3-graph-snapshot",
  "status": "done",
  "files_changed": ["src/llmwikify/kernel/wiki/snapshot.py"],
  "tests_added": ["tests/test_graph_snapshot.py"],
  "benchmark": {"before_ms": 120, "after_ms": 45, "command": "..."},
  "open_issues": [],
  "next_reviewer_focus": ["确认异常路径下快照仍然被释放"]
}
```

**review** — 结论与必须处理项。

```json
{
  "task_id": "p3-graph-snapshot",
  "verdict": "approve",
  "findings": [
    {"severity": "blocker|major|minor", "file": "...", "line": 42, "message": "..."}
  ],
  "required_actions": []
}
```

**bench** — 前后对比，**`regression` 必须是 JSON 布尔值**。

```json
{
  "task_id": "p3-graph-snapshot",
  "before": {"p50_ms": 120, "p95_ms": 180},
  "after": {"p50_ms": 45, "p95_ms": 70},
  "regression": false,
  "environment": "Windows / Python 3.12.8 / warm / 200 pages / median of 15 runs",
  "notes": ""
}
```

**audit** — 批次级审计，不设门。

```json
{
  "batch": "batch-2",
  "new_duplications": [],
  "over_abstractions": [],
  "recommendations": []
}
```

---

## 4. 校验门

`scripts/validate_handoff.py` 是唯一的门。**门不通过，下一阶段不许开始。**

| 阶段 | 必填字段 | 通过条件 | 不通过的后果 |
|---|---|---|---|
| recon | `scope`, `candidates` | `candidates` 非空 | 阻断：没有候选可设计 |
| design | `task_id`, `decision`, `boundary` | `decision == "proceed"` | `observe` / `reject` 进 backlog |
| implement | `task_id`, `status`, `files_changed` | `status == "done"` | `blocked` 退回实现者 |
| review | `task_id`, `verdict` | `verdict == "approve"` | `request_changes` 退回实现者 |
| bench | `task_id`, `before`, `after`, `regression` | `regression is False` | 回归直接阻断合并 |

额外的类型约束：`regression` 必须是布尔值。字符串 `"false"` 会被拒绝——它既不
是合法布尔值，也会让 `regression is not False` 成立从而阻断。这是有意的：
一个把 `"false"` 写进 artifact 的 Agent，不能靠它放行回归。

```powershell
# 全目录校验
D:\tools\python312\python.exe scripts/validate_handoff.py docs/designs/refactor-handoff

# 单个 artifact，机器可读
D:\tools\python312\python.exe scripts/validate_handoff.py <file> --json
```

退出码：`0` 全部通过 / `1` 有失败或被门阻断 / `2` 用法错误。

---

## 5. 写隔离与并发

- **同一时间只允许一个 Implementer 改同一目录**。冲突时编排者强制串行，
  不用「谁后写谁覆盖」。
- 批次内 **每个 PR 最多 3 个文件**。超出说明任务拆错了，回到编排者重拆，
  不要硬塞。
- 并行任务必须**文件所有权互斥**，不能让两个 Implementer 各自改同一个文件再
  靠后续合并解决。

---

## 6. Commit / PR 纪律（沿用 `AGENTS.md`）

- **不主动 commit / push / PR。** 提交前先列出文件清单 + `git diff --stat`，
  等用户确认。
- 提交信息中文，格式 `<type>(<scope>): 说明`，例如
  `fix(db): get_connection 按 (path, profile) 单例，FK 策略不再由构造顺序决定`。
- **fix 与其测试同一个 commit**，工具/测试类 commit 排最前——保证历史里没有
  「红提交」。
- 行尾：仓库 `core.autocrlf=true`，索引存 LF、**工作区用 CRLF**。编辑工具会
  把 CRLF 转成 LF，提交前必须做字节级归一，并用 `git ls-files --eol` 复核
  期望 `i/lf w/crlf`。
- 本机 `git add -p` 等交互式 flag **不可用**；拆 commit 用「写中间版本 →
  提交 → 写回完整版本」。

---

## 7. llmwikify 专属红线

这些是本仓与通用重构模板的差异点，**所有角色都必须遵守**：

1. **分层依赖方向**：`interfaces → apps, kernel, foundation`；`apps → kernel,
   foundation`；`kernel → foundation`；`foundation` 只依赖自己。
   `scripts/check_architecture.py` 必须始终报 0 violations。禁止任何
   `kernel → apps`（含 runtime lazy import）。
2. **禁止上帝工具类**：`CommonUtils`、万能 base class、用 if/else 开关控制
   行为的抽象，一律不做。抽象要用它做的事命名。
3. **三次出现再抽象**：两处相似就保持原样，除非能论证「高频漏改风险」。
4. **性能敏感路径优先保证性能**：剥离出的边界若让热路径变慢，方案作废。
   基准命令是设计的一部分，不是交付后的补充。
5. **默认实现 = 现状**：新边界先委托给现有代码，让第一个 commit 保持行为不变
   且可独立回退。
6. **Windows 现实**：PowerShell 5.1 无 `&&`；`rm -rf $path`、`pkill -f`、
   `docker rm -f $(...)` 一律不用（见 `AGENTS.md` 原则 9）。
7. **`time.time()` 在本机粒度约 15.6 ms**——任何微秒级基准必须用
   `time.perf_counter()`。这既是 Benchmarker 的要求，也是
   `apps/research/db.py::append_events` 那个 flaky 测试的根因。

---

## 8. 与通用版多 Agent 提示词的差异

本协议是通用模板的**改造版**，不是照抄。逐条差异：

| 通用模板假设 | llmwikify 实际 | 本协议的处理 |
|---|---|---|
| 核心层在 `core/` | 五层 `foundation/kernel/apps/reproduction/interfaces` | 角色提示词直接写真实路径；分层由 `check_architecture.py` 守卫 |
| `core/index.py` FTS5 高频 DB | 无此文件；FTS5 只在 `foundation/utils.py`、`kernel/principle_checker.py` 露面 | Recon 不用预设优先级，改为按真实调用链取证 |
| `core/graph_analyzer.py` PageRank | 全仓无 PageRank | 同上，不写死候选点 |
| `core/wiki.py` frontmatter/wikilink 解析 | 分散在 `kernel/path_codec.py`、`kernel/principle_checker.py`、`foundation/config.py` | 复用候选以真实调用点为单位识别 |
| `docs/architecture.md` | `ARCHITECTURE.md` + `docs/architecture/overview.md` | 角色提示词指向真实文件 |
| `tasks.json` + `handoff/` 在仓库根 | 改为 `docs/designs/refactor-handoff/` | 与既有方案文档同处一地，随仓库版本化 |
| SonarQube / CPD / jscpd | 仓库无这些工具 | 改用自建 `scripts/clone_survey.py`（AST 归一化 + 结构哈希），并要求 grep 交叉验证 |
| `pytest --benchmark` | 无 `pytest-benchmark` 依赖 | 用 `scripts/repro_bench_*.sh` + `scripts/profile_lint_*.py`，或自写计时脚本 |
| feature flag 灰度 1 周 | 无 feature flag 体系 | 回退策略改为「独立 commit 可 revert」 |
| 「每个 PR 最多 3 个文件」 | 与本仓批次划分一致 | 直接沿用 |
| 「性能任务优先于复用任务」 | 与批次 1 先于批次 2 一致 | 直接沿用 |
| 「不抽 CommonDBUtils」 | 与本仓禁止上帝工具类一致 | 升级为红线第 2 条 |
| 「一次最多替换 3 个调用点」 | 与「三次出现再抽象」一致 | 直接沿用 |

**保留的通用模板优点**：handoff JSON + schema 校验门、每 PR 文件数上限、
性能先于复用、Reviewer 的 blocker 不可被编排者强行标记完成。

---

## 9. 一次完整跑批流程

1. **Recon** 对批次涉及的范围产出候选，写 `<task_id>.recon.json`。
2. **编排者**逐个候选裁决 `proceed` / `observe` / `reject`，写进
   `docs/designs/refactor-tasks.json`。
3. **Architect** 对每个 `proceed` 候选写 `<task_id>.design.json` +
   `docs/designs/refactor-designs/<task_id>.md`。
4. `python scripts/validate_handoff.py <task_id>.design.json` → 通过才分派。
5. **Implementer** 按设计实现，补测试，写 `<task_id>.implement.json`。
6. `validate_handoff.py` → `status == "done"` 才进 Reviewer。
7. **Reviewer** 审查，写 `<task_id>.review.json`；`approve` 才可合并。
8. **性能任务**追加 **Benchmarker** 写 `<task_id>.bench.json`；
   `regression == false` 才可合并。
9. 批次结束，**ReuseAuditor** 写 `<batch>.audit.json`，结果进入下一批计划。
10. 编排者更新 `docs/designs/refactor-session-notes.md`：决策、回滚点、
    未解决问题。

---

## 10. 命令速查

```powershell
# 校验门
D:\tools\python312\python.exe scripts/validate_handoff.py docs/designs/refactor-handoff
D:\tools\python312\python.exe scripts/validate_handoff.py <file> --json

# 分层守卫（必须 0 violations）
D:\tools\python312\python.exe scripts/check_architecture.py

# 克隆检测（AST 归一化，双口径）
D:\tools\python312\python.exe scripts/clone_survey.py .analysis_tmp/clone_survey.json

# 图谱 / churn（无 LLM 成本）
graphify extract . --code-only
graphify cluster-only . --no-label --no-viz
graphify god-nodes --top 20

# 测试与 lint（本机必须用项目解释器，全局 python 无 pytest）
D:\tools\python312\python.exe -m pytest <files> -q --rootdir=D:\Github\llmwikify
D:\tools\python312\python.exe -m ruff check <files> --output-format=concise
```

---

## 11. 已知限制

- **协议尚未经真实批次验证。** 目前校验器有 30 个单元测试 + 4 处变异验证，
  但没有端到端跑过一个完整批次。首次使用时按 §9 走一遍并修掉暴露的问题。
- **`scripts/repro_bench_graph.py` 的基准前提是反的**（它把 `status` 当对照
  组，而 `status` 才是阻塞方）。Benchmarker 在用它取基线之前必须先重写它。
- **`close_all_threads()` 的闭环未完成**：跨线程释放有显式 API，但根治要靠
  worker 线程自己在 `finally` 里 `close()`。见方案文档 P15。
- **预存 flaky**：`tests/test_autoresearch.py::TestEventsCursor::
  test_get_events_since_returns_only_newer` 受 `time.time()` 粒度影响随机失败，
  非本协议引入，需单独 commit 修。
