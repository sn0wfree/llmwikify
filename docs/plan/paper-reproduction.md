# 论文研报策略复现 — 实施计划

> 创建时间：2026-06-10
> 状态：规划文档（待切分支后实现）
> 版本目标：v0.4.0
> 核心原则：不造新引擎，不造新框架，只做薄适配。

---

## 零、设计原则

实现本功能时，以下 6 条原则指导所有决策。遇到分歧时，回溯原则。

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
|---|---|
| 输入 | 格式不支持 → 提示用户换格式 |
| 理解 | LLM 抽取失败 → 重试 2 次 → 标记 error |
| 复现 | 代码校验失败 → 修复循环 ≤3 轮 → 保存当前代码 |
| 验证 | KernelGateway 失败 → 降级 subprocess |
| 数据 | AKShare 不可用 → 合成数据 + 声明 |
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
|---|---|
| M4（券商研报 + arXiv）| 不砍，全做 |
| 数据源 | AKShare（主）+ iFinD（补），不用 Tushare |
| 代码沙箱 | KernelGateway（安全隔离，~200行）|
| 复现层调用方式 | A+B 结合：主流程 SkillRuntime.execute()（确定性）+ 修复循环 ChatBase.aask_with_tools()（灵活）|
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
│ ③ 复现层（A+B 结合）                                        │
│                                                              │
│ 主流程（方式 A，确定性）：                                    │
│   Skill: repro.generate → 读取 wiki → 生成代码              │
│   Skill: repro.validate → 静态校验 + 语法检查               │
│                                                              │
│ 修复循环（方式 B，LLM 驱动）：                               │
│   校验失败 → ChatBase.aask_with_tools()                     │
│   LLM 自主决策调用 repro.fix → 重新校验                     │
│   循环 ≤3 轮 或通过                                         │
│                                                              │
│ 执行（方式 A）：                                             │
│   Skill: repro.sandbox → KernelGateway 执行                 │
│                                                              │
│ 路径：apps/chat/skills/actions/repro_action.py（~350行）    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ④ 验证层（回测）                                            │
│                                                              │
│ Skill: repro.sandbox                                        │
│   KernelGateway 执行 .ipynb                                 │
│   超时 120s / 隔离执行                                       │
│                                                              │
│ backtrader + DataRouter（AKShare / iFinD）                  │
│   数据获取 → 回测执行 → 指标计算                              │
│   净值曲线 + 交易记录 + 已知偏差                              │
│                                                              │
│ 产出：wiki Backtest.md + Optimization.md                    │
│ 路径：strategy/reproduction/backtest.py（~250行）           │
│ 路径：strategy/data/router.py（~120行）                      │
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

### 4.3 复现层（A+B 结合）

主流程用方式 A（确定性），修复循环用方式 B（LLM 驱动）：

```python
# 注册 Skill
class ReproSkill(Skill):
    name = "repro"
    actions = {
        "generate": SkillAction(handler=generate_handler, ...),
        "validate": SkillAction(handler=validate_handler, ...),
        "fix":      SkillAction(handler=fix_handler, ...),
        "sandbox":  SkillAction(handler=sandbox_handler, ...),
    }

# A+B 结合调用
async def reproduce(wiki, paper_id):
    runtime = SkillRuntime.default()
    ctx = SkillContext(wiki=wiki, llm_client=llm)

    # ── 方式 A：直接调用（固定流程）──
    pages = read_wiki_pages(wiki, paper_id)
    result = await runtime.execute("repro", "generate", {"pages": pages}, ctx)
    code = result.data["code"]

    # ── 方式 A：直接校验 ──
    result = await runtime.execute("repro", "validate", {"code": code}, ctx)

    # ── 方式 B：LLM 驱动修复循环（校验失败时）──
    if result.status == "error":
        chat = ChatBase(llm_client=llm, skill_registry=registry)
        messages = [
            {"role": "system", "content": "你是代码修复助手。校验失败，请修复代码。"},
            {"role": "user", "content": f"代码：\n{code}\n\n错误：\n{result.error}"},
        ]
        async for event in chat.aask_with_tools(
            messages,
            tools=chat.tools_schema(),
            max_iterations=3,
        ):
            if event["type"] == "tool_call_end":
                code = event["result"].data["code"]

    # ── 方式 A：直接执行 ──
    result = await runtime.execute("repro", "sandbox", {"code": code}, ctx)
    wiki.write_page(f"Papers/{paper_id}/Backtest", result.data["report"])
```

