# QuantNodes Factor Backtesting Guide

> 量化因子回测操作指南 — 基于 QuantNodes 平台
> 项目路径: `/home/ll/Public/QuantNodes`

## 1. 项目概述

**QuantNodes** 是一个 AI 原生量化研究平台（v2.5.0），基于 **BaseNode + Pipeline** 架构，提供：
- 317+ 内置因子算子（时序、截面、数学、TA-Lib）
- YAML 配置驱动的回测引擎
- 因子 IC/IR 分析
- 自动因子挖掘（模板枚举 + MCTS 搜索）
- REST API 供外部 Agent 调用

**架构分层：**
```
Layer 3: Meta-Programming AI (StrategyGenerator, PipelineOptimizer)
Layer 2: Pipeline Composition (Pipeline, Parallel, Join, IfNode, MapNode, WhileNode)
Layer 1: Processing Nodes (DatabaseNode, FactorNode, BacktestNode, ConfigNode)
```

## 2. 快速开始

### 2.1 安装

```bash
cd /home/ll/Public/QuantNodes
pip install -e .
quantnodes init    # 创建 .env 和 conn.ini
```

### 2.2 配置数据源

编辑 `conn.ini`（ClickHouse）或使用 CSV：

```ini
[ClickHouse]
host=your-host
port=8123
database=default
user=default
password=your-password
```

### 2.3 首个回测

**Python API 方式：**

```python
from QuantNodes.methods.backtest import run_backtest

result = run_backtest(
    pipeline_code="""
import pandas as pd
from QuantNodes.backtest.strategy_node import MAStrategyNode
from QuantNodes.backtest.broker_node import SimulatedBrokerNode

strategy = MAStrategyNode(config={'short_window': 5, 'long_window': 20})
broker = SimulatedBrokerNode(config={'cash': 1000000, 'commission': 0.001})
quote_data = pd.read_csv('data/stock_data.csv')
""",
    start_date="2023-01-01",
    end_date="2024-12-31",
    initial_cash=1000000.0,
    commission=0.001
)

print(result.summary)
```

**YAML 配置方式：**

```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "X-API-Key: qn_live_..." \
  -H "Content-Type: application/json" \
  -d '{"config_yaml": "...", "start_date": "2023-01-01", "end_date": "2024-12-31"}'
```

## 3. 因子算子库

### 3.1 算子分类速查

| 类别 | 数量 | 文件 | 典型算子 |
|------|------|------|----------|
| **Point (逐元素)** | 46+ | `math_ops.py` | `abs`, `log`, `sign`, `clip`, `fillna`, `where` |
| **Time (时序)** | 65+ | `time_ops.py` | `rolling_mean`, `rolling_std`, `ewm_mean`, `ts_rank`, `ts_delta`, `ts_lag`, `decay_linear`, `vwap` |
| **Section (截面)** | 17+ | `section_ops.py` | `rank`, `zscore`, `winsorize`, `neutralize`, `scale`, `ic`, `rank_ic`, `mad` |
| **Multi-Section** | 15+ | `composite_ops.py` | `aggregate`, `disaggregate`, `aggr_sum`, `aggr_mean`, `merge`, `blend` |
| **TA-Lib** | 174 | `talib_ops.py` | `talib_rsi`, `talib_sma`, `talib_macd_line`, `talib_bbands` |
| **Custom** | 无限 | `custom.py` | 通过装饰器/构建器/模板自定义 |

### 3.2 常用算子示例

```python
from QuantNodes.factor_node.factor_functions import (
    rolling_mean, rolling_std, ts_rank, ts_delta, ts_lag,
    rank, zscore, winsorize, neutralize, ic, rank_ic
)

# 时序算子
ma20 = rolling_mean(factor_data, window=20)        # 20日均值
std20 = rolling_std(factor_data, window=20)         # 20日标准差
momentum = ts_lag(factor_data, window=20)           # 20日滞后
rank_ts = ts_rank(factor_data, window=20)           # 时序排名

# 截面算子
cross_rank = rank(factor_data)                      # 截面排名
zscore_data = zscore(factor_data)                   # 截面标准化
winsorized = winsorize(factor_data, n=3)            # 截面缩尾

# IC 分析
ic_result = ic(factor_col="factor_value", return_col="forward_return")
rank_ic_result = rank_ic(factor_col="factor_value", return_col="forward_return")
```

