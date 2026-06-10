# 论文研报策略复现 — 实施计划

> 创建时间：2026-06-10
> 状态：规划文档（待切分支后实现）
> 版本目标：v0.4.0
> 核心原则：不造新引擎，不造新框架，只做薄适配。

---

## 零、设计原则

实现本功能时，以下 7 条原则指导所有决策。遇到分歧时，回溯原则。

### 原则 1：Wiki 优先（Wiki-First）

**一切产出都写回 wiki，不创建平行数据存储。**

- 论文结构化信息 → wiki 页（Logic/Data/Steps/Factors/Model）
- 生成的代码 → wiki 页（Code）+ 本地文件（.ipynb）
- 回测结果 → wiki 页（Backtest/Optimization）
- 知识图谱 → wiki 的 relation 表
- 会话状态 → DB（仅会话元数据，不存业务数据）

**反模式**：在 strategy/reproduction/ 下维护独立的 JSON/SQLite 存业务数据。

### 原则 2：逻辑一致 > 数字一致

**复现的价值在于「理解论文逻辑」，不在于「复现论文数字」。**

- 回测数字对不上是常态（数据源/滑点/复权/税费差异）
- UI 必须显式声明「已知偏差」
- 分析层重点评估「逻辑是否正确实现」而非「数字是否匹配」
- 如果逻辑正确但数字差异大，这是「已知偏差」，不是 bug

### 原则 3：Prompt 优先于代码（Prompt-Over-Code）

**能用 prompt 解决的，不写代码模块。**

- 理解层：不写 understand.py，用 wiki.md + prompt 驱动
- 分析层：不写 analyze.py，用 prompt 驱动
- 代码生成：不写 codegen.py，用 prompt 驱动
- 只在「必须执行」的环节写代码（回测/沙箱/数据路由）

**判断标准**：如果一个功能的输入是文本、输出也是文本，用 prompt；如果需要执行/计算/IO，写代码。

### 原则 4：优雅降级（Graceful Degradation）

**每层都有降级路径，不因单点失败阻塞全链路。**

| 层 | 降级路径 |
|---|---|---|
| 输入 | 格式不支持 → 提示用户换格式 |
| 理解 | LLM 抽取失败 → 重试 2 次 → 标记 error |
| 理解 | 策略类型无法映射 → 标记 unknown → 自动降级到路径 B（LLM 代码生成）|
| 复现 | 参数配置错误 → 验证合法性，报具体字段 |
| 验证 | 回测超时 → 终止，标注超时 |
| 数据 | AKShare 不可用 → DataCache → SynthProvider |
| 分析 | LLM 分析失败 → 跳过，标注未完成 |

### 原则 5：最小侵入（Minimal Invasiveness）

**不修改现有模块的核心逻辑，只在边缘扩展。**

- 不改 `analyze_source()` 的 prompt（用 Phase 2 补充抽取）
- 不改 `ReActEngine`（用 Skill 扩展能力）
- 不改 `SkillRuntime`（用新 Skill 注册）
- 不改 `PromptRegistry`（用新 YAML 文件）
- 改动仅限于：新增文件 + 在现有注册点追加 1-2 行

### 原则 6：可测试（Testable）

**每个模块可独立测试，不依赖 LLM/网络/沙箱。**

- Prompt 测试：用 mock LLM 返回值
- Skill 测试：用 mock handler
- 回测测试：用缓存的 DataFrame
- 沙箱测试：用 subprocess mock
- 端到端测试：可选（烧 token，仅 CI 中跑）

### 原则 7：少即是多（Less is More）

**能不做就不做，能简单就简单，能复用就不新建。**

- 能用现有 prompt 的，不新建 YAML
- 能用现有 API 的，不新建 MCP 工具
- 能用 wiki 页的，不新建数据库字段
- 能用 Skill 注册的，不新建引擎
- 能用 prompt 解决的分析，不写分析代码
- 能用 3 行解决的，不写 10 行

**判断标准**：每次新增文件/函数/字段/工具时，先问「这个真的需要吗？能不能用已有的替代？」。如果犹豫，就不加。

---

## 版本兼容性

- **v0.4.0 新增功能**，不影响现有 wiki 结构
- wiki.md 模板是**追加**，不是替换：现有 wiki.md 内容不变，只追加 `Papers/` 页面类型
- 现有 `ingest → analyze_source → write_page` 链路**零修改**
- 现有 Skill 系统**零修改**（只注册新 Skill）
- 现有 PromptRegistry **零修改**（只新增 YAML 文件）
- 现有 WebUI **零修改**（只新增 Reproduction 页面）

---

## 一、决策汇总