### 4.3.1 方式选择逻辑

| 阶段 | 方式 | 原因 |
|---|---|---|
| 读取 wiki 知识库 | A（直接调用）| 固定流程 |
| 生成代码 | A（直接调用）| 固定输入 → 固定输出 |
| 校验 | A（直接调用）| 规则检查 |
| **代码修复** | **B（LLM 驱动）**| 校验失败时 LLM 自主判断怎么修 |
| 执行回测 | A（直接调用）| 固定流程 |

### 4.3.2 修复循环（方式 B）

```
校验失败
  ↓
ChatBase.aask_with_tools()
  ↓ LLM 读取错误信息
  ↓ 调用 repro.fix（修改代码）
  ↓ 重新校验
  ↓
  ├─ 通过 → 继续执行
  └─ 再次失败 → 最多重试 3 轮
```

### 4.4 验证层（backtrader）

```python
# strategy/reproduction/backtest.py（~250行）

class BacktestRunner:
    def run(self, code, data, config):
        """执行 backtrader 回测"""
        cerebro = bt.Cerebro()
        # ... 加载策略、数据、配置
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
# repro.generate 产出
code: str  # Python backtrader 策略代码

# repro.validate 产出
validation_result: {
  status: "ok" | "error",
  errors: [{line: int, message: str, severity: str}]
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

**输入**：Source Summary 页内容
**输出**：结构化 JSON（9 个字段）

关键约束：
- 必须从原文中抽取，不能编造
- 每个字段标注 confidence（HIGH/MEDIUM/LOW）
- 公式必须保留 LaTeX 格式
- 步骤必须有明确的输入→输出

```yaml
name: repro_extract
description: "从论文中抽取策略复现所需的 9 类结构化信息"

system: |
  你是一个量化论文结构化抽取器。从给定文档中提取以下 9 类信息：
  
  1. Logic（策略逻辑）— 核心假设、市场逻辑、收益来源、适用条件
  2. Data（数据需求）— 字段列表、时间粒度、标的范围、数据来源
  3. Steps（操作步骤）— 信号/仓位/换仓/止损/成本，每步有输入→输出
  4. Factors（因子）— 名称、定义、公式(LaTeX)、超参、计算周期
  5. Model（模型/框架）— 类型、框架、训练/验证划分、评价指标
  6. Analysis（优劣）— 优势、劣势、适用场景、改进方向
  7. Datasets（数据集）— 名称、来源、时间范围、处理方式
  8. Risks（风险）— 局限、假设风险、实现偏差、数据局限
  9. References（参考）— 原文引用、相关论文、代码仓库
  
  对每类信息标注 confidence: HIGH（文中明确）/ MEDIUM（可推断）/ LOW（需假设）
  
  返回 JSON，key 为上述 9 类名称。

user: |
  论文全文：
  {{ paper_content }}
  
  Source Summary：
  {{ source_summary }}
```

### 6.2 repro_codegen.yaml（代码生成）

**输入**：wiki 5 个页面（Logic/Data/Steps/Factors/Model）
**输出**：可运行的 Python 代码

```yaml
name: repro_codegen
description: "根据论文结构化信息生成 backtrader 策略代码"

