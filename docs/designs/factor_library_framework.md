# 因子库框架设计文档

## 1. 概述

### 1.1 目标

建立基于 6 层方法论的因子库框架，覆盖因子定义、计算、理解、假设、验证、风险管理全流程。

### 1.2 核心原则

- **6 层分离**：每层职责清晰，不混淆
- **假设驱动**：L4 提出假设，L5 检验假设
- **逻辑沉淀**：L4 在假设之外沉淀因子含义，验证后回填 final_meaning
- **自动化验证**：L5 因子分析由 LLM 自动执行
- **版本控制**：因子修改需记录版本

### 1.3 与文章的对应关系

| 文章原版 | 本框架 | 差异说明 |
|---|---|---|
| L1 代码功能层 | **L1 逻辑层** | 合并文章 L1+L2，去掉代码实现 |
| L2 数学定义层 | **L2 计算定义层** | 聚焦代码实现 |
| L3 金融直觉层 | **L3 金融理解层** | 一致 |
| L4 因子含义层 | **L4 因子含义层** | 增加假设驱动 + 逻辑沉淀 |
| L5 因子验证层 | **L5 验证层** | 增加自动化 + 全量因子分析 |
| L6 边界和风险层 | **L6 风险层** | 增加分阶段（P0/P1） |

## 2. 6 层框架定义

### 2.1 框架总览

| 层 | 名称 | 回答的问题 | 产出物 |
|---|---|---|---|
| **L1** | 逻辑层 | 这个因子是什么？公式怎么写？ | 因子定义 + 数学公式 |
| **L2** | 计算定义层 | 代码里怎么实现这个公式？ | 计算步骤 + 代码实现 |
| **L3** | 金融理解层 | 这个指标在金融里描述了什么？ | 金融直觉 + 理论基础 |
| **L4** | 因子含义层 | 提出假设 + 沉淀逻辑 | 假设列表 + 因子含义总结 |
| **L5** | 验证层 | 因子分析 + 假设检验 | 全量分析 + 检验结论 + 综合评估 |
| **L6** | 风险层 | 什么时候失效？暴露什么风险？ | 风险诊断 + 失效条件 |

### 2.2 核心循环

```
L4 提出假设 + 沉淀逻辑
    ↓
L5 因子分析 + 假设检验
    ↓
L4 回填 final_meaning
    ↓
L6 识别失效条件
    ↓
（可能回到 L4 修正假设）
```

### 2.3 每层填写方式

| 层 | 填写方式 | 说明 |
|---|---|---|
| L1 | 人工或 LLM | 因子定义需要人工确认 |
| L2 | 人工或 LLM | 计算步骤需要与代码一致 |
| L3 | 人工或 LLM | 金融理解需要领域知识 |
| L4 | LLM | LLM 根据 L3 提出假设 + 沉淀逻辑 |
| L5 | LLM 自动 | LLM 执行全量因子分析 + 检验假设 |
| L6 | LLM | LLM 分析失效条件 |

### 2.4 L1 逻辑层

**回答的问题**：这个因子是什么？公式怎么写？

| 字段 | 说明 | 示例 |
|---|---|---|
| 因子定义 | 一句话 | 过去20个交易日的涨跌幅 |
| 数学公式 | 公式 | f_t = close_t / close_{t-20} - 1 |
| 输入列 | 需要哪些数据 | [close] |
| 数据频率 | 日频/周频/月频 | 日频 |
| 输出 schema | 输出格式 | [date × Code] |
| NaN 含义 | 输出为 NaN 时代表什么 | 早期数据不足20日 |
| 默认参数 | 默认值及原因 | period=20（约1个月） |
| 参数约束 | 合法范围 | period ≥ 5 |
| 业务约束 | 不能用的情况 | 个股上市不足period日时不可算 |
| 代码位置 | 定义在哪个文件 | factor_backtest.py:_compute_factor_values |

### 2.5 L2 计算定义层

**回答的问题**：代码里怎么实现这个公式？

