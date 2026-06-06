# P3 Design: Ingest + Lint 增强方案

> 创建时间: 2026-04-15
> 状态: 设计方案确认，准备实施
> 关联原则: `docs/LLM_WIKI_PRINCIPLES.md`

---

## 背景

### 当前问题

1. **Ingest 不创建页面** — `ingest_source()` 只返回原始内容，agent 需要自己分析提取 entities/concepts，认知负荷高
2. **Lint 只报告不修复** — 只做检测，不做修复，需要手动逐个处理
3. **自定义类型页面无人创建** — wiki.md 定义了 `Model`, `MacroFactor` 等自定义类型，但 ingest 和 lint 都不知道要创建这些页面
4. **wiki.md 变更后 wiki 不同步** — 用户更新了 wiki.md 自定义类型，但 wiki 内容没有跟上
5. **Agent 缺乏自主性** — 需要用户提醒才能执行 lint 等操作

### 设计目标

1. **Agent 自主发现** — Ingest 后自动检测 gaps，通过 `lint_hint` 返回给 agent
2. **Agent 自主修复** — agent 看到 lint_hint 后，主动调用 `wiki_lint(mode="fix")` 修复
3. **Schema-Aware** — Lint 能解析 wiki.md 自定义类型，检测并修复缺失页面
4. **LLM 主导维护** — LLM 负责"思考"工作，代码负责"结构"工作

---

## 核心设计决策

### Ingest vs Lint — 增强哪个？

**结论：增强 Lint，Ingest 只做轻量集成**

| 维度 | 增强 Ingest | 增强 Lint |
|------|------------|-----------|
| 覆盖范围 | 只影响新 source | 覆盖所有 source 和 wiki 页面 |
| Schema 同步 | wiki.md 变更后需等新 source ingest | 一次 lint 即可同步整个 wiki |
| 职责清晰度 | ingest 职责变复杂 | 职责清晰：lint = schema compliance check + repair |
| Agent 自主性 | 需要 agent 解析分析结果 | agent 看到 lint_hint 直接调用 fix |

**不保留 `--self-create` 模式**，后续再做调整。

### 扫描策略

**选择：混合（增量为主，支持 `--all` 强制全量）**

基于业界最佳实践：
- **两阶段检测**：mtime+size 快速过滤 → content hash 精确确认
- **缓存存储**：现有 SQLite 数据库，新增 `source_analysis` 表
- **缓存失效**：文件内容变化或 schema_version 变化时失效
- **借鉴工具**：watchdog（已有依赖）、Sphinx 的 environment pickle 模式

### LLM 上下文策略

**选择：精简上下文 + 引导 LLM 自主查找**

| 组件 | 包含内容 | 大小限制 | 决策 |
|------|---------|---------|------|
| 结构化 schema | extract_schema 缓存 | ~1000 chars | ✅ 必须 |
| wiki.md 全文 | — | — | ❌ 不需要（extract_schema 时 LLM 已读过） |
| wiki index.md | — | — | ❌ 不需要（引导 LLM 自主查找） |
| 页面名称列表 | 所有页面相对路径 | ~2000 chars | ✅ 必须 |
| source 摘要 | 文件名 + 大小 + 分析状态 + entities | <20 个 source 显示 entities，>20 只显示状态 | ✅ 必须 |
| orphan concepts | 关系图谱孤儿概念 | ~100 chars | ✅ 必须 |
| relation stats | — | — | ❌ 可去掉 |

**总上下文大小：~3500 chars (~900 tokens)**

### 性能限制

**选择：默认限制 10 个，支持 `--all` 或 `--limit N`**

### Schema 变更通知

**选择：Schema Hash + Prompt 结合**

- 使用 wiki.md SHA-256 前 12 位作为 schema hash
- 缓存中包含 schema_hash，失效时重新提取
- Prompt 中指导 agent 在 wiki.md 变更后运行 lint

---

## 架构设计

### 整体流程

