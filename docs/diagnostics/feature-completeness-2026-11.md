# 功能完成度审计 · 2026-11-06

> **方法**：`graphify update .`（25069 节点 / 48668 边 / 1010 社区 / 5 import 环）
> + 扫描 `src/` TODO·NotImplemented·占位 + 扫描 `docs/` 计划文档未完成项
> + **每条均做代码核验**；核验不到的标注「无法确认」，不猜。
>
> 与 [code-survey-2026-11.md](code-survey-2026-11.md) 互补：那份讲**结构/死代码**，这份讲**功能欠账**。

---

## 1. A 类 — 代码内占位（功能确实没完成，生产可达）

| # | 功能 | 位置 | 现状 |
|---|---|---|---|
| A1 | **research 查询分解** | `apps/chat/skills/actions/plan_action.py:36-47` | 占位：直接把原 query 当唯一 sub-query 返回，**不调 LLM**。`research_skill._act_plan:127` 直接消费 → 走 skill 路径的 research 不做查询分解 |
| A2 | **多源综合（claims）** | `apps/chat/skills/actions/summarize_action.py:28-37` | 占位：返回固定 `claims`/`narrative` 模板串，不调 LLM。`research_skill._act_synthesize:254` 直接消费 |
| A3 | **research 打分** | `apps/chat/skills/actions/score_action.py:26` | `# Phase 5 placeholder; Phase 6 wires to LLM-based scorer.` |
| A4 | **通知订阅** | `apps/chat/skills/crud/notify_skill.py:75,121` | `subscribe` 自标 placeholder，返回 `_note: "poll-based"`；无 pub/sub |
| A5 | **scheduler 任务 handler** | `apps/chat/skills/crud/scheduler_skill.py:53-59` | `_placeholder()` 返回 `{"status":"placeholder"}`；`handler_ref` 字段保留未接 |
| A6 | **workflow worktree** | `apps/chat/skills/workflows/executor.py:478` | `worktree_path=None  # TODO: worktree handling in v1.1` |

> **A1/A2/A3 影响面**：`/study` 主路径走 `apps/research/actions.py`（`_plan_sub_queries` 有真实 LLM 规划 + fallback），**不受影响**。受影响的是注册进 skill 工具面的 `research_skill`（`skills/service.py:118`）。

---

## 2. B 类 — 计划有、代码无

| # | 计划项 | 出处 | 状态 | 核验 |
|---|---|---|---|---|
| B1 | Auth Phase 3 — Share 链接 | `docs/designs/auth-and-sharing-roadmap.md:377` | **未开始** | 全仓无 share 签发；`_jwt.py:46` 仅有 `share:<uuid>` docstring；`auth_routes.py:355` `/auth/me` 显式拒 share token |
| B2 | Auth Phase 4 — Central Hub Publish | 同上 `:469` | **未开始** | 无 `foundation/hub/`、无 `publish.py`（grep `hub` 仅命中图算法 centrality） |
| B3 | Skill Action 分组（read/write/analyze… 7 类） | `docs/diagnostics/chat-architecture-2026-06.md:151` | **未开始** | `skills/actions/` 仍扁平 18 文件，仅 `detect/` 子目录 |
| B4 | Memory 双系统合并 | 同上 `:169` | **未开始** | `MemoryManager`（`memory/__init__.py:440`）与 `context_entries` 表（`memory/__init__.py:195` 写入）并存，「谁主谁辅」未决策 |
| B5 | SkillsLoader hot-reload | `docs/releases/phase-6-11-cumulative.md:65` | **未开始** | skills 代码无 reload 路径 |
| B6 | AI Test Framework (ATF) | `docs/designs/AI_TEST_FRAMEWORK.md` | **未开始** | 无 `ai_test`/`atf` 实现（设计稿含 11 个开放问题未决） |
| B7 | **PPT Generator** | `docs/designs/ppt-generator.md`（4 个阶段 checkbox 全空） | **有意移除** | 曾实现（`agent/backend/ppt.*` 12 文件），`6bfbed77 release: v0.34.0 — PPT removed` / `cf38789b` 删除。**文档已过期，非欠账** |

---

