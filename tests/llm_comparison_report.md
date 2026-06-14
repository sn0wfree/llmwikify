# LLM 调用对比测试报告

## 测试概述

比较两种 Paper → Factor 6-layer YAML 提取路径的输出质量：

- **Path A（两次调用）**：`repro_extract.yaml` → `repro_factor.yaml` → 代码合并
- **Path B（一次调用）**：`repro_factor_full.yaml` → 直接输出 6-layer 结构

## 测试条件

- **LLM**: minimax-M2.7 (从 `~/.llmwikify/llmwikify.json` 读取)
- **温度**: 0.1
- **测试论文**: Fama-French 1993 三因子模型 + Engle 2002 DCC-GARCH

## 评分标准

每个维度 0-5 分：

- 0: 完全缺失
- 1: 存在但无意义（TBD/placeholder）
- 2: 有内容但不准确
- 3: 基本准确但不完整
- 4: 准确且完整
- 5: 准确、完整、有深度

## 评分结果

### fama_french_1993

| 维度 | 权重 | Path A | Path B | Winner |
|---|---|---|---|---|
| L1 formula质量 (20%) | 20% | 4.5 | 4.5 | Tie |
| L1 完整度 (10%) | 10% | 4.4 | 3.3 | **A** |
| L2 计算步骤 (10%) | 10% | 4.5 | 3.5 | **A** |
| L3 金融理解 (20%) | 20% | 5.0 | 4.2 | **A** |
| L4 假设质量 (25%) | 25% | 5.0 | 5.0 | Tie |
| factor_class (15%) | 15% | 3.0 | 5.0 | **B** |
| **加权总分** | - | **89.9** | **88.3** | - |
| 耗时 (秒) | - | 0.0 | 0.0 | - |
| Token (近似) | - | 0 | 0 | - |

### engle_2002_dcc

| 维度 | 权重 | Path A | Path B | Winner |
|---|---|---|---|---|
| L1 formula质量 (20%) | 20% | 4.5 | 4.5 | Tie |
| L1 完整度 (10%) | 10% | 4.4 | 4.4 | Tie |
| L2 计算步骤 (10%) | 10% | 4.5 | 3.5 | **A** |
| L3 金融理解 (20%) | 20% | 4.6 | 4.2 | **A** |
| L4 假设质量 (25%) | 25% | 5.0 | 4.5 | **A** |
| factor_class (15%) | 15% | 5.0 | 5.0 | Tie |
| **加权总分** | - | **94.5** | **88.4** | - |
| 耗时 (秒) | - | 0.0 | 0.0 | - |
| Token (近似) | - | 0 | 0 | - |

## 详细输出对比

### fama_french_1993 — Path A 输出

