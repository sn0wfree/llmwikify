# 自动解析文档 → 增量完善知识库（Track C）

日期: 2026-11-03 · 分支: `feat/auto-doc-ingest`（从 `main` 分叉）
上游: [`docs/designs/self-maintenance.md`](self-maintenance.md)

## 背景

需求：**自动解析文档然后完善知识库**。

服务启动后，`apps/agent/maintenance/` 已有两条自动维护轨道（见
`self-maintenance.md`）：

```
轨 A (auto_ingest):  raw/ 新文件 → ingest_source → _llm_process_source
                    → execute_operations → 直接写页
轨 B (gap_filler):   周期 lint 全库 → gap 排序 → 机械修复 / 提案
```

但两者**互不相连**：轨 A 写完新页就结束，不会回头看这些新页是否在知识库里
制造了缺口（孤立源页、缺失概念页、没被链接的提及）。轨 B 要等
`gaps_interval_seconds`（默认 **7 天**）才跑一次全库 lint。

结果是：**一篇新文档进来后，知识库处于"新页已写入、但没被织进既有知识网络"
的状态**，可能持续数天。

## 现状调查（先查，避免重复造轮子）

已有零件（全部在 `main` 上）：

| 能力 | 位置 |
|------|------|
| 文档提取统一入口 | `foundation/extractors/base.py:extract()` |
| 解析 + 归档 | `kernel/wiki/mixins/io/ingest.py:263 ingest_source()` |
| LLM 产出写页计划 | `kernel/wiki/mixins/analysis/llm.py:15 _llm_process_source()` |
| 执行写页（带快照回滚） | `kernel/wiki/mixins/analysis/relation.py:92 execute_operations()` |
| 轨 A 自动 ingest | `apps/agent/maintenance/auto_ingest.py:46` |
| 轨 B 缺口填补 | `apps/agent/maintenance/gap_filler.py:112` |
| lint 8 条规则 | `kernel/wiki/lint/rules/` |
| 提案审核闭环 | `apps/agent/wiki_dream_editor.py:51 create_proposal()` |
| 编排入口 | `apps/agent/maintenance/__init__.py:133 MaintenanceManager.start()` |

**缺口**（本功能要填的）：

1. **ingest 与 gap 之间无串联** —— 核心缺口。
2. 轨 B 是**全库周期**（7 天），且只处理 2 类 gap；`isolated_source`
   优先级 20 < 默认阈值 30，实际从不处理。
3. 没有「针对刚 ingest 的这一篇文档」的**增量**完善能力。

## 顺带修复的既存缺陷

### A. `missing_cross_ref` lint 规则在分层 wiki 上从不触发

写方案时复现验证发现：**`missing_cross_ref` lint 规则在分层 wiki 上完全失效**。

复现（`wiki/concepts/Foo.md` + `wiki/sources/Bar.md` + `wiki/sources/Baz.md`，
后两页正文纯文本提及 Foo）：

```
MissingCrossRefsRule.run(wiki)  →  []        # 期望至少 1 条
```

根因（`kernel/wiki/lint/rules/missing_cross_refs.py`）：

- `candidate` 取自 `pages` 的键，而 `_page_display_name()`
  （`kernel/wiki/mixins/core/utility.py:167`）返回**带目录前缀**的路径
  （`concepts/Foo`）
- 正文里写的是 `Foo`，正则 `\bconcepts/Foo\b` 永远匹配不上
- 反向也错：正文若写 `[[Foo]]`，`_parse_wikilink_target()` 返回 `Foo`，
  与 candidate `concepts/Foo` 不等 → **已链接的页面也被误报**

现有测试全部用**根目录页面**（`write_page("Machine Learning", ...)`），
标题名恰好等于页面名，所以测试全绿而真实分层 wiki 失效 —— 典型测试盲区。

这条规则是轨 B 补交叉引用的**唯一候选来源**，它失效意味着
「自动补交叉引用」这个核心能力一直是死的。因此本方案先修它。

修复后行为（场景矩阵 6/6 符合预期）：

| 场景 | 结果 |
|------|------|
| 正文写标题名 `Foo` | 命中（修复前失效） |
| 正文写完整路径 `concepts/Foo` | 命中（原有行为） |
| 正文写 `[[Foo]]` | 不误报 |
| 正文写 `[[concepts/Foo]]` | 不误报 |
| `concepts/Foo` 与 `entities/Foo` 同名 | 标题名不参与匹配，全路径仍可 |
| 根目录页面 | 行为不变 |

