# llmwikify v0.21.0–v0.23.0 实施规划

> 基于 graphify 项目调研结果与 LLM_WIKI_PRINCIPLES.md 原则对齐分析
>
> 创建日期: 2026-04-12
> 状态: 待实施

---

## 当前基线

| 指标 | 值 |
|------|-----|
| 版本 | 0.20.0 |
| 测试数 | 462 passing, 21 new (P0-P3 fixes) |
| 核心能力 | ingest / query / lint / search / MCP / sink / synthesize / batch --smart |
| P0-P3 问题 | ✅ 全部修复 |
| 原则对齐 | ✅ 核心原则全部覆盖 |

---

## 版本路线图

```
v0.21.0  Watch 模式 + Git Hook
v0.22.0  关系引擎 (LLM 自动关系发现 + SQLite)
v0.23.0  图谱可视化 + 社区检测 + 图查询 + Surprise Score 报告
```

### 依赖关系

```
v0.21.0 (独立)              v0.22.0 (独立)
└── Watch 模式              └── 关系引擎
    ├── watcher.py              ├── relation_engine.py
    ├── CLI: watch              ├── relations 表
    ├── Git hook                ├── Prompt 变更
    └── 测试 (15)               └── CLI: graph-query
                                    └── 测试 (20)

                                    ↓ 依赖

                                v0.23.0 (依赖 v0.22.0)
                                └── 图谱可视化 + 社区检测 + 图查询
                                    ├── graph_export.py
                                    ├── Surprise Score 算法
                                    ├── CLI: export-graph / community-detect / report
                                    └── 测试 (15)
```

---

## v0.21.0 — Watch 模式

### 核心特性

监听 `raw/` 目录的文件系统事件，新文件到达时自动提示或触发 ingest。

```bash
llmwikify watch [raw/] [options]
  --auto-ingest       新文件自动触发 ingest (默认: 仅提示)
  --smart             自动 ingest 时启用 LLM 处理 (需 --auto-ingest)
  --debounce SECS     事件防抖秒数 (默认 2)
  --dry-run           仅打印事件，不执行任何操作
  --git-hook          安装/卸载 git post-commit hook
```

### 设计原则

| 决策 | 选择 | 原则依据 |
|------|------|---------|
| 默认行为 | 仅提示，不自动执行 | "stay involved" — 用户参与 ingest 过程 |
| 自动触发 | `--auto-ingest` 显式开启 | 用户控制权，不静默执行 |
| LLM 处理 | 需同时指定 `--smart` | 与 `ingest --smart` 行为一致 |
| 监听目录 | 默认 `raw/` | 三层架构: raw → wiki → schema |
| Git hook | 可选安装 | 不强制污染 git 配置 |

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llmwikify/core/watcher.py` | **新增** | FileSystemWatcher 类 |
| `src/llmwikify/cli/commands.py` | 修改 | 新增 `watch()` + `git_hook()` 方法 |
| `pyproject.toml` | 修改 | 新增 `[watch]` 可选依赖 |
| `tests/test_v021_watch.py` | **新增** | ~15 测试用例 |
| `README.md` | 修改 | 更新功能说明 |

### 依赖

```toml
[project.optional-dependencies]
watch = ["watchdog>=3.0.0"]
all = ["llmwikify[extractors,mcp,config,watch]"]
```

### Watcher 核心逻辑

```python
class FileSystemWatcher:
    """监听文件系统事件，根据配置提示或自动触发 ingest。"""
    
    def __init__(self, watch_dir, auto_ingest=False, smart=False, debounce=2):
        self.auto_ingest = auto_ingest
        self.smart = smart
        self.debounce = debounce
        self._debounce_timers = {}
    
    def on_created(self, event):
        if event.is_directory:
            return
        # 检测文件类型是否支持
        # 防抖处理
        # 根据 auto_ingest 决定: 打印提示 vs 自动调用 ingest_source