system: |
  根据以下论文信息，生成完整的 backtrader 回测代码。
  
  硬性约束：
  1. 必须使用 bt.Strategy.next() 接口
  2. 必须有 params 类属性（超参与论文一致）
  3. 数据获取用 akshare（import akshare as ak）
  4. 输出 metrics dict: {sharpe, mdd, total_return, annual_return, sortino, calmar, win_rate}
  5. 禁止 import: requests, urllib, socket, subprocess, os.system
  6. 代码必须包含：数据获取、指标计算、bt.Strategy、bt.Cerebro、回测执行、指标输出
  
  代码结构：
  ```python
  import backtrader as bt
  import akshare as ak
  import pandas as pd
  
  class PaperStrategy(bt.Strategy):
      params = (...)  # 超参与论文一致
      
      def __init__(self): ...
      def next(self): ...
  
  if __name__ == "__main__":
      # 数据获取
      data = ...
      # Cerebro 配置
      cerebro = bt.Cerebro()
      cerebro.addstrategy(PaperStrategy)
      cerebro.adddata(data)
      # 执行
      results = cerebro.run()
      # 输出指标
      metrics = {...}
      print(metrics)
  ```

user: |
  策略逻辑：{{ logic }}
  数据需求：{{ data }}
  操作步骤：{{ steps }}
  因子/指标：{{ factors }}
  模型/框架：{{ model }}
```

### 6.3 repro_fix.yaml（代码修复）

**输入**：代码 + 校验错误
**输出**：修复后的代码

```yaml
name: repro_fix
description: "修复校验失败的代码"

system: |
  你是一个 Python 代码修复专家。请修复以下代码中的错误。
  
  规则：
  1. 只修复报错部分，保持其余代码不变
  2. 不能引入新的 import
  3. 不能改变策略逻辑
  4. 修复后必须通过 ruff 检查
  
  返回修复后的完整代码。

user: |
  原始代码：
  {{ code }}
  
  校验错误：
  {{ errors }}
```

### 6.4 repro_analyze_strategy.yaml（策略优劣分析）

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

### 6.5 repro_analyze_backtest.yaml（回测结果分析）

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

### 6.6 repro_plan.yaml（执行步骤拆解）

**输入**：wiki 知识库内容
**输出**：执行步骤列表

```yaml
name: repro_plan
description: "拆解策略复现的执行步骤"

system: |
  根据论文信息，拆解为具体的执行步骤。
  每个步骤包含：
  - order: 执行顺序
  - action: 做什么
  - input: 输入什么
  - output: 输出什么
  - dependency: 依赖哪个前置步骤

user: |
  策略信息：{{ extraction_json }}
```

---

## 七、SkillAction 精确设计

### 7.1 4 个 SkillAction

```python
# 1. repro.generate
class GenerateAction(SkillAction):
    name = "generate"
    description = "根据 wiki 知识库生成 backtrader 策略代码"
    input_schema = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "object",
                "description": "wiki 页面内容 {logic, data, steps, factors, model}"
            }
        },
        "required": ["pages"]
    }
    output_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "language": {"type": "string"}
        }
    }
    handler = generate_handler  # 调用 repro_codegen.yaml prompt

# 2. repro.validate
class ValidateAction(SkillAction):
    name = "validate"
    description = "校验生成的代码是否可运行"
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string"}
        },
        "required": ["code"]
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok", "error"]},
            "errors": {"type": "array"}
        }
    }
    handler = validate_handler  # ruff + AST + import 白名单

# 3. repro.fix
class FixAction(SkillAction):
    name = "fix"
    description = "修复校验失败的代码"
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "errors": {"type": "array"}
        },
        "required": ["code", "errors"]
    }
    handler = fix_handler  # 调用 repro_fix.yaml prompt

# 4. repro.sandbox
class SandboxAction(SkillAction):
    name = "sandbox"
    description = "在沙箱中执行代码"
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string"}
        },
        "required": ["code"]
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "outputs": {"type": "array"},
            "errors": {"type": "array"},
            "execution_time": {"type": "number"}
        }
    }
    handler = sandbox_handler  # KernelGateway 执行
```

---

## 八、KernelGateway 沙箱流程

```
repro.sandbox 被调用
  ↓
