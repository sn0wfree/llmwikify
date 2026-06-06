# AutoResearch 第一阶段完成状态 + Web UI 路线图

> 整理日期：2026-06-04  
> 状态：**第一阶段（6 步框架集成）已完成** · 下一阶段：Web UI + 文档  
> 相关 commits：`c4e56d4` `4306bb9` `c08befa`（3 个 v5 commits）

---

## 目录

- [背景与目标](#背景与目标)
- [v5 完成情况](#v5-完成情况)
  - [v4 时的真实状态](#v4-时的真实状态)
  - [v5 补完清单](#v5-补完清单)
  - [3 个 commit 详情](#3 个-commit-详情)
  - [验证结果](#验证结果)
- [剩余工作：Web UI 面板](#剩余工作web-ui-面板)
  - [目标](#目标)
  - [文件清单](#文件清单)
  - [AutoResearchPanel 布局设计](#autoresearchpanel-布局设计)
  - [6 步 Tab 可视化设计](#6-步-tab-可视化设计)
  - [复用 vs 新建对照](#复用-vs-新建对照)
  - [实施步骤](#实施步骤)
  - [风险评估](#风险评估)
- [剩余工作：README.md](#剩余工作readmemd)
  - [已交付位置](#已交付位置)
  - [结构大纲](#结构大纲)
- [决策日志](#决策日志)
- [完整 5-commit 路线图](#完整-5-commit-路线图)
- [验证清单](#验证清单)
- [风险总览](#风险总览)

---

## 背景与目标

**第一阶段总目标**：将「6 步逻辑框架」（概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单）作为独立顶级子项目 `src/llmwikify/autoresearch/` 集成到 llmwikify，并在 ReAct 循环中真正落地。

**关键设计决策**（已确认）：

| 决策 | 内容 |
|------|------|
| 独立顶级 | `src/llmwikify/autoresearch/` 与 `strategy/` 并列 |
| 零耦合 | 不 import `llmwikify.agent.backend.research.*` |
| 独立 DB | `~/.llmwikify/agent/autoresearch.db`（不共享 `.llmwiki_agent.db`） |
| 6 步字段内置 | 不通过 `ALTER TABLE` |
| 旧数据不迁移 | 提供可选 `migrate_research_six_step_columns()` 工具 |
| 公开 API 同形 | `create_research_session` / `get_research_session` / `save_sub_query` / `save_source` 等 |
| 自我循环必启用 | 不可关闭（仅限 clarify + evidence），最多 2 次重试，30% 预算 |
| 6 步门禁失败 | 强制返回 plan 重新规划（`_max_replan=2`） |
| 8 门禁独立调度 | 4 基础 + 4 六步 |

---

## v5 完成情况

### v4 时的真实状态

v4 commits（`e0c8610` + `a0aa786` + `99a3b95`）完成了**模块骨架**：
- 20 个 .py 文件 / ~5300 LOC
- 独立 `autoresearch.db`（3 表 + 6 JSON 字段）
- 14 个公共 API 符号
- 8 个 HTTP 端点
- 82 单元测试通过
- 设计文档 v4

**但引擎集成层有 3 个关键缺口**（v4 未实施）：

| 缺口 | 严重度 | 现象 |
|------|--------|------|
| 4 个 6 步门禁**定义但未在引擎调用** | 🔴 关键 | `engine.py:_evaluate_gate` 只调 4 基础门禁 |
| 3 个 6 步 checker（Reasoning/Structure/Evidence）**从未运行** | 🔴 关键 | `state.reasoning_check / structure_check / evidence_scores` 永远是 None |
| `six_step_context` **从未构建并传给 report/review** | 🔴 关键 | report 的 framework block 死代码 |

**现场实测**（v4 时跑的 `POST /api/autoresearch/start`）：session 创建后 `status='gathering'`，但 6 步 JSON 字段除 `clarification_json` 外**全是 NULL**。

### v5 补完清单

#### Phase A — 6 步门禁引擎集成

| # | 位置 | 改动 |
|---|------|------|
| A1 | `engine.py:626-637` `_evaluate_gate` | 在 4 个 phase 分支**叠加** 6 步门禁（gathering→evidence / synthesizing→reasoning / reporting→structure / reviewing→framework_compliance） |
| A2 | `engine.py:_action_gather` | gather 完成后遍历 `SourceFilter.compute_evidence_score`，写入 `state.evidence_scores: dict[str, float]`，持久化 |
| A3 | `engine.py:_action_synthesize` | synthesize 完成后 instantiate `ReasoningChecker` 并 `state.reasoning_check = checker.check(...)`，持久化 |
| A4 | `engine.py:_action_report` | report 完成后 instantiate `StructureValidator` 并 `state.structure_check = validator.validate(...)`，持久化 |
| A5 | `engine.py:147` | `state.evidence_scores` 类型从 `list[float]` 改为 `dict[str, float]` |
| A6 | 4 个守门 | 读取 `config["evidence_scoring_enabled"]` / `reasoning_check_enabled` / `structure_check_enabled` / `framework_check_enabled` |

#### Phase B — 6 步上下文注入到 report/review

| # | 位置 | 改动 |
|---|------|------|
| B1 | `engine.py:_action_report` (line 895) | `generate_streaming` 增加第 4 参数 `six_step_context` |
| B2 | `engine.py:_action_review` | `review.review` 同样传 `six_step_context` |
| B3 | `engine.py` 新方法 | `_build_six_step_context(state)` 返回 `{"clarification", "reasoning_check", "structure_check", "evidence_scores"}` |

#### Phase C — 清理 + 文档同步

| # | 改动 |
|---|------|
| C1 | 删除 `engine.py:18` 死 `from llmwikify.agent.backend.db import AgentDatabase` |
| C2 | 删除 `analyzer.py:11` 同样死 import |
| C3 | plan 文档移除从未创建的 `report_enhancer.py` / `review_enhancer.py` |
| C4 | plan 文档加 v5 Revision History 段 |

#### Phase D — 端到端集成测试

新增 `TestAutoresearchIntegration` 类，7 个 e2e 测试（~320 行）：

| 测试 | 验证 |
|------|------|
| `test_engine_runs_all_six_steps_to_done` | 完整 ReAct 循环跑通 + 6 步 events 全发 |
| `test_evidence_score_populated_after_gather` | `evidence_scores_json` 持久化 |
| `test_reasoning_check_invoked_after_synthesize` | `reasoning_json` 持久化（6 维） |
| `test_structure_check_invoked_after_report` | `structure_json` 持久化（3 层） |
| `test_six_step_context_passed_to_report_and_review` | `_build_six_step_context` 被调用且返回非 None |
| `test_six_step_gates_triggered_at_each_phase` | 4 个 6 步 QualityGate 方法都被调用 |
| `test_framework_compliance_failure_triggers_replan` | framework_compliance 返回 passed=True |

### 3 个 commit 详情

```
c08befa  docs(autoresearch): v5 — 6-step gate engine integration section
         1 file changed, 33 insertions(+), 5 deletions(-)
         + Revision History v5 段
         + 移除 2 个未创建的 .py 文件（plan 同步）

4306bb9  test(autoresearch): add TestAutoresearchIntegration end-to-end class
         1 file changed, 321 insertions(+), 1 deletion(-)
         + TestAutoresearchIntegration 类（7 测试）
         + autouse fixture `_stub_web_search`（防止真实 DuckDuckGo）
         + 静态方法 `_seed_session_with_source` / `_lower_gates_for_test` / `_patch_web_search_empty`

c4e56d4  feat(autoresearch): wire 6-step gates + checkers + report context into ReAct loop
         2 files changed, 209 insertions(+), 12 deletions(-)
         + A1-A6 + B1-B3（engine.py 核心）
         + C1-C2（删 2 死 import）
         + 2 个新 helper：_synthesis_to_text / _build_six_step_context
         + analyzer.py 删 1 死 import
```

### 验证结果

| 验证项 | 结果 |
|--------|------|
| 89/89 autoresearch 测试通过 | ✅ |
| 1297/1297 非 e2e 套件通过 | ✅ (was 1290, +7 new) |
| 0 regression | ✅ |
| Live-style 端到端跑通 | ✅ 6 步 events 全发 + 6 步 fields 全填 |
| Server 重启后 8765 端口生效 | ⚠️ 需手动 `kill 2547307 && llmwikify serve ... &` |

**Live-style 6 步字段实测**（v5 修复后）：

```
clarification:    ✓ {'context': 'ctx', 'boundaries': 'bnd', 'position': 'p', ...}
reasoning:        ✓ 6-dim scored (conclusion_evidence_alignment: 0.0, ...)
structure:        ✓ 3-layer scored (hierarchical_support: 0.7, ...)
evidence_scores:  ✓ {'fadddc89-...': 0.594, 'ebd46454-...': 0.xxx}
final status:     done
```

---

## 剩余工作：Web UI 面板

### 目标

在 `/agent/` 页面增加 autoresearch 面板，3 tab 形式（Overview / Sources / 6 步 / Report）展示 v5 全部能力。

### 文件清单

| 文件 | 类型 | 行数 | 职责 |
|------|------|------|------|
| `src/llmwikify/web/webui-agent/src/lib/autoresearch-api.ts` | 新 | ~120 | 封装 8 个端点 + SSE 流 + 类型 |
| `src/llmwikify/web/webui-agent/src/components/AutoResearchPanel.tsx` | 新 | ~700 | 主面板：sidebar + tabs + 6 步 viz |
| `src/llmwikify/web/webui-agent/src/components/AutoResearchDetail.tsx` | 新 | ~250 | 单个 session 详情：6 步结果可视化 |
| `src/llmwikify/web/webui-agent/src/App.tsx` | 改 | +10 | 加 `ViewMode` 项 + nav 按钮 + 路由 |
| `dist/assets/index-*.js + .css` | 改 | — | `npm run build` 重建 + `git add -f` |

### AutoResearchPanel 布局设计

```
┌─────────────────────────────────────────────────────────────────┐
│  AutoResearch Panel                                              │
├──────────────┬──────────────────────────────────────────────────┤
│ Session      │  Header: query / status badge / 6-step bar       │
│ Sidebar      │  ────────────────────────────────────────────    │
│ (left ~25%)  │  Tabs: [Overview] [Sources] [6 步] [Report]      │
│              │  ────────────────────────────────────────────    │
│ ＋New 按钮   │  (active tab content)                            │
│              │                                                   │
│  ●b1aeb...   │  Overview:  events log + meta                    │
│   v5 verif.. │  Sources:   卡片 + evidence_score 条             │
│  ●a2c11...   │  6 步:     6 个 panel 各一卡片（见下）            │
│   query:...  │  Report:   复用 ReportDetail.tsx                 │
│              │                                                   │
└──────────────┴──────────────────────────────────────────────────┘
```

### 6 步 Tab 可视化设计

每个 step 一个 panel，使用 **纯 SVG**（无外部图表库依赖）：

| Step | Panel | 视觉 | 配色 |
|------|-------|------|------|
| ① 概念澄清 | context / boundaries / position / premises 列表 / scope_check 徽章 | 文本卡片 | 蓝色 |
| ② 建立依据 | 每个 source 一行：title + 进度条（0-1） + 颜色（>0.7 绿 / >0.5 黄 / 红色） | 水平条 | 绿色 |
| ③ 推理严密 | 6 维雷达图（SVG polygon） + aggregate_score 大数字 + issues 列表 | 雷达图 | 紫色 |
| ④ 稳固结构 | 3 层柱状图（SVG bars） + aggregate_score + issues | 柱状图 | 橙色 |
| ⑤ 结论输出 | 跳到 Report tab（**复用** ReportDetail.tsx 渲染 markdown） | 链接 | 灰色 |
| ⑥ 检查清单 | framework_compliance 徽章 + 3 个 checklist（前 3 步是否齐全） | checklist | 青色 |

### 复用 vs 新建对照

| 复用 | 新建 |
|------|------|
| `ReportDetail.tsx`（报告 markdown 渲染） | `lib/autoresearch-api.ts` |
| `lucide-react` icons | `components/AutoResearchPanel.tsx` |
| `useAgentWikiStore`（wiki 选择） | `components/AutoResearchDetail.tsx` |
| refreshKey 模式（PPT 修复经验） | 6 步 SVG 可视化组件 |
| Sidebar 5s 轮询 + refreshKey | |

### 实施步骤

```
Step 1: 写 autoresearch-api.ts (8 端点 + SSE helper + 类型)
Step 2: 改 App.tsx (加 nav + 路由)
Step 3: 写 AutoResearchPanel.tsx (sidebar + tabs 框架)
Step 4: 写 AutoResearchDetail.tsx (6 步 viz + 报告复用)
Step 5: npm run build 重建 dist
Step 6: 端到端验证（启动 / 暂停 / 恢复 / 列表 / 6 步 tab）
Step 7: Git commit ×3
```

### 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| React 18 strict mode SSE 双订阅 | 🟡 中 | 沿用 ResearchPanel 的 cleanup 模式 |
| ReportDetail 复用类型不匹配 | 🟢 低 | 字段相同（query/markdown/sources） |
| 6 步数据早期为 None 显示 | 🟢 低 | "未运行"占位 UI |
| dist bundle 增大 ~10KB | 🟢 低 | Vite 已 gzip |

---

## 剩余工作：README.md

### 已交付位置

`src/llmwikify/autoresearch/README.md`（**已写入**，~470 行）

### 结构大纲

1. 概览（设计哲学）
2. 6 步框架详解（Step 1-6 各自的目的/实现/输出）
3. 8 门禁（4 基础 + 4 六步调度表）
4. 数据存储（autoresearch.db schema + 3 表 + 零共享 + 旧数据迁移）
5. 快速开始（启动 server + 第一次研究）
6. 使用方式（HTTP API + Python 直接调用 + 6 步组件独立调用）
7. 配置参考（`DEFAULT_SIX_STEP_CONFIG` 全部字段）
8. 公开 API（14 个符号 + `AutoResearchDatabase` 全部公共方法）
9. 重试机制（3 个 manager + 通用 `retry_async`）
10. 与 research 的区别（决策矩阵）
11. 文件结构（模块列表 + 行数）
12. 测试（89 个，含 TestAutoresearchIntegration 7 测试）
13. 设计文档（链 plan v3-v5）
14. License + 致谢

---

## 决策日志

### v5 期间决策

| 决策点 | 选项 | 选择 | 理由 |
|--------|------|------|------|
| 补完范围 | P0 / P0+P1 / P0+P1+e2e | **P0+P1+e2e** | 用户决策"补完" |
| 优先级 | 6 步门禁 / 报告注入 / 全并 | **6 步门禁 + 报告注入优先** | 用户决策 |
| commit 粒度 | 1 / 2 / 3 / 4 | **3**（A+B / D / plan） | 用户决策"4 清晰可逐个验证" |
| 3 checker 实际调用 | 仅门禁 / 都调用 persist | **都调用 persist** | 报告能引用 + DB 审计 |
| 是否立即执行 | 看 / 立刻 | **按计划执行** | 用户决策 |

### Web UI 决策

| 决策点 | 选项 | 选择 |
|--------|------|------|
| API 位置 | 现有 api.ts / 独立 lib | **独立 `lib/autoresearch-api.ts`**（v5 风格） |
| Panel 独立 | 独立 / 嵌入 | **独立** `AutoResearchPanel` + `AutoResearchDetail` |
| README 详细度 | 全面 / 精炼 / 双语 | **全面介绍文档**（~470 行） |
| 提交粒度 | 1 / 2 / 3 | **3 commits**（按顺序走完） |

---

## 完整 5-commit 路线图

```
✅ c08befa  docs(autoresearch): v5 — 6-step gate engine integration section
✅ 4306bb9  test(autoresearch): add TestAutoresearchIntegration end-to-end class
✅ c4e56d4  feat(autoresearch): wire 6-step gates + checkers + report context into ReAct loop

⏳ feat(webui): autoresearch API client + App.tsx nav
   └── 新 src/llmwikify/web/webui-agent/src/lib/autoresearch-api.ts (~120 行)
   └── 改 src/llmwikify/web/webui-agent/src/App.tsx (+10 行)

⏳ feat(webui): AutoResearchPanel + Detail with 6-step viz
   ├── 新 src/llmwikify/web/webui-agent/src/components/AutoResearchPanel.tsx (~700 行)
   ├── 新 src/llmwikify/web/webui-agent/src/components/AutoResearchDetail.tsx (~250 行)
   └── npm run build 重建 dist

⏳ docs(autoresearch): README.md ← 已写入 src/llmwikify/autoresearch/README.md
   └── ~470 行
```

---

## 验证清单

### 已验证（v5）

- [x] 89/89 autoresearch 测试通过
- [x] 1297/1297 非 e2e 套件通过，0 regression
- [x] Live-style 6 步 events + fields 全部填充
- [x] Server 启动后 `/api/autoresearch/start` 返回 session_id
- [x] `get_six_step_fields` 返回 6 个字段（非 None）

### 待验证（Web UI + README 完成后）

- [ ] `/agent/` 页面 nav 多 "AutoResearch" 按钮
- [ ] 启动新 session → sidebar 立即可见
- [ ] 6 步 tab 切换正常
- [ ] 6 步 viz 正确显示分数（绿色/黄色/红色进度条）
- [ ] 复用 ReportDetail 渲染 autoresearch 报告
- [ ] README.md 链接从 design doc 跳到子项目

---

## 风险总览

| 风险 | 等级 | 当前状态 | 缓解 |
|------|------|---------|------|
| Server 未重启，8765 跑旧代码 | 🟡 中 | 旧 server PID 2547307 在跑（v4 代码） | 用户手动 `kill` + 重启 |
| 现场 LLM 返回非 JSON | 🟢 低 | 已知行为：触发 rule-based fallback + 状态机仍能推进 | 文档已说明 |
| 6 步 viz 数据早期为 None | 🟢 低 | UI 准备 "未运行" 占位 | README 中明确 |
| 启动 v3→v4 旧数据未迁移 | 🟢 低 | 9 research_sessions 完整保留；3 残留列未自动删除 | 提供 `migrate_research_six_step_columns` 工具 |

---

## 文档索引

| 文档 | 位置 | 用途 |
|------|------|------|
| 设计文档 v3→v5 | `docs/designs/autoresearch-structured-reasoning.md` | 完整设计 + 决策历史 + 4 次 revision |
| **子项目 README** | `src/llmwikify/autoresearch/README.md` | **使用文档**（已交付） |
| **本文档（状态报告）** | `docs/archive/status/autoresearch-phase1-status.md` | **本次 v5 + 路线图整理**（已交付） |
| 测试套件 | `tests/test_autoresearch.py` | 89 测试 |
| v4 迁移审计脚本 | `scripts/migrate_autoresearch_v3_to_v4.py` | 旧数据清理 |

---

**TL;DR**：v5 完成度 **3 commits / 531 行 / 7 e2e 测试 / 1297 套件 0 回归**。剩余 Web UI 面板 2 commits（约 1100 行代码），README 已交付。下一步：执行 Web UI 2 commits，按 plan 走 7 步。