### B. `extract` skill action 引用了不存在的模块

`apps/chat/skills/actions/extract_action.py` 引用了两个不存在的东西：

| 原引用 | 实际 |
|--------|------|
| `foundation.extractors.file.extract_file` | 该模块**不存在**（本地文件由 `base.extract()` 分派） |
| `foundation.extractors.web.extract_web` | 实际名字是 `extract_url` |

→ **任何走 skill 路径的 ingest 都会 ImportError**。

修法：改用统一入口 `foundation.extractors.base.extract()`——它已封装
YouTube / HTTP URL / 本地文件（含 markitdown、pdf、text、html）的全部分派，
与 `wiki.ingest_source()` 走同一条路径。相对路径按 wiki root 解析，
返回结构对齐 action 的 docstring 契约（`content` / `metadata`）。

### C. `analyzer.py` 缺 `Any` import（既存 F821）

`kernel/wiki/engines/analyzer.py` 从 v0.40.5 起缺 `from typing import Any`，
ruff 报 F821，会让 ruff 门禁红。它就在 lint 引擎宿主路径上，一行补齐。

## 方案

### Track C — `KnowledgeEnricher`

事件驱动：轨 A 写页成功后，对**本次文档涉及的知识单元**做增量完善。

```
raw/ 新文件
  └─ Track A  ingest_source → _llm_process_source → execute_operations
       └─ Track C  KnowledgeEnricher.enrich()        ← 新增
            ├─ 交叉引用补全（机械，自动写）
            ├─ 孤立源页补链（机械，自动写）
            └─ 缺失概念页（内容，提案待审）
```

### 与轨 B 的边界

| | 轨 B `gap_filler` | 轨 C `enricher` |
|---|---|---|
| 触发 | 周期（全库 lint，7 天） | 事件驱动（ingest 成功后） |
| 范围 | 全库所有 gap | **仅本次文档**涉及的概念 / 源页 |
| LLM 调用 | 1 次（lint gap-detect） | **0 次**（机械补链 + 提案草稿复用已有内容） |
| 写入策略 | 机械自动 + 内容提案 | 同左（沿用双轨） |

轨 C 不做全库扫描——那正是轨 B 的职责，两者互补不重叠。

### 三类补全

| # | 类型 | 判定 | 动作 |
|---|------|------|------|
| 1 | 交叉引用 | 本次的概念被其它页**纯文本提及**且无 wikilink | 首个词边界出现处插 `[[概念]]`，直接写页 |
| 2 | 孤立源页 | 本次新写的源页没有任何页引用它 | 在提及它的页补 `[[源页名]]`，直接写页 |
| 3 | 缺失页面 | LLM 建议建页（`suggested_pages`）但库里没有 | 生成 `create` 提案，等人工审核 |

沿用轨 B 已决策的双轨写入策略：**机械修复自动批准，内容生成走提案**。

### 单元来源（实现期修正）

初版设计把「本次涉及的概念」定义为**本次写出的页面**。端到端验证暴露了这���
缺陷：

> 新文档提到一个**库中已存在**的概念（Risk Parity），老页面里写了它却没有
> 链接 —— 这恰恰是最该补链的对象，却因为该页不是本次 ingest 写出的而被漏掉。

改用 LLM 分析结果里的两个字段作为单元来源（`analyze_source` 的输出）：

| 字段 | 含义 | 用途 |
|------|------|------|
| `cross_refs` | 文档关联的**既有**页面 | 补链目标（可写标题或全路径，需解析） |
| `suggested_pages` | 文档建议创建的页面 | 提案来源 |
| `analysis` 之外 | ingest 实际写出的页 | 补链目标 + 提案候选 |

`cross_refs` 里的名字可能是标题（`Risk Parity`）也可能是全路径
（`concepts/Risk Parity`），统一经 `_resolve_page()` 解析成规范路径，
插入的链接因此始终是 `[[concepts/Risk Parity]]` 形式。

### 关键实现决策

**D1 · wikilink 统一用标题名形式 `[[Foo]]`**