sandbox.py:
  1. 用 nbformat 将 code 转为 .ipynb
  2. 启动 KernelGateway 子进程（127.0.0.1:8899）
  3. 通过 jupyter_client 连接 kernel
  4. 执行 notebook，超时 120s
  5. 捕获输出（stdout/stderr/png）
  6. 销毁 kernel + 停止 gateway
  7. 返回结果

安全约束：
  - Gateway 不暴露公网，仅 127.0.0.1
  - 静态扫描禁网（requests/urllib/socket 列入 DENYLIST）
  - 输出单元格大小限制 1MB
  - 每次复现新建 Kernel，用完销毁
```

---

## 九、待确认细节

| # | 问题 | 影响 |
|---|---|---|
| 1 | AKShare A 股日线复权方式：前复权/后复权/不复权？ | 回测准确性 |
| 2 | backtrader data feed 格式：AKShare DataFrame 需怎么转换？ | backtest.py 复杂度 |
| 3 | KernelGateway：每次新建子进程 vs 常驻进程？ | 资源管理 |
| 4 | 代码生成粒度：单文件 vs 多文件？ | 生成策略 |
| 5 | 知识图谱边类型：策略→因子 用什么 relation type？ | 图谱设计 |
| 6 | WebUI：独立路由还是嵌入 Research？ | 前端工作量 |

---

## 十、简化备选方案

如果 M0 POC 发现某些环节不可行：

| 环节 | 可行时 | 简化方案 |
|---|---|---|
| KernelGateway | 用 Gateway | 降级为 subprocess + nbformat（~50行）|
| AKShare 数据 | AKShare 全覆盖 | 降级为合成数据（SynthProvider）|
| iFinD 集成 | iFinD 可用 | 砍掉，只用 AKShare |
| 修复循环 | 方式 B（LLM 驱动）| 降级为方式 A（固定 3 轮重试）|

---

## 十一、Session/DB 管理

### 复现会话表

```sql
CREATE TABLE reproduction_sessions (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    source_type TEXT NOT NULL,       -- pdf / url / arxiv / doi
    source_ref TEXT NOT NULL,        -- 文件路径 / URL / arXiv ID
    paper_title TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/extracting/reproducing/validating/backtesting/done/error
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
    kind TEXT NOT NULL,              -- extraction / code / validation / backtest / analysis
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

## 十二、触发机制

复现有 3 种方式触发复现：

### 方式 1：MCP 工具（Agent 调用）

```python
# MCP 工具 handler
async def wiki_paper_repro_start(wiki_id, source_type, source_ref):
    """启动复现会话"""
    session_id = db.create_session(wiki_id, source_type, source_ref)
    # 异步执行：ingest → extract → reproduce → backtest
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}
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

        # Phase 2: 论文结构化抽取 → 写入 wiki 页
        extract_paper_structure(wiki, session.paper_title)
        db.create_artifact(session_id, "extraction",
                          wiki_page=f"Papers/{session.paper_title}/Logic")

        # Phase 3: 复现（A+B 结合）→ 代码写入 wiki 页
        db.update_status(session_id, "reproducing")
        code = await reproduce(wiki, session.paper_title)
        wiki.write_page(f"Papers/{session.paper_title}/Code", code)
        db.create_artifact(session_id, "code",
                          wiki_page=f"Papers/{session.paper_title}/Code")

        # Phase 4: 验证（回测）→ 结果写入 wiki 页
        db.update_status(session_id, "backtesting")
        backtest_result = await run_backtest(wiki, session.paper_title, code)
        wiki.write_page(f"Papers/{session.paper_title}/Backtest", backtest_result["report"])
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

## 十三、错误处理策略

### 每层失败处理

| 层 | 失败场景 | 处理方式 |
|---|---|---|
| 输入层 | 文件格式不支持 | 返回错误，提示用户换格式 |
| 输入层 | 文件损坏/空文件 | 返回错误，提示用户检查文件 |
| 理解层 | LLM 抽取失败 | 重试 2 次，失败则标记 session 为 error |
| 理解层 | 抽取结果不完整 | 按已有内容写入，标注缺失字段 |
| 复现层 | 代码生成失败 | 重试 1 次，失败则标记 session 为 error |
| 复现层 | 校验失败 | 方式 B 修复循环（≤3 轮）|
| 复现层 | 修复循环耗尽 | 保存当前代码，标注未通过校验 |
| 验证层 | KernelGateway 启动失败 | 降级为 subprocess（备选方案）|
| 验证层 | 回测执行超时 | 终止执行，标注超时 |
| 验证层 | AKShare 数据不可用 | fallback 到 SynthProvider |
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

## 十四、测试策略

### 单元测试（每个模块独立）

| 测试文件 | 覆盖 | 行数 |
|---|---|---|
| `tests/strategy/reproduction/test_extract.py` | 论文结构化抽取 | ~100 |
| `tests/strategy/reproduction/test_skills.py` | 4 个 SkillAction | ~150 |
| `tests/strategy/reproduction/test_backtest.py` | backtrader 封装 | ~100 |
| `tests/strategy/data/test_router.py` | DataRouter | ~80 |
| `tests/strategy/data/test_akshare.py` | AKShare Provider | ~60 |

### 集成测试（端到端）

| 测试 | 内容 | 耗时 |
|---|---|---|
| `test_e2e_extract` | PDF → wiki 页面 | ~30s |
| `test_e2e_reproduce` | wiki → 代码生成 | ~60s |
| `test_e2e_backtest` | 代码 → 回测报告 | ~60s |
| `test_e2e_full` | PDF → 回测报告（全链路）| ~120s |

### Mock 策略

- LLM 调用：用固定返回值 mock（不烧 token）
- AKShare：用缓存的 DataFrame mock
- KernelGateway：用 subprocess mock

---

## 十五、wiki.md 集成方式

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

## 十六、MCP 工具实现

### 5 个 MCP 工具

```python
# 1. wiki_paper_repro_start
async def handle_start(wiki_id, source_type, source_ref):
    session_id = db.create_session(wiki_id, source_type, source_ref)
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}