| 决策项 | 选择 |
|---|---|---|
| M4（券商研报 + arXiv）| 不砍，全做 |
| 数据源 | AKShare（主）+ iFinD（补），不用 Tushare |
| AKShare 缓存 | 首次获取后存入本地 SQLite，后续优先读缓存 |
| 代码生成 | **默认不走 LLM 生成**，预写通用策略 + 参数化调用优先；预写策略不满足时自动降级到 LLM 生成 |
| 执行沙箱 | 主路径无需沙箱（预写代码），降级路径用 subprocess 执行 LLM 生成的代码 |
| 复现层调用 | 函数式直接调用（不经过 Skill 系统），`extract.py → backtest.py` |
| WebUI | 新增独立 Reproduction 页面（与 Research 平级）|
| 分支 | 当前不切，规划完成后再切 |
| 目标版本 | v0.4.0 |
| 分析层深度 | 后续讨论（M4 阶段再定）|

---

## 二、整体架构

```
用户输入 PDF/URL/arXiv/DOI
  ↓
┌─────────────────────────────────────────────────────────────┐
│ ① 输入 + 通用理解（完全复用 llmwikify，零新代码）            │
│                                                              │
│ extractors.extract() → wiki.ingest_source()                 │
│   → wiki.analyze_source() → generate_wiki_ops()             │
│   → execute_operations()                                    │
│                                                              │
│ 产出：Source Summary 页 + entities/relations/claims          │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ② 论文结构化抽取（1 个新 prompt + 1 个薄函数）              │
│                                                              │
│ repro_extract.yaml prompt：                                 │
│   读取 Source Summary                                       │
│   按 wiki.md 模板抽取：                                     │
│     Logic / Data / Steps / Factors / Model                  │
│     Analysis / Datasets / Risks / References                │
│   写入 wiki 页面                                            │
│                                                              │
│ 路径：strategy/reproduction/extract.py（~80行）             │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ③ 复现层（双路径）                                          │
│                                                              │
│ 路径 A（主路径）：参数化直调                                 │
│   extract.py 读取 wiki 页 → 映射到预定义策略类型             │
│   → {signal_type, params, data_config}                       │
│   → backtest.py 实例化预写策略（无需 LLM 生成）              │
│                                                              │
│ 路径 B（降级路径）：自动代码生成                             │
│   预写策略无匹配 → LLM 生成完整策略代码                      │
│   → subprocess 执行（无需沙箱基础设施）                      │
│   （无人介入，全自动降级）                                   │
│                                                              │
│ 路径：strategy/reproduction/backtest.py（~350行）            │
│ 路径：strategy/reproduction/extract.py（~80行）              │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ④ 验证层（回测）                                            │
│                                                              │
│ backtrader + DataRouter（AKShare / iFinD / DataCache）      │
│   数据获取（缓存优先）→ 回测执行 → 指标计算                   │
│   净值曲线 + 交易记录 + 已知偏差                              │
│                                                              │
│ 产出：wiki Backtest.md + Optimization.md                    │
│ 路径：strategy/reproduction/backtest.py（~350行）           │
│ 路径：strategy/data/router.py（~120行）                      │
│ 路径：strategy/data/cache.py（～100行）                     │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 分析层                                                   │
│                                                              │
│ 理解层中（前置）：                                            │
│   repro_analyze_strategy.yaml → Analysis 页                  │
│                                                              │
│ 验证层后（后置）：                                            │
│   repro_analyze_backtest.yaml → Optimization 页              │
│   复用 GraphAnalyzer 做知识图谱分析                           │
│                                                              │
│ Prompt：2 个新 YAML                                         │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 知识图谱（持续积累）                                         │
│   公式→公式  因子→因子  策略→优势  策略→劣势                  │
│   复现→回测  回测→优化  论文→数据                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、wiki.md 模板

wiki.md 定义论文结构化页面模板，引导 LLM 按固定格式抽取：

```markdown
# 论文/研报策略复现

## 页面类型定义

### Papers/<id>/Logic（策略逻辑）
- 核心假设：这篇论文的核心逻辑是什么？
- 市场逻辑：基于什么市场现象/规律？
- 收益来源：alpha 从哪里来？
- 适用条件：什么条件下有效？

### Papers/<id>/Data（数据需求）
- 字段列表：需要哪些数据字段
- 时间粒度：日/分钟/tick
- 标的范围：股票/期货/期权/指数
- 数据来源：Wind/AKShare/iFinD/其他

### Papers/<id>/Steps（操作步骤）
1. 信号生成：什么条件触发买入/卖出
2. 仓位管理：单票仓位上限/总仓位
3. 换仓频率：日/周/月
4. 止损止盈：具体规则
5. 交易成本：手续费/滑点假设

### Papers/<id>/Factors（因子/指标）
每个因子：
- 名称
- 定义（文字描述）
- 公式（LaTeX 或代码）
- 超参数值
- 计算周期

### Papers/<id>/Model（模型/框架）
- 模型类型：统计/ML/DL/规则
- 框架：backtrader/pandas/sklearn/pytorch
- 训练/验证划分
- 评价指标

### Papers/<id>/Analysis（优劣分析）
- 优势：为什么有效
- 劣势：潜在风险、失效条件
- 适用场景：市场类型、标的范围、时间周期
- 与其他策略的关系
- 改进方向