`wiki_schema.yaml:216` 的示例是带目录前缀的 `[[concepts/Gold Mining]]`，
但代码里唯一的自动补链实现（`gap_filler.py:200`）用的是无前缀形式，
且 `tests/test_maintenance_gap_filler.py:98` 断言 `[[Concept Alpha]]`。

**修正（实现期）**：既有的 `test_v026_wikilink_fix.py:484` 断言 concept 是
`concepts/Risk Parity`（页面名），说明**带前缀才是本项目规范**，且正文里
也可能写全路径。因此：

- 规则的 `concept` 字段 = **页面名**（保持既有契约）
- 新增 `concept_title` 字段 = 标题名（供补链方匹配正文）
- 补链产出 = **页面名**形式 `[[concepts/Risk Parity]]`（符合 schema）
- 规则侧**两种形式都识别**为「已链接」，存量页面不产生新误报

**D2 · 标题名冲突时排除候选**

`concepts/Foo` 与 `entities/Foo` 同名时，标题名有歧义，正文匹配会误判。
构建「标题名 → 页面名」映射时，一对多的标题名不参与标题名匹配
（仍可用全路径匹配）。

**D3 · 正文匹配兼容两种写法**

正文既可能写 `Risk Parity`（自然语言）也可能写 `concepts/Risk Parity`
（路径形式），规则对两者都做词边界匹配。

**D4 · 补链与源页引用共用一个插入器**

轨 B 的 `_link_first_occurrence()` 逻辑不平凡（要避开已有 wikilink 内部的
命中），两个调用点共享同一段正则逻辑，抽到
`apps/agent/maintenance/wikilink.py` 供两处使用。

**D5 · 提案复用 `WikiDreamProposalManager`**

轨 C 不自建提案存储，直接复用既有审核闭环（WebUI / `wiki_dream_skill`）。

**D6 · 失败隔离**

单页补链失败只记错误计数，不影响其余页、不影响轨 A 的写页结果
（轨 A 已写完才触发轨 C）。

## 端到端测试

功能写完后缺一条自动化证据链：「放文档进 raw/ → 知识库被完善」。
`tests/e2e/` 目录是 **Playwright UI E2E**（起真实服务器 + 浏览器，
`conftest.py` 里有 session 级 uvicorn fixture），链路测试不需要服务器与
浏览器，因此放在顶层 `tests/test_auto_doc_ingest_flow.py`，随 CI 默认跑。

### 测试矩阵

| # | 路径 | 断言 |
|---|------|------|
| 1 | 正常：raw/ 文档 → ingest → LLM 写页 → enricher 织网 | 页面落盘、`stats["pages_written"]`、补链写入、index 更新 |
| 2 | LLM 失败 → 提案兜底 | `stats["fallback_proposals"] >= 1`，内容进提案队列不丢失 |
| 3 | enricher 失败 → 不影响已写页 | 页面已写入、`stats["last_error"]` 含 enrich 前缀 |
| 4 | 重复处理同一文件 | 第二次跳过（`_is_processed`），不重复写页 |

### 设计取舍

- **不 mock `ingest_source`**：走真实 `extract()`（本地 markdown），
  才能覆盖「解析 → 归档 → 写页」全链
- **mock `_llm_process_source`**：LLM 不可调用，且本测试要验证的是
  「编排是否正确」而非「LLM 输出质量」。返回固定的 `write_page` operations
- **直接调 `_process_file`**：绕开 watchdog（CI 环境常未装），
  与 `test_fallback_proposal_persists_to_db` 的既存失败无关
- **enricher 注入失败桩**：验证隔离性，不让 enricher 的异常吃掉写页结果

## 配置

轨 C 的开关与预算在 `~/.llmwikify/llmwikify.json` 的 `maintenance.enricher` 段：

```json
{
  "maintenance": {
    "enricher": {
      "enabled": true,
      "max_units_per_doc": 10,
      "max_links_per_unit": 5,
      "propose_missing_pages": true
    }
  }
}
```

| 键 | 默认 | 含义 |
|----|------|------|
| `enabled` | `true` | ingest 后是否运行增量完善 |
| `max_units_per_doc` | `10` | 单篇文档最多处理的知识单元数 |
| `max_links_per_unit` | `5` | 单个单元最多补多少条 `[[链接]]` |
| `propose_missing_pages` | `true` | LLM 建议建页但库里没有时是否进提案队列 |