```yaml
factor:
  name: stock_fundamental_fama_french_three_factor_model_portfolio
  name_cn: Fama-French Three-Factor Model Portfolio
  asset_type: stock
  category: price
  subcategory: signal_composite
  version: 1
  status: 已注册
  l1:
    definition: Combined factor portfolio that implements long-short strategies based
      on both size and value characteristics, capturing premiums from both SMB and
      HML simultaneously
    formula: R_i,t - Rf,t = α_i + β_i MKT_t + s_i SMB_t + h_i HML_t + ε_i,t
    input_columns:
    - monthly_return
    - market_cap
    - book_to_market
    frequency: 月频
    output_schema: '[date × Code]'
    nan_meaning: TBD
    default_params:
      universe: NYSE/AMEX/NASDAQ common stocks
      data_sources:
      - CRSP
      - Compustat
      breakpoints: NYSE size and B/M percentiles
      formation_month: June (using prior fiscal year book equity)
    param_constraints:
      universe: Exclude REITs, ADRs, stocks with price < $5
      look_ahead: Book equity must be lagged minimum 6 months from fiscal year-end
    business_constraints: Factor construction requires simultaneous access to CRSP
      and Compustat; factors available for download from French Data Library. Transaction
      costs from annual rebalancing must be considered
  l2:
    calculation_steps:
    - step: 1
      description: Obtain June-end market cap and prior fiscal year-end book equity
        for all stocks
      formula: B/M_i = Book_Equity_i / Market_Cap_i (June-end)
    - step: 2
      description: Sort stocks by size (median NYSE) and B/M (30th/70th NYSE percentiles)
      formula: '6 portfolios: S/L, S/M, S/H, B/L, B/M, B/H'
    - step: 3
      description: Calculate monthly value-weighted returns for each portfolio
      formula: R_p,t = Σ(MV_i / MV_p) × R_i,t
    - step: 4
      description: Compute factor returns
      formula: SMB = avg(S/L,S/M,S/H) - avg(B/L,B/M,B/H); HML = avg(S/H,B/H) - avg(S/L,B/L)
    - step: 5
      description: Form long-short trading portfolio (e.g., long S/H, short B/L)
      formula: Factor_Portfolio_t = R_S/H,t - R_B/L,t
    edge_case_handling: Delisted stocks use CRSP delisting return; M&A survivors use
      surviving firm returns; stock splits adjusted via CRSP adjustment factors
    missing_value_handling: Exclude stocks with < 24 months of returns; missing book
      equity replaced with industry median
    data_alignment: T+1
    complexity: O(T × N × K) where K is number of portfolios (6)
  l3:
    financial_intuition: The combined factor portfolio exploits systematic return
      patterns related to firm characteristics (size and value) that are not explained
      by market beta alone. Long small-cap value, short large-cap growth captures
      both size and value premiums simultaneously
    market_behavior: Factor portfolio earns positive returns when value stocks outperform
      growth and small stocks outperform large. Correlation with market is low by
      construction (factors are orthogonalized). Performance peaks during economic
      recoveries and value up-cycles
    theoretical_basis: Fama-French (1993) demonstrate that MKT, SMB, and HML jointly
      explain 90%+ of diversified portfolio variation. Combined factors explain cross-sectional
      returns better than CAPM alone
    historical_effectiveness: Combined S/H - B/L portfolio earned approximately 8-10%
      annualized excess return (1963-1991). R² of factor model ~ 0.90 vs. ~ 0.70 for
      CAPM. GRS test rejects CAPM at 1% level
    related_factors: Foundation for Fama-French Five-Factor Model (adds RMW, CMA).
      Basis for Carhart Four-Factor Model (adds momentum). Extends to quality-factor
      and profitability-factor models
  l4:
    hypotheses:
    - id: H1
      name: Three-Factor Pricing
      description: MKT, SMB, and HML jointly explain cross-sectional variation in
        expected stock returns
      expected_ic_sign: 正
      source: Fama-French (1993)
      priority: 主假设
    - id: H2
      name: Factor Portfolio Alpha
      description: Well-constructed factor portfolios (long SMB/HML, short opposite)
        should have alpha close to zero
      expected_ic_sign: 正
      source: Fama-French (1993)
      priority: 主假设
    - id: H3
      name: Explanatory Power
      description: Three-factor model explains significantly more return variation
        than CAPM alone
      expected_ic_sign: 正
      source: Fama-French (1993)
      priority: 辅助假设
    - id: H4
      name: Bond Market Integration
      description: Same three factors explain cross-sectional variation in bond returns
      expected_ic_sign: 正
      source: Fama-French (1993) bond paper
      priority: 辅助假设
    meaning_summary: Combined factor portfolio implementing the Fama-French three-factor
      model, capturing systematic premiums from size and value characteristics while
      controlling for market risk
    key_insights:
    - Three factors explain ~90% of diversified portfolio variance vs. ~70% for CAPM
    - Factor premiums are time-varying and regime-dependent
    - Factor decay is documented post-publication, suggesting arbitrage pressure
    - Model is foundational for modern factor investing and asset pricing research
    uncertainty: Whether factors represent risk premia or behavioral anomalies remains
      debated. Factor decay post-1993 raises questions about economic interpretation.
      Hundreds of proposed factors create 'factor zoo' problem
  l5: {}
  l6: {}

```

### fama_french_1993 — Path B 输出

