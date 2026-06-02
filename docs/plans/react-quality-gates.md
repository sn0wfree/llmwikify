# ReAct 范式完善 + 工程质量提升方案

> 状态：设计阶段
> 分支：`feature/quick-research-display-language`
> 创建日期：2026-05-29

## 一、现状分析

### 当前架构

```
plan → gather → analyze(LLM) → synthesize → report(LLM) → review(LLM) → done
```

- 引擎已有 ReAct 循环：`_react_loop()` → Reason → Act → Observe → 循环
- `_reason()` 先调 LLM，失败后回退到规则判断
- `_observe()` 从 DB 刷新状态并生成观察文本

### 核心缺陷

1. **源质量不可控：** 搜索结果直接入库，低质量源（空内容、导航页、无关页面）污染综合结果
2. **无阶段间检查：** 综合→报告之间无质量检查点，错误传播无感知
3. **观察仅为被动统计：** `_observe` 中的 "Average source credibility" 始终为 0（`analyze_source` prompt 不返回 `credibility` 字段）
4. **无测试覆盖关键路径：** 源过滤、质量门禁、增强观察均无测试

### 关键发现

`analyze_source` prompt 返回的数据包含：
- `content_type`（技术文章/新闻/论文等）
- `claims`（含 `confidence`: high/medium/low）
- `data_gaps`（需要更多信息的主题）
- `potential_contradictions`（与现有 wiki 的矛盾）

**但不包含 `credibility` 或 `quality` 评分**，所以 `_observe` 中尝试读取 `analysis.credibility` 的代码实际无法工作。

---

## 二、设计原则

1. **零额外 LLM 调用：** 复用现有 `analyze_source` LLM 调用，增强其输出 schema
2. **规则化预过滤：** 用确定性规则快速过滤明显低质量源，不消耗 token
3. **门禁作为观察：** 质量门禁结果注入 `state.observations`，由 Reasoner 决策（不硬编码 action）
4. **利用现有数据：** 从 `analyze_source` 的现有输出推导质量评分

---

## 三、修正后的方案

### 方案对比

| 维度 | 原方案（已废弃） | 修正方案 |
|------|-----------------|----------|
| 源质量评估 | LLM-based（10 次额外调用） | 混合：规则预过滤 + 增强现有分析 |
| 实施范围 | 5 大模块全做 | 2 阶段：核心 + 增强 |
| 门禁设计 | 硬编码 action | 作为观察注入，Reasoner 决策 |
| 可观测性 | 新增 metrics 表 + 模块 | 推迟到 Phase 2 |
| 增强观察 | 4 个新方法 | 3 行关键评估 |
| 预计工作量 | 5-7 天 | 2-3 天 |
| LLM 调用增加 | +10 次/研究 | 0 次（增强现有输出） |

---

## 四、模块详细设计

### 模块 1：源质量预过滤（规则化，零 LLM 调用）

**新增文件：** `src/llmwikify/agent/backend/research/source_filter.py`

#### 设计思路

在 `SourceGatherer` 采集源后、`SourceAnalyzer` 分析前，增加一层规则化预过滤：
- 过滤明显低质量源（空内容、导航页、重复 URL）
- 计算质量评分供后续阶段使用
- 不消耗 LLM token，纯确定性规则

#### 类定义

```python
class SourceFilter:
    """Rule-based source pre-filter. No LLM calls."""

    # 已知高质量域名（可扩展）
    HIGH_QUALITY_DOMAINS: set[str] = {
        "arxiv.org", "github.com", "nature.com", "science.org",
        "ieee.org", "acm.org", "wikipedia.org", "docs.python.org",
        "developer.mozilla.org", "stackoverflow.com",
        "pubmed.ncbi.nlm.nih.gov", "scholar.google.com",
    }

    # 已知低质量域名模式
    LOW_QUALITY_PATTERNS: list[str] = [
        "pinterest.com", "quora.com", "reddit.com/r/",
        "medium.com/@", "substack.com",
    ]

    # 导航页标题模式
    NAV_PAGE_PATTERNS: list[str] = [
        "Home |", "Menu", "Skip to", "Loading...",
        "404", "Page Not Found",
    ]
```