```

### Git Hook 逻辑

```bash
# .git/hooks/post-commit (安装时生成)
#!/bin/sh
llmwikify batch raw/ --smart --limit 0 2>/dev/null || true
```

### 测试用例 (15)

| # | 用例 |
|---|------|
| 1 | 监听器启动/停止 |
| 2 | 文件创建事件检测 |
| 3 | 文件修改事件检测 |
| 4 | 文件删除事件检测 |
| 5 | 目录忽略 |
| 6 | 防抖机制 (快速连续写入只触发一次) |
| 7 | 默认模式：仅打印提示 |
| 8 | `--auto-ingest`: 自动调用 ingest_source |
| 9 | `--auto-ingest --smart`: 自动 LLM 处理 |
| 10 | 不支持的文件类型被忽略 |
| 11 | `--dry-run` 模式 |
| 12 | git hook 安装 |
| 13 | git hook 卸载 |
| 14 | git hook 执行逻辑 |
| 15 | 多文件并发写入 |

---

## v0.22.0 — 关系引擎

### 核心特性

1. **LLM 自动关系发现** — ingest 时从 raw 源提取概念关系
2. **关系置信度标签** — `EXTRACTED` / `INFERRED` / `AMBIGUOUS`
3. **关系持久化** — SQLite relations 表
4. **关系查询接口** — neighbors / path / stats / context
5. **关系 Lint** — 矛盾检测 / 孤立概念

### 数据库 Schema

```sql
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 源概念（页面名或实体）
    target TEXT NOT NULL,           -- 目标概念
    relation TEXT NOT NULL,         -- 关系类型
    confidence TEXT NOT NULL CHECK(confidence IN ('EXTRACTED','INFERRED','AMBIGUOUS')),
    source_file TEXT,               -- 来源的 raw 文件
    context TEXT,                   -- 原文摘录/上下文
    wiki_pages TEXT,                -- 关联的 wiki 页面 (JSON array)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_relations_source ON relations(source);
CREATE INDEX idx_relations_target ON relations(target);
CREATE INDEX idx_relations_pair ON relations(source, target);
```

### 关系类型体系

| 类型 | 语义 | 示例 |
|------|------|------|
| `is_a` | 分类关系 | FlashAttention **is_a** Attention 优化 |
| `uses` | 依赖关系 | Attention **uses** Softmax |
| `related_to` | 松散关联 | Transformer **related_to** NLP |
| `contradicts` | 矛盾关系 | 论文A **contradicts** 论文B |
| `supports` | 支持关系 | 实验 **supports** 假设 |
| `replaces` | 替代关系 | FlashAttention **replaces** Standard Attention |
| `optimizes` | 优化关系 | KV Cache **optimizes** Inference |
| `extends` | 扩展关系 | LoRA **extends** 微调方法 |

### Ingest 流程变更

```
原始: extract() → LLM 生成 wiki pages → execute_operations()
新增: extract() → LLM 生成 wiki pages + relations → execute_operations() + write_relations()
```

### Prompt 变更

在 `generate_wiki_ops.yaml` 的 LLM 指令中增加关系提取指令:

```yaml
relation_extraction: |
  同时提取源文件中的概念关系。返回 JSON 数组:
  [
    {"source": "概念A", "target": "概念B", "relation": "uses", "confidence": "EXTRACTED"},
    ...
  ]
  confidence 规则:
  - EXTRACTED: 源文件直接陈述的关系
  - INFERRED: 通过上下文合理推断的关系
  - AMBIGUOUS: 不确定或需要人工审查的关系
```

### 新增 CLI 命令

```bash
llmwikify graph-query <subcommand> [args]

Subcommands:
  neighbors <concept>        列出概念的所有关系
  path <A> <B>               查找 A 到 B 的最短路径
  stats                      图谱统计 (节点数/边数/度数分布)
  context <id>               查看某关系的原始上下文
```

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llmwikify/core/relation_engine.py` | **新增** | RelationEngine 类 |
| `src/llmwikify/core/wiki.py` | 修改 | relations 表初始化、关系写入方法 |
| `prompts/_defaults/generate_wiki_ops.yaml` | 修改 | 增加关系提取指令 |
| `src/llmwikify/cli/commands.py` | 修改 | 新增 graph-query 子命令 |
| `tests/test_v022_relations.py` | **新增** | ~20 测试用例 |

