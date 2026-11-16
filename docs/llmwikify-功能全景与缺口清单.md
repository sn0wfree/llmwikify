# llmwikify 功能全景与缺口清单

> 第十一轮 · 功能梳理（**未改动仓库任何文件**）
> 基线 `main` @ `3e09b0c3`（2026-11-10）· 1387 commits
> 对照 `feat/auto-doc-ingest` @ `a0b0f019` · `v0.41-dev` @ `582a7203`
> 核对基准：仓库自带的 `docs/diagnostics/feature-completeness-2026-11.md`（2026-11-06）——**已过期 5 天，逐条重核**
>
> ⚠ **Auth 相关条目已于 2026-11-16 复核并就地更新**（标注「11-16 复核」）；其余条目仍以 11-10 基线为准。

---

## 0. 三句话结论

1. **功能面很大但不算薄**：4 个入口面（CLI 34 / MCP 28 / HTTP 87 路由 / WebUI 14 页）+ 8 个核心能力域，**没有一个入口面是空壳**。
2. **缺口集中在两处**：① **research 的 skill 路径三个占位**（A1 查询分解 / A2 多源综合 / A3 打分）—— README 承诺的"分解问题 → 多源综合 → 打分"在 skill 路径上是假的；② **Auth 的 Share（Phase 3）与 Hub（Phase 4）全部未动**（11-16 复核：PAT 链路与多用户授权已闭环，只剩 share / hub）。
3. **README 有 5 处数字/描述与实现不符**（"50+ skills" 实际 39、**DuckDB storage 根本没用于存储**、MCP 工具数自相矛盾）。低垂果实，改 README 5 分钟。

---

## 1. 功能全景

### 1.1 四个入口面（实测数量）

| 面 | 数量 | 说明 |
|---|---|---|
| **CLI 命令** | **34** | `interfaces/cli/commands/`，全部走 `Command` protocol + `CommandBase._sub` |
| **MCP 工具** | **28** | `interfaces/mcp/tools.py`，`@mcp.tool` 注册 |
| **HTTP 路由** | **87 条 / 78 唯一路径** | GET 51 · POST 29 · DELETE 4 · PUT 3；11 个 router 分组 |
| **WebUI 路由** | **14**（+1 redirect） | `/agent/research` → `/agent/autoresearch` |
| WebUI 组件 | 84 个 tsx | |

**CLI 命令全表（34）**

```
analyze-source   auth          batch          build-index    community-detect
db               dict          doctor         enrich         export-graph
fix-wikilinks    graph-analyze graph-query    help           ingest
init             init-llm      knowledge-gaps lint           log
migrate-config   qmd           read_page      references     report
search           serve         sink-status    status         suggest-synthesis
synthesize       watch         wikis          write_page
```

**HTTP 路由分组**

| 前缀 | 路由数 | 面 |
|---|---|---|
| `/api/wiki` | 23 | 单 wiki 的页面读写、索引、搜索、lint |
| `/sessions/{id}` | 8 | Agent 会话 + SSE 流 |
| `/api/wikis` | 8 | 多 wiki 注册/切换/列表 |
| `/api/auth` | 7 | 登录、token、me |
| `/api/maintenance` | 6 | 自维护端点 |
| `/wiki-dream/proposals` | 5 | 提案审批闭环 |
| `/confirmations/{id}` | 3 | 人工确认队列 |
| `/v1` | — | **OpenAI 兼容端点** |
| 其余 | ~27 | config / logs / notifications / research-runs / llm-metrics / tools |

### 1.2 八个核心能力域