#### 核心方法

```python
def filter_sources(
    self, sources: list[dict], query: str
) -> tuple[list[dict], list[dict]]:
    """
    过滤源，返回 (保留的源, 被过滤的源)。

    过滤规则（按优先级）：
    1. 内容长度 < 100 字 → 过滤
    2. 重复 URL（归一化后相同）→ 过滤
    3. 纯导航页（标题匹配 NAV_PAGE_PATTERNS）→ 过滤
    4. 内容仅含导航元素（"Home", "Contact", "About" 占比 > 50%）→ 过滤
    """

def compute_quality_score(self, source: dict) -> float:
    """
    基于规则计算质量分 (0.0-1.0)。

    评分维度：
    - 域名权威性: 0.3 (HIGH_QUALITY_DOMAINS → 1.0, LOW_QUALITY_PATTERNS → 0.3)
    - 内容长度: 0.2 (1000+ 字 → 1.0, 500-1000 → 0.7, <500 → 0.3)
    - 内容结构: 0.2 (有标题/段落/列表 → 1.0, 纯文本 → 0.5)
    - URL 清晰度: 0.15 (短路径 → 1.0, 长参数/追踪链接 → 0.3)
    - 类型匹配: 0.15 (wiki/pdf > web > youtube)
    """

def _normalize_url(self, url: str) -> str:
    """URL 归一化，用于去重。"""

def _is_nav_page(self, content: str) -> bool:
    """检测是否为导航页。"""
```

#### 集成位置

在 `gatherer.py` 的 `_gather_one` 方法中，源入库前调用 `filter_sources`：

```python
# gatherer.py 现有代码（约 line 250-260）
source_id = self.session_manager.add_source(...)

# 改为：
from .source_filter import SourceFilter
_filter = SourceFilter(self.config)
filtered, rejected = _filter.filter_sources([source], query)
if rejected:
    logger.debug("Source filtered: %s (quality too low)", source.get("url"))
    continue  # 跳过低质量源
source_id = self.session_manager.add_source(...)
```

#### 配置项（config.py 新增）

```python
"source_filter_enabled": True,        # 是否启用源预过滤
"source_min_content_length": 100,     # 最小内容长度（低于此过滤）
"source_min_quality_score": 0.3,      # 最低质量分（低于此过滤）
```

---

### 模块 2：增强分析输出（修改现有 prompt）

**修改文件：** `src/llmwikify/prompts/_defaults/analyze_source.yaml`

#### 设计思路

在现有 `analyze_source` prompt 的输出 schema 中新增 `quality_assessment` 字段，复用已有的 LLM 调用，零额外成本。

#### 新增输出字段

在 prompt 的 JSON 输出示例中新增：

```json
{
  "topics": [...],
  "entities": [...],
  "relations": [...],
  "claims": [...],
  "key_facts": [...],
  "suggested_pages": [...],
  "content_type": "...",
  "potential_contradictions": [...],
  "data_gaps": [...],

  "quality_assessment": {
    "credibility": 7,
    "relevance": 8,
    "completeness": 6,
    "issues": ["来源未署名", "数据缺乏引用"]
  }
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `credibility` | int (0-10) | 来源权威性：是否为已知可信来源、是否有署名、是否有引用 |
| `relevance` | int (0-10) | 与查询主题的相关程度 |
| `completeness` | int (0-10) | 内容完整程度：是否有充分论述、是否有数据支撑 |
| `issues` | list[str] | 质量问题列表：如"来源未署名"、"数据缺乏引用"、"内容过时" |

#### 为什么这样做

1. **复用现有 LLM 调用：** `analyze_source` 已经在做内容分析，LLM 已经读取了内容
2. **LLM 已有足够信息：** 分析时已提取 `content_type`、`claims`、`data_gaps`，可以推导质量
3. **零额外成本：** 只修改 prompt，不增加 API 调用
4. **修正现有 bug：** `_observe` 中的 "Average source credibility" 终于能正常工作

#### 修改后的 `_observe` 可信度读取

```python
# 现有代码（line 406）：
scores = [s.get("analysis", {}).get("credibility", 0) for s in analyzed]

