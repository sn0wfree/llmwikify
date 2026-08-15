# Self-Maintenance — 服务启动后的知识库自我维护

> **Status**: implementing | **Branch**: `dev/refocus-v0.40-2026-07-05` | **Date**: 2026-08-15

## Problem

服务被拉起（`llmwikify serve`）后，知识库的维护仍然全部依赖人工触发：

- raw/ 目录新文件需要手动 `llmwikify ingest` / `batch --self-create`
- lint 检出的 knowledge gap（unreferenced entity / missing cross-ref /
  isolated source / outdated page）只产生报告，没有下游消费者
- `WikiScheduler` 定义了 `daily_lint` / `weekly_gaps` 等任务但从未被
  lifespan 驱动（"有任务无电源"）
- 无启动自检、无 DB 例行维护、无聚合健康报告

## Solution

新建 `MaintenanceManager`（`apps/agent/maintenance/`），由 server lifespan
启动，覆盖 registry 中**全部 LOCAL wiki**。**双轨写入策略**（用户决策）：

```
轨 A (自动写入): raw/ 新文件 → ingest_source → _llm_process_source
                → execute_operations → 直接写页 + ingest_log 审计
                依据: 放入 raw/ 即用户主动行为 = 隐式授权
                兜底: LLM 写页失败 → 降级进提案队列, 内容不丢失

轨 B (提案制):   lint gap 检测 → 优先级排序 → 分流:
                - 机械修复 (missing_cross_ref 补 wikilink): 自动批准
                - 内容生成 (unreferenced_entity 新页面): 人工审核
                复用 WikiDreamProposalManager (create/approve/reject)
```

### Architecture

```
lifespan (core.py)
  └─ MaintenanceManager.start() / .stop()
       ├─ AutoIngestService (per-wiki, watcher on_event 回调)
       │    FileSystemWatcher(raw_dir) → ingest+LLM写页(to_thread) → audit
       ├─ GapFiller (周期 tick, to_thread)
       │    wiki.lint() → gaps → 机械修复 / ProposalManager
       ├─ DB maintenance (周期 tick: wal_checkpoint + VACUUM, busy 跳过)
       └─ health_report() (聚合状态, 供 API)
```

### Key decisions

| # | 决策 | 理由 |
|---|------|------|
| 1 | 新建 MaintenanceManager 而非激活 WikiScheduler | 用户决策；健康报告/自检聚合需要统一入口；scheduler 保留给 scheduler_skill 手动 CRUD |
| 2 | kernel/storage/watcher.py **零改动** | 用现有 `on_event` 回调（watcher.py:131）消费事件，避免 kernel 内反向依赖 |
| 3 | LLM 写页复用 kernel 现有 self-create 链 | `ingest_source → _llm_process_source → execute_operations`（batch.py:112-118 同链），不 import apps/chat |
| 4 | 全部同步调用 `asyncio.to_thread()` 包裹 | `lint()` / `ingest_source()` / LLM 调用是阻塞的，直接进 asyncio loop 会卡死 FastAPI |
| 5 | 全局 LLM semaphore ≤ 3 | 对齐 api.minimaxi.com 并发限制（AGENTS.md） |
| 6 | 配置放 `~/.llmwikify/llmwikify.json` 的 `maintenance` 段 | maintenance 是 wiki 级功能，不属于 chat memory（`memory_config.json` 语义不符） |
| 7 | REMOTE wiki 跳过 | FileSystemWatcher / lint / DB 均只适用本地 |
| 8 | API 只调公开方法 | `trigger(task=...)` 分发，不暴露 `_tick` 私有方法 |

### Config

```json
{
  "maintenance": {
    "enabled": true,
    "auto_ingest": {
      "enabled": true,
      "write_mode": "auto",
      "fallback_to_proposal": true,
      "max_concurrent_per_wiki": 1,
      "debounce_seconds": 2.0
    },
    "gap_filler": {
      "enabled": true,
      "max_per_cycle": 5,
      "min_priority": 30,
      "auto_approve_mechanical": true
    },
    "lint_interval_seconds": 86400,
    "gaps_interval_seconds": 604800,
    "db_maintenance_interval_seconds": 604800
  }
}
```

### Gap priority

| gap type | priority | 处理 |
|----------|----------|------|
| `unreferenced_entity` (mention_count N) | `min(100, 50+N*10)` | LLM 草拟新页 → 提案（人工审核） |
| `missing_cross_ref` (mention_count N) | `min(80, 30+N*10)` | 机械补 `[[wikilink]]` → 自动批准 |
| `isolated_source` | 20 | 低于默认阈值 30，不处理（可能刻意独立） |
| `potentially_outdated` | 25 | 低于默认阈值，仅报告 |

### API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/maintenance/health` | GET | 聚合健康报告（per-wiki 状态 + 历史趋势） |
| `/api/maintenance/status` | GET | 当前任务运行状态 |
| `/api/maintenance/trigger?task=ingest\|gaps\|lint\|db\|all` | POST | 手动触发 |

## Files changed

| File | Type | 说明 |
|---|---|---|
| `apps/agent/maintenance/__init__.py` | NEW | MaintenanceManager 编排 |
| `apps/agent/maintenance/config.py` | NEW | MaintenanceConfig 加载 |
| `apps/agent/maintenance/auto_ingest.py` | NEW | AutoIngestService |
| `apps/agent/maintenance/gap_filler.py` | NEW | GapDetector + GapFiller |
| `interfaces/server/http/maintenance_routes.py` | NEW | REST 端点 |
| `interfaces/server/core.py` | edit | lifespan start/stop |
| `tests/test_maintenance_manager.py` | NEW | 单元测试 |
| `tests/test_maintenance_auto_ingest.py` | NEW | 轨 A 测试 |
| `tests/test_maintenance_gap_filler.py` | NEW | 轨 B 测试 |

## Failure modes

- watcher 线程异常 → 不影响 server，log + 计数
- LLM 写页失败 → 降级提案队列（轨 A 兜底）
- 单 wiki 维护失败 → per-wiki try/except 隔离，其余 wiki 不受影响
- DB VACUUM busy → 跳过本轮（`PRAGMA busy_timeout` 短超时）
- shutdown → watcher.stop() + task.cancel() + gather(return_exceptions=True)

## Verification

```bash
ruff check src/llmwikify/apps/agent/maintenance/ tests/test_maintenance_*.py
pytest tests/test_maintenance_*.py -x
python scripts/check_architecture.py   # 0 violation
# 手动: serve → 往 raw/ 丢 .md → 观察 ingest_log + 新页面
# 手动: POST /api/maintenance/trigger?task=gaps → 观察提案队列
```