### Papers/<id>/Datasets（数据集）
- 数据集名称
- 来源
- 时间范围
- 处理方式（清洗/复权/标准化）

### Papers/<id>/Risks（风险与偏差）
- 已知局限
- 假设风险
- 实现偏差
- 数据局限

### Papers/<id>/References（参考文献）
- 原文引用
- 相关论文
- 代码仓库

### Papers/<id>/Backtest（回测结果）
- 指标汇总
- 净值曲线
- 交易记录
- 已知偏差说明

### Papers/<id>/Optimization（优化建议）
- 参数调整
- 因子改进
- 风控增强
- 其他改进
```

---

## 四、各层详解

### 4.1 输入层（零新代码）

完全复用 llmwikify 现有链路：

```
llmwikify ingest <source>
  → extractors.extract(source)        # 30+ 格式
  → wiki.ingest_source(content)       # raw/ + 元数据
  → wiki.analyze_source(raw_path)     # LLM 提取
  → execute_operations()              # 写入 wiki 页
```

### 4.2 论文结构化抽取（Phase 2）

Phase 1 产出 Source Summary 后，Phase 2 读取它并生成论文专属页面：

```python
# strategy/reproduction/extract.py（~80行）

async def extract_paper_structure(wiki, source_summary_page):
    """读取 Source Summary，按 wiki.md 模板生成论文结构化页面"""
    summary = wiki.read_page(source_summary_page)
    # 调用 repro_extract.yaml prompt
    # LLM 返回结构化 JSON
    # 按 wiki.md 模板写入各页面
    for page_name, content in extraction_result.items():
        wiki.write_page(f"Papers/{paper_id}/{page_name}", content)
    # 写入知识图谱
    wiki.write_relations(relations)
```

### 4.3 复现层（双路径）

**主路径（A）**：预写策略 + 参数化调用。**降级路径（B）**：自动 LLM 代码生成 + subprocess 执行。无人介入。

```python
# strategy/reproduction/backtest.py（~350行）

# ── 路径 A：预写通用策略 ──
class GenericStrategy(bt.Strategy):
    """单一策略类，signal_type 决定逻辑分支"""
    params = (
        ('signal_type', 'ma_cross'),
        ('params', {}),
        ('position_pct', 0.1),
        ('stop_loss', None),
    )

    def next(self):
        signal = self._compute_signal()
        if signal > 0 and not self.position:
            self.buy(size=self._calc_size())
        elif signal < 0 and self.position:
            self.close()

    def _compute_signal(self) -> float:
        st = self.params.signal_type
        p = self.params.params
        if st == 'ma_cross':
            fast = bt.indicators.SMA(self.data.close, period=p['fast'])
            slow = bt.indicators.SMA(self.data.close, period=p['slow'])
            return (fast[0] - slow[0]) / slow[0]
        elif st == 'rsi':
            rsi = bt.indicators.RSI(self.data.close, period=p.get('period', 14))
            return (50 - rsi[0]) / 50
        elif st == 'factor_rank':
            ...
        return 0.0


# extract.py（~80行）
async def extract_paper_structure(wiki, paper_id):
    """读取 wiki 页，返回策略参数或标记需要代码生成"""
    pages = read_wiki_pages(wiki, paper_id)
    result = await LLM.aask("repro_extract", {"pages": pages})
    # result.signal_type == "unknown" → 降级到路径 B
    return result


# ── 路径 B：自动降级到 LLM 代码生成（预写策略不满足时）──
async def generate_and_run_custom(wiki, config, data):
    """LLM 生成完整策略代码 + subprocess 执行"""
    code = await LLM.aask("repro_codegen", {
        "pages": read_wiki_pages(wiki, config['paper_id']),
        "strategy_config": config,
    })
    # 写入临时 .py 文件，subprocess 执行
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run([sys.executable, f.name],
                               capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)


# run_reproduction 主流程
async def run_reproduction(wiki_id, paper_id):
    wiki = Wiki(wiki_id)
    config = await extract_paper_structure(wiki, paper_id)
    data = await DataRouter.get(config['data_config'])

    if config.get('signal_type') != 'unknown':
        # 路径 A：参数化直调
        result = BacktestRunner.run(GenericStrategy, config, data)
    else:
        # 路径 B：LLM 生成 + 执行
        result = await generate_and_run_custom(wiki, config, data)

    wiki.write_page(f"Papers/{paper_id}/Backtest", result['report'])
```

### 4.4 验证层（backtrader + DataCache）

数据获取流程：**Cache Hit → AKShare → iFinD → SynthProvider**

```python
# strategy/data/cache.py（~100行）

class DataCache:
    """AKShare 数据本地缓存"""
    DB_PATH = "~/.llmwikify/data_cache.db"

    def get(self, symbol, start, end) -> pd.DataFrame | None:
        """命中返回 DataFrame，未命中返回 None"""
        ...

    def set(self, symbol, start, end, df: pd.DataFrame):
        """写入缓存"""
        ...


# strategy/reproduction/backtest.py

