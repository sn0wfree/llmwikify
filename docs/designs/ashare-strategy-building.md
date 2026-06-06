# 多市场量化策略构建扩展 — 设计文档

## Overview

在 AutoResearch 6 步框架基础上，扩展多市场量化策略构建能力。支持 **A 股、期货、期权** 三大市场，集成趋势跟踪、多因子、统计套利、期权定价等策略类型，使用 backtrader 回测框架。

## 目录结构重构

第二阶段代码独立于现有 `agent/` 目录，构建在 `src/llmwikify/strategy/` 顶级子目录：

```
src/llmwikify/strategy/                    # 第二阶段根目录
├── __init__.py
├── config.py                              # 策略全局配置
├── factor/                                # 因子子系统
│   ├── __init__.py
│   ├── miner.py                           # 因子挖掘
│   ├── validator.py                       # 因子验证
│   ├── analyzer.py                        # 因子分析（相关性/去重/归因）
│   ├── neutralizer.py                     # 因子中性化（申万+对数市值）
│   ├── decay_monitor.py                   # 因子衰减监控（每日）
│   ├── report.py                          # 因子分析报告
│   └── store.py                           # 因子持久化
├── strategy/                              # 策略子系统
│   ├── __init__.py
│   ├── base.py                            # 策略基类
│   ├── stock/                             # 股票策略
│   │   ├── __init__.py
│   │   ├── trend.py                       # 趋势跟踪
│   │   ├── multi_factor.py                # 多因子
│   │   └── stat_arb.py                    # 统计套利
│   ├── futures/                           # 期货策略
│   │   ├── __init__.py
│   │   ├── trend.py                       # 期货趋势
│   │   └── spread.py                      # 期货套利
│   ├── option/                            # 期权策略
│   │   ├── __init__.py
│   │   ├── pricing.py                     # 期权定价
│   │   ├── volatility.py                  # 波动率交易
│   │   └── combination.py                 # 期权组合
│   ├── backtester.py                      # backtrader 回测
│   ├── risk_manager.py                    # 风控模块
│   └── optimizer.py                       # 策略优化
├── data/                                  # 数据层
│   ├── __init__.py
│   ├── provider.py                        # 多市场数据提供者
│   ├── cache.py                           # 数据缓存
│   └── industry.py                        # 申万行业映射
├── api/                                   # API 层
│   ├── __init__.py
│   └── routes.py                          # 策略 API 路由
└── db/                                    # DB 层
    ├── __init__.py
    ├── schema.py                          # 策略表定义
    └── migrations.py                      # DB 迁移
```

### 子目录职责

| 目录 | 职责 | 与第一阶段关系 |
|------|------|---------------|
| `factor/` | 因子全生命周期（挖掘/验证/分析/中性化/监控/报告/存储） | **独立** |
| `strategy/` | 策略实现（股票/期货/期权/回测/风控/优化） | **依赖** factor |
| `data/` | 多市场数据获取与缓存 | **独立** |
| `api/` | API 路由层 | **独立** |
| `db/` | 数据库 schema 和迁移 | **独立** |

## Problem Statement

现有 AutoResearch 引擎专注于**信息研究**（收集 → 分析 → 综合 → 报告），缺乏**量化建模和策略构建**能力：

1. **无数据源集成** — 无法获取股票、期货、期权行情数据
2. **无因子体系** — 缺乏因子挖掘、验证、组合能力
3. **无回测引擎** — 无法验证策略历史表现
4. **无策略框架** — 缺乏股票/期货/期权的标准化策略实现
5. **无风控模块** — 缺乏风险评估和控制机制
6. **无衍生品定价** — 缺乏期权定价和希腊字母计算

## TradingAgent 借鉴分析

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 是多 Agent 交易框架（82.6k stars），其核心架构可借鉴：

### 核心架构

```
TradingAgent 角色分工
├── Analyst Team（分析师团队）
│   ├── Fundamentals Analyst（基本面）
│   ├── Sentiment Analyst（情绪面）
│   ├── News Analyst（新闻面）
│   └── Technical Analyst（技术面）
├── Researcher Team（研究员团队）
│   ├── Bullish Researcher（多头）
│   └── Bearish Researcher（空头）
├── Trader Agent（交易员）
└── Risk Management & Portfolio Manager（风控+组合管理）
```

### 借鉴架构

| 借鉴点 | TradingAgent | 第二阶段应用 |
|-------|-------------|------------|
| **多 Agent 辩论** | Bullish vs Bearish | 策略决策前的多空辩论 |
| **分析师团队** | 4 个专业分析师 | 因子分析 + 行情分析 |
| **决策日志** | `~/.tradingagents/memory/` | 交易反思与优化 |
| **市场支持** | Yahoo Finance（多市场） | iFinD + Tushare + AKShare |
| **配置系统** | `TRADINGAGENTS_*` env vars | 复用第一阶段配置 |
| **持久化** | LangGraph checkpoint | 复用第一阶段 DB |

### 借鉴但不依赖