```
┌─────────────────────────────────────────────────────────────┐
│ 首次运行 wiki lint                                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. _compute_schema_hash()                                    │
│    └── SHA-256(wiki.md) → 'abc123def456'                    │
│                                                              │
│ 2. _llm_extract_schema()                                     │
│    ├── Input: wiki.md 全文                                   │
│    ├── LLM: extract_schema.yaml                              │
│    ├── Output: 完整结构化 schema JSON                         │
│    └── Cache: schema_cache 表 (SQLite)                       │
│                                                              │
│ 3. _build_lint_context()                                     │
│    ├── Read cached schema (结构化 JSON)                       │
│    ├── Get page list                                         │
│    ├── Summarize sources (<20 显示 entities, >20 只显示状态)   │
│    └── Get orphan concepts                                   │
│    └── 总计 ~3500 chars                                      │
│                                                              │
│ 4. _llm_detect_gaps()                                        │
│    ├── Input: 精简上下文                                      │
│    ├── LLM: lint_gap_detection.yaml                          │
│    ├── Output: [{"type": "missing_custom_page", ...}]        │
│    └── Cache: lint_cache 表 (SQLite)                         │
│                                                              │
│ 5. 返回结果                                                    │
│    └── {"issues": [...], "schema_hash": "abc123def456"}      │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 后续运行 wiki lint (schema 未变)                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. _compute_schema_hash() → 'abc123def456' (相同)            │
│ 2. _is_cache_valid() → True                                 │
│ 3. _get_cached_issues() → 直接返回缓存结果                    │
│ 4. 返回结果 (无需 LLM 调用)                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Agent 工作流

```
场景 1: Ingest 后自动检测

用户: "ingest raw/article.pdf"
Agent:
  1. 调用 wiki_ingest("raw/article.pdf")
  2. 收到结果:
     {
       "source_name": "article.pdf",
       "content": "...",
       "analysis": {
         "topics": ["AI", "GPU"],
         "entities": [...],
         "suggested_pages": [...]
       },
       "lint_hint": {
         "issues_found": 3,
         "schema_hash": "abc123def456",
         "suggestion": "Call wiki_lint(mode='fix') to repair",
         "top_issues": [...]
       }
     }
  3. 根据 analysis 创建建议页面
  4. 看到 lint_hint → 调用 wiki_lint(mode="fix", limit=10)
  5. 报告用户

场景 2: Wiki.md 变更后同步

用户: "我更新了 wiki.md，新增了 Model 页面类型"
Agent:
  1. 读取 wiki.md → 看到新类型
  2. 调用 wiki_lint(mode="check") → 检测 gaps
     ├── _load_wiki_schema() 加载最新 wiki.md
     ├── _detect_schema_gaps(schema) 检测缺失的 Model 页面
     └── 返回 gap 列表
  3. 看到 gaps → 调用 wiki_lint(mode="fix", limit=10)
  4. LLM 生成修复操作：
     ├── 读取 source_analysis 缓存（优先）
     ├── 如果缓存缺失，读取 source 文件内容
     └── 创建 Model 页面
  5. 执行修复 → 报告结果