### 关系使用场景

| 场景 | 说明 |
|------|------|
| **Ingest 时交叉引用** | LLM 提取关系 → 自动更新 wiki 页面链接 |
| **查询时图谱增强** | FTS5 + relations 联合搜索，回答更精准 |
| **Lint 矛盾检测** | 检测 `supports` vs `contradicts` 冲突 |
| **图谱可视化** | wikilink + relations 合并为 NetworkX 图 |
| **路径查询** | 查找两个概念之间的关联路径 |

### 测试用例 (20)

| # | 用例 |
|---|------|
| 1-3 | relations 表创建 / schema 验证 |
| 4-6 | 关系写入 (单条/批量/去重) |
| 7-9 | 邻居查询 (双向/单向/过滤置信度) |
| 10-12 | 路径查询 (有路径/无路径/最短路径) |
| 13-15 | 图谱统计 (节点数/边数/度数分布) |
| 16-17 | 矛盾关系检测 |
| 18-19 | 孤立概念检测 |
| 20 | ingest 时自动提取关系 |

---

## v0.23.0 — 图谱可视化 + 社区检测 + 图查询 + Surprise Score

### 核心特性

1. **图谱可视化导出** — HTML (交互式) / SVG / GraphML
2. **社区检测** — Leiden 算法 (默认) / Louvain (备选)
3. **Surprise Score 报告** — 多维度可解释的意外连接分析
4. **图查询增强** — explain / find-similar

### 新增 CLI 命令

```bash
llmwikify export-graph [options]
  --format html|svg|graphml    输出格式 (默认 html)
  --output graph.html          输出路径
  --min-degree 2               过滤低度数节点
  --confidence EXTRACTED       最小置信度过滤

llmwikify community-detect [options]
  --algorithm leiden|louvain   检测算法 (默认 leiden)
  --resolution 1.0             分辨率参数，控制社区粒度 (默认 1.0)
  --json                       输出 JSON 格式 (供程序消费)
  --dry-run                    仅打印统计，不生成报告

llmwikify report [options]
  --top 10                     显示前 N 个意外连接
```

**不生成 graph_index.md** — 社区检测是按需分析工具，输出到 stdout/JSON/HTML，不写入 wiki 目录。符合 "The LLM writes and maintains all of it" 原则。

### Surprise Score 算法

借鉴 graphify 核心创新，为 llmwikify 定制的多维度意外连接评分:

```python
def _surprise_score(self, G, source, target, relation_data, communities):
    """多维度意外连接评分，回答"为什么这个连接值得注意？"
    
    评分维度:
    1. 置信度权重: AMBIGUOUS(3) > INFERRED(2) > EXTRACTED(1)
    2. 跨来源类型: paper↔analysis, code↔paper 等 (+2)
    3. 跨知识域: 不同域名/不同子目录 (+2)
    4. 跨社区: Leiden 检测的结构距离远 (+1)
    5. 边缘→核心: 低度节点连接高度节点 (+1)
    """
    score = 0
    reasons = []
    
    # 1. 置信度权重
    conf = relation_data.get("confidence", "EXTRACTED")
    conf_bonus = {"AMBIGUOUS": 3, "INFERRED": 2, "EXTRACTED": 1}.get(conf, 1)
    score += conf_bonus
    if conf in ("AMBIGUOUS", "INFERRED"):
        reasons.append(f"{conf.lower()} 关系 - 非源文件直接陈述")
    
    # 2. 跨来源类型
    src_type = relation_data.get("source_type_a")
    tgt_type = relation_data.get("source_type_b")
    if src_type and tgt_type and src_type != tgt_type:
        score += 2
        reasons.append(f"跨来源类型 ({src_type} ↔ {tgt_type})")
    
    # 3. 跨知识域
    domain_a = relation_data.get("domain_a", "")
    domain_b = relation_data.get("domain_b", "")
    if domain_a and domain_b and domain_a != domain_b:
        score += 2
        reasons.append(f"连接不同知识域")
    
    # 4. 跨社区
    comm_a = communities.get(source)
    comm_b = communities.get(target)
    if comm_a is not None and comm_b is not None and comm_a != comm_b:
        score += 1
        reasons.append(f"桥接不同社区")
    
    # 5. 边缘→核心
    deg_a = G.degree(source)
    deg_b = G.degree(target)
    if min(deg_a, deg_b) <= 2 and max(deg_a, deg_b) >= 5:
        score += 1
        peripheral = source if deg_a <= 2 else target
        hub = target if deg_a <= 2 else source
        reasons.append(f"边缘概念「{peripheral}」意外连接核心概念「{hub}」")
    
    return score, reasons
```