- **借鉴思想**：多 Agent 协作、分析师团队、决策日志
- **不复用代码**：保持独立架构
- **统一接口**：研究 API 与策略 API 设计一致
- **数据源互补**：TradingAgent 用 Yahoo Finance，我们用 iFinD/Tushare/AKShare

## 并行开发计划

### 开发策略：选项 B（并行独立开发）

两个阶段可并行开发，借鉴架构但不依赖代码：

```
第 1 周：基础模块
├── 第一阶段：DB 迁移 + config + clarifier
└── 第二阶段：data_provider + data_cache

第 2 周：核心模块
├── 第一阶段：reasoning_checker + structure_validator + 自我循环
└── 第二阶段：factor_miner + factor_validator + 策略实现

第 3 周：完善
├── 第一阶段：重试机制 + 集成测试
└── 第二阶段：回测引擎 + 风控模块 + 测试

第 4 周：集成
├── 第一阶段：端到端测试
└── 第二阶段：端到端测试
└── 整体联调
```

### 借鉴点（不依赖）

| 借鉴项 | 来源 | 应用到 |
|-------|------|--------|
| 质量门禁架构 | 第一阶段 | 策略质量校验 |
| 自我循环模式 | 第一阶段 | 策略优化迭代 |
| DB 迁移模式 | 第一阶段 | 策略表创建 |
| Prompt 模板结构 | 第一阶段 | 策略 prompt |
| 配置系统 | 第一阶段 | 策略 config |
| 多 Agent 辩论 | TradingAgent | 策略决策（可选） |
| 决策日志 | TradingAgent | 交易反思（可选） |

## 扩展架构

```
AutoResearch 6步框架（`src/llmwikify/agent/`）
    │
    ├── 研究阶段（现有）
    │     └── 概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单
    │
    └── 第二阶段（`src/llmwikify/strategy/`，独立子目录）
          │
          ├── 因子子系统（`factor/`）
          │     ├── miner.py → validator.py → analyzer.py
          │     │     → neutralizer.py → store.py
          │     ├── decay_monitor.py（每日）
          │     └── report.py（单独输出）
          │
          ├── 策略子系统（`strategy/`）
          │     ├── stock/        （趋势/多因子/统计套利）
          │     ├── futures/      （趋势/套利）
          │     ├── option/       （定价/波动率/组合）
          │     └── base.py + backtester.py + risk_manager.py + optimizer.py
          │
          ├── 数据层（`data/`）
          │     └── provider.py + cache.py + industry.py
          │
          ├── API 层（`api/`）
          │     └── routes.py
          │
          └── DB 层（`db/`）
                └── schema.py + migrations.py
```

### 多市场支持

| 市场 | 品种 | 交易特点 | 策略类型 |
|------|------|---------|---------|
| A 股 | 股票、ETF | T+1、涨跌停限制 | 趋势跟踪、多因子、统计套利 |
| 期货 | 商品期货、股指期货 | T+0、保证金交易、双向交易 | 趋势跟踪、跨期/跨品种套利 |
| 期权 | 股指期权、商品期权 | T+0、非线性收益、希腊字母 | 定价、波动率交易、组合策略 |

## 数据层（`data/` 子目录）

### 数据源选型

| 数据源 | 类型 | 覆盖市场 | 用途 | 授权状态 |
|--------|------|---------|------|---------|
| Tushare | A 股行情 | 股票、基金、期货 | 日线/分钟线/财务/分红 | 需注册（免费额度） |
| AKShare | 多市场数据 | 股票、期货、期权 | 行情/财务/宏观/行业 | 开源免费 |
| iFinD | 专业数据 | 股票、期货、期权、宏观 | 全品种行情/财务/衍生品 | 需付费授权 |

### 数据源优先级

```
优先级 1: iFinD（数据最全）
优先级 2: Tushare（A 股数据）
优先级 3: AKShare（开源备选）
```

### 数据层目录结构

```
data/
├── provider.py        # 多市场数据提供者
├── cache.py           # 数据缓存
└── industry.py        # 申万行业映射
```

### 多市场数据提供者（`data/provider.py`）

```python
class MultiMarketDataProvider:
    """多市场数据提供者"""

    def __init__(self, config: dict):
        self.config = config
        self.primary_provider = config.get("primary_provider", "ifind")
        self._providers = {}
        self._cache_dir = config.get("data_cache_dir", ".cache/market_data")

    # 股票数据
    async def get_stock_daily(self, symbol, start_date, end_date) -> pd.DataFrame: ...
    async def get_stock_financial(self, symbol, report_type="income") -> pd.DataFrame: ...
    async def get_stock_list(self, market="A") -> pd.DataFrame: ...

    # 期货数据
    async def get_futures_daily(self, symbol, start_date, end_date) -> pd.DataFrame: ...
    async def get_futures_contracts(self, exchange="SHFE") -> pd.DataFrame: ...

    # 期权数据
    async def get_option_daily(self, symbol, start_date, end_date) -> pd.DataFrame: ...
    async def get_option_contracts(self, underlying) -> pd.DataFrame: ...
    async def get_option_greeks(self, symbol, date) -> dict: ...

    # 宏观数据
    async def get_macro_data(self, indicator, start_date, end_date) -> pd.DataFrame: ...
```

