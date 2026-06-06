# Sink 功能设计决策记录

> 本文档记录 llmwikify Query Sink 功能的完整设计思考过程。
> 创建时间：2026-04-10 | 版本：v0.14.0 规划

---

## 1. 问题起源

### 1.1 原始问题

当同一个问题被反复询问时，`update_existing=False`（默认）行为会创建大量副本：

```
Query: Gold Mining
Query: Gold Mining (2026-04-10)
Query: Gold Mining (2026-04-10-1)
Query: Gold Mining (2026-04-10-2)
...
```

每个副本都有一定价值（不同角度、补充信息），但内容可能 80% 重叠，造成知识碎片化。

### 1.2 核心矛盾

| 矛盾 | 说明 |
|------|------|
| 不想覆盖 | `update_existing=True` 全量覆盖，旧内容中可能有独特信息永久丢失 |
| 不想副本 | 默认行为创建带时间戳的副本，知识碎片化 |
| 需要思考 | LLM 应该在合并前做综合思考，而不是系统自动追加 |

---

## 2. 方案演进

### 2.1 方案 A：auto_merge（系统自动追加）

```python
wiki.synthesize_query(query, answer, auto_merge=True)
# 系统自动追加到旧页面末尾
```

**否决原因**：
- LLM 失去对页面质量的控制权
- 页面变成"追加日志"而非"知识页面"
- 违反原则 "The LLM owns this layer entirely"
- 搜索时 FTS 返回长页面，用户不知道哪个版本正确
- 违反原则 "the synthesis already reflects everything you've read"

### 2.2 方案 B：LLM 辅助合并（仅增强 hint）

```python
hint = "有相似页面，建议先读旧内容再合并"
```

**否决原因**：
- 依赖 LLM 主动行为，实际可能被忽略
- 副本仍然会创建，只是有提示
- 没有解决根本问题——LLM 可能因为"太麻烦"而不合并

### 2.3 方案 C：Sink 缓冲机制（最终方案）

```
Query 发生时                          Lint/整理时
───────────────                      ─────────────────────
新答案不直接写入正式页面              LLM 读取 sink + 正式页面
而是追加到 sink 缓冲区                综合整理 → 更新正式页面
保留完整时间线                        清空已处理的 sink
```

**选择原因**：
- 与现有三层架构对称：Raw → Sink → Wiki → Schema
- 时间线天然保留，不污染正式页面
- Lint 时强制处理，不依赖 LLM 主动性
- LLM 仍然拥有所有决策权（何时合并、如何合并）

---

## 3. 关键设计决策

### 3.1 存储位置

**决策**：`wiki/.sink/` 隐藏子目录，文件命名 `{topic}.sink.md`

| 备选方案 | 否决原因 |
|----------|----------|
| 同目录 `{topic}.md` | `glob("*.md")` 会误扫描，干扰正式页面操作 |
| 同目录 `{topic}.sink` | Obsidian 不渲染 |
| 同文件内 HTML 注释分隔 | 搜索时索引含 sink 内容，体验混乱 |
| 根目录 `sink/` | 概念上属于 wiki 层但物理位置在外，违背三层架构 |
| **`wiki/.sink/` 隐藏目录 `{topic}.sink.md`** | ✅ Obsidian 自动隐藏不干扰，语义正确（wiki 的操作缓冲区），文件系统自包含 |

### 3.2 双向链接

**决策**：frontmatter 显式存储

**正式页面** `wiki/Query: Gold Mining.md`：
```yaml
---
sink_path: wiki/.sink/Query: Gold Mining.sink.md
sink_entries: 5
last_merged: 2026-04-08
---
```

**Sink 文件** `wiki/.sink/Query: Gold Mining.sink.md`：
```yaml
---
formal_page: "Query: Gold Mining"
formal_path: wiki/Query: Gold Mining.md
created: 2026-04-08
---
```

**价值**：
- LLM 读正式页面时能知道有 pending updates
- `wiki_lint` 能自动检查一致性
- Obsidian 中可通过 wikilink 跳转

### 3.3 搜索标记

**决策**：`wiki_search` 和 `wiki_read_page` 都附加 `has_sink`, `sink_entries`