| # | 能力域 | 状态 | 关键位置 |
|---|---|---|---|
| 1 | **Wiki 核心** | 完整 | ingest → page → 双向 wikilink → 索引 → FTS5 搜索 → 多 wiki 注册表 |
| 2 | **Smart Lint** | 完整（8 规则） | `kernel/wiki/lint/rules/`：data_gaps / dated_claims / knowledge_gaps / missing_cross_refs / outdated_pages / potential_contradictions / query_page_overlap / redundancy |
| 3 | **知识图谱** | 完整（8 种关系） | PageRank、社区检测（Louvain）、HTML/SVG/GraphML 导出、D3 力导向图 |
| 4 | **Chat + Skills Agent** | 完整 | ReAct 流式、工具调用、人工确认、39 个 Skill 子类 |
| 5 | **Research** | **⚠ 双路径，部分占位** | engine 路径完整；**skill 路径的 plan/score/summarize 是占位** |
| 6 | **自维护（AutoResearch / Wiki Dream / Maintenance）** | 较新，持续建设 | 提案闭环已打通（跨实例可见 + 可审批） |
| 7 | **Auth & 多 wiki** | **✅ 鉴权已闭环**<br>11-16 复核 | JWT + PAT + **每请求授权裁决**（用户 / 组 / public 三类主体，读写二值）；管理面：CLI + `/api/auth/{me,grants,users,groups}` + WebUI `/agent/access`。**Share / Hub 未做** |
| 8 | **提取器** | 完整（7 个覆盖 8 类格式） | PDF / Office / 图片 / 音频 / Web / YouTube（markitdown 兜底） |

### 1.3 内部规模

| 指标 | 数量 |
|---|---|
| Skill 子类 / 注册进 registry | 39 / 21 |
| Skill action 文件 | 27 |
| CRUD skill / workflows / pipelines | 8 / 7 / 4 |
| multi_wiki 模块 | 5 |
| research harness（质量门） | 6 |
| 关系类型 | 8 |
| 图谱关系取值 | `is_a` `uses` `related_to` `contradicts` `supports` `replaces` `optimizes` `extends` |

---

## 2. README 声明 vs 实际实现（5 处不符）

> **11-16 复核：第 1/2/3 条已在 README 就地修正**（数字改为实测值，矛盾表述已消解）。
> 第 4/5 条（research skill 路径占位）属代码问题，未动。

| README 声明 | 实测 | 判定 |
|---|---|---|
| "50+ built-in skills" | 运行时注册 **38** 个（Skill 子类 41） | **已修** → README 改为 "38 built-in skills" |
| "**26** MCP tools" 与 "**28** tools over stdio + HTTP" | `@mcp.tool` 装饰器 28 处；接线修复后（`bc316bb8`）单 wiki 服务器 **20** 个、多 wiki 服务器 **26** 个 | **已修** → 统一写"单 wiki 20 / 多 wiki 26"，并给出核实文档链接 |
| "YAML frontmatter + **DuckDB storage**" | DuckDB 全仓仅出现在 `doctor_cmd.py:178` 的依赖检查里，**从未用于存储** | **已修** → 改为 "SQLite storage" |
| "breaks down questions into **sub-queries**" | engine 路径真实；**skill 路径 A1 是占位**，不调 LLM | **部分不实**（代码问题，未动） |
| "synthesizes **structured reports**" | engine 路径真实；**skill 路径 A2 claims 是固定模板** | **部分不实**（代码问题，未动） |
| "8 relation types" | 8 ✓ | 实 |
| "Smart Lint: 5 类" | 8 个规则 | 保守说法，不算错 |

★ **DuckDB 那条值得单独说**：一个"实际未被使用的东西"出现在 README 的功能描述里，
会让人以为有列式分析能力。实际存储是 SQLite + FTS5，**DuckDB 只是 doctor 会检查它装没装**
（它仍在 `pyproject.toml` 的 dependencies 里，但全仓无读写调用）。

---

## 3. 缺口清单

> 以仓库自带的 2026-11-06 审计为底稿，**逐条重核到 2026-11-10 的 main**。

### 3.1 A 类 · 代码内占位（生产可达，功能确实没完成）—— **6 项，全部仍在**

