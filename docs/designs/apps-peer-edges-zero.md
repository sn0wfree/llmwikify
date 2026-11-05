# 消除全部 apps↔apps 依赖 — 第一类搬迁 + 第二类协议下沉

> 分支 `feat/auto-doc-ingest` · 2026-07 · 架构债 E 组收尾

## 结果

apps 子包间横向依赖：**58 → 0**（结构级与运行时级均为 0）

允许方向改为「**→ research / → wiki**」——两个领域共享层；
`chat` 与 `agent` 是应用层，**互不依赖**（原先的 chat↔agent 环被拆掉）。

## 第一类：放错了家的模块（5 条边 → 0）

| 原位置 | 新位置 | 消除的边 |
|---|---|---|
| `apps/agent/notifications/` | `apps/wiki/notifications/` | wiki→agent |
| `apps/agent/scheduler/` | `apps/wiki/scheduler/` | wiki→agent |
| `apps/agent/wiki_dream_editor.py` | `apps/wiki/dream_editor.py` | wiki→agent |
| `apps/agent/tools/` 的 `WikiToolRegistry` | `apps/wiki/tool_registry.py` | wiki→agent |
| `apps/research/web_search.py` | `foundation/web/search.py` | agent→research |

这些是 **wiki 领域能力**（dream 提案、通知、定时维护、wiki 工具）或
**基础设施**（HTTP 搜索客户端），住在 `agent/` 或 `research/` 里
导致 wiki/agent 反向依赖。

`apps/agent/tools/__init__.py` 拆分后保留为惰性 shim
（PEP 562，不产生 import-time 边）。

## 第二类：拆 chat↔agent 环（3 条边 → 0）

原环：`chat.orchestrator → agent.skill_adapter → chat.skills`

| 动作 | 结果 |
|---|---|
| `ConfirmationManager` → `kernel/skills/confirmation.py`（97 行，零内部依赖） | agent→chat -1 |
| `handle_get_skill_commands` + `SKILL_COMMANDS_TOOL` → `apps/chat/skills/commands_tool.py` | agent→chat -1 |
| `SkillToolAdapter` + `CompositeToolRegistry` → `apps/chat/skills/tool_adapter.py` | chat→agent -1 |

搬迁后 `apps/agent/` 只剩 `maintenance/`（其核心子系统），
`apps/wiki/` 承载全部 wiki 领域能力。

## checker 升级

- `APPS_ALLOWED_TARGETS = {research, wiki}` —— 应用层可消费领域共享层
- structural 基线为空（任何模块级 app↔app 边即失败）
- runtime 基线清空（全部消除后作为天花板）

## 验证

- 全量 pytest：part1 与上一批完全一致（271）；
  part2 唯一新失败是 `web_search` 子模块导入路径，已修
  （`test_autoresearch.py` 158 passed，仅剩已知 flaky）
- `ruff check src/ tests/` 通过
- `check_architecture.py`：0 layer violation + 0 structural + 0 runtime
- 414 文件编译通过；全量导入冒烟通过；惰性 shim 验证通过