| 字段 | 说明 | 示例 |
|---|---|---|
| 计算步骤 | 分步骤描述 | 1. 取close序列 2. 计算pct_change(20) |
| 中间产物 | 计算过程中的数据 | 日收益率序列、20日滚动窗口 |
| 边界处理 | 前period个数据如何处理 | 前20个日期输出NaN |
| 缺失值处理 | 输入有NaN时怎么处理 | 保持NaN（不插值） |
| 数据对齐 | 因子日期与价格日期如何对齐 | 因子日期 = 价格日期（同一天） |
| 计算复杂度 | 时间复杂度 | O(T × N) |

### 2.6 L3 金融理解层

**回答的问题**：这个指标在金融里描述了什么？

| 字段 | 说明 | 示例 |
|---|---|---|
| 金融直觉 | 描述了什么 | 过去20天市场对该股票的认可程度 |
| 市场行为刻画 | 刻画了什么市场行为 | 价格相对于近期均值的偏离 |
| 理论基础 | 基于什么金融理论 | 行为金融学的锚定效应、动量效应 |
| 历史有效性 | 在A股/全球市场的历史表现 | 短期动量在A股2010-2020年有效 |
| 与同类因子的关系 | 与相关因子的区别/联系 | 与反转因子方向相反 |

### 2.7 L4 因子含义层

**回答的问题**：这个因子可能预测什么？（提出假设 + 沉淀逻辑）

#### 假设提出

| 字段 | 说明 | 示例 |
|---|---|---|
| 假设列表 | 多个待检验的假设 | H1 动量延续、H2 反转回落、H3 波动放大 |
| 每个假设的预期 IC 符号 | 预期正/负 | H1: 正, H2: 负 |
| 假设来源 | 基于什么理论或经验 | 行为金融学、市场微观结构 |
| 假设优先级 | 主假设 vs 辅助假设 | H1 为主假设，H2-H5 为辅助 |
| 假设限制 | 最多几个未验证 | 5 |
| 已验证假设归档 | 已验证的假设 | archived_hypotheses |

#### 逻辑沉淀

| 字段 | 说明 | 示例 |
|---|---|---|
| meaning_summary | 因子含义总结 | 20日动量因子捕捉股票在近20个交易日内的价格趋势。如果H1成立：趋势跟随信号；如果H2成立：反转信号 |
| key_insights | 关键洞察 | 短期动量在A股可能表现为反转（与美股不同）；动量与波动率因子可能存在交互效应 |
| uncertainty | 不确定性说明 | 因子含义尚不明确，需L5验证后确定 |

#### 验证后回填

| 字段 | 说明 | 示例 |
|---|---|---|
| final_meaning | 验证后确定的因子含义 | 反转因子（H2成立） |

### 2.8 L5 验证层

**回答的问题**：因子分析 + 假设检验

#### 因子分析

| 模块 | 内容 |
|---|---|
| IC 分析 | IC / RankIC / ICIR / RankICIR / IC t-stat / IC 正比例 |
| 分组分析 | 分组收益（G1-G5）/ 分组单调性 / 多空收益 / 多空 NAV / 多空 Sharpe / 最大回撤 |
| 收益分析 | 年化收益 / 年化波动率 / Sharpe / Calmar / Sortino / 最大回撤 |
| 换手分析 | 平均换手率 / 换手率标准差 / 换手率分布 |
| 稳定性分析 | 分年度表现 / 分行业表现 / 分市值组表现 |
| 样本外分析 | OOS RankIC / OOS 分组收益 / OOS 多空收益 / OOS Sharpe |
| 成本分析 | 交易成本假设 / 扣除成本后收益 / 成本敏感度 |

#### 假设检验

| 字段 | 说明 |
|---|---|
| hypothesis_testing | L4 每个假设的检验结果 |
| conclusion | 支持 / 不支持 / 部分支持 |

#### 综合评估

| 字段 | 说明 | 示例 |
|---|---|---|
| score | 因子综合评分（0-100） | 45 |
| status | 通过 / 待更新 / 失败 | 待更新 |
| final_meaning | 验证后确定的因子含义 | 反转因子（H2成立） |
| validation_date | 验证日期范围 | 2024-01-01~2024-07-19 |

### 2.9 L6 风险层

**回答的问题**：什么时候失效？暴露什么风险？