```python
# search 返回
{"page_name": "Query: Gold Mining", "has_sink": true, "sink_entries": 5, ...}

# read_page 返回
{"page_name": "Query: Gold Mining", "has_sink": true, "sink_entries": 5, ...}

# index.md 显示
- [[Query: Gold Mining]] - Gold mining is... 📥 5 pending updates
```

**原因**：LLM 在搜索和读取阶段都能感知到 pending 内容，引导其在生成答案前查看 sink。

### 3.4 MCP 工具数量

**决策**：仅新增 1 个工具 `wiki_sink_status`，其余复用现有工具

| 操作 | 工具调用 |
|------|----------|
| 发现相似页面 | `wiki_search(topic)` |
| 读旧页面 | `wiki_read_page("Query: Gold Mining")` |
| 读 sink | `wiki_read_page("wiki/.sink/Query: Gold Mining.sink.md")` |
| 清空 sink | `wiki_write_page("wiki/.sink/Query: Gold Mining.sink.md", content)` |
| 查看哪些 sink 有待处理 | `wiki_sink_status()` |

### 3.5 默认行为

**决策**：有相似页面时，默认 status="sunk"（进入 sink），不创建副本

**理由**：
- 副本积累是问题的根源
- sink 是安全的默认行为——知识不丢失
- LLM 可以在 lint 时批量处理

---

## 4. 原则对齐分析

| 原则 | 符合度 | 说明 |
|------|--------|------|
| **三层架构** | ✅ | Sink 是 Wiki 层的操作状态（缓冲区），物理位置在 wiki/.sink/ 与概念一致 |
| **LLM 拥有 Wiki** | ✅ | LLM 控制所有 Sink 操作（何时读、何时合并、何时清空） |
| **知识复利** | ✅✅ | 比原设计更好——每次查询都持久化，定期整合精炼 |
| **LLM 自主决策** | ✅ | 提供信息和工具，不强制行动 |
| **增量维护** | ✅ | Sink 使维护更自然——日常不整理，lint 时批量处理 |
| **零域假设** | ✅ | 可选、可配置、文档化 |

### 注意事项

- `status="sunk"` 时**仍然更新 index.md**，但只在正式页面条目后附加 pending 标记
- 不创建独立的 index 条目（sink 条目不是独立页面）
- 建议的措辞应该是**观察性**而非**指令性**（"我注意到..."而非"你应该..."）

---

## 5. Merge 策略设计

### 5.1 参数演进

| 阶段 | 参数 | 问题 |
|------|------|------|
| v0.12.x | `update_existing: bool = False` | "update" 语义不清，LLM 可能以为会保留旧内容 |
| v0.14.0 | `merge_or_replace: str = "sink"` | 三种策略语义明确 |

### 5.2 三种策略

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `"sink"`（默认） | 追加到 sink 文件 | 不确定是否需要立即合并 |
| `"merge"` | 读取旧内容 → LLM 综合合并 → 全量替换 | LLM 已读取旧内容并准备好合并版本 |
| `"replace"` | 直接覆盖正式页面 | LLM 提供了完整的替换版本 |

### 5.3 为什么 "merge" 和 "replace" 行为相同？

两者都是全量替换正式页面，区别在于**语义引导**：

- `merge` 暗示 LLM 应该先读旧内容、做综合，然后再调用
- `replace` 暗示 LLM 已经准备好完整的新版本

行为相同，但指导 LLM 的工作流程不同。

---

## 6. Sink 建议生成设计

### 6.1 核心价值

将 Sink 从"被动存储"升级为"知识生长引擎"。每次查询不仅是存储，还为下次查询提供上下文和改进方向。

### 6.2 四种建议类型

| 类型 | 检测逻辑 | 输出示例 |
|------|----------|----------|
| **内容缺口** | 比较新答案与正式页面的主题覆盖率 | `Content Gap: Previous answer covered "environmental impact" but this answer doesn't.` |
| **来源质量** | 检测无来源、遗漏重要来源、新增来源 | `Missing Sources: Previous answer cited [[Environmental Law]]. Consider whether still relevant.` |
| **查询模式** | 统计同一问题的重复次数、查询复杂度趋势 | `Repeated Question: Asked 3 times with variations. Consider adding FAQ section.` |
| **知识生长** | 检测新概念出现、可能的矛盾 | `New Concepts: Mentions Cyanidation, Heap Leaching. Consider if any deserve own page.` |