class BacktestRunner:
    def run(self, strategy_cls, config, data):
        """执行回测"""
        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy_cls, **config)
        cerebro.adddata(data)
        results = cerebro.run()
        return {
            "metrics": {sharpe, mdd, total_return, ...},
            "pnl_curve": ...,
            "trades": [...],
        }
```

### 4.5 分析层（LLM prompt）

前置分析（理解层中）：`repro_analyze_strategy.yaml` → Analysis 页
后置分析（验证层后）：`repro_analyze_backtest.yaml` → Optimization 页

---

## 五、层间数据格式

### ① 输入层 → 理解层

```python
ExtractedContent:
  text: str           # 提取的全文
  source_type: str    # "pdf" / "url" / "youtube"
  title: str
  metadata: dict

SectionMetadata:
  sections: list[{id, title, word_count, preview}]
  total_words: int
  has_headers: bool
```

### ② 理解层 → 复现层

```python
# wiki.md 模板定义的 9 个页面，每个页面是 markdown
pages = {
  "logic":      wiki.read_page("Papers/<id>/Logic"),
  "data":       wiki.read_page("Papers/<id>/Data"),
  "steps":      wiki.read_page("Papers/<id>/Steps"),
  "factors":    wiki.read_page("Papers/<id>/Factors"),
  "model":      wiki.read_page("Papers/<id>/Model"),
  "analysis":   wiki.read_page("Papers/<id>/Analysis"),
  "datasets":   wiki.read_page("Papers/<id>/Datasets"),
  "risks":      wiki.read_page("Papers/<id>/Risks"),
  "references": wiki.read_page("Papers/<id>/References"),
}
```

### ③ 复现层 → 验证层

```python
# extract.py 产出（参数配置）
strategy_config: {
  signal_type: str,            # "ma_cross" / "rsi" / "factor_rank" / ...
  params: dict,                 # 信号参数 {fast: 5, slow: 20, ...}
  position_pct: float,         # 仓位比例
  stop_loss: float | None,     # 止损
  data_config: {               # 数据配置
    symbols: list[str],
    start: str,
    end: str,
    freq: str,                 # "1d" / "1h"
  }
}
```

### ④ 验证层 → 分析层

```python
backtest_result: {
  metrics: {
    total_return: float,
    annual_return: float,
    sharpe_ratio: float,
    sortino_ratio: float,
    max_drawdown: float,
    calmar_ratio: float,
    win_rate: float,
    profit_factor: float,
  },
  pnl_curve: pd.Series,        # 净值曲线
  trades: list[{               # 交易记录
    date: str,
    symbol: str,
    side: "buy" | "sell",
    price: float,
    shares: int,
    value: float,
  }],
  equity_curve_png: str,       # base64 编码的净值曲线图
}
```

### ⑤ 分析层 → wiki 回写

```python
optimization_result: {
  performance_assessment: str,
  risk_analysis: str,
  optimization_suggestions: list[str],
  comparison_with_paper: str,
  applicable_scenarios: str,
  limitations: list[str],
}
```

---

## 六、Prompt 设计

### 6.1 repro_extract.yaml（结构化抽取）

**输入**：wiki 页面内容（Logic/Data/Steps/Factors/Model）
**输出**：结构化 JSON（9 个 wiki 字段 + strategy_config）

关键约束：
- 必须从原文中抽取，不能编造
- 每个字段标注 confidence（HIGH/MEDIUM/LOW）
- 公式必须保留 LaTeX 格式
- 步骤必须有明确的输入→输出
- **必须映射到预定义策略类型**（ma_cross / rsi / factor_rank / ...）

```yaml
name: repro_extract
description: "从论文中抽取策略复现所需的 9 类结构化信息 + 策略参数"

system: |
  你是一个量化论文结构化抽取器。从给定文档中提取：

  A) 9 类 wiki 信息：
  1. Logic（策略逻辑）— 核心假设、市场逻辑、收益来源、适用条件
  2. Data（数据需求）— 字段列表、时间粒度、标的范围、数据来源
  3. Steps（操作步骤）— 信号/仓位/换仓/止损/成本，每步有输入→输出
  4. Factors（因子）— 名称、定义、公式(LaTeX)、超参、计算周期
  5. Model（模型/框架）— 类型、框架、训练/验证划分、评价指标
  6. Analysis（优劣）— 优势、劣势、适用场景、改进方向
  7. Datasets（数据集）— 名称、来源、时间范围、处理方式
  8. Risks（风险）— 局限、假设风险、实现偏差、数据局限
  9. References（参考）— 原文引用、相关论文、代码仓库

  B) strategy_config（回测配置）：
  将论文策略映射到以下预定义信号类型之一：
  - ma_cross: 均线交叉（需 fast/slow 周期）
  - rsi: RSI 阈值（需 period/overbought/oversold）
  - factor_rank: 多标的因子排名（需 factor 列名/窗口/头寸数）
  - volatility: 波动率策略（需 lookback/rebalance 周期）
  - momentum: 动量策略（需 lookback/holding 周期）
  - signal_composite: 多信号组合（需各信号权重）
  - unknown: 以上均不匹配，需 LLM 生成自定义代码

  返回 JSON，包含 "wiki"（9 个字段）+ "strategy_config"（signal_type + params）。

  如果论文策略无法映射到任何预定义类型，设 signal_type = "unknown"，
  框架会自动降级到 LLM 代码生成路径。