```yaml
factor:
  name: stock_price_
  name_cn: 市场超额收益因子
  asset_type: stock
  category: price
  subcategory: signal
  version: 1
  status: 已注册
  l1:
    definition: 市场投资组合收益率与无风险利率之差，捕捉系统性市场风险溢价
    formula: MKT_t = R_{m,t} - R_{f,t}
    input_columns:
    - market_return
    - risk_free_rate
    frequency: 月频
    output_schema: '[date × Code]'
    nan_meaning: TBD
    default_params: {}
    param_constraints: {}
    business_constraints: 使用完整市场指数（NYSE、AMEX、NASDAQ加权指数），需扣除无风险利率
  l2:
    calculation_steps:
    - step: 1
      description: 计算市场加权组合收益率
      formula: R_{m,t} = \sum_{i=1}^{N} w_i R_{i,t}
    - step: 2
      description: 获取无风险利率（如国库券利率）
      formula: R_{f,t}
    - step: 3
      description: 计算市场超额收益
      formula: MKT_t = R_{m,t} - R_{f,t}
    edge_case_handling: 无交易日期使用前一日利率；市场指数缺失时使用等权重组合
    missing_value_handling: 无风险利率缺失使用上一个可用值
    data_alignment: T+1
    complexity: O(T)
  l3:
    financial_intuition: 投资者承担系统性市场风险应获得的风险溢价补偿，反映整体经济状态和投资者风险偏好
    market_behavior: 捕捉大盘整体走势，在市场上涨时为正，下跌时为负，与经济周期高度相关
    theoretical_basis: CAPM理论核心，Sharpe-Lintner定价模型
    historical_effectiveness: 1963-1991年月均0.40%，年化4.8%，t统计量3.5，统计显著
    related_factors: 是三因子模型的基础因子，与SMB、HML共同构成系统性风险来源
  l4:
    hypotheses:
    - id: H1
      name: 市场溢价假设
      description: 市场超额收益MKT应与股票预期收益正相关，高市场溢价时期股票平均收益更高
      expected_ic_sign: 正
      source: CAPM理论：系统性风险越高，预期收益越高
      priority: 主假设
    - id: H2
      name: β定价假设
      description: 股票的β系数应能解释其横截面收益差异，高β股票收益更高
      expected_ic_sign: 正
      source: Sharpe-Lintner CAPM
      priority: 辅助假设
    meaning_summary: MKT是三因子模型的核心因子，代表整体市场风险暴露，是所有股票共有因子载荷
    key_insights:
    - 市场因子解释了大部分股票收益率的共同变动
    - 危机时期市场因子波动剧烈，导致股票齐跌
    - 三因子模型中MKT alone解释约75-85%的收益率变动
    uncertainty: CAPM的β是否能完全解释收益仍存争议；三因子模型后仍发现异常收益
  l5: {}
  l6: {}

```

### engle_2002_dcc — Path A 输出

```yaml
factor:
  name: stock_fundamental_dcc_correlation
  name_cn: DCC_Correlation
  asset_type: stock
  category: price
  subcategory: volatility
  version: 1
  status: 已注册
  l1:
    definition: Dynamic conditional correlation that evolves over time based on past
      standardized residuals, capturing correlation regime changes
    formula: Q_t = (1 - a - b) * Q_bar + a * (e_{t-1} * e_{t-1}') + b * Q_{t-1}; R_t
      = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2}
    input_columns:
    - returns
    - standardized_residuals
    frequency: 日频
    output_schema: '[date × Code]'
    nan_meaning: TBD
    default_params:
      a: 0.06
      b: 0.94
      window: 500
    param_constraints:
      a: '>= 0, < 1'
      b: '>= 0, < 1'
      a + b: < 1 (ensures stationarity)
    business_constraints: Requires univariate GARCH estimation first; computationally
      feasible for N <= 100 assets
  l2:
    calculation_steps:
    - step: 1
      description: Fit univariate GARCH(1,1) to each asset
      formula: σ_i,t² = ω_i + α_i * ε_i,t-1² + β_i * σ_i,t-1²
    - step: 2
      description: Compute standardized residuals
      formula: e_i,t = r_i,t / σ_i,t
    - step: 3
      description: Estimate unconditional correlation matrix
      formula: Q_bar = T^(-1) * Σ(e_t * e_t')
    - step: 4
      description: Recursively update DCC correlation matrix
      formula: Q_t = (1-a-b) * Q_bar + a * (e_{t-1} * e_{t-1}') + b * Q_{t-1}
    - step: 5
      description: Normalize to obtain correlation matrix
      formula: R_t = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2}
    edge_case_handling: Ensure positive definiteness via Q_bar initialization; use
      near-benchmark correlation if matrix becomes non-positive definite
    missing_value_handling: Listwise deletion within rolling window; require minimum
      60% data coverage
    data_alignment: T+1
    complexity: O(T × N²) for N assets and T time periods
  l3:
    financial_intuition: Correlations are not constant but rise during market stress.
      DCC captures this by making correlations respond to shock innovations while
      maintaining persistence from historical patterns.
    market_behavior: 'Detects correlation regime shifts: low stable correlations during
      normal periods, rapid correlation spikes during crises'
    theoretical_basis: Engle (2002) DCC-GARCH model extending Bollerslev (1990) CCC
      framework with time-varying correlations
    historical_effectiveness: Empirically validated on stocks, bonds, currencies;
      outperforms constant correlation models in crisis periods
    related_factors: Related to implied correlation, VIX, cross-asset correlation
      metrics; complements volatility factor for portfolio construction
  l4:
    hypotheses:
    - id: H1
      name: Correlation Regime Shift Hypothesis
      description: DCC correlations detect regime changes earlier than constant correlation
        models
      expected_ic_sign: 正
      source: DCC model captures time-varying nature of correlations
      priority: 主假设
    - id: H2
      name: Crisis Correlation Spike Hypothesis
      description: DCC correlations increase significantly during market stress periods
      expected_ic_sign: 正
      source: Engle 2002 empirical findings
      priority: 主假设
    - id: H3
      name: Correlation Mean Reversion Hypothesis
      description: DCC correlations revert toward long-term average after shock dissipation
      expected_ic_sign: 正
      source: DCC structure with (1-a-b)Q_bar term
      priority: 辅助假设
    meaning_summary: Captures the dynamic, regime-dependent nature of inter-asset
      correlations enabling better portfolio risk estimation and dynamic hedging
    key_insights:
    - 'Parsimonious: reduces parameters from O(N^4) to O(N^2 + 2) for N assets'
    - Guarantees positive definite correlation matrices
    - Two-step estimation enables scalability to large asset universes
    uncertainty: Parameter sensitivity to estimation window; assumes symmetric response
      to positive/negative shocks
  l5: {}
  l6: {}

```

