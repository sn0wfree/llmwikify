# llmwikify 架构评审与演进方案（摘要）

日期: 2026-11-02 · 分支: v0.41-dev
**完整版（含交互图与业界对标表）**: [`architecture-review-2026-11.html`](architecture-review-2026-11.html)

## 结论

四层分层架构（foundation → kernel → apps → interfaces）方向正确、
由 `scripts/check_architecture.py` 机器校验（0 violation）。
**问题不在骨架，而在层与层的接缝**：抽象被绕过、语义被复制、契约被手工同步。

## 规模基线

| 层 | LOC | 文件 | 覆盖 |
|----|-----|------|------|
| foundation | 8,529 | 53 | 83.0% |
| kernel | 15,285 | 78 | 82.0% |
| apps | 44,797 | 201 | 78.4% |
| interfaces | 11,746 | 75 | 82.2% |
| **合计** | **80,357** | **407** | **80.3%** |

测试: 5286 passed / 277 个测试文件 / 覆盖率 24302–30279 语句

## 四个 P0

| # | 问题 | 证据 |
|---|------|------|
| P0-01 | 5 套 Agent 循环并存 | `runner_v2.py` · `research_runner.py` · `base.py:283` · `subagent_worker.py:81` · `research/engine.py` |
| P0-02 | 存储抽象被 95 处直连 FS 击穿 | `kernel/storage/backend.py:9` 声称可换后端，Protocol 实际仅被调用 5 处 |
| P0-03 | SSE 契约前后端漂移 | 后端 17 种事件（`apps/chat/agent/events.py:17-42`）vs 前端 12 种（`ui/webui/src/api.ts:33-44`），5 类无对应类型 |
| P0-04 | apps.chat ↔ apps.research 包级循环 | `apps/research/engine.py:16-30` ↔ `apps/chat/gatherer.py:147` |

## 业界三条主线

1. **单一运行时 + 声明式编排** — LangGraph Pregel / Temporal Operator / K8s reconcile
2. **状态外置 + 可持久化** — LangGraph Checkpointer / Temporal 事件溯源 / K8s etcd
3. **契约即代码 + 自动校验** — K8s CRD / protobuf / OpenAPI codegen

llmwikify 在这三条上均落后一代；优势在本地优先、零代码技能插件、
完整知识图谱与 lint 体系、MCP 原生、多入口。

## 八项改进（按依赖顺序）

| # | 方案 | 产出 |
|---|------|------|
| 1 | 收敛 Agent 运行时 | 5 套循环 → 1 套 `AgentRuntime` + 4 份声明式 Plan（删 ~1800 行） |
| 2 | 存储端口化 | `foundation/storage/page_store.py` 定义 `PageStore`；95 处直连收敛；`InMemoryStore` 落地 |
| 3 | 抽取共享内核 | `apps/knowledge/` 解除 chat↔research 循环 |
| 4 | 契约即代码 | `events.schema.json` 单一源 → 生成前端 TS → CI 校验漂移 |
| 5 | 状态外置 | `Checkpointer` + SQLite，进程内 dict 降级为 LRU 缓存，修内存泄漏 |
| 6 | 显式能力声明 | `Rule.snapshot_capable` / `Skill.exposed`，取代反射与白名单 |
| 7 | 拆分 God Object | `orchestrator.py` 1016 行 → 5 个单一职责模块；chat 单包 33.5k → 三包 |
| 8 | 工程门禁 | 架构/契约/类型/覆盖率四道门禁进 CI；e2e 可跑；发布产物含 UI |

## 三阶段路线

- **Phase 1 止血 + 固契约** — 方案 4 / 6 / 8 前半 / 死代码清理 / 发布修复
- **Phase 2 结构收敛** — 方案 1 / 3 / 5，钩子统一到 foundation 16 点
- **Phase 3 纵深优化** — 方案 2 / 7，类型门禁收敛，性能与可观测性收尾

原则：**先立契约，再动结构；先有门禁，再做重构。**
每阶段结束时代码库必须比开始时更绿（测试数增加、门禁提高、违规数减少）。

## 实测更正（2026-11-02，Phase 1 实施后）

完整版 HTML 里关于「死代码」的两处判断经实测有误，已修订：

| 原判断 | 实测 | 处置 |
|--------|------|------|
| `apps/chat/research_engine/`（9 文件）是 `sys.modules` 替换 shim，属死代码 | **不是**：`apps/chat/clarifier.py:13` 与 `apps/chat/harness/review.py:10` 在 import 它的 `llm_step` | 保留，不动 |
| `WikiCLI` 是意外的双轨，应删除 | **不是**：它是有意的 backward-compat 公开 API（`llmwikify/__init__.py` 导出） | 保留，加显式弃用说明；不再新增方法 |
| `apps/chat/agent/unified/`（13 文件 / 1119 LOC）生产零引用 | 判断正确 | 已在 Phase 1 删除（含 7 个纯 shim 测试文件） |

## 关键取舍

- **大重构 vs 覆盖率提升抢带宽** — 先做不改行为的项（契约/门禁/死代码），再做搬迁
- **收敛误伤扩展性** — 统一的是执行骨架，不是场景语义；差异留在 Plan 而非引擎
- **端口化的回归面** — `InMemoryStore` 与 `LocalFileStore` 跑同一套测试，差异必须为零