### 3.3 算子注册 API

```python
from QuantNodes.factor_node.factor_functions import (
    list_operators, get_operator, operator_info, generate_documentation
)

# 列出所有算子
time_ops = list_operators('time')       # 时序算子列表
section_ops = list_operators('section') # 截面算子列表

# 获取特定算子
op = get_operator('rolling_mean', 'time')
result = op(data, window=20)

# 算子文档
info = operator_info('rolling_mean')
docs = generate_documentation('markdown')
```

### 3.4 自定义算子

**方式一：装饰器**

```python
from QuantNodes.operators import CustomOperator

@CustomOperator.point("my_double")
def my_double(f, multiplier=2.0):
    return f * multiplier
```

**方式二：构建器链**

```python
my_ewm_30 = (CustomOperator.time("my_ewm_30")
    .param("span", int, 30, "窗口大小")
    .execute(lambda s, span: s.ewm_mean(span=span))
    .register())
```

**方式三：模板工厂**

```python
my_ewm_30 = CustomOperator.time_from("my_ewm_30", "ewm_mean", span=30)
```

## 4. 因子分析

### 4.1 IC 分析流程

```python
from QuantNodes.methods.factor import analyze_factor

result = analyze_factor(
    factor_code="""
import polars as pl
result = pl.DataFrame({
    "date": ["2024-01-01", "2024-01-01", "2024-01-02"],
    "code": ["A", "B", "A"],
    "factor_value": [0.1, 0.2, 0.3],
    "forward_return": [0.05, 0.03, 0.02],
})
""",
    analysis_type="both",  # "ic", "correlation", 或 "both"
    start_date="2024-01-01",
    end_date="2024-12-31"
)
```

### 4.2 IC 指标说明

| 指标 | 计算方式 | 含义 |
|------|---------|------|
| **IC Mean** | 每期 Pearson 相关系数的均值 | 因子预测能力 |
| **IC Std** | 每期 Pearson 相关系数的标准差 | 因子稳定性 |
| **ICIR** | IC Mean / IC Std | 风险调整后的因子质量 |
| **Rank IC Mean** | 每期 Spearman 秩相关系数的均值 | 非线性预测能力 |

### 4.3 IC 计算逻辑

```python
# 按日期分组计算 IC
ic_series = df.group_by("date").agg([
    pl.corr("factor_value", "forward_return").alias("ic"),
])

# IC Mean, IC Std
ic_mean = ic_values.mean()
ic_std = ic_values.std()

# ICIR
icir = ic_mean / (ic_std + 1e-8)

# Rank IC (Spearman)
rank_ic_series = df.group_by("date").agg([
    pl.corr(
        pl.col("factor_value").rank(),
        pl.col("forward_return").rank()
    ).alias("rank_ic"),
])
```

### 4.4 六维因子评估

文件：`QuantNodes/research/factor_evaluator.py`

| 维度 | 指标 | 说明 |
|------|------|------|
| **收益** | IC Mean, ICIR, Rank IC | 因子预测能力 |
| **稳定性** | Rolling IC 一致性 | 因子在不同时期的稳定性 |
| **分散化** | 与已有因子的相关性 | 因子独特性 |
| **换手率** | 排名变化率 | 交易成本影响 |
| **单调性** | 分位数组合收益单调性 | 因子是否单调有效 |
| **覆盖率** | 非空因子值比例 | 数据可用性 |

## 5. 回测配置

### 5.1 YAML 配置模板