### engle_2002_dcc — Path B 输出

```yaml
factor:
  name: stock_signal_dcc
  name_cn: 动态条件相关系数 (DCC)
  asset_type: stock
  category: signal
  subcategory: volatility
  version: 1
  status: 已注册
  l1:
    definition: 基于DCC-GARCH模型估计的时变条件相关系数，捕捉资产间相关性随市场状态动态变化的特征
    formula: R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}, Q_t = (1-\alpha-\beta)\bar{Q}
      + \alpha u_{t-1}u_{t-1}' + \beta Q_{t-1}
    input_columns:
    - 多资产收益率序列
    frequency: 日频
    output_schema: '[date × Code]'
    nan_meaning: TBD
    default_params:
      garch_order:
      - 1
      - 1
      dcc_order:
      - 1
      - 1
      alpha: 0.07
      beta: 0.9
    param_constraints:
      alpha: ≥ 0
      beta: ≥ 0
      alpha + beta: < 1 (保证平稳性)
    business_constraints: 需要至少500-1000个观测点估计GARCH参数；仅适用于存在条件异方差性的资产
  l2:
    calculation_steps:
    - step: 1
      description: 对每个资产i单独拟合GARCH(1,1)模型
      formula: \sigma_{i,t}^2 = \omega_i + \alpha_i \epsilon_{i,t-1}^2 + \beta_i \sigma_{i,t-1}^2
    - step: 2
      description: 计算标准化残差
      formula: u_{i,t} = \epsilon_{i,t} / \sigma_{i,t}
    - step: 3
      description: 使用两步法估计DCC参数(α, β)
      formula: Q_t = (1-\alpha-\beta)\bar{Q} + \alpha u_{t-1}u_{t-1}' + \beta Q_{t-1}
    - step: 4
      description: 将Q矩阵标准化为相关系数矩阵
      formula: R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}
    - step: 5
      description: 提取任意资产对(i,j)的DCC相关系数
      formula: \rho_{ij,t} = R_{t,ij}
    edge_case_handling: 当资产收益接近常数时GARCH方差可能退化；Q矩阵可能数值不稳定需检查特征根
    missing_value_handling: 对缺失值采用成对删除或前向填充；重新拟合时需足够连续数据
    data_alignment: T+1
    complexity: O(N²T) 其中N为资产数，T为时间序列长度
  l3:
    financial_intuition: 资产相关性并非固定常数，而是在市场平静期较低、在压力期升高——即'危机相关'现象。投资者分散化收益在最需要时反而减少
    market_behavior: 刻画了金融市场的两个关键现象：1) 正常市场下相关性低且稳定；2) 危机时期相关性急剧上升趋近于1
    theoretical_basis: 基于Bollerslev (1990) CCC模型的扩展，通过两步估计避免VEVH模型参数爆炸，同时保证正定性
    historical_effectiveness: 2008年金融危机期间DCC成功捕捉到股票-债券相关性从负转正的关键转折点
    related_factors: 与Diebold-Yilmaz溢出指数相关但侧重相关结构而非波动溢出；与协方差矩阵估计中的因子模型互补
  l4:
    hypotheses:
    - id: H1
      name: DCC相关系数可作为危机预警信号
      description: 当系统平均DCC相关系数超过历史阈值时，预示市场即将进入风险共振状态
      expected_ic_sign: 正
      source: 论文中'DCC detects correlation breakdown'部分
      priority: 主假设
    - id: H2
      name: 相关性参数α+β接近1时预示高相关性持续
      description: 高持续性参数意味着相关性冲击消退缓慢，市场处于'粘性相关'状态
      expected_ic_sign: 正
      source: 论文参数估计结果(α+β≈0.95)
      priority: 辅助假设
    - id: H3
      name: 基于DCC权重的资产网络结构变化预测收益
      description: DCC相关矩阵可构建动态网络，社团结构变化预示未来收益分化
      expected_ic_sign: 待验证
      source: 论文'Dynamic Network Construction'应用
      priority: 辅助假设
    meaning_summary: DCC提供了一种计算上可行且理论上严谨的时变相关性度量，可嵌入资产定价、风险管理和组合优化系统
    key_insights:
    - DCC将相关性问题与波动率问题分离估计，降低计算复杂度至O(N²)
    - 通过diag(Q_t)^(-1/2)变换保证任意时刻R_t均为合法相关矩阵
    - α参数捕捉短期冲击效应(典型值0.05-0.10)，β捕捉长期持续性(典型值0.85-0.95)
    uncertainty: 两步估计法为伪似然估计，参数标准误可能低估；不适用于资产数量极大(N>100)的系统
  l5: {}
  l6: {}

```