```

---

## Schema 缓存设计

### extract_schema 输出结构

```json
{
  "standard_page_types": [
    {"type": "Source", "location": "wiki/sources/{slug}.md", "purpose": "..."},
    {"type": "Entity", "location": "wiki/entities/{name}.md", "purpose": "..."},
    {"type": "Concept", "location": "wiki/concepts/{name}.md", "purpose": "..."},
    {"type": "Comparison", "location": "wiki/comparisons/{a}-vs-{b}.md", "purpose": "..."},
    {"type": "Synthesis", "location": "wiki/synthesis/{topic}.md", "purpose": "..."},
    {"type": "Claim", "location": "wiki/claims/{slug}.md", "purpose": "..."},
    {"type": "Query", "location": "wiki/Query: {Topic}.md", "purpose": "..."},
    {"type": "Overview", "location": "wiki/overview.md", "purpose": "..."}
  ],
  "custom_page_types": [
    {"type": "Model", "location": "wiki/models/{name}.md", "purpose": "ML model description"}
  ],
  "relation_types": ["is_a", "uses", "related_to", "contradicts", "supports", "replaces", "optimizes", "extends"],
  "page_conventions": {
    "naming": {
      "language": "English",
      "format": "Title Case with spaces",
      "max_length": 80,
      "avoid_chars": ["&", "/", "#", "?"],
      "slug_format": "hyphens-for-paths"
    },
    "frontmatter": {
      "required": ["title", "type", "created", "sources"],
      "optional": ["updated", "tags"]
    },
    "wikilink_syntax": {
      "basic": "[[Page Name]]",
      "section": "[[Page Name#Section]]",
      "alias": "[[Page Name|Display Text]]"
    },
    "citation_format": {
      "page_level": "## Sources\n- [Source: Title](raw/filename)",
      "inline": "[Source](raw/filename)"
    }
  },
  "page_templates": {
    "Claim": ["## Claim", "## Supporting Evidence", "## Contradicting Evidence"],
    "Entity": ["## Description", "## Sources", "## Knowledge Graph Relations"],
    "Source": ["## Summary", "## Key Facts", "## Sources"],
    "Concept": ["## Summary", "## Details", "## Sources"]
  },
  "special_pages": {
    "index.md": "Auto-updated content catalog. Do NOT edit manually.",
    "log.md": "Append-only chronological record.",
    "overview.md": "Top-level synthesis. Revise as understanding deepens."
  },
  "workflows": {
    "ingest": ["Read wiki.md", "Create source summary", "Create entity/concept pages", "Add wikilinks", "Cite sources", "Write graph relations", "Log operation"],
    "query": ["Search for pages", "Read full content", "Check sink", "Synthesize answer", "Save via wiki_synthesize"],
    "lint": ["Run health check", "Fix broken links", "Connect orphans", "Check sink status", "Review recommendations"]
  },
  "query_conventions": {
    "naming": "Query: {Topic} (first 50 chars, title-cased)",
    "date_suffix": "Query: {Topic} (YYYY-MM-DD) for similar queries",
    "sink_location": "wiki/.sink/Query: Topic.sink.md"
  },
  "claim_statuses": ["supported", "contested", "unverified"]
}
```

### SQLite 缓存表

```sql
CREATE TABLE IF NOT EXISTS schema_cache (
    schema_hash TEXT PRIMARY KEY,
    schema_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lint_cache (
    id INTEGER PRIMARY KEY,
    schema_hash TEXT NOT NULL,
    index_hash TEXT NOT NULL,
    source_mtime REAL NOT NULL,
    issues_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_analysis (
    source_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    analyzed_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    analysis_result TEXT,
    status TEXT DEFAULT 'analyzed'
);
```

### 缓存失效逻辑

```python
def _is_lint_cache_valid(self) -> bool:
    cached = self._get_lint_cache()
    if not cached:
        return False
    
    # 1. wiki.md 内容变了 → 失效
    current_schema_hash = self._compute_schema_hash()
    if cached['schema_hash'] != current_schema_hash:
        return False
    
    # 2. index.md 内容变了 → 失效
    current_index_hash = self._compute_index_hash()
    if cached['index_hash'] != current_index_hash:
        return False
    
    # 3. 有新 source 文件 → 失效
    latest_source_mtime = self._get_latest_source_mtime()
    if latest_source_mtime > cached['source_mtime']:
        return False
    
    return True
```

---

## Lint Gap 检测上下文

### 完整上下文示例

```
=== WIKI SCHEMA (structured) ===
{
  "standard_page_types": [...],
  "custom_page_types": [...],
  "relation_types": [...],
  "page_conventions": {...}
}

=== EXISTING PAGES (42 total) ===
  - entities/NVIDIA
  - entities/Apple
  - concepts/Risk Parity
  ...

=== SOURCE FILES ===
  - raw/nvidia-blackwell.md [analyzed]
    Entities: NVIDIA, Blackwell, GPU, TSMC
  - raw/risk-parity-study.md [analyzed]
    Entities: Risk Parity, Portfolio
  - raw/macro-trends-2024.md [not analyzed]

=== ORPHAN CONCEPTS (in knowledge graph but no wiki page) ===
["Transformer", "Attention Mechanism", "KV Cache"]
```

### Lint Gap Detection Prompt

```yaml
name: lint_gap_detection
description: "Detect gaps between wiki schema and current state."

system: |
  You are a wiki gap detector. Based on the schema and current state,
  identify gaps that need to be filled.
  
  IMPORTANT: The context below gives you a high-level view. If you need
  more details about specific pages or sources, you should recommend
  the user to:
  - Search: wiki_search("topic")
  - Read: wiki_read_page("Page Name")
  - Read source: Check raw/filename.md
  
  DETECTION TASKS:
  1. MISSING CUSTOM PAGES - check custom_page_types, find missing pages
  2. ORPHAN CONCEPTS - concepts in relations but no pages exist
  3. MISSING CROSS-REFERENCES - pages mention concepts without wikilinks
  4. SCHEMA NON-COMPLIANCE - pages not following conventions
  
  OUTPUT FORMAT:
  Return JSON array:
  [
    {"type": "missing_custom_page", "page_type": "Model", 
     "page_name": "BERT", "source": "raw/article.md", 
     "purpose": "ML model description"},
    {"type": "orphan_concept", "concept": "Transformer", 
     "suggested_type": "Concept"},
    {"type": "missing_cross_ref", "concept": "GPU", 
     "mentioned_in": ["entities/NVIDIA"]},
    {"type": "non_compliant_page", "page": "entities/Apple", 
     "issues": ["missing sources section"]}
  ]

user: |
  {{ full_context }}
  
  Identify all gaps between the schema and current state.
```

---

## 降级策略

### LLM 调用失败时

```python
def _llm_detect_gaps(self) -> list[dict]:
    try:
        # 检查缓存
        if self._is_lint_cache_valid():
            return self._get_cached_issues()
        
        # 调用 LLM
        context = self._build_lint_context()
        result = self._call_llm("lint_gap_detection", context)
        
        # 缓存结果
        self._cache_issues(result['gaps'])
        
        return result['gaps']
    
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        # 降级到基础检测
        return self._fallback_detect_gaps()

def _fallback_detect_gaps(self) -> list[dict]:
    """Basic gap detection without LLM."""
    gaps = []
    
    # 1. Orphan concepts (from relation engine)
    engine = self.get_relation_engine()
    for concept in engine.find_orphan_concepts():
        gaps.append({
            "type": "orphan_concept",
            "concept": concept,
            "note": "Detected without LLM analysis",
        })
    
    # 2. Missing cross-refs (basic heuristic)
    gaps.extend(self._detect_missing_cross_refs_basic())
    
    return gaps
```

---

## Token 消耗估算

| 阶段 | 输入 tokens | 输出 tokens | 估算成本 (GPT-4o) |
|------|------------|------------|------------------|
| extract_schema | 1000-5000 | 500-1500 | $0.005-0.02 |
| lint_gap_detection | 850-1000 | 500-1500 | $0.005-0.02 |
| **首次总计** | **1850-6000** | **1000-3000** | **$0.01-0.04** |
| **后续 (缓存命中)** | **0** | **0** | **$0** |

---

## 文件变更清单

| # | 文件 | 操作 | 变更说明 |
|---|------|------|---------|
| 1 | `src/llmwikify/core/wiki.py` | **修改** | • 新增 `_compute_schema_hash()`<br>• 新增 `_cache_schema()` / `_get_cached_schema()`<br>• 新增 `_llm_extract_schema()`<br>• 新增 `_llm_detect_gaps()`<br>• 新增 `_fallback_detect_gaps()`<br>• 新增 `_build_lint_context()`<br>• 新增 `_summarize_sources()`<br>• 修改 `lint()` 增加 `mode`, `limit`, `force` 参数<br>• 保留 `_detect_broken_links()` 和 `_detect_orphan_pages()` |
| 2 | `src/llmwikify/core/index.py` | **修改** | • 新增 `schema_cache`, `lint_cache`, `source_analysis` 表创建 |
| 3 | `src/llmwikify/prompts/_defaults/extract_schema.yaml` | **新增** | LLM schema 提取 prompt |
| 4 | `src/llmwikify/prompts/_defaults/lint_gap_detection.yaml` | **新增** | LLM gap 检测 prompt |
| 5 | `src/llmwikify/mcp/server.py` | **修改** | `wiki_lint()` 增加 `mode`, `limit`, `force` 参数 |
| 6 | `src/llmwikify/cli/commands.py` | **修改** | `wiki lint` 增加 `--fix`, `--all`, `--limit N`, `--force` 标志 |
| 7 | `tests/test_lint_v2.py` | **新增** | Lint v2 测试 |

---

## CLI 设计

```bash
# 只检测
llmwikify wiki lint

# 检测 + 自动修复（默认限制 10 个）
llmwikify wiki lint --fix

# 检测 + 修复所有（无限制）
llmwikify wiki lint --fix --all

# 检测 + 修复前 20 个
llmwikify wiki lint --fix --limit 20

# 强制全量扫描（忽略缓存）
llmwikify wiki lint --fix --force
```

### 输出示例

```
=== Wiki Lint (mode: check) ===
Total pages: 42
Issues found: 15

Schema hash: abc123def456 (cached)

Issues:
  ❌ [missing_custom_page] models/BERT: Source mentions 'BERT' which should have a 'Model' page
  ❌ [orphan_concept] Transformer: In relations but no page exists
  ❌ [missing_cross_ref] GPU: Mentioned in 3 pages without wikilinks
  ❌ [non_compliant_page] entities/Apple: Missing sources section

Run with --fix to automatically repair these issues.
```

---

## 实施顺序

### Phase 1: 基础检测 + Schema 缓存（核心功能）

1. 新增 `_compute_schema_hash()` — SHA-256 hash
2. 新增 `_llm_extract_schema()` — LLM 提取 schema
3. 新增 `_cache_schema()` / `_get_cached_schema()` — 缓存管理
4. 新增 `_build_lint_context()` — 组合上下文
5. 新增 `_llm_detect_gaps()` — LLM gap 检测
6. 新增 `_fallback_detect_gaps()` — 降级检测
7. 修改 `lint()` 增加 `mode`, `limit`, `force` 参数
8. 保留 `_detect_broken_links()` 和 `_detect_orphan_pages()`（代码实现）

### Phase 2: 修复功能（后续）

9. 新增 `_llm_generate_repairs()` — LLM 生成修复操作
10. 新增 `_execute_repairs()` — 执行增量修复
11. 新增 `_merge_content()` — 智能合并
12. 新增 `source_analysis` 表 + 增量扫描

### Phase 3: Ingest 集成（后续）

13. 修改 `ingest_source()` 增加 `auto_analyze` + `lint_hint`
14. 更新 `ingest_instructions.yaml`
15. 更新 `wiki_schema.yaml` 工作流

---

## 与原则文档的符合度

| 原则原文 | 新设计 | 符合度 |
|---------|--------|--------|
| "The LLM reads it, extracts the key information, and integrates it into the existing wiki" | `lint(mode="fix")` 自动检测并修复 gaps | ✅ |
| "A single source might touch 10-15 wiki pages" | lint 检测自定义类型缺失页面，覆盖所有 source | ✅ |
| "Lint. Periodically, ask the LLM to health-check the wiki. Look for: contradictions, stale claims, orphan pages..." | `lint(mode="check")` + `lint(mode="fix")` | ✅ |
| "The LLM is good at suggesting new questions to investigate" | LLM gap detection 自动发现缺失页面 | ✅ |
| "You never (or rarely) write the wiki yourself — the LLM writes and maintains all of it" | LLM 主导维护，agent 通过工具执行 | ✅ |

---

## 待决策事项

| 事项 | 状态 | 说明 |
|------|------|------|
| `--self-create` 模式 | 暂不保留 | 后续再做调整 |
| Web Search 集成 | 暂不加 | 后续添加 |
| Source 扫描策略 | C: 混合 | 增量为主，`--all` 强制全量 |
| LLM 修复内容来源 | C: 混合 | 优先 analysis，不够时读 source |
| 性能限制 | B: 默认限制 10 个 | `--all` 或 `--limit N` 可选 |
| Schema 变更通知 | C: Hash + Prompt | 双重保障 |
| 缓存存储 | SQLite | 现有数据库 |
| index.md 包含 | 否 | 引导 LLM 自主查找 |
| wiki.md 全文包含 | 否 | extract_schema 时 LLM 已读过 |
| source 摘要详细程度 | D: 动态 | <20 显示 entities, >20 只显示状态 |

---

## 最终实施决策（2026-04-15 更新）

### 方案选择：直接传递 wiki.md 全文（方案 A）

**放弃 Schema 缓存层**，改为让 LLM 直接读取 wiki.md 全文 + wiki 状态摘要，一次性检测 gaps。

### 决策依据

| 维度 | 方案 A（直接传递） | 方案 B（Schema 缓存） |
|------|-------------------|---------------------|
| 代码行数 | ~80 行新增 | ~250 行新增 |
| 缓存表 | 0 个 | 3 个 |
| Prompt 文件 | 1 个 | 2 个 |
| 调试复杂度 | 低 | 高 |
| 维护成本/年 | ~$70 | ~$530+ |
| Token/次 | ~4500-5000 | ~900（缓存命中 0） |
| 成本/次 | ~$0.02 | ~$0.005 |

**关键判断**：wiki.md 是约定文档，几乎不可能超过 50KB。方案 B 的"省钱"被隐性维护成本完全抵消。

### 实施计划

| Step | 文件 | 操作 |
|------|------|------|
| 1 | `src/llmwikify/prompts/_defaults/direct_lint.yaml` | 新增 |
| 2 | `src/llmwikify/core/wiki.py` | 修改：新增 `_build_lint_context`, `_llm_detect_gaps`, `_fallback_detect_gaps`；修改 `lint()` 签名 |
| 3 | `src/llmwikify/cli/commands.py` | 修改：lint 增加 `--mode`, `--limit`, `--force` |
| 4 | `src/llmwikify/mcp/server.py` | 修改：`wiki_lint` 增加 `mode`, `limit`, `force` |
| 5 | `tests/test_direct_lint.py` | 新增 |

### 新签名

```python
def lint(self, mode="check", limit=10, force=False, generate_investigations=False) -> dict
```