### 数据缓存（`data/cache.py`）

```python
class DataCache:
    """数据缓存管理"""
    def __init__(self, cache_dir: str, ttl_hours: int = 24): ...
    def get(self, key: str) -> pd.DataFrame | None: ...
    def set(self, key: str, data: pd.DataFrame) -> None: ...
```

### 申万行业映射（`data/industry.py`）

```python
class SWIndustryMapping:
    """申万一级行业映射"""
    def __init__(self, data_provider): ...
    def get_sw_l1(self, symbol: str) -> str: ...
    def get_all(self) -> pd.DataFrame: ...
    def update_mapping(self) -> None: ...
```

## 因子体系（`factor/` 子目录）

### 因子类型

| 因子类别 | 因子示例 | 说明 |
|---------|---------|------|
| 动量因子 | MOM_20, MOM_60 | 20日/60日动量 |
| 波动率因子 | VOL_20, VOL_60 | 20日/60日波动率 |
| 价值因子 | PE, PB, PS | 市盈率/市净率/市销率 |
| 成长因子 | ROE_GROWTH, REVENUE_GROWTH | ROE增长率/营收增长率 |
| 质量因子 | ROE, ROA, GROSS_MARGIN | ROE/ROA/毛利率 |
| 流动性因子 | TURNOVER, VOLUME_RATIO | 换手率/量比 |
| 技术因子 | RSI, MACD, BB_WIDTH | RSI/MACD/布林带宽度 |

### 因子子系统（7 个模块）

```
factor/
├── miner.py           # 因子挖掘
├── validator.py       # 因子验证
├── analyzer.py        # 因子分析（相关性/去重/归因）
├── neutralizer.py     # 因子中性化（申万+对数市值）
├── decay_monitor.py   # 因子衰减监控（每日）
├── report.py          # 因子分析报告
└── store.py           # 因子持久化
```

### 因子挖掘（`factor/miner.py`）

```python
class FactorMiner:
    """因子挖掘器"""

    def __init__(self, data_provider, config: dict):
        self.data_provider = data_provider
        self.config = config

    async def compute_factor(self, factor_name: str,
                             symbols: list[str],
                             start_date: str,
                             end_date: str) -> pd.DataFrame:
        """计算单个因子"""
        ...

    async def compute_all_factors(self, symbols: list[str],
                                  start_date: str,
                                  end_date: str) -> dict[str, pd.DataFrame]:
        """计算所有因子"""
        ...

    def get_factor_library(self) -> dict[str, Callable]:
        """获取因子库"""
        ...
```

### 因子验证（`factor/validator.py`）

```python
class FactorValidator:
    """因子验证器"""

    def __init__(self, config: dict):
        self.config = config

    def validate_ic(self, factor_df, returns_df) -> dict:
        """IC 验证"""
        ...

    def validate_icir(self, factor_df, returns_df) -> dict:
        """ICIR 验证"""
        ...

    def validate_turnover(self, factor_df) -> dict:
        """换手率验证"""
        ...

    def validate_decay(self, factor_df, returns_df, max_lag: int = 20) -> dict:
        """因子衰减验证"""
        ...

    def run_quantile_test(self, factor_df, returns_df, n_quantiles: int = 5) -> dict:
        """分层回测（单调性检验）"""
        ...
```

### 因子分析（`factor/analyzer.py`）

```python
class FactorAnalyzer:
    """因子分析器"""

    def __init__(self, config: dict):
        self.config = config
        self.correlation_threshold = 0.7  # 去重阈值

    def analyze_correlation(self, factor_dfs: dict) -> dict:
        """因子相关性分析"""
        ...

    def dedup_factors(self, factor_dfs: dict, ic_values: dict) -> list[str]:
        """去重：保留部分相关性（保留 IC 较高者）"""
        ...

    def factor_attribution(self, portfolio_returns, factor_returns) -> dict:
        """因子归因分析"""
        ...
```

### 因子中性化（`factor/neutralizer.py`）

```python
class FactorNeutralizer:
    """因子中性化器"""

    def __init__(self, config: dict):
        self.config = config
        self.industry_classification = "sw"  # 申万一级
        self.market_cap_method = "log_regression"  # 对数市值回归

    def neutralize(self, factor_df, industry_dummies, market_cap) -> pd.DataFrame:
        """申万行业 + 对数市值双重中性化"""
        ...
```

### 因子衰减监控（`factor/decay_monitor.py`）

```python
class FactorDecayMonitor:
    """因子衰减监控器（每日）"""

    def __init__(self, config: dict):
        self.config = config
        self.check_interval_days = 1
        self.ic_decay_warning = 0.2
        self.ic_decay_critical = 0.3

    async def run_daily_check(self) -> dict:
        """每日检查"""
        ...

    def generate_daily_report(self) -> dict:
        """生成每日衰减报告"""
        ...
```