user: |
  wiki 页面内容：
  {{ pages }}

### 6.2 repro_analyze_strategy.yaml（策略优劣分析）

**输入**：抽取结果 JSON
**输出**：分析报告 markdown

```yaml
name: repro_analyze_strategy
description: "分析策略的优劣与适用场景"

system: |
  分析该策略的：
  1. 优势 — 为什么有效、在什么条件下有效
  2. 劣势 — 潜在风险、失效条件、过拟合风险
  3. 适用场景 — 市场类型（牛/熊/震荡）、标的范围、时间周期
  4. 因子质量 — 每个因子的可信度、衰减风险
  5. 操作步骤 — 步骤是否可执行、是否存在前瞻偏差
  6. 与其他策略的关系 — 是否可组合、是否存在冲突
  7. 改进方向 — 已知文献中的改进方案

user: |
  策略信息：{{ extraction_json }}
```

### 6.3 repro_analyze_backtest.yaml（回测结果分析）

**输入**：回测指标 + 策略分析
**输出**：分析报告 markdown

```yaml
name: repro_analyze_backtest
description: "分析回测结果，提出优化建议"

system: |
  根据回测结果和策略分析，输出：
  1. 业绩评估 — Sharpe/MDD/年化是否合理
  2. 风险分析 — 最大回撤、波动率、集中度风险
  3. 优化建议 — 参数调整、因子改进、风控增强
  4. 与论文对比 — 数字差异的原因分析
  5. 适用场景 — 什么市场/周期/标的下有效
  6. 局限性 — 数据/假设/实现的已知局限

user: |
  回测指标：{{ metrics }}
  交易记录：{{ trades }}
  策略分析：{{ strategy_analysis }}
  已知偏差：{{ deviations }}
```

### 6.4 repro_codegen.yaml（代码生成 — 降级路径）

**输入**：wiki 页面 + 策略配置
**输出**：完整可运行的 Python 回测脚本

```yaml
name: repro_codegen
description: "预写策略无法满足时，LLM 生成自定义回测代码"

system: |
  根据论文信息生成完整的 backtrader 回测代码。

  硬性约束：
  1. 使用 bt.Strategy.next() 接口
  2. 数据获取用 akshare
  3. 输出 metrics dict: {sharpe, mdd, total_return, ...}
  4. 代码必须可独立运行（python xxx.py）
  5. 禁止 import: requests, urllib, socket, subprocess, os

user: |
  wiki 页面：{{ pages }}
  策略配置：{{ strategy_config }}
```


## 七、待确认细节

| # | 问题 | 影响 |
|---|---|---|
| 1 | AKShare A 股日线复权方式：前复权/后复权/不复权？ | 回测准确性 |
| 2 | backtrader data feed 格式：AKShare DataFrame 需怎么转换？ | backtest.py 复杂度 |
| 3 | 知识图谱边类型：策略→因子 用什么 relation type？ | 图谱设计 |
| 4 | WebUI：独立路由还是嵌入 Research？ | 前端工作量 |
| 5 | LLM 成本：每篇 ~3-4 次调用（~30K-50K tokens），用户需知情 | 用户体验 |
| 6 | 错误后恢复：重试/从失败 phase 恢复/中断清理？ | Session 管理 |
| 7 | 用户反馈循环：调参重跑/多策略比较/导出.py？ | 功能范围 |

---

## 八、简化备选方案

如果 M0 POC 发现某些环节不可行：

| 环节 | 可行时 | 简化方案 |
|---|---|---|
| 数据路由 | AKShare 全覆盖 | 降级为合成数据（SynthProvider）|
| iFinD 集成 | iFinD 可用 | 砍掉，只用 AKShare |
| 策略映射 | LLM 能映射到预定义信号类型 | 降级为手动填写参数 |
| Wiki 模板 | 自动注入模板 | 降级为手动粘贴 |
| 分析层 | LLM 分析可用 | 跳过，不阻塞回测 |

---

## 九、Session/DB 管理

### 复现会话表