补链接是纯文本操作，不消耗 LLM 配额；提案需人工在 WebUI 审核。
完整的字段说明、调优建议与三轨对比见
[`self-maintenance.md` 的 Config 章节](self-maintenance.md#config)。

## 修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kernel/wiki/lint/rules/missing_cross_refs.py` | edit | 修规则：标题名/全路径双向匹配 + 两种 wikilink 形式都识别 + 歧义排除；输出加 `concept_title` |
| `kernel/wiki/engines/analyzer.py` | edit | 补 `Any` import（既存 F821，ruff 门禁红） |
| `apps/chat/skills/actions/extract_action.py` | edit | 修两个不存在的 import（`extractors.file` / `extract_web`），改走 `base.extract()` 统一入口 |
| `apps/agent/maintenance/wikilink.py` | NEW | 公共补链插入器（从 gap_filler 抽出） |
| `apps/agent/maintenance/enricher.py` | NEW | `KnowledgeEnricher` + `EnrichResult` + `collect_units` |
| `apps/agent/maintenance/gap_filler.py` | edit | 改用公共插入器 + 用 `concept_title` 匹配正文（行为不变） |
| `apps/agent/maintenance/config.py` | edit | 加 `EnricherConfig`，接入 `MaintenanceConfig` / `load_maintenance_config` / `to_dict` |
| `apps/agent/maintenance/auto_ingest.py` | edit | 写页成功后触发 enricher |
| `apps/agent/maintenance/__init__.py` | edit | 创建 enricher 并注入 auto_ingest；status 暴露 enricher 状态 |
| `interfaces/cli/commands/enrich.py` | NEW | `llmwikify enrich <path>` 端到端手动触发 |
| `interfaces/cli/commands/__init__.py` | edit | 注册命令 |
| `tests/test_lint_missing_cross_refs.py` | NEW | 规则修复测试（分层目录场景，9 项） |
| `tests/test_maintenance_enricher.py` | NEW | enricher 单测（22 项） |
| `tests/test_cli_enrich.py` | NEW | CLI 测试（7 项） |
| `docs/designs/auto-doc-enrichment.md` | NEW | 本文档 |

## 风险

| 风险 | 缓解 |
|------|------|
| 修 lint 规则后轨 B 开始补链，行为变化 | 机械修复本就自动批准且幂等（首现插入）；121 项既有 lint 测试全绿 |
| 规则修复后可能产生新误报（带前缀 wikilink） | 两种形式都识别为已链接 |
| 同名页面歧义 | 歧义标题名不参与标题名匹配（仍可用全路径匹配） |
| 补链污染正文 | 只在词边界首现处插一次；概念名做正则转义 |
| 提案噪音（suggested_pages 过多） | 受 `max_units_per_doc` 预算限制；已有页不提案 |
| LLM 不可用 | 补链是纯文本操作，不依赖 LLM；提案是可选路径 |
| 补链与轨 B 重复 | 轨 C 只处理本次文档相关页，轨 B 走全库周期 |

## 执行流程

```
KnowledgeEnricher.enrich(llm_result, exec_result):
  1. concepts = ops 写出的概念页 ∪ analysis.cross_refs
     sources  = ops 写出的 sources/ 页
     suggested= analysis.suggested_pages 的名字
  2. for each concept (受 max_units_per_doc 限):
       a. _resolve_page(name) → 规范页面名（标题 → 全路径）
       b. search(标题) → 提及它的页
       c. 读页 → 正文纯文本命中（避开已有 wikilink）？
          → 插入 [[规范页面名]] → 写页        （类型 1）
  3. for each source: 同上                    （类型 2）
  4. for each suggested:
       库里已有同名页？→ 跳过
       → 生成 create 提案                     （类型 3）
  5. 返回 EnrichResult 统计
```

## 测试用例

| # | 场景 | 期望 |
|---|------|------|
| 1 | 规则：分层目录页被正文纯文本提及 | 报出 `missing_cross_ref` |
| 2 | 规则：正文已写 `[[Foo]]` | 不误报 |
| 3 | 规则：正文已写 `[[concepts/Foo]]` | 不误报 |
| 4 | 规则：`concepts/Foo` 与 `entities/Foo` 同名 | 标题名不参与匹配，全路径仍可 |
| 5 | 规则：根目录页面（存量行为） | 不回归（121 项既有测试） |
| 6 | enricher：概念被提及未链接 | 插入 `[[概念]]`，写页成功 |
| 7 | enricher：概念已被链接 | 不重复插入 |
| 8 | enricher：cross_refs 指向既有页 | 老页面被补链 |
| 9 | enricher：cross_refs 用标题书写 | 解析成规范路径后补链 |
| 10 | enricher：建议页无对应页 | 生成 `create` 提案 |
| 11 | enricher：建议页已存在 | 不提案 |
| 12 | enricher：源页孤立 | 在提及页补链接 |
| 13 | enricher：search 失败 | 不崩溃，计数 |
| 14 | CLI：`llmwikify enrich <path>` | 端到端解析+写页+完善 |

## 端到端验证

真实代码路径（`ingest_source` → `execute_operations` → `enrich`）跑一个场景：
库中已有 `concepts/Risk Parity`，两个老页面纯文本提及它；新文档同时提到
Risk Parity 与 Monte Carlo Simulation。

```
[3] 完善: 2 概念 / 1 源页 → 4 链接, 1 提案, 0 错误

  sources/Portfolio A: See [[concepts/Risk Parity]] here.
  sources/Portfolio B: Also see [[concepts/Risk Parity]].
  sources/New Source: Covers [[concepts/Risk Parity]] and [[concepts/Monte Carlo Simulation]].

  提案: Backtesting (create)
  完善后 lint 剩余 missing_cross_ref: []
```

## 实现期审查发现并修复的缺陷

实现完成后做了两轮独立审查（一轮针对 Track C 本身，一轮针对
skill/ingest 链路），以下问题已修复。其中 **#1 和 #4 是本次改动引入的
回归**，审查抓到了它们。

### Track C 本身

| # | 问题 | 后果 | 修法 |
|---|------|------|------|
| 1 | 补链插进全路径中间 | `concepts/Foo` 变 `concepts/[[concepts/Foo]]` —— 坏链 | 标题 pattern 不匹配 `/` 旁的片段（`concept_pattern`），全路径交给 `path_pattern` |
| 2 | 已链接的页被重复插链 | 同一页出现两个指向同页的链接 | 新增 `is_linked()`，`[[Foo]]` 与 `[[concepts/Foo]]` 都算已链接 |
| 3 | 名字解析失败仍写链 | 产出指向不存在页面的坏链 | 解析不到就跳过该单元并计入 `skipped_units` |
| 4 | lint 性能退化 | 1400 页扫描 12s → 42s（对抗场景 61x） | 倒排索引（词序列→候选）+ 泛化 gram 过滤 + 词集合预检，**降至 0.92s** |
| 5 | 补链改写页面 H1 标题 | `# Foo` 变 `# [[concepts/Foo]]` | mask 加入 markdown 标题行 |
| 6 | 同名歧义判定不确定 | `title_to_page` 由 set 迭代构造，赢家随 `PYTHONHASHSEED` 变 | `sorted()` 构造；enricher 侧同样排除歧义标题 |
| 7 | 同一建议重复排队 | 两条相同提案 | `_proposed_pages` 去重 |
| 8 | 计数器覆盖而非累加 | 第二次 ingest 后统计丢失 | `+=` |
| 9 | cross_ref 未按目录分类 | `sources/X` 被归入概念桶 | 统一分类函数，裸标题才默认入概念桶 |

### skill / ingest 链路

| # | 问题 | 后果 | 修法 |
|---|------|------|------|
| 10 | `ingest_skill` 用错 action key | **管线静默失效**：返回 ok 但零字节写入 | key 改 `write`/`read`；写失败返回 `fail` 而非吞掉 |
| 11 | extract 同步阻塞 event loop | 3 个并发 107s、心跳 tick=1（loop 饿死） | `asyncio.to_thread` + `wait_for` 硬超时，降至 36s、tick=2329 |
| 12 | jieba 停用词表无编码指定 | Windows 上模块级 `UnicodeDecodeError` | `encoding="utf-8"` |
| 13 | `wiki_graph` 工具相对导入层级错 | `ModuleNotFoundError`，调用即炸 | `...kernel` → `....kernel` |
| 14 | 版本号常量取错 | wiki.md 合并通知永远写 `0.11.0` | `from llmwikify import __version__` |
| 15 | 二进制文件解码未兜底 | 未知扩展名 + 二进制 → 未捕获异常 | `errors="replace"` |
| 16 | 提案闭环是断的 | maintenance 写的提案，WebUI 的实例**既看不到也批不了** | 有 DB 时读写一律以 DB 为真源（`_load_proposals`）；状态变更同步内存缓存 |
| 17 | async handler 里同步跑 LLM / 重 IO | `analyze`、`lint` 一次调用可阻塞数十秒；`write` 重建 index.md（400 页 359ms） | 新增 `safe_call_async`（`asyncio.to_thread` + 可选超时），6 个 action 与 8 个 detect 全部改用 |
| 18 | enricher 持有从未使用的 LLM 信号量与限流器 | 让人误以为它的读写受并发约束 | 删除两个参数与 `ensure_global_llm_fallback` 调用（enricher 不调 LLM，该调用只会改动全局配置） |

### 测试

新增 38 项回归测试，覆盖上述每一类：坏链形态、重复链接、解析失败、
标题行保护、跨 `PYTHONHASHSEED` 确定性（8 个 seed）、性能护栏
（1400 页 < 5s）、ingest pipeline 真实写入、event loop 不被饿死、
stats 累加、`wiki_graph` 导入、jieba 编码、版本号、跨实例提案可见与可审批（5 项）、action 不阻塞 event loop（8 项）。

其中 `tests/test_apps_chat_skills_pipelines.py` 原先用 `MagicMock`
伪造了 `write_page`/`read_page` 两个 key，正好与代码里的错误 key
一致，把 #10 掩盖得干干净净 —— 已改为使用真实 skill 对象。

### 已知限制（不在本次范围）

- `wiki.write_page` 每次重建整个 `index.md`（400 页约 359ms），
  批量补链的写入代价与此成正比；`max_links_per_unit` 兜住上限。

## 验证

```bash
ruff check src/llmwikify/ tests/
# → All checks passed!

mypy src/llmwikify/apps/agent/maintenance/enricher.py \
      src/llmwikify/apps/agent/maintenance/wikilink.py \
      src/llmwikify/kernel/wiki/patterns.py \
      src/llmwikify/kernel/wiki/lint/rules/missing_cross_refs.py \
      src/llmwikify/interfaces/cli/commands/enrich.py
# → exit 0

pytest tests/test_lint_missing_cross_refs.py tests/test_maintenance_enricher.py \
       tests/test_maintenance_wikilink.py tests/test_maintenance_extended.py \
       tests/test_cli_enrich.py \
       tests/test_apps_chat_skills_actions.py tests/test_apps_chat_skills_pipelines.py \
       tests/test_apps_wiki_service.py tests/test_apps_chat_skills_crud.py \
       tests/test_kernel_latent_defects.py \
       tests/test_v015_features.py tests/test_v026_wikilink_fix.py \
       tests/test_maintenance_gap_filler.py tests/test_maintenance_auto_ingest.py \
       tests/test_maintenance_comprehensive.py tests/test_lint_engine.py
# → 420 passed, 2 failed（均为既存失败，见下）

python scripts/check_architecture.py
# → ✅ 0 architecture violations across 4 layers
```

### 回归对照

全量 `pytest tests/ --ignore=tests/e2e` 的失败/错误清单与 HEAD 基线 diff：

```
base=365  new=365
新增: FAILED tests/test_autoresearch.py::TestEventsCursor::test_get_events_since_returns_only_newer
消失: FAILED tests/test_apps_chat_agent_runner_v2.py::test_run_context_elapsed_increases_with_time
```

总数不变（365 = 365），增减各一条且都是**已知的 Windows 计时器 flaky**
（依赖 `time.time()` ~15.6ms 分辨率，`get_events_since` 用 `>` 比较时间戳）。
连跑三次的失败数为 1/1/2，属随机抖动，与本次改动无关。

本次涉及的两个既存失败（stash 对照确认 HEAD 上同样失败）：

| 测试 | 原因 |
|------|------|
| `test_fallback_proposal_persists_to_db` | watchdog 未安装 → `AutoIngestService.start()` 返回 False → 拿不到 `auto_ingest_services["w1"]` |
| `test_on_watch_event_deleted_removes_from_pending` | Windows 路径分隔符：测试用 `/some/path.md`，代码存 `\some\path.md` |