### 因子分析报告（`factor/report.py`）

```python
class FactorReport:
    """因子分析报告（单独输出）"""

    def __init__(self, config: dict):
        self.config = config

    async def generate_report(self, factor_data: dict) -> dict:
        """生成因子分析报告"""
        return {
            "overview": ...,
            "top_factors": ...,
            "correlation_matrix": ...,
            "quantile_test": ...,
            "decay_trend": ...,
            "recommendations": ...,
        }

    def export_markdown(self, report: dict) -> str: ...
    def export_json(self, report: dict) -> str: ...
```

### 因子存储（`factor/store.py`）

```python
class FactorStore:
    """因子数据库存储"""

    def __init__(self, db):
        self.db = db

    def save_factor_values(self, factor_name: str, values: pd.DataFrame) -> None: ...
    def load_factor_values(self, factor_name: str, start_date: str, end_date: str) -> pd.DataFrame: ...
    def save_ic_history(self, factor_name: str, ic_series: pd.Series) -> None: ...
```

### 因子组合（仍属于 strategy 子系统）

因子组合在 `strategy/stock/multi_factor.py` 中实现，**不属于** `factor/` 子目录。

```python
class FactorCombiner:
    """因子组合器（位于 strategy 子系统）"""

    def __init__(self, config: dict):
        self.config = config

    def equal_weight(self, factor_dfs: list) -> pd.DataFrame: ...
    def ic_weight(self, factor_dfs: list, ic_values: list) -> pd.DataFrame: ...
    def optimization_weight(self, factor_dfs: list, returns_df) -> pd.DataFrame: ...
```

## 策略体系（`strategy/` 子目录）

### 目录结构

```
strategy/
├── base.py                # 策略基类
├── backtester.py          # backtrader 回测
├── risk_manager.py        # 风控模块
├── optimizer.py           # 策略优化
├── stock/                 # 股票策略
│   ├── trend.py           # 趋势跟踪
│   ├── multi_factor.py    # 多因子
│   └── stat_arb.py        # 统计套利
├── futures/               # 期货策略
│   ├── trend.py           # 期货趋势
│   └── spread.py          # 期货套利
└── option/                # 期权策略
    ├── pricing.py         # 期权定价
    ├── volatility.py      # 波动率交易
    └── combination.py     # 期权组合
```

### 策略基类（`strategy/base.py`）

```python
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成交易信号"""
        ...

    @abstractmethod
    def position_sizing(self, signals: pd.DataFrame,
                        capital: float) -> pd.DataFrame:
        """仓位管理"""
        ...

    def validate_data(self, data: pd.DataFrame) -> bool:
        """数据验证"""
        ...
```

### 股票策略（`strategy/stock/`）

#### 趋势跟踪（`strategy/stock/trend.py`）

```python
class StockTrendStrategy(BaseStrategy):
    """股票趋势跟踪策略"""

    def __init__(self, config: dict):
        super().__init__(config)

    def generate_signals(self, prices: pd.DataFrame) -> pd.DataFrame:
        """生成交易信号"""
        ...
```

#### 多因子（`strategy/stock/multi_factor.py`）

```python
class StockMultiFactorStrategy(BaseStrategy):
    """股票多因子策略"""

    def __init__(self, factor_miner, factor_validator,
                 factor_analyzer, factor_combiner, config: dict):
        super().__init__(config)
        self.factor_miner = factor_miner
        self.factor_validator = factor_validator
        self.factor_analyzer = factor_analyzer
        self.factor_combiner = factor_combiner

    async def generate_signals(self, symbols: list[str],
                               start_date: str, end_date: str) -> pd.DataFrame:
        """生成多因子信号"""
        # 1. 计算所有因子
        # 2. 验证因子
        # 3. 去重 + 中性化
        # 4. 组合因子
        # 5. 生成信号
        ...
```

#### 统计套利（`strategy/stock/stat_arb.py`）

```python
class StockStatArbStrategy(BaseStrategy):
    """股票统计套利策略（配对交易）"""

    def find_cointegrated_pairs(self, prices: pd.DataFrame) -> list[tuple]: ...
    def generate_signals(self, pair: tuple, prices: pd.DataFrame) -> pd.DataFrame: ...
```

### 期货策略（`strategy/futures/`）

```python
# strategy/futures/trend.py
class FuturesTrendStrategy(BaseStrategy):
    """期货趋势跟踪策略"""
    ...

# strategy/futures/spread.py
class CalendarSpreadStrategy(BaseStrategy):
    """跨期套利策略"""
    ...

class IntercommoditySpreadStrategy(BaseStrategy):
    """跨品种套利策略"""
    ...
```

### 期权策略（`strategy/option/`）