### 6.3 建议格式（观察性措辞）

```markdown
### 💡 Suggestions for Improvement
- Content Gap: Previous answer covered environmental impact but this answer doesn't.
- Missing Sources: Previous answer cited [[Environmental Law]]. Consider whether still relevant.
- Repeated Question: This question (or variations) has been asked 3 times.
- New Concepts: Mentions Cyanidation, Heap Leaching not in formal page.
```

**措辞原则**：观察性（"Previous answer covered X"）而非指令性（"You must add X"）。

### 6.4 生成时机

在 `_append_to_sink()` 中生成，作为条目的一部分写入 sink 文件。

---

## 7. Sink 增强设计

### 7.1 去重检测

追加新条目时，检测与 sink 中现有条目的文本相似度：

```markdown
> ⚠️ High similarity (78%) with entry from 2026-04-10.
> Consider using merge_or_replace="replace" to consolidate.
```

阈值：Jaccard ≥ 0.7 标记为高相似。

### 7.2 过期警告

`sink_status()` 和 `lint()` 中增加 urgency 字段：

| 天数 | urgency | 说明 |
|------|---------|------|
| 0-7 | `ok` | 正常 |
| 7-14 | `attention` | 值得关注 |
| 14-30 | `aging` | 需要处理 |
| 30+ | `stale` | 已过时 |

`lint()` 返回 `sink_warnings` 列表，包含所有 urgency != "ok" 的 sink。

---

## 8. 完整数据流

```
synthesize_query(query, answer, merge_or_replace="sink")
    |
    +--> _find_similar_query_page(query) → dict {page_name, preview, score, ...}
    |        |
    |        +--> No match --> _create_query_page() → status="created"
    |        |
    |        +--> match + merge_or_replace="replace" --> overwrite → status="replaced"
    |        |
    |        +--> match + merge_or_replace="merge" --> overwrite → status="merged"
    |        |
    |        +--> match + merge_or_replace="sink" (default)
    |                     |
    |                     +--> _generate_sink_suggestions() → 四种建议
    |                     +--> _check_sink_duplicate() → 去重警告
    |                     +--> _append_to_sink() → 追加条目 + 建议 + 警告
    |                     +--> _update_page_sink_meta() → 更新 frontmatter
    |                     +--> _update_index_file() → 更新 index.md
    |                     → status="sunk"
    |
    +--> Returns {status, hint, sink_path, ...}

搜索/读取时:
    search()      → 结果附加 has_sink, sink_entries
    read_page()   → 返回附加 has_sink, sink_entries
    lint()        → 包含 sink_status + sink_warnings

维护时:
    sink_status() → 总览所有 sinks + urgency
    read_sink()   → 解析条目（含建议）
    clear_sink()  → 清空条目，更新 last_merged
```

---

## 9. 被否决的方案记录

### 9.1 方案：合并操作由 LLM 完成，系统提供提示词

**否决原因**：好的方向，但需要系统基础设施支持（sink），否则 LLM 永远不会主动合并。

### 9.2 方案：默认引导 LLM 立即合并（update_existing=True）

**否决原因**：LLM 可能在没有读旧内容的情况下直接覆盖，丢失旧知识。

### 9.3 方案：全局单文件 sink（query_sink.md）

**否决原因**：文件会变得巨大，难以管理，按主题分文件更清晰。

### 9.4 方案：同文件内 HTML 注释分隔

**否决原因**：搜索时会索引到 sink 内容，搜索结果不干净。

---

## 10. 参考

- 原则文档：`docs/LLM_WIKI_PRINCIPLES.md`
- 当前代码：`src/llmwikify/core/wiki.py`（v0.13.0 sink 基础实现）
- MCP 服务器：`src/llmwikify/mcp/server.py`
- 测试文件：`tests/test_sink_flow.py`
