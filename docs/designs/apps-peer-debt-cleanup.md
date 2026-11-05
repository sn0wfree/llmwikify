# 架构债清理 — apps→apps 违规收敛 + shim 迁移

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查 E 组

## 成果

apps 子包间横向依赖：**58 → 12 处 import（-79%）**

| 边 | 前 | 后 |
|---|---|---|
| research → chat | **39** | **1** |
| agent → wiki | 3 | 0 |
| chat → wiki | 3 | 1 |
| wiki → chat | 3 | 0 |
| chat → research | 26 | 46（允许方向，模块搬迁后变多） |
| wiki → research | 0 | 2（允许方向） |

剩余 12 处全部记入 `check_architecture.py` 基线，**只减不增**——
新增边会让检查 exit 1（已用探针验证）。

## 做了什么

### 1. 让违规可见可防

`scripts/check_architecture.py` 原本只查 4 个顶层 layer，apps 内部的
横向依赖完全看不见。新增：

- apps peer 包检测（含 `apps/api` 这种无 `__init__.py` 的命名空间包）
- 允许方向：`→ research`（research 层可被消费）
- `APPS_PEER_BASELINE` 记录当前规模，**只减不增**

### 2. shim 清理（源码走新位置，shim 仅留给外部）

- `execution_context`：3 处源码改从 `kernel/agent/` 导入
- `unified/{core,loop,steps,pipelines}`：9 个测试文件改测 **kernel 真代码**
  （原先测的是 re-export shim，等于没测到维护对象）
- skill 框架类型 `SkillResult/SkillAction/SkillContext` → **`kernel/skills/types.py`**
  （自包含 dataclass，仅依赖 stdlib；`apps/chat/skills/base.py` 保留 re-export）

### 3. research 模块从 apps/chat 迁出（18 个）

```
apps/chat/state.py              → apps/research/state.py
apps/chat/prompts.py            → apps/research/prompts.py
apps/chat/gatherer.py           → apps/research/gatherer.py
apps/chat/clarifier.py          → apps/research/clarifier.py
apps/chat/synthesizer.py        → apps/research/synthesizer.py
apps/chat/session.py            → apps/research/session.py
apps/chat/reasoning_checker.py  → apps/research/reasoning_checker.py
apps/chat/engine_helpers.py     → apps/research/engine_helpers.py
apps/chat/retry_managers.py     → apps/research/retry_managers.py
apps/chat/task_manager.py       → apps/research/task_manager.py
apps/chat/agent/research_runner.py    → apps/research/runner.py
apps/chat/agent/research_bridge.py    → apps/research/bridge.py
apps/chat/harness/{quality_gate,review,source_analyzer,
                   source_filter,structure_validator}.py
                                 → apps/research/harness/
apps/chat/config.py + config_defaults.yaml
                                 → apps/research/six_step_config{,_defaults}.yaml
```

### 4. 共享基础设施下沉

- `apps/chat/providers/` → **`foundation/llm/providers/`**
  （provider 注册表被 research/wiki/interfaces/foundation 共用，
  放 chat 里既造成 apps 横向依赖，也让 foundation 反向依赖 apps）
- `apps/wiki/db.py` → **`apps/wiki_db.py`**（apps 级共享模块，
  与 `db.py`/`db_base.py` 同级；chat/agent/research 都用它）
- `AutoResearchDatabase` → `apps/research/db.py`
  （`apps/chat/db/__init__.py` 用 PEP 562 惰性 re-export，
  避免 research.db ↔ chat.db 循环导入）

### 5. AGENTS.md 文档漂移修正

- 删除不存在的 `reproduction/`（目录早已移除）
- 删除不存在的 `kernel/quant/llm_client.py` shim 条目
- apps→apps 规则改写为「允许 `→ research`，其余记基线棘轮」
- shim 清单更新为当前实际状态

## 剩余债务（12 处，已入基线）

| 边 | 数 | 性质 |
|---|---|---|
| wiki → agent | 4 | WikiService 编排 agent 子系统（dream/notifications/scheduler/tools） |
| agent → chat | 3 | skill_adapter 依赖 chat 的 skill registry / confirmation |
| api → chat | 1 | openai_server 是 chat 的 API 适配层 |
| chat → agent | 1 | orchestrator 用 skill_adapter |
| chat → wiki | 1 | agent_service 持有 WikiService |
| agent → research | 1 | gap_filler 用 WebSearch |
| research → chat | 1 | **共享 SQLite**：ChatDatabase 是三个 facade 的公共基类（真实耦合） |

`research → chat` 只剩 1 处是**结构性**的：三个 DB facade 共用一个
SQLite 文件，`AutoResearchDatabase` 继承 `ChatDatabase`。要彻底消除需
把 DB 层整体下沉（`apps/dbs/` 包），属于下一批工作。

## 验证

- 全量 `pytest`（分两块跑）失败+错误集合与基线**零新增**
  （新增仅 1 个已知 flaky 计时器 `test_run_context_elapsed_increases_with_time`；
  消失 3 个基线 flaky）
- `ruff check src/ tests/` 通过
- `check_architecture.py` 0 layer violation + peer 债务不超基线
- 410 文件编译通过；顶层包导入冒烟 1.1s 无循环