| 字段 | 说明 | P0/P1 |
|---|---|---|
| window_sensitivity | 不同窗口期的表现差异 | P0 |
| regime_sensitivity | 牛市/熊市/震荡的表现差异 | P0 |
| style_exposure | 暴露于哪些风格因子 | P0 stub，P1 接入外部风格因子库 |
| industry_concentration | 因子是否集中在某些行业 | P0 |
| crowding_level | 因子是否被过度使用 | P0 |
| decay_analysis | 预测力随持有期如何变化 | P0 |
| failure_conditions | 什么时候因子会失效 | P0 |
| risk_notes | 使用该因子时的风险 | P0 |

## 3. 因子命名规范

### 3.1 四段式命名

```
{资产类型}_{类别}_{子类}_{参数}
```

### 3.2 资产类型

| 资产类型 | 代码前缀 | 说明 |
|---|---|---|
| 股票 | stock | A 股、港股、美股等 |
| 期货 | futures | 商品期货、股指期货、国债期货 |
| 期权 | options | 场内期权、场外期权 |

### 3.3 类别与子类

| 类别 | 代码 | 子类 |
|---|---|---|
| 价量因子 | price | momentum / reversal / volatility / liquidity / volume |
| 基本面因子 | fundamental | value / growth / quality / size |
| 复合因子 | composite | signal |

### 3.4 命名示例

- `stock_price_momentum_20d` — 股票-价量-动量-20日
- `stock_price_volatility_20d` — 股票-价量-波动-20日
- `stock_fundamental_value_60d` — 股票-基本面-估值-60日
- `futures_price_basis_5d` — 期货-价量-基差-5日
- `options_price_implied_vol_20d` — 期权-价量-隐含波动-20日

## 4. 因子分类体系

```
价量因子 (price)
├── 动量类 (momentum)
│   ├── stock_price_momentum_5d
│   ├── stock_price_momentum_20d
│   └── stock_price_momentum_60d
├── 反转类 (reversal)
│   └── stock_price_reversal_5d
├── 波动类 (volatility)
│   └── stock_price_volatility_20d
├── 流动类 (liquidity)
│   └── stock_price_turnover_20d
└── 成交量类 (volume)
    └── stock_price_volume_ratio

基本面因子 (fundamental)
├── 估值类 (value)
│   └── stock_fundamental_value_60d
├── 成长类 (growth)
│   └── stock_fundamental_growth_60d
├── 质量类 (quality)
│   └── stock_fundamental_quality_20d
└── 规模类 (size)
    └── stock_fundamental_size

复合因子 (composite)
└── 信号类 (signal)
    └── stock_composite_signal_mom_vol
```

## 5. 因子 YAML 结构

### 5.1 完整结构