| # | 功能 | 位置 | 现状 | 用户可见后果 |
|---|---|---|---|---|
| **A1** | research 查询分解 | `skills/actions/plan_action.py:36` | 直接把原 query 当唯一 sub-query，**不调 LLM** | skill 路径的 research 不分解问题 |
| **A2** | 多源综合（claims） | `skills/actions/summarize_action.py:28` | 返回固定 `claims`/`narrative` 模板串 | skill 路径的综合结果是模板，不是真综合 |
| **A3** | research 打分 | `skills/actions/score_action.py:26` | `# Phase 5 placeholder; Phase 6 wires to LLM-based scorer` | 打分恒为占位 |
| **A4** | 通知订阅 | `skills/crud/notify_skill.py:75,121` | `subscribe` 自标 placeholder，`_note: "poll-based"` | 无 pub/sub，只有轮询 |
| **A5** | scheduler 任务 handler | `skills/crud/scheduler_skill.py:53` | `_placeholder()` → `{"status":"placeholder"}`；`handler_ref` 保留未接 | 定时任务建了但不会真执行 |
| **A6** | workflow worktree | `skills/workflows/executor.py:478` | `worktree_path=None  # TODO: v1.1` | 工作流无隔离工作区 |

> ★ **这 6 项在 11-06 → 11-11 的 59 个 commit 里，一个都没动。**
> 而同期 main 做了大量架构/性能改造（apps↔apps 依赖归零、DB 层下沉、O(N²) 消除、索引事务批量化…）。
> **说明当前迭代重心在"结构与性能"，功能面的欠账被排在后面** —— 这正是"还缺啥功能"的主要答案。

### 3.2 B 类 · 计划有、代码无

| # | 功能 | 出处 | 状态（11-16 复核） |
|---|---|---|---|
| **B1** | Auth Share 链接 | `auth-and-sharing-roadmap.md` Phase 3 | **数据层就绪，功能未做**。`share_tokens` 独立表 + `ShareTokenRepository` 已落地（P6，Q5=a）；share JWT / `GET /share/{slug}` / share CLI / RemoteWiki 只读 / WebUI ShareView 均未实现 |
| **B2** | Central Hub Publish | 同上 Phase 4 | **仍未开始**。无 `foundation/hub/`、无 `publish.py` |
| **B3** | Skill Action 分组（read/write/analyze… 7 类） | `chat-architecture-2026-06.md` | **仍未开始**。`skills/actions/` 仍扁平 20 文件（仅 `detect/` 有子目录） |
| **B4** | Memory 双系统合并 | 同上 | **仍未开始**。`MemoryManager` 与 `context_entries` 表并存（后者仍有 6 处引用），"谁主谁辅"未决 |
| **B5** | SkillsLoader hot-reload | `phase-6-11-cumulative.md` | **仍未开始**。skills 代码无 reload 路径 |
| **B6** | AI Test Framework (ATF) | `AI_TEST_FRAMEWORK.md`（12 个开放问题） | **仍未开始**。无 `ai_test`/`atf` 实现 |
| **B7** | PPT Generator | `ppt-generator.md`（67 个空 checkbox） | **有意移除**（v0.34 删除）。文档已过期，**非欠账** —— 但它占了"未完成 checkbox"的 44%，会严重干扰盘点 |

**★ 本轮新扫出来的 B 类（11-06 审计没列）** —— 从设计稿的未完成 checkbox 里挖出来的：

| # | 功能 | 出处 | 未完成项 |
|---|---|---|---|
| **B8** | **Auth PAT 完整链路** | `auth-and-sharing-roadmap.md:638-641` | ✅ **已完成（11-16 复核）** —— schema + utils + 删 argon2、PAT 路由 + middleware、CLI `create-token/list-tokens/revoke-token`、WebUI 无密码登录（PAT→JWT 换发）全部落地 |
| **B9** | Auth Phase 3 — share + remote wiki | 同上 `:643` | 🟡 commits 12-15 中的 **数据层已做**（`share_tokens` 独立表）；share JWT / 路由 / CLI / RemoteWiki 只读未做 |
| **B10** | Auth Phase 4 — 中央 hub publish + **独立仓立项** | 同上 `:644-645` | ⬜ 未开始（跨仓立项） |