# 2. wiki_paper_repro_status
async def handle_status(session_id):
    session = db.get_session(session_id)
    artifacts = db.get_artifacts(session_id)
    return {
        "status": session.status,
        "progress": session.progress,
        "artifacts": [{"kind": a.kind, "wiki_page": a.wiki_page, "score": a.score} for a in artifacts],
    }

# 3. wiki_paper_repro_report
async def handle_report(session_id):
    """从 wiki 页读取抽取结果（不从 DB 读）"""
    session = db.get_session(session_id)
    wiki = Wiki(session.wiki_id)
    extraction_page = f"Papers/{session.paper_title}/Logic"  # 示例
    return {"extraction": wiki.read_page(extraction_page)}

# 4. wiki_paper_repro_code
async def handle_code(session_id):
    """从 wiki 页读取代码（不从 DB 读）"""
    session = db.get_session(session_id)
    wiki = Wiki(session.wiki_id)
    code_page = f"Papers/{session.paper_title}/Code"
    return {"code": wiki.read_page(code_page)}

# 5. wiki_paper_repro_backtest
async def handle_backtest(session_id):
    """从 wiki 页读取回测结果（不从 DB 读）"""
    session = db.get_session(session_id)
    wiki = Wiki(session.wiki_id)
    backtest_page = session.backtest_wiki_page
    return {"backtest": wiki.read_page(backtest_page) if backtest_page else None}
