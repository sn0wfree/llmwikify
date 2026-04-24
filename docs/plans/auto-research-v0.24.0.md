# llmwikify v0.31.0 自动研究功能设计

> **核心架构**：四模块协同工作，形成「计划 → 搜索发现 → 分析研究 → 迭代循环」的完整研究闭环
>
> 基于 Deep Research 技能设计理念
> 参考 Perplexity / OpenAI Research 交互模式
>
> 创建日期: 2026-04-23
> 最后更新: 2026-04-23
> 状态: 实施中 (Phase 1)
> 前置依赖: v0.22.0 (关系引擎)

---

## 一、功能定位与边界

### 1.1 核心价值

| 价值维度 | 说明 | 量化预期 |
|---------|------|---------|
| **降低搜索摩擦** | 用户知道有知识缺口，但懒得手动搜索 → 系统预筛选 → 一键确认 | 知识积累速度提升 **2-3x** |
| **研究报告闭环** | 搜索结果 → 结构化报告 → 写入 wiki → 成为知识库一部分 | 研究成果永久可追溯 |
| **知识网络自完善** | 红链、孤儿概念、断层信息 → 自动发现补全建议 | Wiki 完整性提升 **40-60%** |
| **符合 Lint 流程精神** | 原则 P41 明确支持: "data gaps that could be filled with a web search" | 对原则的自然延伸 |
| **降低维护负担** | P66: "人类放弃 wiki 是因为维护负担增长快于价值" | 这正是 LLM 擅长的苦力工作 |

### 1.3 关键设计决策确认

| 决策点 | 选择 | 说明 |
|--------|------|------|
| **命令体系** | `find` (P1) + `study` (P2) + `research` (P2) | 三阶段拆分，职责分明 |
| **计划模块** | `plan` 内部模块，不单独暴露 CLI | 智能大脑：任务拆解 + 终止判断 |
| **搜索引擎** | SearXNG + arXiv 双引擎 | 网页 + 学术论文全覆盖 |
| **Ingest 模式** | Phase 1 输出命令列表，不自动执行 | 保留用户控制权，避免副作用 |
| **多轮迭代** | Phase 2 实现 `plan` → `research-search` → `research-analyze` 循环 | 信息饱和后自动终止 |
| **报告生成方式** | Phase 1 模板 + Phase 2 LLM 增强 | 先做结构化模板，后续加入 LLM 分析 |
| **存储位置** | `wiki/Research/` 用户可见 + `.research/` 隐藏 | 分离产物与内部状态 |
| **审计日志** | log.md 摘要 + Research/ 完整报告 | 双重记录 |

### 1.2 绝对红线（永远不能突破）

| 红线 | 原则依据 | 违反后果 |
|------|---------|---------|
| ❌ **不能自动写入 `raw/` 目录** | P29: Raw sources 是用户 curated 的真理来源 | 破坏三层架构 |
| ❌ **不能静默后台收集** | P15: "stay involved" — 用户必须知情 | 失去用户信任 |
| ❌ **不能自动创建/修改 wiki 页面** | 与 Dream Editor 提案机制一致 | 破坏控制权 |
| ❌ **不能无限广度搜索** | 每次搜索必须与当前 wiki 语义锚定 | 信息噪音 + 主题跑偏 |

### 1.4 与现有原则的对齐矩阵

| 原则原文 | 实现方式 | 状态 |
|---------|---------|------|
| "incrementally builds and maintains a persistent wiki" | 自动发现知识缺口 + 搜索建议 | ✅ |
| "The cross-references are already there" | 红链检测 → 自动研究建议 | ✅ |
| "noting where new data contradicts old claims" | 搜索结果可信度评分 + 矛盾标记 | ✅ |
| "data gaps that could be filled with a web search" (P41) | lint 集成研究建议 | ✅ ✨ (直接引用) |
| "stay involved — I read the summaries, check the updates" | 提案式 + 确认流程，不自动执行 | ✅ |
| "The LLM writes and maintains all of it" | 搜索候选由系统提供，ingest 由用户确认 | ✅ |
| "The human's job is to curate sources" | 帮助找到要 curate 的来源，不替代 curation | ✅ |

---

## 二、四模块协同架构（最终版）

