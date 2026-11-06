# 代码梳理报告（graphify 图谱 + AST 复核）· 2026-11-06

> 基线 commit：`28e6ca73`（`feat/auto-doc-ingest`）
> 图谱：`graphify-out/graph.json`，24988 节点 / 48492 边 / 918 社区，`built_at_commit=28e6ca73`

## 1. 方法

| 步骤 | 工具 | 用途 |
|------|------|------|
| 刷新图谱 | `graphify update .` | AST 抽取 + 聚类，产出 `graph.json` / `GRAPH_REPORT.md` |
| 分层依赖矩阵 | 自写 AST 脚本（图谱边 + 源码校验） | 层间 / apps 内 peer 边统计 |
| 边健康检查 | `graphify diagnose multigraph` | 同端点折叠风险 |
| 可达性分析 | 自写 AST 导入图 BFS | 从 5 个生产入口出发的模块闭包 |
| 坏导入扫描 | 自写 AST 导入解析 | 校验每条 `llmwikify.*` 导入是否指向真实模块 |

> 图谱自身有两个已知局限，本次结论均经源码二次核对：
> 1. 边为**无向**（`directed: false`），跨层方向需靠 `relation` 字段判断；
> 2. 符号名匹配会误连（如 `foundation/callback/integrations/auto_ingest.py` → `apps/agent/maintenance/auto_ingest.py` 实为同名误配，源码无此 import）。

## 2. 规模与分层

`src/llmwikify` 共 **413 个 Python 模块 / 81316 LOC**：

| 层 | 文件 | LOC | 占比 |
|----|------|-----|------|
| interfaces | 77 | 12617 | 15.5% |
| apps | 199 | 43823 | 53.9% |
| kernel | 80 | 15414 | 19.0% |
| foundation | 55 | 9355 | 11.5% |

apps 内部最大块：`chat/skills` 12788 LOC、`chat/agent` 7930 LOC、`agent/maintenance` 2323 LOC、`chat/memory` 1920 LOC。

## 3. 依赖结构

跨层边（imports / imports_from / calls / uses / inherits）：

| 源 → 目标 | 边数 | 判定 |
|---|---|---|
| interfaces → apps | 57 | 允许 |
| interfaces → kernel | 102 | 允许 |
| interfaces → foundation | 196 | 允许 |
| apps → kernel | 332 | 允许 |
| apps → foundation | 167 | 允许 |
| kernel → foundation | 22 | 允许 |
| **kernel → apps / foundation → kernel|apps / apps → interfaces** | **0** | 红线保持 |

`python scripts/check_architecture.py` → **0 violation**；apps peer **0 structural + 0 runtime**。

apps 内部横向边仅剩运行时调用（chat→research 110、chat→wiki 23、agent→wiki 13），均为允许的「应用层 → 领域共享层」方向。

## 4. 耦合热点

入度 TOP（符号）：

| 入度 | 符号 | 位置 |
|---|---|---|
| 421 | `Wiki` | `kernel/wiki/wiki.py` |
| 296 | `SkillContext` | `kernel/skills/types.py` |
| 166 | `ChatRunnerV2` | `apps/chat/agent/runner_v2.py` |
| 125 | `SkillRegistry` | `apps/chat/skills/registry.py` |
| 122 | `PromptRegistry` | `foundation/prompts/prompt_registry.py` |
| 120 | `SkillResult` | `kernel/skills/types.py` |

入度 TOP（文件）：`kernel/wiki/wiki.py` 452、`apps/chat/agent/runner_v2.py` 295、`foundation/llm/streamable.py` 268、`kernel/skills/types.py` 251、`kernel/storage/index.py` 194。

`kernel/wiki/wiki.py` 由 13 个 mixin 组合而成（`kernel/wiki/mixins/{core,io,analysis}/*`），是全项目最大耦合点。

## 5. 可达性分析（生产死代码）

以 `llmwikify.__main__`、`interfaces.cli`、`interfaces.server`、`interfaces.mcp`、`interfaces.web` 为入口做导入图 BFS：

- **可达：379 / 414 模块**
- **不可达：35 模块 / 2643 LOC**

按性质分类：

### 5.1 生产死代码（仅测试引用）