```sql
CREATE TABLE reproduction_sessions (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    source_type TEXT NOT NULL,       -- pdf / url / arxiv / doi
    source_ref TEXT NOT NULL,        -- 文件路径 / URL / arXiv ID
    paper_title TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/extracting/reproducing/backtesting/done/error
    current_phase TEXT,
    progress REAL DEFAULT 0.0,
    config_json TEXT,                -- 回测配置（手续费/滑点/初始资金）
    backtest_wiki_page TEXT,         -- 回测报告 wiki 页名称（如 "Papers/<id>/Backtest"）
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

> **原则 1 约束**：sessions 表只存会话元数据，**不存业务数据**。回测结果等业务数据存 wiki 页，通过 `backtest_wiki_page` 字段引用。

### 复现产物表

```sql
CREATE TABLE reproduction_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- extraction / code / backtest / analysis
    wiki_page TEXT,                  -- 对应的 wiki 页名称（如 "Papers/<id>/Backtest"）
    file_path TEXT,                  -- 本地文件路径（.ipynb / .py，可选）
    score REAL,                     -- 就绪度评分 / 质量评分
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
);
```

> **原则 1 约束**：artifacts 表只存元数据（kind/wiki_page/file_path/score），**不存业务内容**。所有业务内容（抽取结果/代码/回测报告）存 wiki 页。

### 复现事件表（SSE 重启用）

```sql
CREATE TABLE reproduction_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
);
```

### DB 初始化

复用现有 `AgentDatabase`（`~/.llmwikify/agent/.llmwiki_agent.db`），通过幂等 `CREATE TABLE IF NOT EXISTS` 扩展 schema。

---

## 十、触发机制

复现有 3 种方式触发复现：

### 方式 1：MCP 工具（Agent 调用）

```python
# MCP 工具 handler（2 个：start + report）
async def wiki_paper_repro_start(wiki_id, source_type, source_ref):
    """启动复现会话"""
    session_id = db.create_session(wiki_id, source_type, source_ref)
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}

async def wiki_paper_repro_report(session_id):
    """返回全部信息（status + artifacts + code + backtest）"""
    # 见十四、MCP 工具实现
    ...
```

### 方式 2：REST API（WebUI 调用）

```python
@router.post("/api/reproduction/start")
async def start_reproduction(request: Request):
    """WebUI 调用"""
    session_id = db.create_session(...)
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id}

@router.get("/api/reproduction/{session_id}/stream")
async def stream_progress(session_id: str):
    """SSE 流式进度"""
    async def event_generator():
        async for event in db.get_events(session_id):
            yield f"data: {json.dumps(event)}\n\n"
    return EventSourceResponse(event_generator())
```

### 方式 3：CLI（命令行）

```bash
llmwikify reproduce <source> --wiki <wiki_id>
```

### run_reproduction 主流程

```python
async def run_reproduction(session_id):
    """复现主流程（异步执行）"""
    session = db.get_session(session_id)
    wiki = Wiki(session.wiki_id)

    try:
        # Phase 1: 输入 + 通用理解（复用 llmwikify）
        db.update_status(session_id, "extracting")
        source = resolve_input(session.source_type, session.source_ref)
        wiki.ingest_source(source)
        wiki.analyze_source(source)

        # Phase 2: 论文结构化抽取 → 写入 wiki 页 + 获取策略参数
        db.update_status(session_id, "extracting")
        config = await extract_paper_structure(wiki, session.paper_title)
        db.create_artifact(session_id, "extraction",
                          wiki_page=f"Papers/{session.paper_title}/Logic")

        # Phase 3: 数据获取（缓存优先）
        db.update_status(session_id, "fetching_data")
        data = await DataRouter.get(config['data_config'])

        # Phase 4: 回测（双路径）
        db.update_status(session_id, "backtesting")
        if config.get('signal_type') != 'unknown':
            # 路径 A：预写策略 + 参数化调用
            backtest_result = BacktestRunner.run(GenericStrategy, config, data)
        else:
            # 路径 B：LLM 生成代码 + subprocess 执行（自动降级）
            backtest_result = await generate_and_run_custom(wiki, config, data)
        wiki.write_page(f"Papers/{session.paper_title}/Backtest", backtest_result['report'])
        db.update_session(session_id, backtest_wiki_page=f"Papers/{session.paper_title}/Backtest")
        db.create_artifact(session_id, "backtest",
                          wiki_page=f"Papers/{session.paper_title}/Backtest")

        # Phase 5: 分析 → 优化建议写入 wiki 页
        db.update_status(session_id, "analyzing")
        await analyze_results(wiki, session.paper_title, backtest_result)
        db.create_artifact(session_id, "analysis",
                          wiki_page=f"Papers/{session.paper_title}/Optimization")

        db.update_status(session_id, "done")
    except Exception as e:
        logger.error(f"Reproduction {session_id} failed: {e}")
        db.update_status(session_id, "error", error=str(e))
```

---

## 十一、错误处理策略

### 每层失败处理

| 层 | 失败场景 | 处理方式 |
|---|---|---|
| 输入层 | 文件格式不支持 | 返回错误，提示用户换格式 |
| 输入层 | 文件损坏/空文件 | 返回错误，提示用户检查文件 |
| 理解层 | LLM 抽取失败 | 重试 2 次，失败则标记 session 为 error |
| 理解层 | 抽取结果不完整 | 按已有内容写入，标注缺失字段 |
| 理解层 | LLM 无法映射到已知策略类型 | 标记 strategy_type 为 unknown，提示用户手动指定 |
| 复现层 | 策略参数配置错误 | 验证参数合法性，报具体字段错误 |
| 验证层 | 回测执行超时 | 终止执行，标注超时 |
| 验证层 | AKShare 数据不可用 | fallback 到 DataCache，再 fallback 到 SynthProvider |
| 验证层 | 数据缓存查不到 | 同 AKShare fallback 流程 |
| 分析层 | LLM 分析失败 | 跳过分析，标注未完成 |

### 全局错误处理

```python
async def run_reproduction(session_id):
    try:
        ...
    except Exception as e:
        logger.error(f"Reproduction {session_id} failed: {e}")
        db.update_status(session_id, "error", error=str(e))
        # 发送通知（如果配置了）
        await notify(session_id, f"复现失败: {e}")