```python
# strategy/option/pricing.py
class OptionPricingModel:
    """期权定价模型"""
    def black_scholes(self, ...): ...
    def binomial_tree(self, ...): ...
    def monte_carlo(self, ...): ...

# strategy/option/volatility.py
class VolatilityTradingStrategy(BaseStrategy):
    """波动率交易策略"""
    ...

# strategy/option/combination.py
class OptionCombinationStrategy(BaseStrategy):
    """期权组合策略"""
    def iron_condor(self, ...): ...
    def straddle(self, ...): ...
    def strangle(self, ...): ...
    def butterfly(self, ...): ...
    def calendar_spread(self, ...): ...
```

### 回测引擎（`strategy/backtester.py`）

```python
class BacktraderRunner:
    """backtrader 回测运行器"""
    def add_strategy(self, strategy_class, **kwargs): ...
    def add_data(self, data_df, name=""): ...
    def run(self) -> dict: ...
```

### 风控模块（`strategy/risk_manager.py`）

```python
class RiskManager:
    """风险管理器"""
    def check_position_limits(self, positions): ...
    def check_drawdown_limit(self, current_drawdown): ...
    def check_concentration_limit(self, portfolio): ...
    def calculate_var(self, returns, confidence=0.95): ...
    def calculate_cvar(self, returns, confidence=0.95): ...
```

### 策略优化（`strategy/optimizer.py`）

```python
class StrategyOptimizer:
    """策略优化器"""
    def grid_search(self, param_grid, metric="sharpe_ratio"): ...
    def random_search(self, param_space, n_iter=100): ...
    def walk_forward(self, data, strategy_class, train_ratio=0.7): ...
```

## 回测引擎集成

### backtrader 集成

```python
class BacktraderRunner:
    """backtrader 回测运行器"""

    def __init__(self, config: dict):
        self.config = config
        self.cerebro = bt.Cerebro()

    def add_strategy(self, strategy_class, **kwargs):
        """添加策略"""
        self.cerebro.addstrategy(strategy_class, **kwargs)

    def add_data(self, data_df: pd.DataFrame, name: str = ""):
        """添加数据"""
        data = bt.feeds.PandasData(dataname=data_df)
        self.cerebro.adddata(data, name=name)

    def run(self) -> dict:
        """运行回测"""
        self.cerebro.broker.setcash(self.config.get("initial_cash", 1000000))
        self.cerebro.broker.setcommission(self.config.get("commission", 0.001))

        results = self.cerebro.run()
        return self._parse_results(results)

    def _parse_results(self, results) -> dict:
        """解析回测结果"""
        strat = results[0]
        return {
            "final_value": self.cerebro.broker.getvalue(),
            "returns": strat.analyzers.returns.get_analysis(),
            "sharpe": strat.analyzers.sharpe.get_analysis(),
            "drawdown": strat.analyzers.drawdown.get_analysis(),
            "trades": strat.analyzers.trades.get_analysis(),
        }
```

### 回测指标

```python
class BacktestMetrics:
    """回测指标计算"""

    @staticmethod
    def calculate_metrics(returns: pd.Series) -> dict:
        """计算完整回测指标"""
        return {
            "total_return": (1 + returns).prod() - 1,
            "annual_return": returns.mean() * 252,
            "annual_volatility": returns.std() * np.sqrt(252),
            "sharpe_ratio": returns.mean() / returns.std() * np.sqrt(252),
            "sortino_ratio": BacktestMetrics._sortino_ratio(returns),
            "max_drawdown": BacktestMetrics._max_drawdown(returns),
            "calmar_ratio": BacktestMetrics._calmar_ratio(returns),
            "win_rate": (returns > 0).sum() / len(returns),
            "profit_factor": returns[returns > 0].sum() / abs(returns[returns < 0].sum()),
        }
```

## 风控模块

```python
class RiskManager:
    """风险管理器"""

    def __init__(self, config: dict):
        self.config = config

    def check_position_limits(self, positions: dict) -> bool:
        """检查仓位限制"""
        ...

    def check_drawdown_limit(self, current_drawdown: float) -> bool:
        """检查回撤限制"""
        ...

    def check_concentration_limit(self, portfolio: dict) -> bool:
        """检查集中度限制"""
        ...

    def calculate_var(self, returns: pd.Series,
                      confidence: float = 0.95) -> float:
        """计算 VaR（风险价值）"""
        ...

    def calculate_cvar(self, returns: pd.Series,
                       confidence: float = 0.95) -> float:
        """计算 CVaR（条件风险价值）"""
        ...
```

## 策略优化

```python
class StrategyOptimizer:
    """策略优化器"""

    def __init__(self, backtest_runner: BacktraderRunner,
                 config: dict):
        self.backtest_runner = backtest_runner
        self.config = config

    def grid_search(self, param_grid: dict,
                    metric: str = "sharpe_ratio") -> dict:
        """网格搜索优化"""
        ...

    def random_search(self, param_space: dict,
                      n_iter: int = 100,
                      metric: str = "sharpe_ratio") -> dict:
        """随机搜索优化"""
        ...

    def walk_forward(self, data: pd.DataFrame,
                     strategy_class,
                     train_ratio: float = 0.7) -> dict:
        """滚动窗口优化（防止过拟合）"""
        ...
```