```
                    llmwikify research "topic"
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  🧠 Plan (内部模块 - 智能大脑)                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ 任务拆解     │→│ 关键词生成   │→│ 终止判断     │              │
│  │ 3-5个维度   │  │ 每轮关键词   │  │ 5种终止条件  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🔍 Research-Search (Phase 1 - 纯搜索)                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ SearXNG     │  │ arXiv API   │→│ 去重排序     │              │
│  │ 网页搜索     │  │ 论文搜索     │  │ 质量评分     │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  📊 Research-Analyze (Phase 2 - LLM 分析)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ 信息整合     │→│ 缺口识别     │→│ 价值评估     │              │
│  │ 交叉验证     │  │ 矛盾点       │  │ 边际价值     │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  继续搜索?   │
                    └──────┬──────┘
                           │
                      ─────┴─────
                      │          │
                      ▼          ▼
                    下一轮     ┌─────────────────┐
                     循环      │  生成最终报告   │
                              └────────┬────────┘
                                       │
                                       ▼
                               📄 wiki/Research/
                               📝 log.md 记录
```

---

## 三、研究报告格式设计

### 3.1 报告模板（Phase 1）

```markdown
# 研究报告：{主题}

> 研究时间：{YYYY-MM-DD HH:MM}  
> 使用关键词：`{关键词1}`、`{关键词2}`、`{关键词3}`  
> 总结果数：{N} | 高可信度来源：{M}

---

## 摘要

（Phase 2 由 LLM 生成此部分）

---

## 高可信度来源（可信度 ≥ 0.8）

| # | 评分 | 标题 | 域名 | 发布时间 |
|---|------|------|------|---------|
| 1 | ⭐⭐⭐⭐⭐ | [{标题}]({URL}) | {domain} | {date} |
| 2 | ⭐⭐⭐⭐ | [{标题}]({URL}) | {domain} | {date} |

---

## 全部候选来源

### 1. {标题}
- **URL**: {url}
- **域名**: {domain}
- **可信度评分**: {score} ({reasons})
- **发布时间**: {date}
- **摘要**: 
  > {snippet}

---

## 后续建议

- 可使用 `ingest {url}` 命令摄入单个来源
- 可使用 `research --depth "深度关键词"` 进行进一步研究

---

*本报告由 llmwikify 自动研究功能生成*
```

### 3.2 文件命名规范

```
wiki/Research/
  └── YYYY-MM-DD-{slugified-topic}.md

示例：
wiki/Research/
  ├── 2026-04-23-Deep-Research-AI-Research-Skills.md
  └── 2026-04-24-SearXNG-Self-hosted-Search-Engine.md
```

---

## 四、命令体系设计

### 4.1 职责边界矩阵

| 命令 | 阶段 | 暴露 | LLM | 核心角色 | 核心职责 |
|-----|------|------|-----|---------|---------|
| **plan** (内部) | Phase 2 | ❌ 内部 | ✅ 有 | 🧠 大脑 / 协调器 | 任务拆解 + 关键词生成 + 终止判断 + 报告整合 |
| **research-search** | Phase 1 | ✅ CLI | ❌ 无 | 🔍 搜索器 | 双引擎并行搜索 + 去重排序 + 质量评分 |
| **research-analyze** | Phase 2 | ✅ CLI | ✅ 有 | 📊 分析器 | 信息整合 + 缺口识别 + 矛盾检测 + 价值评估 |
| **research** | Phase 2 | ✅ CLI | ✅ 有 | 🔄 执行器 | 主循环：`plan` → `research-search` → `research-analyze` 多轮迭代 |

### 4.2 完整控制流

```
第 1 轮: plan → 任务拆解 + 生成关键词
    ↓
第 1 轮: research-search → 双引擎搜索，收集来源
    ↓
第 1 轮: research-analyze → 分析来源，识别缺口，评估价值
    ↓
第 2 轮: plan → 评估覆盖度，判断是否继续
    ├─ 继续 → 生成下一轮关键词
    └─ 完成 → 生成最终报告

终止条件:
  ✓ 信息饱和（连续两轮价值 < 20%）
  ✓ 轮次上限（默认 5 轮）
  ✓ 价值过低（单轮价值 < 10%）
  ✓ 用户主动终止
  ✓ 任务已完成（所有维度覆盖 ≥ 80%）
```

---

## 五、详细功能设计

### 功能 1：research-search 命令 - 外部搜索资料（Phase 1）

#### CLI 接口
```bash
llmwikify research-search <topic> [options]

Options:
  --depth quick|standard|deep    搜索深度 (控制结果数量)
  --arxiv-only                    只搜索 arXiv 论文
  --no-arxiv                      只搜索网页，不搜索 arXiv
  --json                          仅输出 JSON（跳过交互）
  --save                          自动保存报告到 wiki/Research/
  --no-cache                      强制刷新缓存
```