```yaml
factor:
  # === 元数据 ===
  name: stock_price_momentum_20d
  name_cn: 股票20日动量
  asset_type: stock
  category: price
  subcategory: momentum
  version: 1
  created_at: 2024-01-01
  updated_at: 2024-07-19
  status: 已注册

  # === L1 逻辑层 ===
  l1:
    definition: 过去20个交易日的涨跌幅
    formula: f_t = close_t / close_{t-20} - 1
    input_columns: [close]
    frequency: 日频
    output_schema: "[date × Code]"
    nan_meaning: 早期数据不足20日
    default_params: { period: 20 }
    param_constraints: { period: "≥5" }
    business_constraints: 个股上市不足period日时不可算
    code_location: factor_backtest.py:_compute_factor_values

  # === L2 计算定义层 ===
  l2:
    calculation_steps:
      - step: 1
        description: 取close序列
        input: close_wide [date × Code]
        output: close_series [date × scalar]
      - step: 2
        description: 计算20日收益率
        input: close_series
        output: factor_wide [date × Code]
        formula: f_t = close_t / close_{t-20} - 1
    edge_case_handling: 前20个日期输出NaN
    missing_value_handling: 保持NaN（不插值）
    data_alignment: 因子日期 = 价格日期（同一天）
    complexity: O(T × N)

  # === L3 金融理解层 ===
  l3:
    financial_intuition: 过去20天市场对该股票的认可程度
    market_behavior: 价格相对于近期均值的偏离
    theoretical_basis: 行为金融学的锚定效应、动量效应
    historical_effectiveness: 短期动量在A股2010-2020年有效
    related_factors: 与反转因子方向相反；与波动率因子无直接关系

  # === L4 因子含义层 ===
  l4:
    hypotheses:
      - id: H1
        name: 动量延续
        description: 高动量→未来继续涨
        expected_ic_sign: 正
        source: 行为金融学动量效应
        priority: 主假设
        status: 未验证
      - id: H2
        name: 反转回落
        description: 高动量→未来反而跌（过热）
        expected_ic_sign: 负
        source: 过度反应理论
        priority: 辅助假设
        status: 未验证
      - id: H3
        name: 波动放大
        description: 高动量→波动率增大
        expected_ic_sign: 正（与波动率因子相关）
        source: 市场微观结构
        priority: 辅助假设
        status: 未验证
    hypothesis_limit: 5
    archived_hypotheses: []
    meaning_summary: |
      20日动量因子捕捉股票在近20个交易日内的价格趋势。
      - 如果H1成立：趋势跟随信号
      - 如果H2成立：反转信号
      - 实际含义取决于L5验证结果
    key_insights:
      - 短期动量在A股可能表现为反转（与美股不同）
      - 动量与波动率因子可能存在交互效应
    uncertainty: |
      因子含义尚不明确，需L5验证后确定：
      1. 如果H1成立：趋势跟随因子
      2. 如果H2成立：反转因子
      3. 如果H3成立：波动放大因子
    final_meaning: null  # L5验证后回填

  # === L5 验证层 ===
  l5:
    factor_analysis:
      ic_analysis:
        ic_mean: -0.044
        ic_std: 0.05
        icir: -0.88
        rank_ic_mean: -0.044
        rank_ic_std: 0.05
        rank_icir: -0.88
      group_analysis:
        group_returns: {G1: 0.05, G2: 0.03, G3: 0.01, G4: -0.02, G5: -0.05}
        group_monotonicity: G1>G2>G3>G4>G5
        ls_ann_return: -0.538
        ls_sharpe: -2.132
        ls_max_drawdown: 0.15
      return_analysis:
        ann_return: -0.538
        ann_volatility: 0.25
        sharpe: -2.132
        max_drawdown: 0.15
        calmar: -3.587
        sortino: -2.8
      turnover_analysis:
        avg_turnover: 0.35
        turnover_std: 0.1
      stability_analysis:
        yearly: {2024: {rank_ic: -0.04, ls_return: -0.5}}
        industry: {金融: {rank_ic: -0.06}, 消费: {rank_ic: -0.03}}
        market_cap: {大盘: {rank_ic: -0.05}, 中盘: {rank_ic: -0.04}, 小盘: {rank_ic: -0.03}}
      oos_analysis:
        oos_rank_ic: -0.039
        oos_ls_return: -0.45
        oos_sharpe: -1.8
      cost_analysis:
        cost_bps: 15
        net_ann_return: -0.65
        cost_sensitivity: {5bp: -0.58, 10bp: -0.62, 15bp: -0.65, 20bp: -0.68}
    hypothesis_testing:
      - hypothesis_id: H1
        conclusion: 不支持（反向）
      - hypothesis_id: H2
        conclusion: 支持
      - hypothesis_id: H3
        conclusion: 支持
    overall_assessment:
      score: 45
      status: 待更新
      final_meaning: 反转因子（H2成立）
    validation_date: 2024-01-01~2024-07-19

  # === L6 风险层 ===
  l6:
    window_sensitivity: {5: -0.02, 20: -0.04, 60: -0.06}
    regime_sensitivity: {bull: 有效, bear: 失效, sideways: 中性}
    style_exposure: {size: 0.3, value: 0.1, momentum: 0.0}
    industry_concentration: 中等
    crowding_level: 中等
    decay_analysis: {1d: 有效, 5d: 有效, 20d: 衰减, 60d: 失效}
    failure_conditions: 市场剧烈反转时、流动性危机时
    risk_notes: 可能暴露于系统性风险
```

## 6. 因子目录结构