| 模块 | LOC | 说明 |
|---|---|---|
| `apps/chat/agent/unified/**`（12 模块） | 1165 | 通用框架已迁 `kernel/agent/`，此树仅 9 个测试文件引用；生产零入口 |
| `kernel/principle_checker.py` | 468 | 仅 `test_v019_*` 引用；`scripts/check_prompt_principles.py` 仍 import 已不存在的 `llmwikify.core.principle_checker`（**断链**） |
| `apps/chat/db_migrations.py` | 235 | 仅测试 + `scripts/migrate_autoresearch_v3_to_v4.py` 调用 |
| `apps/chat/agent/protocols.py` | 137 | 全仓无引用 |
| `apps/chat/research_engine/{engine,actions,gates,llm_step,observer,reasoner,report,resume}.py` | 144 | v0.40 收敛后遗留 re-export shim（`routes.py` 仍被生产使用） |
| `apps/chat/{actions,engine,report,db}.py`、`apps/wiki/db.py`、`apps/chat/agent/execution_context.py`、`apps/chat/agent/unified/loop.py` | ~100 | 迁移遗留 shim（AGENTS.md 已登记为保留项） |
| `apps/agent/tools/`（包 `__init__`） | 35 | 无外部引用 |

### 5.2 误报（实际可达）

| 模块 | LOC | 原因 |
|---|---|---|
| `interfaces/web/server.py` | 101 | 独立入口 `python -m llmwikify.interfaces.web.server` |
| `foundation/templates/`、`foundation/prompts/_defaults/` | 79 | 按文件路径加载的资产，非 import 引用 |

## 6. 本轮发现的缺陷（P0，已修）

**坏导入：`llmwikify.apps.research.six_step_config_manager` 从未存在过。**

- 引入：`efba3812`（apps→apps 违规清理）。该 commit 为消除 `wiki → chat` peer 边，把
  `from llmwikify.apps.chat.config_manager import get_global_config_manager`
  批量改写为 `from llmwikify.apps.research.six_step_config_manager import ...`，
  但目标模块在该路径下从未存在过。
- 影响（3 文件 6 处运行时 import）：
  - `apps/wiki/service.py:92,119` → `get_llm()` / `get_llm_spec()` 抛 `ModuleNotFoundError`
  - `interfaces/server/http/agent/config.py:27,86,126,142` → `/api/agent/config*` 4 个端点 500
- 为何没被拦下：`check_architecture.py` 只校验**层级方向**，不校验 import 目标是否存在；相关测试也未覆盖这两条路径。

**修复**：`git mv apps/chat/config_manager.py → apps/config_manager.py`（共享基础设施层，与 `apps/db_base.py`、`apps/db.py` 同级，非 peer 子包），6 处导入改指 `llmwikify.apps.config_manager`。

验证：ruff 通过；`check_architecture.py` 0 violation + 0 peer；运行时冒烟通过（`ConfigManager.load_effective_llm_config()` 正常返回）；相关 3 个测试文件与基线逐条比对 **15 failed / 12 error 完全一致**（均为已知 Windows SQLite teardown 锁），零新增。

**教训**：架构检查只管方向，不管存在性。建议把「坏导入扫描」纳入 `scripts/check_architecture.py`（AST 解析 `llmwikify.*` 导入 → 校验模块存在），否则同类回归还会再来。

## 7. 建议清单（按优先级）

| # | 项 | 收益 | 风险 |
|---|---|---|---|
| 1 | 把坏导入扫描并入 `check_architecture.py` | 防止 P0 回归复发 | 低 |
| 2 | 处置 `apps/chat/agent/unified/`（1165 LOC + 9 个测试文件） | 消除双份事件常量（`events.py` 与 `unified/events.py`）的漂移风险 | 中：需确认外部是否 import |
| 3 | 删/并 `apps/chat/research_engine/*` 遗留 shim（`routes.py` 改指 `apps/research/routes.py`） | 消除 8 个 shim | 低 |
| 4 | `scripts/check_prompt_principles.py` 的 `llmwikify.core.*` 断链修正 | 脚本可用 | 低 |
| 5 | `kernel/principle_checker.py`（468 LOC）：接入 `kernel/wiki/lint` 规则，或标记为待删 | 减少 468 LOC 死代码 | 中：功能未接线 |
| 6 | `apps/chat/agent/protocols.py`（137 LOC）删除 | 减少死代码 | 低 |

## 8. 复现

```bash
graphify update .                                   # 刷新图谱
graphify diagnose multigraph                        # 边健康
python scripts/check_architecture.py                # 分层 + peer 基线
```

可达性 / 坏导入脚本（本次新增，临时）：
`scratch/reach_scan.py`、`scratch/bad_imports.py`（位于会话 scratch 目录，未入库）。