> ★ **B8 是被埋得最深、性价比最高的一项**：Phase 2 已经做完，剩下的是**纯增量**（4 个 commit），
> 而且它带出 **WebUI 无密码登录** —— 这是目前"个人自建 wiki"最大的体验缺口。
> ★ **B10 里的"hub 服务端独立仓立项"是唯一需要动组织的一步**（跨仓），其余都在本仓。

### 3.3 C 类 · 技术债（7 项，4 项已解）

| # | 项 | 11-06 状态 | **11-11 实测** |
|---|---|---|---|
| **C1** | 统一 `@retry`（3 套并存） | 3 套 | **大幅推进**：只剩 **2 处**（`apps/research/retry_managers.py` 已收敛） |
| **C2** | `@lazy_attr` / `cached_property` 样板 | 20 处 | 11 处已换 `cached_property`（实测 4 个文件含该字样，口径需复核）；带参 5 处需 `@lazy_attr` |
| **C3** | mypy baseline 未收紧 | 681 错 / 138 文件 | 声明已标注"已过期"，`ignore_errors=true` 仍在；v0.41-dev 已做第一层递减（移除 14 条豁免，修 12 文件真实类型错误） |
| **C4** | 5 个 import 环 | 5 个 | `_version.py` 叶子模块已建并断开大部分环；**残留 3 处** `from llmwikify import __version__`（其中 2 处在函数内，不影响 import 期） |
| **C5** | 6 处 `TODO(refactor): C901` 误导标注 | 6 处 | **0 处 ✅ 已删** |
| **C6** | `apps/chat/agent/unified/` 生产死树 | 13 文件 / 1165 LOC | **main 上剩 10 文件**；**v0.41-dev 已删 13 个文件**并把循环迁到 `kernel/agent/runtime.py` —— 行动项是**合并分支**，不是重做 |
| **C7** | AGENTS.md 缺 `kernel/multi_wiki/` | 缺 | **已补 ✅** |

### 3.4 假信号（别当欠账）

- **graph 孤儿节点 620 个** —— 绝大多数是假阳性（FastAPI 路由装饰器 / CLI 注册 / Protocol 方法 / hook 多态调用在图里天然无入边）。抽查 `cross_wiki_search` / `build_minimal` / `research_reviewer` **全部实际可达**。
- **`research_timeout` / `--self-create` / WebSocket push** —— **均已实现**，勿再当欠账。
- **`hook_adapter.py` 的 3 处 `pass`** —— 设计如此（AgentHook 13 点里没有对应点）。
- **`GET /api/skills` 无 `Depends(auth)`** —— ⚠ **11-16 复核：`public_read` 已废弃**，非回环请求无 token 一律 401（中间件层拦截），该豁免不再是理由。

---

## 4. 已实现但还没上线（`v0.41-dev` 54 个 commit 未合并）

这是"还缺啥功能"里**最不该漏的一块** —— 这些不是欠账，是**做完了但没合**：

| 功能 | commit | 价值 |
|---|---|---|
| **存储端口化（两阶段）** | `f6cf13b8` `5134adbd` | 内容 I/O 全部端口化，名单清零 |
| **状态外置** | `cf53788c` | `SessionStateStore` + SQLite 租约，**修 `_tool_registries` 泄漏** |
| **统一 Agent 运行时** | `881cd46b` `457b1039` | research 循环迁到共享骨架，chat↔research 循环解开 |
| **apps/knowledge 共享基座** | `429615e4` | 同上 |
| **SSE 契约即代码** | `673d95d5` | 后端 `events.py` 成为唯一真源（配合 main 的 `duration_ms` 补齐） |
| **lint P4/P4b 页面快照** | `1a11078a` | 一次 lint 每页只读一遍（性能） |
| **显式能力声明** | `54f73434` | `lint snapshot_mode` + `Skill.exposed` |
| **CI 三闸门** | `c8dcd37c` | 架构校验 + 契约校验 + WebUI CI，**覆盖率门禁 15 → 76** |
| **发版修复** | `959455d6` | wheel 带上 UI + 版本号同步 + all extras 补 llm |
| **CLI 单测 380 项** | 4 个 `test(cli)` commit | doctor/lint/qmd/wikis/init 172 + 15 小命令 83 + migrate/init-llm/graph 98 + db 27 |