## 配置参数（`src/llmwikify/strategy/config.py`）

```python
DEFAULT_STRATEGY_CONFIG = {
    # ─── 数据源配置（`data/` 子系统）──────────────────
    "primary_provider": "ifind",  # ifind | tushare | akshare
    "ifind_token": None,
    "tushare_token": None,
    "data_cache_dir": ".cache/market_data",
    "data_cache_ttl_hours": 24,
    "sw_industry_update_days": 7,  # 申万行业更新频率

    # ─── 市场配置 ─────────────────────────────────────
    "markets": ["stock", "futures", "option"],
    "stock_config": {
        "exchange": "SSE",
        "lot_size": 100,
    },
    "futures_config": {
        "exchanges": ["SHFE", "DCE", "CZCE", "CFFEX"],
        "margin_ratio": 0.1,
        "contract_multiplier": 10,
    },
    "option_config": {
        "exchanges": ["SSE", "SZSE"],
        "option_type": "stock_index",
    },

    # ─── 因子配置（`factor/` 子系统）──────────────────
    "factor_library": "default",
    "factor_rebalance_days": 20,
    "factor_neutralize": True,
    "factor_correlation_threshold": 0.7,         # 去重阈值
    "factor_dedup_strategy": "keep_higher_ic",   # 保留 IC 较高
    "factor_industry_classification": "sw",      # 申万行业
    "factor_market_cap_method": "log_regression",  # 对数市值回归
    "factor_check_interval_days": 1,              # 每日检查
    "factor_ic_decay_warning": 0.2,               # 警告阈值
    "factor_ic_decay_critical": 0.3,              # 严重阈值
    "factor_alert_method": "report_only",         # 仅报告
    "factor_report_output": "both",               # markdown + json
    "factor_quantile_n_groups": 5,                # 分层数量
    "factor_store_retention_days": 365,           # 因子值保留

    # ─── 策略配置（`strategy/` 子系统）────────────────
    "strategy_type": "multi_factor",
    "rebalance_days": 20,
    "position_sizing": "equal_weight",

    # ─── 回测配置 ─────────────────────────────────────
    "backtest_initial_cash": 1000000,
    "backtest_commission": 0.001,
    "backtest_slippage": 0.001,
    "backtest_enable_short": True,

    # ─── 期货特定配置 ─────────────────────────────────
    "futures_commission_rate": 0.0001,
    "futures_margin_ratio": 0.1,
    "futures_slippage_ticks": 1,

    # ─── 期权特定配置 ─────────────────────────────────
    "option_pricing_model": "black_scholes",
    "option_risk_free_rate": 0.03,
    "option_dividend_yield": 0.02,

    # ─── 风控配置 ─────────────────────────────────────
    "max_position_size": 0.1,
    "max_drawdown_limit": 0.2,
    "max_sector_exposure": 0.3,
    "var_confidence": 0.95,
    "futures_max_leverage": 5,
    "option_max_loss_ratio": 0.05,

    # ─── 优化配置 ─────────────────────────────────────
    "optimization_method": "grid_search",
    "optimization_metric": "sharpe_ratio",
    "walk_forward_train_ratio": 0.7,
}
```

## File Changes（`src/llmwikify/strategy/`）

### 顶层文件

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `__init__.py` | Python | ~30 | 包初始化 |
| `config.py` | Python | ~80 | 策略全局配置 |

### `factor/` 子目录（7 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `factor/__init__.py` | ~20 | |
| `factor/miner.py` | ~250 | 因子挖掘 |
| `factor/validator.py` | ~150 | 因子验证 |
| `factor/analyzer.py` | ~200 | 因子分析（相关性/去重/归因） |
| `factor/neutralizer.py` | ~150 | 申万+对数市值中性化 |
| `factor/decay_monitor.py` | ~150 | 每日 IC 衰减监控 |
| `factor/report.py` | ~150 | 因子分析报告（单独输出） |
| `factor/store.py` | ~150 | 因子持久化 |

### `strategy/` 子目录（10 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `strategy/__init__.py` | ~20 | |
| `strategy/base.py` | ~100 | 策略基类 |
| `strategy/backtester.py` | ~250 | backtrader 回测 |
| `strategy/risk_manager.py` | ~200 | 风控模块 |
| `strategy/optimizer.py` | ~200 | 策略优化 |
| `strategy/stock/trend.py` | ~200 | 股票趋势跟踪 |
| `strategy/stock/multi_factor.py` | ~250 | 股票多因子 |
| `strategy/stock/stat_arb.py` | ~250 | 股票统计套利 |
| `strategy/futures/trend.py` | ~200 | 期货趋势 |
| `strategy/futures/spread.py` | ~250 | 期货套利 |
| `strategy/option/pricing.py` | ~300 | 期权定价 |
| `strategy/option/volatility.py` | ~200 | 波动率交易 |
| `strategy/option/combination.py` | ~250 | 期权组合 |