### 报告输出示例

```markdown
# 意外连接报告

## 概览
- 总页面数: 47
- 总关系数: 123
- 检测到社区数: 5
- 模块度: 0.62 (0-1，越高社区划分越清晰)

## Top 10 最意外的连接

### 1. 意外分数: 7
**FlashAttention** → **GPU Memory Bottleneck**
- 关系: optimizes
- 置信度: AMBIGUOUS (+3)
- 跨来源类型: paper ↔ analysis (+2)
- 桥接不同社区 (+1)
- 边缘概念连接核心概念 (+1)

### 2. 意外分数: 6
**KV Cache** → **PageAttention**
- 关系: related_to
- 置信度: INFERRED (+2)
- 跨来源类型: paper ↔ code (+2)
- 桥接不同社区 (+1)
- 边缘概念连接核心概念 (+1)
```

### 社区检测空图处理

| 场景 | 判断条件 | 行为 |
|------|---------|------|
| 空图 | 节点数 = 0 | 返回空结果 + warning |
| 孤立节点 | 边数 = 0，节点 > 0 | 每个节点自成社区，modularity=0 |
| 单节点 | 节点数 = 1 | 1 个社区，modularity=0 |
| 完全连通 | 所有节点在一个社区 | 建议调高 resolution 参数 |
| 碎片化 | 社区数 > 节点数/2 | 建议调低 resolution 参数 |

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llmwikify/core/graph_export.py` | **新增** | 图谱导出功能 (HTML/SVG/GraphML) |
| `src/llmwikify/cli/commands.py` | 修改 | 新增 export-graph / community-detect / report 命令 |
| `pyproject.toml` | 修改 | 新增 `[graph]` 可选依赖 |
| `tests/test_v023_graph.py` | **新增** | ~15 测试用例 |
| `README.md` | 修改 | 更新功能说明 |

### 依赖

```toml
[project.optional-dependencies]
graph = [
    "networkx>=3.0",
    "pyvis>=0.3.0",
    "python-louvain>=0.16",
]
all = ["llmwikify[extractors,mcp,config,watch,graph]"]
```

### 测试用例 (15)

| # | 用例 |
|---|------|
| 1-4 | 图谱构建 (wikilink + relations 合并) |
| 5-7 | HTML/SVG/GraphML 导出 |
| 8-10 | 社区检测 (Leiden/Louvain/空图处理) |
| 11-13 | Surprise Score 评分与排序 |
| 14-15 | 报告生成 |

---

## 预期测试总数

| 阶段 | 新增 | 累计 |
|------|------|------|
| 当前基线 | 462 | 462 |
| v0.21.0 | +15 | 477 |
| v0.22.0 | +20 | 497 |
| v0.23.0 | +15 | 512 |

---

## 与 LLM Wiki Principles 的对齐

| 原则原文 | 实现方式 | 状态 |
|---------|---------|------|
| "incrementally builds and maintains a persistent wiki" | Watch 模式监听 raw/ 自动触发 ingest | ✅ |
| "The cross-references are already there" | 关系引擎自动提取概念关系 | ✅ |
| "noting where new data contradicts old claims" | 矛盾关系检测 + AMBIGUOUS 标签 | ✅ |
| "Obsidian's graph view is the best way to see the shape of your wiki" | NetworkX + pyvis 导出交互式 HTML | ✅ |
| "Organized by category (entities, concepts, sources, etc.)" | Leiden 社区检测 (按需运行) | ✅ |
| "The LLM is good at suggesting new questions to investigate" | Surprise Score 意外连接报告 | ✅ |
| "stay involved — I read the summaries, check the updates" | Watch 默认仅提示，`--auto-ingest` 显式开启 | ✅ |
| "The wiki is just a git repo" | Git post-commit hook | ✅ |
| "The LLM writes and maintains all of it" | 不生成 graph_index.md，社区检测输出到 stdout/JSON | ✅ |
| "pick what's useful, ignore what isn't" | 所有新功能都是可选依赖 | ✅ |
| "good answers can be filed back into the wiki as new pages" | Query Sink 机制 (已有) | ✅ |
| "A search engine over the wiki pages" | SQLite FTS5 (已有) + 图谱增强搜索 | ✅ |
| "health-check the wiki" | lint + 关系矛盾检测 (已有+新增) | ✅ |

---

## 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Watch 默认行为 | 仅提示 | 尊重 "stay involved" 原则 |
| 社区检测算法 | Leiden (默认) + Louvain (备选) | Leiden 保证社区连通性，质量优先 |
| 社区命名 | 算法 ID (无 LLM 命名) | 降低成本，用户可自行理解 |
| 社区结果存储 | **不生成 graph_index.md** | 无独特消费者，算法不应直接写入 wiki 目录 |
| Surprise Score | 借鉴 graphify 并定制 | 多维度可解释的意外连接度量 |
| 图谱可视化 | HTML/SVG/GraphML | 人类看图比读 markdown 更直观 |
| 关系存储 | SQLite relations 表 | 结构化查询，与 wikilink 互补 |
| graph_index.md | **不生成** | 三方消费者 (人类/LLM/工具) 都不需要 markdown 格式 |

---

## 从 graphify 借鉴的内容

| graphify 特性 | 借鉴方式 | llmwikify 差异 |
|--------------|---------|---------------|
| Watch 模式 + git hook | 直接采用 | 默认仅提示，不自动执行 |
| 关系提取 + 置信度 | 直接采用 | 关系类型体系自定义 |
| Surprise Score 算法 | 借鉴核心思想，5 维定制 | 去除 AST 相关维度，增加跨知识域 |
| 社区检测 (Leiden) | 直接采用 | 不生成独立报告文件 |
| 图谱可视化 (HTML) | 直接采用 | 使用 pyvis 而非 vis.js 手写 |
| 语义缓存 | 暂不实现 | v0.23.0 之后考虑 |

---

## 实施检查清单

### v0.21.0
- [ ] 创建 `src/llmwikify/core/watcher.py`
- [ ] 修改 `src/llmwikify/cli/commands.py` 添加 watch/git-hook 命令
- [ ] 修改 `pyproject.toml` 添加 `[watch]` 依赖
- [ ] 创建 `tests/test_v021_watch.py` (15 用例)
- [ ] 更新 `README.md`

### v0.22.0
- [ ] 创建 `src/llmwikify/core/relation_engine.py`
- [ ] 修改 `src/llmwikify/core/wiki.py` 添加 relations 表
- [ ] 修改 `prompts/_defaults/generate_wiki_ops.yaml` 增加关系提取指令
- [ ] 修改 `src/llmwikify/cli/commands.py` 添加 graph-query 子命令
- [ ] 创建 `tests/test_v022_relations.py` (20 用例)

### v0.23.0
- [ ] 创建 `src/llmwikify/core/graph_export.py`
- [ ] 修改 `src/llmwikify/cli/commands.py` 添加 export-graph / community-detect / report 命令
- [ ] 修改 `pyproject.toml` 添加 `[graph]` 依赖
- [ ] 创建 `tests/test_v023_graph.py` (15 用例)
- [ ] 更新 `README.md`
