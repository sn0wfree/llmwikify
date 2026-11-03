# Phase 1 完成 — 止血 + 固契约

日期: 2026-11-02 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 交付

| 子项 | 提交 | 文档 |
|------|------|------|
| A 契约即代码 | `673d95d5` | [phase1-a-contract-as-code.md](phase1-a-contract-as-code.md) |
| B 显式能力声明 | `54f73434` | [phase1-b-capability-declarations.md](phase1-b-capability-declarations.md) |
| C CI 门禁 | `c8dcd37c` | [phase1-c-ci-gates.md](phase1-c-ci-gates.md) |
| D 死代码清理 | `cb8f424d` | [phase1-d-dead-code.md](phase1-d-dead-code.md) |
| E 发布链路 | `959455d6` | [phase1-e-release-chain.md](phase1-e-release-chain.md) |

## 解决的问题

| 编号 | 问题 | 处置 |
|------|------|------|
| P0-03 | SSE 契约前后端漂移（后端 17 / 前端 12） | 后端 `EVENT_SPECS` 单一真源 → 生成前端 TS + JSON Schema；CI 校验 |
| P1-03 | lint 快照靠反射判断，规则作者不知情则静默失效 | `Rule.snapshot_mode` 显式声明，矛盾即报错 |
| P1-05 | Skill 硬编码白名单，注册了却调不到 | `Skill.exposed` 显式 opt-in，策略从 adapter 移到 skill |
| P2-04 | 架构校验 / 契约校验 / WebUI 全无 CI；门禁 fail_under=15 | contract job + webui.yml；门禁 15 → 76（实测 77.31%） |
| P2-01 | `apps/chat/agent/unified/` 13 文件生产零引用 | 删除（含 7 个纯 shim 测试） |
| P2-05 | wheel 不带 UI，`pip install` 后 `serve --web` 404 | 前端构建产物落到 Python 包内，wheel 收录 |
| P2-06 | 版本号发版后不同步（真 bug）；`all` extras 漏 `llm` | bump workflow 同步两处 + 一致性校验；补 `llm` |

顺带修掉的实际缺陷：

- `confirmation_required.duration_ms` 前端声明必填而两个后端发射点都不发
- `research_runner.EVENT_PHASE` 与 `events.PHASE` 同名不同源

## 两处判断更正（实测后）

| 原判断 | 实测 | 处置 |
|--------|------|------|
| `apps/chat/research_engine/` 是死代码 | **不是**：`clarifier.py` / `harness/review.py` 在用 | 保留 |
| `WikiCLI` 是意外双轨 | **不是**：有意的 backward-compat 公开 API | 保留 + 显式弃用说明 |

架构文档（HTML + md）已同步更正。

## 量化

| 指标 | 之前 | 之后 |
|------|------|------|
| SSE 契约 | 后端 17 / 前端 12（手写） | 单一真源，生成，CI 校验 |
| 死代码 | `unified/` 13 文件 1119 LOC | 0 |
| wheel 内容 | 无 UI | 39 个 webui 条目 + index.html |
| CI workflow | 6 | 7（+ WebUI） |
| 覆盖率门禁 | 15（实测 16.27%） | 76（实测 77.31%） |
| 新增回归网 | — | 契约 13 + 能力声明 16 + 版本 7 = **36 项** |
| 删除测试 | — | 7 个死测试文件（活代码覆盖已保住） |

## 未做（Phase 2 / 3）

- 方案 1 收敛 Agent 运行时（5 套循环 → 1 套 + 4 份 Plan）
- 方案 3 抽取 `apps/knowledge/` 共享内核（解除 chat↔research 循环）
- 方案 5 状态外置（Checkpointer）
- 方案 2 存储端口化（95 处直连 FS）
- 方案 7 拆分 God Object
- mypy 豁免按层递减
- e2e 测试（pytest 默认 `--ignore=tests/e2e`）