### `data/` 子目录（3 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `data/__init__.py` | ~20 | |
| `data/provider.py` | ~400 | 多市场数据提供者 |
| `data/cache.py` | ~80 | 数据缓存 |
| `data/industry.py` | ~120 | 申万行业映射 |

### `api/` 子目录（1 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `api/__init__.py` | ~20 | |
| `api/routes.py` | ~300 | 策略 API 路由 |

### `db/` 子目录（2 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `db/__init__.py` | ~20 | |
| `db/schema.py` | ~100 | 策略表 schema 定义 |
| `db/migrations.py` | ~100 | DB 迁移脚本 |

### 现有文件修改

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `src/llmwikify/config.py` | ~30 行 | 新增 strategy 章节 |
| `src/llmwikify/server/http/routes.py` | ~40 行 | 注册策略 API 路由 |
| `src/llmwikify/agent/backend/db.py` | ~30 行 | 共享 DB 连接 |

### 测试扩展（`tests/strategy/`）

| 测试类 | 行数 | 说明 |
|--------|------|------|
| `TestFactorMiner` | ~100 | 因子挖掘测试 |
| `TestFactorValidator` | ~80 | 因子验证测试 |
| `TestFactorAnalyzer` | ~80 | 因子分析测试 |
| `TestFactorNeutralizer` | ~80 | 因子中性化测试 |
| `TestFactorDecayMonitor` | ~80 | 因子衰减监控测试 |
| `TestFactorReport` | ~80 | 因子分析报告测试 |
| `TestStockTrend` | ~100 | 股票趋势跟踪测试 |
| `TestStockMultiFactor` | ~100 | 股票多因子测试 |
| `TestStockStatArb` | ~100 | 股票统计套利测试 |
| `TestFuturesTrend` | ~100 | 期货趋势跟踪测试 |
| `TestFuturesSpread` | ~100 | 期货套利测试 |
| `TestOptionPricing` | ~100 | 期权定价测试 |
| `TestOptionVolatility` | ~80 | 波动率交易测试 |
| `TestOptionCombination` | ~100 | 期权组合策略测试 |
| `TestBacktester` | ~80 | 回测引擎测试 |
| `TestRiskManager` | ~100 | 风控模块测试 |
| `TestDataProvider` | ~100 | 多市场数据提供者测试 |
| `TestSWIndustryMapping` | ~50 | 申万行业映射测试 |

## 数据库层（`db/` 子目录）

### 目录结构

```
db/
├── schema.py          # 策略表 schema 定义
└── migrations.py      # DB 迁移脚本
```

### 数据库表

```sql
-- 策略会话表
CREATE TABLE strategy_sessions (
    id TEXT PRIMARY KEY,
    research_session_id TEXT,
    strategy_type TEXT NOT NULL,
    market TEXT NOT NULL,  -- stock | futures | option
    status TEXT NOT NULL DEFAULT 'pending',
    config_json TEXT,
    result_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (research_session_id) REFERENCES research_sessions(id)
);

-- 因子元数据表
CREATE TABLE strategy_factors (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    factor_type TEXT NOT NULL,
    market TEXT NOT NULL,
    ic_value REAL,
    icir_value REAL,
    turnover REAL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES strategy_sessions(id)
);

-- 因子值表（含中性化）
CREATE TABLE factor_values (
    id TEXT PRIMARY KEY,
    factor_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_value REAL,
    industry_neutral_value REAL,
    market_cap_neutral_value REAL,
    final_value REAL,
    sw_l1_code TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(factor_name, symbol, date)
);

-- 每日因子衰减监控
CREATE TABLE factor_daily_decay (
    id TEXT PRIMARY KEY,
    factor_name TEXT NOT NULL,
    check_date TEXT NOT NULL,
    current_ic REAL,
    historical_ic_30d_avg REAL,
    decay_ratio REAL,
    alert_level TEXT,  -- normal | warning | critical
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(factor_name, check_date)
);

-- 因子分析报告
CREATE TABLE factor_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    report_type TEXT NOT NULL,  -- full | summary | decay
    content_markdown TEXT,
    content_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES strategy_sessions(id)
);

-- 申万行业映射
CREATE TABLE sw_industry_mapping (
    symbol TEXT NOT NULL,
    sw_industry_code TEXT NOT NULL,
    sw_industry_name TEXT,
    sw_l1_code TEXT NOT NULL,
    sw_l1_name TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, sw_industry_code)
);

-- 回测结果表
CREATE TABLE strategy_backtests (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    strategy_class TEXT NOT NULL,
    market TEXT NOT NULL,
    params_json TEXT,
    metrics_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES strategy_sessions(id)
);

-- 期货合约表
CREATE TABLE futures_contracts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    contract_multiplier REAL,
    margin_ratio REAL,
    tick_size REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 期权合约表
CREATE TABLE option_contracts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    underlying TEXT NOT NULL,
    strike_price REAL,
    expiry_date TEXT,
    option_type TEXT,
    exchange TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

## API 扩展

```python
# ─── 多市场策略构建 API ─────────────────────────────────