```

---

## 十二、测试策略

### 单元测试（每个模块独立）

| 测试文件 | 覆盖 | 行数 |
|---|---|---|
| `tests/strategy/reproduction/test_extract.py` | 论文结构化抽取 | ~100 |
| `tests/strategy/reproduction/test_backtest.py` | 预写策略 + backtrader 封装 | ~120 |
| `tests/strategy/reproduction/test_config.py` | 配置验证 | ~40 |
| `tests/strategy/data/test_router.py` | DataRouter | ~80 |
| `tests/strategy/data/test_cache.py` | 数据缓存 | ~80 |

### 集成测试（端到端）

| 测试 | 内容 | 耗时 |
|---|---|---|
| `test_e2e_extract` | PDF → wiki 页面 | ~30s |
| `test_e2e_full` | PDF → 抽取 → 回测 → 报告（全链路）| ~90s |

### Mock 策略

- LLM 调用：用固定返回值 mock（不烧 token）
- AKShare：用缓存的 DataFrame mock（无网络调用）

---

## 十三、wiki.md 集成方式

### 方案：用户手动写入（Phase 1）

wiki.md 是 wiki 的 schema 文件，定义页面类型和约定。复现功能的 wiki.md 模板需要用户手动添加到 wiki.md 中：

```bash
# 用户执行
llmwikify init  # 已有 wiki.md
# 手动将 Papers 页面类型添加到 wiki.md
```

### 方案：CLI 命令自动注入（Phase 2）

```bash
llmwikify reproduce --init-wiki  # 自动将 Papers 页面类型注入 wiki.md
```

### 实现

```python
# strategy/reproduction/wiki_template.py

PAPERS_TEMPLATE = """
## Papers（论文/研报策略复现）

### Papers/<id>/Logic（策略逻辑）
...

### Papers/<id>/Data（数据需求）
...
"""

def inject_papers_template(wiki_root):
    """将 Papers 模板注入 wiki.md"""
    wiki_md_path = os.path.join(wiki_root, "wiki.md")
    with open(wiki_md_path, "r") as f:
        content = f.read()
    if "Papers/<id>/Logic" not in content:
        with open(wiki_md_path, "a") as f:
            f.write(PAPERS_TEMPLATE)
```

---

## 十四、MCP 工具实现

> 原则 7（Less is More）：只暴露 2 个工具，不拆分细粒度 API。

### 2 个 MCP 工具（Less is More）

```python
# 1. wiki_paper_repro_start — 触发复现
async def handle_start(wiki_id, source_type, source_ref):
    session_id = db.create_session(wiki_id, source_type, source_ref)
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}

# 2. wiki_paper_repro_report — 返回全部信息（status + artifacts + code + backtest）
async def handle_report(session_id):
    session = db.get_session(session_id)
    artifacts = db.get_artifacts(session_id)
    wiki = Wiki(session.wiki_id)

    result = {
        "status": session.status,
        "progress": session.progress,
        "paper_title": session.paper_title,
        "artifacts": [],
    }

    for a in artifacts:
        item = {"kind": a.kind, "wiki_page": a.wiki_page, "score": a.score}
        if a.wiki_page:
            item["content"] = wiki.read_page(a.wiki_page)
        result["artifacts"].append(item)

    return result
```

---

## 十五、arXiv/DOI 输入适配

### arXiv

```python
# strategy/reproduction/input_adapter.py（~80行）

import arxiv

def download_arxiv(arxiv_id: str) -> str:
    """下载 arXiv 论文 PDF，返回本地路径"""
    client = arxiv.Client()
    search = client.results(arxiv.Search(id_list=[arxiv_id]))
    paper = next(search)
    paper.download_pdf(dirpath=".cache/repro/", filename=f"{arxiv_id}.pdf")
    return f".cache/repro/{arxiv_id}.pdf"
```

### DOI

```python
from habanero import Crossref

def resolve_doi(doi: str) -> str:
    """解析 DOI，返回 PDF URL（如有 OA）"""
    cr = Crossref()
    result = cr.works(doi)
    # 尝试获取 OA PDF 链接
    for link in result.get("message", {}).get("link", []):
        if link.get("content-type") == "application/pdf":
            return link["URL"]
    raise ValueError(f"DOI {doi} 无可用 PDF")