```
factors/
├── index.yaml                    # 因子目录索引（包含所有因子摘要）
├── README.md                     # 因子库使用说明
├── stock/
│   ├── price/
│   │   ├── momentum_20d.yaml     # 模板 1：动量因子
│   │   └── volatility_20d.yaml   # 后续扩展
│   └── fundamental/
│       └── value_60d.yaml        # 模板 2：估值因子
├── futures/                      # 后续扩展
└── options/                      # 后续扩展
```

## 7. L4 假设生命周期

```
未验证 (unverified)
    ↓ LLM 决定检验
验证中 (verifying)
    ↓ 检验完成
支持 (supported) / 不支持 (unsupported) / 部分支持 (partial)
    ↓ 归档
归档 (archived)
```

## 8. L5 自动检验流程

```
触发条件：用户请求验证 / 定时任务 / 新因子注册
    ↓
LLM 读取 L4 假设列表
    ↓
LLM 执行全量因子分析（IC / 分组 / 收益 / 换手 / 稳定性 / OOS / 成本）
    ↓
LLM 检验 L4 每个假设
    ↓
更新 YAML（因子分析结果 + 假设状态 + 综合评估）
    ↓
L4 回填 final_meaning
    ↓
生成验证报告（HTML）
```

## 9. 因子详情页内容板块

| 板块 | 内容 | 层级 | 展示形式 |
|---|---|---|---|
| 因子卡片 | 名称、类别、一句话描述、验证状态 | L1+L4+L5 | 顶部卡片 |
| 逻辑定义 | 一句话定义、数学公式、输入列、输出 schema、默认参数、约束 | L1 | 文本 + 公式 + 参数表 |
| 计算过程 | 计算步骤、代码实现、中间产物、边界处理 | L2 | 流程图 + 代码片段 |
| 金融理解 | 金融直觉、理论基础、历史有效性 | L3 | 文本段落 |
| 因子含义 | 假设列表 + 因子含义总结 + 关键洞察 + 不确定性 | L4 | 假设卡片 + 文本段落 |
| 验证结果 | 因子分析（IC/分组/收益/换手/稳定性/OOS/成本）+ 假设检验 + 综合评估 | L5 | 图表 + 表格 |
| 风险诊断 | 窗口敏感度、市场环境对比、风格暴露雷达图 | L6 | 图表 |
| 历史版本 | 因子修改记录、验证更新记录 | 全部 | 时间线 |

## 10. 因子目录展示

按类别分组：

```
价量因子
├── 动量类
│   ├── stock_price_momentum_20d — 待验证
│   └── stock_price_momentum_60d — 已通过
├── 波动类
│   └── stock_price_volatility_20d — 已通过
└── ...

基本面因子
├── 估值类
│   └── stock_fundamental_value_60d — 待验证
└── ...
```

## 11. 实施计划

| 步骤 | 内容 | 文件 |
|---|---|---|
| 1 | 写设计文档（本文档） | `docs/designs/factor_library_framework.md` |
| 2 | 创建 factors/ 目录结构 | `factors/stock/price/` `factors/stock/fundamental/` |
| 3 | 写模板因子 YAML（stock_price_momentum_20d） | `factors/stock/price/momentum_20d.yaml` |
| 4 | 写第二个模板因子 YAML（stock_fundamental_value_60d） | `factors/stock/fundamental/value_60d.yaml` |
| 5 | 写 index.yaml 索引 | `factors/index.yaml` |
| 6 | 写 README 说明 | `factors/README.md` |

## 12. 第一批模板因子

### 12.1 stock_price_momentum_20d

- 选择理由：最经典、最常用、6 层最容易写清楚
- 已有代码：factor_backtest.py:_compute_factor_values

### 12.2 stock_fundamental_value_60d

- 选择理由：覆盖基本面因子、与动量因子形成对比
- 已有代码：factor_backtest.py:_compute_factor_values

## 13. 待深入讨论

- [ ] L5 综合评估的评分规则
- [ ] L6 风格暴露的 P1 接入方案
- [ ] 因子详情页的 UI 交互设计
- [ ] L5 自动检验的触发机制
- [ ] 因子版本控制的具体实现