```

---

## 十七、arXiv/DOI 输入适配

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

## 十八、文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `strategy/reproduction/config.py` | ~50 | AKShare/iFinD/backtest 配置 |
| `strategy/reproduction/extract.py` | ~80 | 论文结构化抽取（调 LLM + write_page）|
| `strategy/reproduction/backtest.py` | ~250 | backtrader 薄封装 |
| `strategy/reproduction/wiki_template.py` | ~50 | wiki.md 模板注入 |
| `strategy/data/router.py` | ~120 | AKShare + iFinD 路由 |
| `apps/chat/skills/actions/repro_action.py` | ~350 | 4 个 SkillAction（generate/validate/fix/sandbox）|
| `prompts/_defaults/repro_extract.yaml` | ~80 | 结构化抽取 |
| `prompts/_defaults/repro_analyze_strategy.yaml` | ~60 | 策略优劣分析 |
| `prompts/_defaults/repro_codegen.yaml` | ~100 | 代码生成 |
| `prompts/_defaults/repro_fix.yaml` | ~60 | 代码修复 |
| `prompts/_defaults/repro_analyze_backtest.yaml` | ~80 | 回测分析 |
| `prompts/_defaults/repro_plan.yaml` | ~50 | 执行步骤拆解 |
| `web/webui/src/pages/Reproduction/index.tsx` | ~200 | 主页面 |
| `web/webui/src/pages/Reproduction/NewSession.tsx` | ~150 | 新建会话 |
| `web/webui/src/pages/Reproduction/Detail.tsx` | ~200 | 详情（5个tab）|
| `web/webui/src/components/BacktestChart.tsx` | ~100 | 净值曲线 |
| `web/webui/src/components/ReadinessBadge.tsx` | ~50 | 就绪度徽章 |
| **合计** | **~1980** | **Python ~980 + YAML ~430 + TS ~700** |

---

## 十九、时间线

| 周 | 里程碑 | 交付 |
|---|---|---|
| W1 | M0 骨架 | config + 路由 + Skill 注册 + POC 验证 |
| W2-3 | M1 理解层 | 3 篇论文端到端 → wiki 页 + 图谱 + 策略分析 |
| W4-5 | M2 复现层 | Skill 生成代码 + sandbox 跑通 |
| W6-7 | M3 验证层 | AKShare/iFinD + 回测报告 + 偏差声明 |
| W8 | M4 分析层 | 结果分析 + 优化建议 + 全链路串通 |
| W9-10 | M5 Multi-input | arXiv/DOI/券商研报 |
| W11-12 | M6 测试 + RC | e2e 30+、性能、文档、v0.4.0-rc |
| W13-16 | 缓冲 | bug fix、边缘场景、优化 |

---

## 二十、M0 POC 验证（3 个快速验证）

| POC | 内容 | 耗时 | 目的 |
|---|---|---|---|
| AKShare 数据 | 能否拿到 A 股日线？期货？期权？ | 30min | 验证数据源可用性 |
| wiki.md 模板 | repro_extract prompt 能否从 Source Summary 生成正确页面？ | 1h | 验证抽取可行性 |
| KernelGateway | 能否启动 + 执行简单 notebook？ | 30min | 验证沙箱可行性 |

---

## 二十一、依赖

```toml
[project.optional-dependencies]
repro = [
  "jupyter-kernel-gateway>=2.5",
  "jupyter-client>=8.6",
  "nbformat>=5.10",
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

## 二十二、MCP 工具列表

| 工具名 | 输入 | 输出 |
|---|---|---|
| `wiki_paper_repro_start` | wiki_id, source_type, source_ref | session_id |
| `wiki_paper_repro_status` | session_id | status, progress |
| `wiki_paper_repro_report` | session_id | 抽取结果 |
| `wiki_paper_repro_code` | session_id | notebook 路径 |
| `wiki_paper_repro_backtest` | session_id, symbol, start, end | metrics, curves |

---

## 二十三、风险与缓解

| 风险 | 缓解 |
|---|---|
| 论文回测数字对不上 | UI「已知偏差」模板 + 逻辑一致 ≠ 数字一致 |
| KernelGateway 复杂度 | M0 POC 验证，失败则降级为 subprocess |
| LLM 不可重现 | seed + low temp + prompt 版本号 |
| iFinD 无 token | fallback 到 AKShare |
| 券商研报 OCR 成本 | 仅按需触发 |
| 代码生成质量 | 三层校验 + smoke test |