```

### 券商研报 OCR 降级

```python
async def extract_broker_report(pdf_path: str) -> str:
    """券商研报提取，图表多时降级到 vision-LLM"""
    result = extractors.extract(pdf_path)
    if len(result.text) < 500:  # 提取率低，可能是扫描件
        # 按页预算 2 页，调 vision-LLM
        pages = extract_pages_with_figures(pdf_path, max_pages=2)
        for page in pages:
            description = await llm.describe_image(page.image)
            result.text += f"\n\n[图表描述] {description}"
    return result.text
```

---

## 十六、文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `strategy/reproduction/config.py` | ~50 | AKShare/iFinD/backtest 配置 |
| `strategy/reproduction/extract.py` | ~80 | 论文结构化抽取（调 LLM + write_page）|
| `strategy/reproduction/backtest.py` | ~350 | 预写通用策略 + backtrader 封装 |
| `strategy/reproduction/wiki_template.py` | ~50 | wiki.md 模板注入 |
| `strategy/data/router.py` | ~120 | AKShare + iFinD 路由 |
| `strategy/data/cache.py` | ~100 | AKShare 数据本地缓存 |
| `prompts/_defaults/repro_extract.yaml` | ~80 | 结构化抽取（含策略类型映射）|
| `prompts/_defaults/repro_codegen.yaml` | ~80 | 降级路径：LLM 生成代码 |
| `prompts/_defaults/repro_analyze_strategy.yaml` | ~60 | 策略优劣分析 |
| `prompts/_defaults/repro_analyze_backtest.yaml` | ~80 | 回测分析 |
| `web/webui/src/pages/Reproduction/index.tsx` | ~200 | 主页面 |
| `web/webui/src/pages/Reproduction/NewSession.tsx` | ~150 | 新建会话 |
| `web/webui/src/pages/Reproduction/Detail.tsx` | ~200 | 详情（5个tab）|
| `web/webui/src/components/BacktestChart.tsx` | ~100 | 净值曲线 |
| `web/webui/src/components/ReadinessBadge.tsx` | ~50 | 就绪度徽章 |
| **合计** | **~1770** | **Python ~910 + YAML ~300 + TS ~700** |

---

## 十七、时间线

| 周 | 里程碑 | 交付 |
|---|---|---|
| W1 | M0 骨架 | config + backtest.py 骨架 + DataCache + 路由 + POC |
| W2-3 | M1 理解层 | 3 篇论文端到端 → wiki 页 + 策略类型映射 |
| W4-5 | M2 复现层 | backtest.py 预写策略 + extract.py 参数直调 |
| W6-7 | M3 验证层 | DataCache + AKShare/iFinD + 回测报告 |
| W8 | M4 分析层 | 结果分析 + 优化建议 + 全链路串通 |
| W9-10 | M5 Multi-input | arXiv/DOI/券商研报 |
| W11-12 | M6 测试 + RC | e2e 20+、性能、文档、v0.4.0-rc |
| W13-16 | 缓冲 | bug fix、边缘场景、优化 |

---

## 十八、M0 POC 验证（4 个快速验证）

| POC | 内容 | 耗时 | 目的 |
|---|---|---|---|
| AKShare 数据 | 能否拿到 A 股日线？期货？期权？ | 30min | 验证数据源可用性 |
| DataCache | 缓存读写 + 与 AKShare 集成 | 30min | 验证缓存机制 |
| wiki.md 模板 | repro_extract prompt 能否从 Source Summary 生成正确参数？ | 1h | 验证抽取可行性 |
| **最小 E2E** | Source Summary → repro_extract → 参数 → backtest.py 执行 + AKShare → 输出指标 | **2h** | 验证全链路无断裂点 |

---

## 十九、依赖

```toml
[project.optional-dependencies]
repro = [
  "akshare>=1.16",
  "backtrader>=1.9.78",
  "arxiv>=2.1",
  "habanero>=1.2",
]
ifind = [
  "ifind-py>=1.0",
]
```

---

## 二十、MCP 工具列表

| 工具名 | 参数 | 返回 |
|---|---|---|
| `wiki_paper_repro_start` | wiki_id, source_type, source_ref | session_id |
| `wiki_paper_repro_report` | session_id | status, progress, artifacts (全部内容) |

---

## 二十一、风险与缓解

| 风险 | 缓解 |
|---|---|---|
| 论文回测数字对不上 | UI「已知偏差」模板 + 逻辑一致 ≠ 数字一致 |
| LLM 不可重现 | seed + low temp + prompt 版本号 |
| iFinD 无 token | fallback 到 AKShare |
| 券商研报 OCR 成本 | 仅按需触发 |
| 策略类型映射失败 | LLM 无法映射到已知类型 → 自动降级到路径 B（LLM 代码生成 + 输出验证）|
| AKShare 数据不可靠 | DataCache 缓存 + SynthProvider 兜底 |
| **LLM 调用成本** | **~3-4 次/篇（提取 + 策略分析 + 回测分析），比代码生成方案减少 ~50%** |
| **WebUI 复杂度** | **M0 评估砍掉 ReadinessBadge，合并页面** |