```yaml
version: "1.0"
name: "momentum_20d"
description: "20日动量因子策略"

# 数据源
data:
  source: "csv"                    # csv 或 clickhouse
  path: "data/stock_data.csv"
  columns: [date, code, open, high, low, close, volume]
  date_column: "date"
  code_column: "code"

# 因子定义
factors:
  - name: returns_20d
    expr: "close / ts_lag(close, 20) - 1"

# 算子操作
operations:
  - type: time_series
    name: momentum_ma
    category: ts_mean
    inputs: [returns_20d]
    params:
      window: 20

# 合成
composite:
  - name: alpha
    formula: "rank(momentum_ma)"

# 回测参数
backtest:
  start_date: "2023-01-01"
  end_date: "2024-12-31"
  initial_cash: 1000000
  commission: 0.001
  slippage: 0.001
  signals:
    buy_threshold: 0.05
    sell_threshold: -0.03
  positions:
    max_positions: 10
    rebalance_freq: "weekly"

# 输出
output:
  format: "parquet"
  path: "outputs/momentum_result.parquet"
  save_signals: true
  save_positions: true
  save_equity_curve: true
```

### 5.2 ClickHouse 数据配置

```yaml
data:
  source: clickhouse
  conn_ini: conn.ini
  conn_section: ClickHouse
  table: quote.cn_stock
  columns: [ts_code, trade_date, open, high, low, close, vol]
  column_mapping:
    ts_code: code
    trade_date: date
    vol: volume
  query_filter: "WHERE trade_date >= toDateTime('2023-07-01')"
```

### 5.3 内置策略模板

| 模板文件 | 策略类型 | 核心逻辑 |
|----------|---------|---------|
| `momentum.yaml` | 动量策略 | 20日收益率排名 |
| `dual_ma.yaml` | 双均线策略 | 短期均线上穿长期均线 |
| `rsi_strategy.yaml` | RSI反转 | RSI 超卖买入 |
| `mean_reversion.yaml` | 均值回归 | Z-score 偏离阈值 |
| `bollinger_bands.yaml` | 布林带突破 | 突破上下轨 |
| `volume_price.yaml` | 量价背离 | 成交量与价格背离 |

## 6. 绩效指标

### 6.1 收益指标

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| **Total Return** | (期末净值 / 期初净值) - 1 | 总收益率 |
| **Annualized Return** | (1 + Total Return)^(252/交易日) - 1 | 年化收益率 |

### 6.2 风险指标

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| **Sharpe Ratio** | (年化收益 - 3%) / 年化波动率 | 风险调整收益 |
| **Sortino Ratio** | (年化收益 - 3%) / 下行波动率 | 只考虑下行风险 |
| **Max Drawdown** | min((净值 - 峰值) / 峰值) | 最大回撤 |
| **Calmar Ratio** | 年化收益 / abs(最大回撤) | 收益回撤比 |
| **Annualized Volatility** | 日收益标准差 * sqrt(252) | 年化波动率 |

### 6.3 交易指标

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| **Win Rate** | 盈利次数 / 总交易次数 | 胜率 |
| **Profit Factor** | 总盈利 / 总亏损 | 盈亏比 |
| **Avg Win** | 总盈利 / 盈利次数 | 平均盈利 |
| **Avg Loss** | 总亏损 / 亏损次数 | 平均亏损 |
| **Total Trades** | 执行的交易总数 | 交易频率 |

### 6.4 BacktestResult 结构

```python
@dataclass
class BacktestResult:
    positions: pd.DataFrame      # 持仓记录
    trades: pd.DataFrame         # 交易记录
    orders: pd.DataFrame         # 订单记录
    equity_curve: pd.DataFrame   # 净值曲线
    statistics: Dict[str, Any]   # 绩效指标字典
    final_cash: float            # 期末现金
    total_return: float          # 总收益率
    sharpe_ratio: float          # Sharpe 比率
    max_drawdown: float          # 最大回撤
    win_rate: float              # 胜率
```

## 7. API 使用

### 7.1 Python API

```python
# 回测
from QuantNodes.methods.backtest import run_backtest
result = run_backtest(pipeline_code="...", start_date="2020-01-01", end_date="2024-12-31")

# 因子分析
from QuantNodes.methods.factor import analyze_factor
result = analyze_factor(factor_code="...", analysis_type="both")

# 算子直接调用
from QuantNodes.factor_node.factor_functions import rolling_mean, rank, zscore, ic, rank_ic

# Pipeline 构建
from QuantNodes.core import Pipeline, Parallel, Join
pipeline = NodeA() >> NodeB() >> NodeC()
result = pipeline.execute(data)
```