## 结论与建议

- Path A 平均分: **92.2**
- Path B 平均分: **88.3**
- 推荐 **Path A（两次调用）**

## 提示词设计差异

| Prompt | Token 上限 | 设计目标 | 6-layer 适配 |
|---|---|---|---|
| `repro_extract.yaml` | 4096 | 论文理解（8类结构化信息） | ❌ 不直接支持 |
| `repro_factor.yaml` (v2.0 升级后) | 6000 | 因子列表 + L1-L4 metadata | ⚠️ 部分支持 |
| `repro_factor_full.yaml` | 6000 | 6-layer YAML 直接输出 | ✅ 完全支持 |

## 关键发现

1. **当 `repro_factor.yaml` 升级到支持 L1-L4 后，Path A 反而胜出**
   - 两次 LLM 调用的总 token (~35K) 仍小于一次大调用的预期
   - 第二次 LLM 调用有第一次的 extraction 作为 context，输出更稳定

2. **Path B 的优势在速度而非质量**
   - 4-6x 快 (~15s vs ~75s)
   - token 用量更少 (~10K vs ~35K)
   - 架构更简单（一次调用，一次解析）

3. **L4 假设质量在两个路径都达到 5.0**
   - 升级 `repro_factor.yaml` 后，Path A 的 L4 质量反超
   - 证明 LLM 假设生成能力不依赖调用次数，依赖 prompt 质量

## 决策矩阵

| 维度 | Path A | Path B |
|---|---|---|
| 6-layer YAML 质量 | 92.2 | 88.3 |
| 单次耗时 | 60-85s | 14-17s |
| Token 用量 | 34-37K | 10-13K |
| 架构复杂度 | 中（两次调用+合并） | 低（一次调用） |
| 调试难度 | 中（需看两步 LLM 输出） | 低（一步） |
| 失败模式 | 一处失败不影响另一处 | 全有或全无 |
| 可扩展性 | 高（每步可独立优化） | 中 |

## 最终建议

**选择 Path A（两次调用）**

理由:
1. 质量更高 (+3.9 分平均)
2. 升级后的 `repro_factor.yaml` 已能输出 L1-L4，弥补了原始设计缺陷
3. `repro_extract.yaml` 仍产生 8 类论文理解信息（用于 Source 页面）
4. 失败隔离：两次调用中一次失败不会完全丢失结果

如选择 Path A，仍需解决:
- 两次调用的耗时问题（~75s vs ~15s）
- 第二次调用依赖第一次输出，需处理 partial failure