# 修改为：
scores = [
    s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
    for s in analyzed
]
```

---

### 模块 3：质量门禁（规则化，注入观察）

**新增文件：** `src/llmwikify/agent/backend/research/quality_gate.py`

#### 设计思路

在 ReAct 循环的每个阶段转换点，检查数据质量是否满足下一阶段的输入要求。门禁结果作为**观察信息**注入 `state.observations`，由 LLM Reasoner 决定下一步行动（不硬编码 action）。

#### 数据结构

```python
@dataclass
class GateResult:
    """质量门禁检查结果。"""
    passed: bool
    gate_name: str
    summary: str          # 人类可读摘要
    details: dict         # 详细数据
    suggestion: str       # 建议（供 Reasoner 参考）
```

#### 类定义

```python
class QualityGate:
    """阶段间质量门禁。结果作为观察注入 ReAct 循环。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.min_sources = config.get("gate_min_sources", 3)
        self.min_type_diversity = config.get("gate_min_type_diversity", 2)
        self.min_analyzed = config.get("gate_min_analyzed", 2)
        self.min_avg_credibility = config.get("gate_min_avg_credibility", 5)
        self.max_knowledge_gaps = config.get("gate_max_knowledge_gaps", 3)
        self.min_reinforced_claims = config.get("gate_min_reinforced_claims", 2)
```

#### 四个检查点

```python
def check_after_gathering(self, state: ResearchState) -> GateResult:
    """
    采集后检查：源数量和多样性是否足够进入分析阶段。

    检查项：
    1. 源数 >= min_sources (默认 3)
    2. 源类型多样性 >= min_type_diversity (默认 2)
    3. 至少 1 个源内容 > 500 字

    通过: summary="8 sources gathered, 3 types, OK"
    失败: summary="Only 2 sources, need 3+", suggestion="gather_more"
    """

def check_after_analysis(self, state: ResearchState) -> GateResult:
    """
    分析后检查：源质量是否足够进入综合阶段。

    检查项：
    1. 已分析源数 >= min_analyzed (默认 2)
    2. 平均 credibility >= min_avg_credibility (默认 5)
    3. 无未处理的矛盾（potential_contradictions 为空）

    通过: summary="Avg credibility 7.2/10, OK"
    失败: summary="Avg credibility 3.2/10, too low"
           suggestion="gather_higher_quality_sources"
    """

def check_after_synthesis(self, state: ResearchState) -> GateResult:
    """
    综合后检查：综合质量是否足够进入报告阶段。

    检查项：
    1. 强化声明数 >= min_reinforced_claims (默认 2)
    2. 知识缺口 <= max_knowledge_gaps (默认 3)

    通过: summary="5 reinforced claims, 2 gaps, OK"
    失败: summary="Only 1 reinforced claim, need 2+"
           suggestion="replan_for_gaps"
    """

def check_before_report(self, state: ResearchState) -> GateResult:
    """
    报告前检查：是否有足够数据生成报告。

    检查项：
    1. 综合数据存在 (state.synthesis is not None)
    2. 源数 >= 2

    通过: summary="Synthesis ready, 8 sources"
    失败: summary="No synthesis data"
           suggestion="synthesize_again"
    """
```

#### 集成到 engine.py

```python
async def _react_loop(self, session_id, query, resume):
    state = ResearchState(...)
    gate = QualityGate(self.config)

    while state.phase != "done":
        # ... 现有逻辑 ...

        # ── ACT: 执行动作 ──
        # (现有 action 代码)

        # ── OBSERVE: 刷新状态 ──
        self._observe(state)

        # ── 质量门禁检查（新增）──
        gate_result = self._evaluate_gate(state, gate)
        if gate_result:
            state.observations.append(
                f"[质量门禁] {gate_result.gate_name}: {gate_result.summary}"
            )
            if not gate_result.passed:
                state.observations.append(
                    f"⚠ 门禁未通过，建议: {gate_result.suggestion}"
                )

        state.round += 1

def _evaluate_gate(self, state, gate):
    """根据当前阶段选择对应的门禁检查。"""
    if state.phase == "gathering":
        return gate.check_after_gathering(state)
    elif state.phase == "analyzing":
        return gate.check_after_analysis(state)
    elif state.phase == "synthesizing":
        return gate.check_after_synthesis(state)
    elif state.phase == "reporting":
        return gate.check_before_report(state)
    return None
```

#### 配置项（config.py 新增）

```python
# 质量门禁配置
"gate_enabled": True,
"gate_min_sources": 3,
"gate_min_type_diversity": 2,
"gate_min_analyzed": 2,
"gate_min_avg_credibility": 5,
"gate_max_knowledge_gaps": 3,
"gate_min_reinforced_claims": 2,
```

---

### 模块 4：增强观察（3 行关键评估）

**修改文件：** `engine.py` 的 `_observe` 方法

#### 设计思路

在现有 `_observe` 方法末尾新增 3 行关键质量评估，利用模块 2 增强后的 `quality_assessment` 数据。

#### 新增代码（追加到 `_observe` 末尾）

```python
# ── 关键质量评估（新增）──
analyzed = [s for s in state.sources if s.get("analysis")]
if analyzed:
    cred_scores = [
        s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
        for s in analyzed
    ]
    avg_cred = sum(cred_scores) / len(cred_scores)
    if avg_cred < 5:
        state.observations.append(
            f"⚠ 平均可信度偏低 ({avg_cred:.1f}/10)，建议获取更高质量源"
        )
    elif avg_cred >= 7:
        state.observations.append(
            f"✓ 源质量良好 (平均 {avg_cred:.1f}/10)"
        )

if len(state.knowledge_gaps) > 3:
    state.observations.append(
        f"⚠ {len(state.knowledge_gaps)} 个知识缺口，可能影响报告完整性"
    )
```

---

### 模块 5：测试（随功能一起写）

#### 新增测试类

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|----------|
| `TestSourceFilter` | 5 | 过滤规则、质量评分、重复检测、导航页检测、边界情况 |
| `TestQualityGate` | 6 | 4 个检查点 × (通过 + 失败)、边界值 |
| `TestEnhancedObservations` | 3 | 可信度评估、缺口警告、正常情况 |
| `TestEngineWithGates` | 2 | 集成：门禁注入观察、Reasoner 读取建议 |
| `TestSourceFilterIntegration` | 3 | 预过滤集成到 gather 流程 |

**总计：** 19 个新测试用例

#### 测试示例

```python
class TestSourceFilter:
    def test_filter_short_content(self):
        """内容 < 100 字的源被过滤。"""
        sources = [{"content": "短", "url": "http://example.com", "title": "Test"}]
        f = SourceFilter({})
        kept, rejected = f.filter_sources(sources, "test query")
        assert len(rejected) == 1

    def test_filter_duplicate_url(self):
        """重复 URL 只保留一个。"""
        sources = [
            {"content": "A" * 200, "url": "http://example.com/a", "title": "A"},
            {"content": "B" * 200, "url": "http://example.com/a", "title": "B"},
        ]
        f = SourceFilter({})
        kept, rejected = f.filter_sources(sources, "test")
        assert len(kept) == 1

    def test_quality_score_high_domain(self):
        """高质量域名得高分。"""
        source = {
            "content": "A" * 1000,
            "url": "https://arxiv.org/abs/2301.00001",
            "source_type": "web",
        }
        f = SourceFilter({})
        score = f.compute_quality_score(source)
        assert score >= 0.7

    def test_quality_score_low_domain(self):
        """低质量域名得低分。"""
        source = {
            "content": "A" * 1000,
            "url": "https://pinterest.com/pin/123",
            "source_type": "web",
        }
        f = SourceFilter({})
        score = f.compute_quality_score(source)
        assert score <= 0.5


class TestQualityGate:
    def test_after_gathering_pass(self):
        """采集后门禁通过：源数 >= 3。"""
        state = ResearchState(
            sources=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
            sub_queries=[{"id": "1"}, {"id": "2"}],
        )
        gate = QualityGate({"gate_min_sources": 3})
        result = gate.check_after_gathering(state)
        assert result.passed

    def test_after_gathering_fail(self):
        """采集后门禁失败：源数 < 3。"""
        state = ResearchState(sources=[{"id": "1"}], sub_queries=[{"id": "1"}])
        gate = QualityGate({"gate_min_sources": 3})
        result = gate.check_after_gathering(state)
        assert not result.passed
        assert "gather_more" in result.suggestion

    def test_after_analysis_low_credibility(self):
        """分析后门禁失败：平均可信度低。"""
        state = ResearchState(
            sources=[
                {"analysis": {"quality_assessment": {"credibility": 3}}},
                {"analysis": {"quality_assessment": {"credibility": 4}}},
            ],
        )
        gate = QualityGate({"gate_min_avg_credibility": 5})
        result = gate.check_after_analysis(state)
        assert not result.passed
```

---

## 五、实施顺序

```
Step 1: SourceFilter (规则化预过滤)
  ├── source_filter.py (新增, ~100 行)
  ├── config.py (新增 3 个配置项)
  ├── gatherer.py (集成 filter)
  └── test_research.py (5 个测试)

Step 2: 增强 analyze_source prompt
  ├── analyze_source.yaml (修改: 新增 quality_assessment 输出)
  └── engine.py (_observe 修正 credibility 读取路径)

Step 3: QualityGate (规则化门禁)
  ├── quality_gate.py (新增, ~120 行)
  ├── engine.py (集成门禁到 _react_loop)
  ├── config.py (新增 7 个门禁配置项)
  └── test_research.py (6 个测试)

Step 4: 增强 _observe (3 行关键评估)
  ├── engine.py (_observe 新增 3 行)
  └── test_research.py (3 个测试)

Step 5: 集成测试
  └── test_research.py (2 个集成测试 + 现有测试回归)
```

---

## 六、影响范围

| 文件 | 改动类型 | 行数估计 |
|------|----------|----------|
| `source_filter.py` | 新增 | ~100 行 |
| `quality_gate.py` | 新增 | ~120 行 |
| `engine.py` | 修改 | ~30 行 |
| `gatherer.py` | 修改 | ~10 行 |
| `config.py` | 修改 | ~15 行 |
| `analyze_source.yaml` | 修改 | ~20 行 |
| `test_research.py` | 修改 | ~350 行 (19 个测试) |

**总计：** 新增 ~220 行，修改 ~425 行

---

## 七、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 源质量评估 | 混合：规则预过滤 + 增强现有分析 | 零额外 LLM 调用，复用已有数据 |
| 门禁失败处理 | 注入观察，Reasoner 决策 | 符合 ReAct 范式，不硬编码 |
| 可观测性 | 推迟到 Phase 2，用现有 logging | 项目早期不需要额外存储 |
| 测试策略 | 随功能一起写 | 确保每个模块独立可测 |
| 质量评分存储 | 存入 analysis JSON | 不新增 DB 列，兼容现有 schema |

---

## 八、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 门禁过于严格 | 研究卡在某个阶段 | 设置最大重试次数（`max_gate_retries`）、超时降级 |
| prompt 修改影响分析质量 | 现有分析可能变差 | 先在测试环境验证，对比修改前后输出 |
| 预过滤误杀 | 过滤掉有价值的源 | 可配置 `source_filter_enabled=False` 关闭 |
| 门禁检查耗时 | 增加循环延迟 | 规则化检查，< 1ms |

---

## 九、后续 Phase 2（按需实施）

1. **可观测性（metrics）：** 新增 `research_metrics` 表，记录阶段耗时、LLM 调用、质量分布
2. **边界情况 LLM 二次评估：** 当 credibility 在 4-6 灰色地带时，调 LLM 做二次判断
3. **源新鲜度检测：** 基于 URL 模式或 HTTP 头检测内容时效性
4. **自动重试策略：** 门禁失败时自动调整搜索策略（如切换搜索关键词）