> ★ **「覆盖率门禁 15 → 76」是这一批里最值钱的一条** ——
> 门禁从 15% 提到 76% 意味着**以后不能再悄悄退化**。这一条没合并之前，
> 前面所有"补测试"的工作都缺一个卡口。

---

## 5. 建议的补功能顺序（按 成本 / 价值 比）

| 序 | 做什么 | 成本 | 价值 | 理由 |
|---|---|---|---|---|
| **1** | **对齐 README 数字** | 5 分钟 | 中 | 5 处不符，其中 DuckDB 那条会误导人以为有列式分析能力 |
| **2** | **合并 `v0.41-dev`** | 中（54 commit） | **高** | 已写完的存储端口化 / 状态外置 / 统一运行时 / **覆盖率门禁 76**；不合并则 C6 永远收敛不了 |
| **3** | ~~**B8 Auth PAT 链路**~~ | — | — | ✅ **已完成（11-16 复核）** |
| **4** | **A1+A2+A3 research 三个占位** | 中 | **高** | README 头牌能力，skill 路径上目前是假的；且 `v0.41-dev` 正在统一 Agent 运行时，**做完再接收益更高** |
| **5** | A4+A5+A6（通知/scheduler/worktree） | 中 | 中 | 三个都是 CRUD/工作流的基础设施，做完才谈得上"自动化" |
| **6** | B3 Skill 分组 + B4 Memory 合并 | 中 | 中 | 结构性债，不影响用户可见功能 |
| **7** | B1/B2/B9/B10（Share + Hub） | **大** | 中高 | Phase 3/4 + 独立仓立项，**是产品决策不是技术决策**，要先拍板再动手（share 数据层已就绪） |
| **8** | B6 ATF | 大 | 中 | 12 个开放问题未决，先要设计收敛 |
| — | B5 SkillsLoader hot-reload | 小 | 小 | 加个 reload 路径即可，可搭车做 |

### 需要你拍板的三件事

1. **Skill 数量口径**：README 说 50+，实际 39 个子类 / 21 处注册。是**补到 50**，还是**把 README 改成真实数字**？
2. **Auth 走多远**：B8（PAT + 无密码登录）已完成并加上多用户授权（P1–P6）。剩下的是 **B9 share**（本仓可闭环，数据层已就绪）与 **B10 Hub**（含跨仓独立仓立项）—— 要做哪个？
3. **`v0.41-dev` 什么时候合**：它是 54 个 commit 的大重构，合并前需要一次完整的回归验证窗口 —— 现在就合，还是等某个版本窗口？

---

## 6. 复现

```bash
# CLI 命令数（AST 扫 registry）
grep -rn "class .*Command" src/llmwikify/interfaces/cli/commands/ | wc -l

# MCP 工具数
grep -c "@mcp.tool" src/llmwikify/interfaces/mcp/tools.py

# HTTP 路由数
grep -rhoE "@\w+\.(get|post|put|delete|patch)\(" src/llmwikify/interfaces/server/http/ | wc -l

# A 类占位仍存
grep -rn "placeholder\|Phase 5\|Phase 6" src/llmwikify/apps/chat/skills/actions/ src/llmwikify/apps/chat/skills/crud/ src/llmwikify/apps/chat/skills/workflows/

# 设计稿未完成 checkbox（注意 ppt-generator 已废弃，会污染统计）
grep -rc "^\s*[-*]\s*\[ \]" docs/designs/*.md | grep -v ":0"

# v0.41-dev 未合并
git log --oneline proxy/main..proxy/v0.41-dev | wc -l
```