### 7.2 REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/backtest/run` | POST | 运行回测（YAML 配置） |
| `/api/backtest/history` | GET | 回测历史 |
| `/api/backtest/templates` | GET | 回测模板列表 |
| `/api/factor/analyze` | POST | 因子分析（IC + 相关性） |
| `/api/factor/{name}/metrics` | GET | 因子指标 |
| `/api/prompts/strategy/{type}` | GET | 策略 prompt |
| `/api/prompts/factor/{type}` | GET | 因子 prompt |

**调用示例：**

```bash
# 运行回测
curl -X POST http://localhost:8000/api/backtest/run \
  -H "X-API-Key: qn_live_..." \
  -H "Content-Type: application/json" \
  -d '{
    "config_yaml": "version: \"1.0\"\nname: test\n...",
    "start_date": "2023-01-01",
    "end_date": "2024-12-31"
  }'

# 因子分析
curl -X POST http://localhost:8000/api/factor/analyze \
  -H "X-API-Key: qn_live_..." \
  -d '{"factor_code": "...", "analysis_type": "both"}'

# 获取策略 prompt
curl http://localhost:8000/api/prompts/strategy/momentum \
  -H "X-API-Key: qn_live_..."
```

### 7.3 Pipeline 组合模式

```python
# 线性 Pipeline
pipeline = LogReturnNode() >> VolatilityNode(window=20) >> SharpeRatioNode()

# Parallel + Join（多因子并行计算后合并）
factors = Parallel({
    'ret_1d': LogReturnNode(),
    'ret_5d': LogReturnNode() >> Pipeline([lambda x: x.rolling(5).mean()]),
    'volatility': VolatilityNode(window=10),
})
combine = Join(lambda ret_1d, ret_5d, volatility: (ret_1d + ret_5d) / (volatility + 1e-6))
result = (factors >> combine).execute(data['close'])

# IfNode（条件分支）
strategy = IfNode(
    condition=lambda data: data['volatility'].mean() > 0.02,
    true_node=HighVolStrategy(),
    false_node=LowVolStrategy()
)
```

## 8. 自动因子挖掘

### 8.1 AutoResearcher

文件：`QuantNodes/research/auto_researcher.py`

三阶段流水线：
1. **模板枚举**：从 4 个因子族（动量、均值回归、波动率、量价）系统生成候选
2. **MCTS 搜索**：蒙特卡洛树搜索探索因子公式空间
3. **LLM 增强**（可选）：外部 Agent 辅助因子优化

### 8.2 因子族模板

| 因子族 | 模板示例 | 说明 |
|--------|---------|------|
| **动量** | `ts_lag(close, N) / close - 1` | 价格动量 |
| **均值回归** | `(close - rolling_mean(close, N)) / rolling_std(close, N)` | Z-score 均值回归 |
| **波动率** | `rolling_std(returns, N)` | 波动率 |
| **量价** | `ts_corr(close, volume, N)` | 量价相关性 |

### 8.3 Wiki 因子库集成

文件：`QuantNodes/research/wiki.py`

使用 `llmwikify` 进行 Markdown 因子知识管理：
- 存储/检索/更新/删除因子、策略、逻辑、复现
- 因子、策略、研究报告之间的关系图
- 页面类型：Factor, Logic, Strategy, Reproduction

## 9. 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| **IC 接近 0** | 因子无预测力 | 检查数据质量、经济逻辑、换用非线性算子 |
| **ICIR 过低** | 因子不稳定 | 尝试不同窗口、增加平滑、检查市场状态 |
| **回测 Sharpe 低** | 交易成本过高 | 降低换手率、增大调仓周期 |
| **Max Drawdown 大** | 风控不足 | 添加止损、限制仓位、增加风控节点 |
| **过拟合** | 参数过多 | 使用 Walk-Forward、Out-of-Sample 测试 |
| **数据缺失** | 覆盖率低 | 过滤低覆盖率股票、填充缺失值 |

---

**相关文件：**
- 项目路径：`/home/ll/Public/QuantNodes`
- Wiki 知识库：`/home/ll/Public/strategy/wiki.md`
- Wiki 因子页面：`wiki/factors/`
- Wiki 策略页面：`wiki/strategies/`
- Wiki 回测页面：`wiki/backtests/`
