# DB 层下沉 — apps/chat/db → apps/chat_db

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应架构债 E 组的最后一块

## 问题

三个 DB facade（Chat / Research / Wiki）**共用一个 SQLite 文件**，
`AutoResearchDatabase` 继承 `ChatDatabase` 以确保三张表都建出来。
`ChatDatabase` 却住在 `apps/chat/db/` 里，于是 `apps/research/db.py`
必须 import `apps.chat.db` —— 这是 `research → chat` 最后一条结构性
依赖（应用依赖应用，而非应用依赖基础设施）。

同理 `ALL_PHASE6_DDL`（memory 表 DDL）住在 `apps/chat/memory/`，
却被 `chat_db` 反向依赖。

## 修复

### 1. `apps/chat/db/` → `apps/chat_db/`

与 `db_base.py` / `wiki_db.py` / `db.py` 同级 —— apps 级共享基础设施，
不是应用子包。`apps/chat/db.py` 保留为兼容 shim。

- 21 个文件的绝对导入路径改写
- `apps/chat/__init__.py` 的相对导入改为绝对路径
- 18 个测试文件同步改写

### 2. `ALL_PHASE6_DDL` → `apps/chat_db/tables.py`

DML/DDL 属 DB 层。`chat/memory/{facts,consolidation}_store.py`
改为从 `apps.chat_db.tables` 导入（chat → chat_db，非 peer 边）。

### 3. checker 的 peer 判定改为显式应用包清单

原先「apps/ 下所有目录都是 peer」把 `chat_db` 也当成了应用包，
搬过去反而新增了 4 条假边。现在：

```
APPS_APP_PACKAGES = {agent, api, chat, research, wiki}
```

共享基础设施（chat_db / wiki_db / db_base / db）**不是 peer**。

## 结果

apps 子包横向依赖：**58 → 11 处（-81%）**

| 边 | 最初 | E 批次后 | 本批后 |
|---|---|---|---|
| **research → chat** | **39** | **1** | **0** |
| agent → wiki | 3 | 0 | 0 |
| chat → wiki | 3 | 1 | 1 |
| wiki → chat | 3 | 0 | 0 |
| 总债务 | 58 | 12 | **11** |

剩余 11 处全部是编排/适配关系（wiki→agent 4、agent→chat 3、
api→chat 1、chat→agent 1、chat→wiki 1、agent→research 1），
已记入 `check_architecture.py` 基线，只减不增。

## 验证

- 全量 pytest（分两块）与基线**零新增**：
  相对基线仅 1 个已知 flaky 计时器；
  相对 db 搬迁前仅 1 个已知 flaky 计时器（`test_get_events_since_...`，
  上一轮它在"消失"清单里，双向波动）
- `ruff check src/ tests/` 通过
- `check_architecture.py` 0 layer violation + peer 债务不超基线
- 411 文件编译通过；关键导入冒烟通过
- 顺带修复：批量替换误伤 `chat.db_migrations` → `chat_db_migrations`
  （1 处）