#### arXiv ID 精确查询
```bash
llmwikify research-search 2401.12345              # 通过 arXiv ID 直接定位论文
llmwikify research-search arXiv:2401.12345        # 带前缀格式也支持
```

#### 交互流程
```
$ llmwikify research-search "transformer attention"

🔍 SearXNG 搜索中... [████████░░░░░░░░] 12/15
🔍 arXiv 搜索中...    [████████████████] 8/10
✅ 找到 20 个结果 → 去重后 18 个 → 排序后显示前 15

📋 搜索结果：
┌─────┬────────┬────────────────────────────────────┬─────────┬────────────┐
│  #  │  评分  │  标题                               │  类型    │  发布时间   │
├─────┼────────┼────────────────────────────────────┼─────────┼────────────┤
│  1  │  0.92  │  Attention Is All You Need         │ 📄 arXiv │ 2017-06-12 │
│  2  │  0.87  │  Transformer Architecture Overview │ 🌐 Web   │ 2024-01-15 │
│ ... │  ...   │  ...                               │ ...     │ ...        │
└─────┴────────┴────────────────────────────────────┴─────────┴────────────┘

📝 高可信度来源建议 Ingest (共 5 个，评分 ≥ 0.8):
  llmwikify ingest https://arxiv.org/abs/1706.03762
  llmwikify ingest https://github.com/...
  llmwikify ingest https://...
  llmwikify ingest https://...
  llmwikify ingest https://...

下一步操作：
  [S] 保存报告到 wiki/Research/
  [V] 查看完整报告 (Markdown)
  [Q] 退出

? 请选择操作: _
```

### 功能 2：research-analyze 命令 - 深度分析（Phase 2）

```bash
llmwikify research-analyze <sources.json>             # 分析来源列表
llmwikify research-analyze --from-report <path>       # 从已有报告继续分析
```

### 功能 3：research 命令 - 完整研究（Phase 2，主命令）

```bash
llmwikify research <topic> [options]

Options:
  --max-rounds N                  最大搜索轮次 (默认: 5)
  --auto / --interactive          全自动运行 / 每轮需确认 (默认: --auto)
  --no-cache                      强制刷新缓存
  --list                          列出所有研究会话
  --continue <session-id>         继续之前的研究
```

---

### 功能 2：来源可信度评分系统

| 可信度 | 默认处理 | 显示样式 |
|-------|---------|---------|
| ≥ 0.8 | 默认选中 | ✨ 高亮 + 绿色 |
| 0.5 - 0.8 | 默认未选中 | 正常显示 |
| < 0.5 | 默认隐藏 | 🚫 灰色 + 折叠 |

#### 评分因素
| 因素 | 权重范围 | 说明 |
|------|---------|------|
| 域名类型 | +0.2 ~ -0.5 | 学术 > 官方 > 博客 > 论坛 > 垃圾站 |
| 内容类型 | +0.1 ~ -0.2 | 论文 > 文档 > 新闻 > 博客 > 论坛 |
| 作者权威性 | +0.1 | 已验证作者 / 知名机构 |
| 引用计数 | +0.0 ~ +0.1 | 学术论文引用数 / 100 |
| 广告 / 垃圾信号 | -0.1 ~ -0.5 | 激进广告、标题党、内容农场 |

---

### 功能 5：定期研究机会扫描

**配置**：默认关闭，用户可在 config 中显式开启

**调度**：每周一 09:00 自动运行

**输出**：写入 `log.md` 和 `Research/opportunities-YYYY-MM-DD.md`

---

### 功能 3-5：后续版本

- 红链自动研究建议（Phase 2）
- 知识锚点机制（Phase 2+）
- 定期研究机会扫描（Phase 3）

---

## 六、核心数据结构

### 6.1 SearchResult

```python
class ResultType(Enum):
    WEB = "web"          # 网页结果
    ARXIV = "arxiv"      # arXiv 论文

@dataclass
class SearchResult:
    """单个搜索结果的数据结构"""

    # 核心字段
    result_type: ResultType
    url: str
    title: str
    snippet: str

    # 来源标识
    source_engine: str  # "searxng" / "arxiv"

    # 时间字段
    published_date: str | None
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 评分字段
    reliability_score: float  # 0.0 - 1.0
    relevance_score: float    # 与搜索关键词的匹配度

    # 论文特有字段
    authors: list[str] = field(default_factory=list)
    arxiv_id: str = ""
    doi: str = ""
    category: str = ""
    citation_count: int | None = None
    pdf_url: str = ""

    # 可解释性
    reliability_reasons: list[str] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        """综合评分 = 类型权重(0.35) + 可信度(0.3) + 相关性(0.35)"""
        type_weight = 1.0 if self.result_type == ResultType.ARXIV else 0.6
        return type_weight * 0.35 + self.reliability_score * 0.3 + self.relevance_score * 0.35
```