## 3. C 类 — 需要升级（技术债 / 架构）

| # | 项 | 证据 | 建议 |
|---|---|---|---|
| C1 | **统一 `@retry`**（3 套并存） | `foundation/llm/streamable.py` 4 个循环骨架 + `apps/research/retry_managers.py` 4 个 + `tool_executor.py:167` + `executor.py:428` | 已承诺：等 minmax key 恢复、`acceptance_real_llm.py` 跑通后再动 |
| C2 | **`@lazy_attr` / `cached_property`**（实测 20 处样板） | `code-reuse-audit-2026-11.md:134`；`grep lazy_attr foundation/` = 0 | ✅ 安全子集 **11 处**已换 `cached_property`（见 audit §六 第 8 项）；带参 5 处需 `@lazy_attr`，`initialize()`/`asyncio.Lock` 4 处明确不动 |
| C3 | **mypy baseline 未收紧** | `pyproject.toml:81-84` 「681 错 / 138 文件」+ `:226 ignore_errors=true` | 逐模块递减豁免 |
| C4 | **5 个 import 环** | graphify 报告；根因 `mixins/analysis/status.py:5 from llmwikify import __version__` | 改 `from llmwikify._version import __version__` 类的叶子导入即可断环 |
| C5 | **6 处 `TODO(refactor): C901` 过复杂标注** | ruff `select = [E,F,I,W,B,C4,UP]` **不含 mccabe**，注释无工具强制 → 决定**不拆**（均为 wiki 读写/索引/链接核心函数，纯可读性收益不足以覆盖回归风险），改为删除 6 条误导注释 | 2026-11-06 已删，`grep C901 src/` = 0 |
| C6 | **`apps/chat/agent/unified/` 生产死树**（13 文件/1165 LOC + 9 测试，事件常量为生产侧超集、handlers 6 组方法与 `ChatRunnerV2` 平行重写） | code-survey §5.1；本轮实测 events 21⊃16、4+2 组同名方法 | **已标记 + 方案已出，暂缓执行**。定位约束：本项目核心是知识处理而非 agent 框架 → 不入当前批次。方案与分阶段见 [unified-loop-merge-plan.md](../designs/unified-loop-merge-plan.md) |
| C7 | **AGENTS.md 包职责清单缺 `kernel/multi_wiki/`** | `AGENTS.md:168` 只列 `kernel/{wiki,graph,search,storage}/`，实际还有独立子包 `kernel/multi_wiki/`（`RemoteWiki` / `WikiRegistry`） | 下次 agents-sync 修订时补一行 |

---

## 4. 已排除的假信号（避免误判）

| 扫描信号 | 结论 |
|---|---|
| graph 孤儿节点 620 个「public 无入边」 | **假阳性为主**：FastAPI 路由装饰器、CLI `run/setup_parser` 注册、Protocol 方法、hook 多态调用，图里都无入边。抽查 `cross_wiki_search`/`build_minimal`/`research_reviewer`/`_build_legacy_client` **全部实际可达** |
| `hook_adapter.py` 3 处 `pass` 占位 | 设计如此：AgentHook 13 点无对应点；且 `grep ctx.tool_calls/observations` 在 `foundation/callback/` **0 命中**，无 hook 读被硬编码为空的字段 |
| `GET /api/skills` 无 `Depends(auth)` | 中间件 `public_read=True` 覆盖 GET（`middleware.py:253`），非漏洞；是否该私有是产品决策 |
| `registry.py:169,207` `except ImportError: pass` | 该树生产不可达（C6），守卫本身无害 |
| `research_timeout` / `--self-create` / WebSocket push | **均已实现**（`engine.py:162`、`ingest.py`、`channels/websocket.py`），勿再当欠账 |

---

## 5. 复现

```bash
graphify update .                                    # 刷新图谱 → graphify-out/
rg -n "TODO|NotImplementedError|placeholder" src/llmwikify --type py
rg -n "^\s*- \[ \]" docs/designs --glob "*.md"
git log --oneline --all --grep="ppt" -i              # 判断「有意移除」vs「没做」
```

图孤儿分析脚本：会话 scratch `orphan_scan.py`（未入库）。