@router.post("/strategy/start")
async def start_strategy_build(request: Request):
    """启动策略构建（支持股票/期货/期权）"""
    ...

@router.get("/strategy/{session_id}/stream")
async def strategy_stream(session_id: str):
    """策略构建 SSE 流"""
    ...

@router.get("/strategy/{session_id}/factors")
async def get_factors(session_id: str):
    """获取因子列表"""
    ...

# ─── 回测 API ─────────────────────────────────────────

@router.post("/strategy/{session_id}/backtest")
async def run_backtest(session_id: str):
    """运行回测"""
    ...

@router.get("/strategy/{session_id}/backtest/{backtest_id}")
async def get_backtest_result(session_id: str, backtest_id: str):
    """获取回测结果"""
    ...

# ─── 期货特定 API ─────────────────────────────────────

@router.get("/strategy/futures/contracts")
async def get_futures_contracts(exchange: str = "SHFE"):
    """获取期货合约列表"""
    ...

@router.get("/strategy/futures/spread")
async def get_futures_spread(symbol1: str, symbol2: str):
    """获取期货价差数据"""
    ...

# ─── 期权特定 API ─────────────────────────────────────

@router.get("/strategy/option/contracts")
async def get_option_contracts(underlying: str):
    """获取期权合约列表"""
    ...

@router.get("/strategy/option/pricing")
async def calculate_option_price(symbol: str, model: str = "black_scholes"):
    """计算期权价格"""
    ...

@router.get("/strategy/option/greeks")
async def get_option_greeks(symbol: str):
    """获取期权希腊字母"""
    ...

# ─── 风控 API ─────────────────────────────────────────

@router.get("/strategy/{session_id}/risk")
async def get_risk_metrics(session_id: str):
    """获取风险指标"""
    ...

@router.post("/strategy/{session_id}/risk/check")
async def check_risk_limits(session_id: str):
    """检查风险限制"""
    ...
```

## 实施计划（基于 `src/llmwikify/strategy/`）

### Phase 1：基础设施（~200 行）

1. 创建 `strategy/__init__.py`
2. 创建 `strategy/config.py`
3. 创建 `db/__init__.py` + `db/schema.py` + `db/migrations.py`
4. 创建 `data/__init__.py`
5. 创建 `api/__init__.py`
6. 创建 `factor/__init__.py` + `strategy/__init__.py`

### Phase 2：数据层（~620 行）

1. 新建 `data/provider.py`（多市场数据提供者）
2. 新建 `data/cache.py`（数据缓存）
3. 新建 `data/industry.py`（申万行业映射）
4. 集成 Tushare + AKShare + iFinD

### Phase 3：因子子系统（~970 行）

1. 新建 `factor/miner.py`
2. 新建 `factor/validator.py`
3. 新建 `factor/analyzer.py`
4. 新建 `factor/neutralizer.py`
5. 新建 `factor/decay_monitor.py`
6. 新建 `factor/report.py`
7. 新建 `factor/store.py`

### Phase 4：策略基类与股票策略（~820 行）

1. 新建 `strategy/base.py`（策略基类）
2. 新建 `strategy/stock/trend.py`
3. 新建 `strategy/stock/multi_factor.py`
4. 新建 `strategy/stock/stat_arb.py`

### Phase 5：期货策略（~450 行）

1. 新建 `strategy/futures/trend.py`
2. 新建 `strategy/futures/spread.py`

### Phase 6：期权策略（~750 行）

1. 新建 `strategy/option/pricing.py`
2. 新建 `strategy/option/volatility.py`
3. 新建 `strategy/option/combination.py`

### Phase 7：回测、风控与优化（~650 行）

1. 新建 `strategy/backtester.py`
2. 新建 `strategy/risk_manager.py`
3. 新建 `strategy/optimizer.py`

### Phase 8：API 与集成（~640 行）

1. 新建 `api/routes.py`（策略 API）
2. 修改 `server/http/routes.py`（注册路由）
3. 集成测试

## Risk Mitigation

1. **数据源授权**：iFinD 需付费授权，Tushare 需注册 token，AKShare 免费
2. **数据质量**：多数据源交叉验证 + 缓存机制
3. **过拟合风险**：walk-forward 优化 + 样本外测试
4. **回撤控制**：最大回撤限制 + 动态止损
5. **计算性能**：并行因子计算 + 数据缓存
6. **期货风险**：保证金监控 + 强平预警 + 杠杆限制
7. **期权风险**：希腊字母监控 + Delta 对冲 + 波动率风险控制
8. **流动性风险**：滑点模型 + 成交量过滤

## Verification

1. **单元测试**：每个模块独立测试
2. **集成测试**：完整策略构建流程测试
3. **回测验证**：使用历史数据验证策略
4. **实盘模拟**：模拟交易验证策略
5. **性能测试**：因子计算和回测性能测试
6. **期货测试**：期货套利策略验证
7. **期权测试**：期权定价和组合策略验证