### 5.2 ResearchReport（新增）

```python
@dataclass
class ResearchReport:
    """研究报告数据结构"""
    
    # 元数据
    topic: str
    search_time: str  # ISO format
    search_keywords: list[str]
    
    # 搜索结果
    total_results: int
    high_confidence_count: int
    results: list[SearchResult]
    
    # Phase 2+ LLM 字段
    summary: str | None = None
    key_findings: list[str] | None = None
    suggested_follow_ups: list[str] | None = None
    
    # 方法
    def to_markdown(self) -> str:
        """渲染为 Markdown 报告"""
        ...
    
    def get_filename(self) -> str:
        """生成 wiki 文件名"""
        date = self.search_time.split('T')[0]
        slug = self._slugify(self.topic)
        return f"{date}-{slug}.md"
    
    def save_to_wiki(self, wiki_dir: Path) -> Path:
        """保存到 wiki/Research/"""
        research_dir = wiki_dir / 'Research'
        research_dir.mkdir(exist_ok=True)
        file_path = research_dir / self.get_filename()
        file_path.write_text(self.to_markdown())
        return file_path
```

---

## 七、文件变更清单（最终版）

### Phase 1 新增文件

| 文件 | 预计行数 | 说明 |
|------|---------|------|
| `src/llmwikify/fetchers/__init__.py` | ~10 | 模块导出 |
| `src/llmwikify/fetchers/base.py` | ~50 | ResultType 枚举 + SearchResult 数据类 |
| `src/llmwikify/fetchers/searxng.py` | ~150 | SearXNG JSON API 客户端 |
| `src/llmwikify/fetchers/arxiv_client.py` | ~150 | arXiv Atom API 客户端 |
| `src/llmwikify/fetchers/merger.py` | ~100 | 结果去重 + 混合排序 |
| `src/llmwikify/core/research_report.py` | ~150 | ResearchReport 数据结构 + Markdown 渲染 |
| `src/llmwikify/core/wiki_mixin_research_search.py` | ~100 | Wiki Research Search Mixin |
| `tests/test_v031_fetchers.py` | ~200 | 搜索模块单元测试 |
| `tests/test_v031_research_report.py` | ~100 | 研究报告生成测试 |

### Phase 2 新增文件（后续）

| 文件 | 预计行数 | 说明 |
|------|---------|------|
| `src/llmwikify/research/__init__.py` | ~10 | 模块导出 |
| `src/llmwikify/research/session.py` | ~150 | ResearchSession + RoundResult 数据类 |
| `src/llmwikify/research/planner.py` | ~200 | ResearchPlanner 计划器 |
| `src/llmwikify/research/analyst.py` | ~200 | Research-Analyze 分析核心逻辑 |
| `src/llmwikify/research/engine.py` | ~150 | Research 主循环引擎 |
| `src/llmwikify/research/report_generator.py` | ~150 | 高级报告生成 |
| `src/llmwikify/core/wiki_mixin_research.py` | ~100 | Wiki Research Mixin |

### 修改文件

| 文件 | 变更内容 |
|------|---------|
| `src/llmwikify/core/wiki.py` | P1: 新增 `WikiResearchSearchMixin`; P2: 新增 `WikiResearchMixin` |
| `src/llmwikify/cli/commands.py` | P1: 新增 `research-search` 命令; P2: 新增 `research-analyze` + `research` 命令 |
| `src/llmwikify/config.py` | 新增 `search` 配置块（含 searxng + arxiv 子配置） |
| `pyproject.toml` | 新增 `fetchers` 可选依赖组（feedparser） |

### 存储目录结构

```
wiki/
├── Research/                      # 研究报告（用户可见，参与索引）
│   └── YYYY-MM-DD-{topic}.md
│
└── .research/                     # 研究系统内部存储（隐藏）
    ├── sessions/
    │   └── {uuid}-{topic}.json    # 会话状态持久化
    └── cache/
        ├── searxng/               # 搜索结果缓存（7 天）
        └── metadata/              # 来源元数据缓存（30 天）
```

---

## 八、配置设计

```yaml
search:
  enabled: true

  searxng:
    base_url: https://searx.be  # 公共实例默认值，用户可替换为自建
    timeout: 30
    max_results: 15
    engines: ["google", "duckduckgo", "wikipedia"]

  arxiv:
    enabled: true
    timeout: 30
    max_results: 10
    sort_by: relevance            # relevance | submittedDate | lastUpdatedDate

  quality:
    min_reliability_threshold: 0.5
    high_confidence_threshold: 0.8

  scoring:
    domain_weights:
      "arxiv.org": 0.9
      "github.com": 0.85
      "edu": 0.8
      "org": 0.7
      "com": 0.6
      "xyz": 0.3
```

---

## 九、与现有系统的集成点

| 集成点 | 文件 | 方式 |
|--------|------|------|
| **Wiki 主类** | `wiki.py` | P1: 新增 `WikiResearchSearchMixin`; P2: 新增 `WikiResearchMixin` |
| **CLI 命令** | `commands.py` | P1: 新增 `research-search` 命令; P2: 新增 `research-analyze` + `research` 命令 |
| **配置系统** | `config.py` | 新增 `search` 配置块（searxng + arxiv 子配置） |
| **Ingest 流程** | `wiki_mixin_ingest.py` | Phase 1 输出命令列表; Phase 2 可考虑一键执行 |
| **Log 系统** | `wiki_mixin_page_io.py` | 复用 `append_to_log` 记录研究摘要 |
| **索引系统** | `index.py` | `wiki/Research/` 下的报告自动参与索引 |
| **依赖管理** | `pyproject.toml` | 新增 `fetchers` 可选依赖组（feedparser） |

---

## 十、实施检查清单

### Phase 1 (research-search 命令 - 纯搜索，3 周)
- [ ] 创建 `fetchers/` 模块基础框架
- [ ] 实现 `base.py`: ResultType 枚举 + SearchResult 数据类
- [ ] 实现 `searxng.py`: SearXNG JSON API 客户端 + 结果映射
- [ ] 实现 `arxiv_client.py`: arXiv Atom API 客户端 + ID 精确查询
- [ ] 实现 `merger.py`: DOI/arXiv/URL 三级去重 + 混合排序
- [ ] 实现 `ResearchReport` 数据类 + Markdown 模板渲染
- [ ] 创建 `WikiResearchSearchMixin` 并集成到 Wiki 主类继承链
- [ ] 编写 CLI `research-search` 命令 + 交互式流程
- [ ] 实现报告保存到 `wiki/Research/` + log.md 记录
- [ ] 新增 `search` 配置块（searxng + arxiv）
- [ ] 更新 `pyproject.toml` 新增 `fetchers` 可选依赖
- [ ] 编写 `test_v031_fetchers.py` 单元测试
- [ ] 编写 `test_v031_research_report.py` 测试
- [ ] 文档更新 + 使用示例

### Phase 2 Part 1 (research-analyze 命令 - 单次分析，2 周)
- [ ] 实现 `session.py`: ResearchSession + RoundResult 数据类
- [ ] 实现 `.research/` 会话状态持久化
- [ ] 实现 `planner.py`: 任务拆解 + 关键词生成
- [ ] 实现 `analyst.py`: 信息整合 + 缺口识别 + 价值评估
- [ ] 实现 CLI `research-analyze` 命令
- [ ] 缓存机制实现（7 天搜索缓存 + 30 天元数据缓存）
- [ ] 新增 `--no-cache` 参数支持

### Phase 2 Part 2 (research 主命令 - 多轮迭代，2 周)
- [ ] 实现 `engine.py`: `plan` → `research-search` → `research-analyze` 主循环
- [ ] 实现 5 种终止条件判断
- [ ] 实现 CLI `research` 主命令
- [ ] 实现 `--list` / `--continue` 会话管理
- [ ] 实现 `--auto` / `--interactive` 模式切换
- [ ] 实现高级报告生成器（整合所有轮次信息）
- [ ] 完整集成测试
- [ ] 文档更新

### Phase 3 (高级功能，后续)
- [ ] 红链自动研究建议集成到 lint
- [ ] 知识锚点 embedding 匹配（避免重复搜索已有知识）
- [ ] MCP 工具接口暴露
- [ ] 定期研究机会扫描
- [ ] wiki 内会话索引页面
