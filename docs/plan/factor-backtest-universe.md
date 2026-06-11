# 因子回测多标支持 实施计划

> 范围：`/agent/factor`（单因子测试）
> 版本：v0.4.1
> 日期：2026-06-11
> 参考：`~/Public/单因子回测/`、`QuantNodes/research/factor_test/`

---

## 1. 目标与背景

### 1.1 当前问题

`src/llmwikify/reproduction/factor_backtest.py` 中的 `run_factor_backtest()` 接受单个
OHLCV DataFrame，**整条链路都是单标的**：

| 层 | 文件 | 单标 |
|---|---|---|
| 前端 | `FactorPanel.tsx:57` | `useState('600660.SH')` |
| API | `factor.py:64` | `FactorBacktestRequest.symbol: str` |
| 自动回测 | `paper.py:_auto_backtest` | `symbol: "000300.SH"` |
| 数据源 | `router.py:DataSource` | `get(symbol) -> DataFrame` |
| 因子引擎 | `factor_backtest.py:109-244` | `pd.qcut()` 时间序列分组 |
| 策略引擎 | `strategies.py:198-243` | `len(group) < 2` 直接跳过 |

结果：用户拿到的不是真正的"单因子检验"，而是"单只股票时间序列上的回归"。
`FactorRankStrategyNode` 等需要多标的的策略完全失效（`len(group)<2` 跳过所有日期）。

### 1.2 目标

1. **截面 IC + 截面分组** —— 学术标准做法（参考 QuantNodes `ICAnalyzerNode` / `GroupAnalyzerNode`）
2. **股票池支持** —— 沪深 300 / 中证 500 / 中证 1000 / 上证 50 / 全 A / 自定义
3. **日频 / 月频 调仓** —— 切换后能给出不同结果
4. **多空对冲** —— 多头组 - 空头组 + 基准对冲
5. **保持向后兼容** —— 旧单标 backtest 调用方式不破坏

### 1.3 借鉴来源

| 来源 | 取什么 |
|---|---|
| `~/Public/单因子回测/factor_performance.py` | `cal_ic()`、`cal_group_ret()`、`cal_longshort_ret()` 学术实现 |
| `~/Public/单因子回测/factor_config.py` | 股票池/调仓/分组/对冲参数体系 |
| `QuantNodes/research/factor_test/nodes/ic_analyzer_node.py` | Spearman Rank IC + 因子 rank 自相关 |
| `QuantNodes/research/factor_test/nodes/group_analyzer_node.py` | 截面 qcut + 各组日度净值 + 对冲基准 |
| `QuantNodes/research/factor_test/nodes/long_short_node.py` | 多空组合构建 + 评价 |
| `QuantNodes/research/factor_test/pipeline_runner.py` | 12 阶段编排思路 |
| `QuantNodes/research/factor_test/utils/performance_metrics.py` | 单利/复利净值、最大回撤、年化 |

---

## 2. 核心设计

### 2.1 数据流（参考 QuantNodes PipelineRunner）

```
User Form
  universe: HS300        (指数代码或自定义代码列表)
  adj_mode: D            (D=日频 / M-end=月末调仓)
  hedge: equal           (equal/HS300/ZZ500/SZ50)
  n_groups: 5
  factor_direction: 1    (1=越大越好, -1=越小越好)
        |
        v
GET /api/factor/{slug}/backtest
        |
        v
1. resolve_universe("HS300") -> ["000001", "600519", ...]  (300 只)
        |
        v
2. DataRouter.get_universe(symbols, start, end)
   -> DataFrame [date, Code, open, high, low, close, volume]  (long format)
        |
        v
3. pivot to wide close_wide: [date × Code]  (300 cols)
        |
        v
4. _compute_factor_matrix(close_wide, factor_class, factor_params)
   -> factor_wide: [date × Code]
        |
        v
5. _compute_return_matrix(close_wide, forward_days)
   -> return_wide: [date × Code]
        |
        v
6. generate_adj_dates(date_index, adj_mode)
   -> adj_dates: list[pd.Timestamp]
        |
        v
7. _compute_cross_section_ic(factor_wide, return_wide, adj_dates)
   -> ic_series: list[{date, ic, rank_ic}], ic_mean, ic_std, rank_icir...
        |
        v
8. _compute_cross_section_groups(factor_wide, return_wide, adj_dates, n_groups)
   -> group_returns: {G1: Series, ...}
   -> group_curves:  {G1: Series(nav), ...}
        |
        v
9. _compute_long_short(group_curves, adj_dates, factor_direction, hedge)
   -> longshort_net: Series(nav)
   -> longshort_ann_ret, longshort_sharpe, longshort_mdd
        |
        v
10. 写 wiki/factor-backtest/{slug}-{universe}-{date}.md
        |
        v
11. 返回 JSON 给前端
```

### 2.2 关键算法（来源映射）

| 步骤 | 函数 | 借鉴自 | 行号 |
|---|---|---|---|
| 截面 IC | `_compute_cross_section_ic` | `ICAnalyzerNode._calc_ic` | `ic_analyzer_node.py:41-101` |
| 截面分组 | `_compute_cross_section_groups` | `GroupAnalyzerNode._calc_group_return` | `group_analyzer_node.py:56-193` |
| 多空组合 | `_compute_long_short` | `LongShortNode._calc_longshort` | `long_short_node.py:39-90` |
| 净值评价 | `evaluation()` | `performance_metrics.evaluation` | `performance_metrics.py:53-150` |
| 调仓日生成 | `generate_adj_dates` | `AdjustDateNode` | `adjust_date_node.py` |

### 2.3 字段映射（HKEX 学术指标 → 我们的 result）

| 学术指标 | 字段 | 显示 |
|---|---|---|
| IC 均值 (Pearson) | `ic_mean` | ✓ |
| IC 标准差 | `ic_std` | ✓ |
| ICIR | `icir` | ✓ |
| IC t-stat | `t_stat` | ✓ |
| Rank IC 均值 (Spearman) | `rank_ic_mean` | ✓ 新 |
| Rank ICIR | `rank_icir` | ✓ 新 |
| IC>0 比例 (胜率) | `win_rate` | ✓ |
| 多头组年化收益 | `annual_return` (现有) | ✓ |
| 最大回撤 | `max_drawdown` | ✓ |
| 换手率 | `turnover` | ✓ |
| **新增** | | |
| 多空年化 | `longshort_ann_return` | ✓ 新 |
| 多空 Sharpe | `longshort_sharpe` | ✓ 新 |
| 多空最大回撤 | `longshort_mdd` | ✓ 新 |
| 多空净值曲线 | `longshort_curve` | ✓ 新 (chart) |
| 截面样本量 | `n_stocks_per_date` | ✓ 新 (info) |
| 股票池 | `universe` | ✓ 新 (info) |
| 调仓频率 | `adj_mode` | ✓ 新 (info) |

---

## 3. 实施阶段

### Phase 1: 多标数据获取

**1.1 `src/llmwikify/reproduction/universe.py` (新建, ~80 行)**

```python
INDEX_ALIASES = {
    "HS300": "000300", "000300": "000300", "000300.SH": "000300",
    "沪深300": "000300",
    "ZZ500": "000905", "000905": "000905", "000905.SH": "000905",
    "中证500": "000905",
    "SZ50": "000016", "000016": "000016", "000016.SH": "000016",
    "上证50": "000016",
    "ZZ1000": "000852", "000852": "000852", "000852.SH": "000852",
    "中证1000": "000852",
    "ZZ800": "000906", "000906": "000906",
    "CSI300": "000300", "CSI500": "000905",
}

def get_index_constituents(index_code: str) -> list[str]:
    """调 AKShare 获取指数成分股 (6 位代码列表)."""

def resolve_universe(spec: str | list[str]) -> list[str]:
    """解析 universe spec. 字符串→指数代码→成分股; 列表→直接返回."""
```

**1.2 `src/llmwikify/reproduction/router.py` 改造**

新增两个方法（保留现有 `get` 不变）：

```python
def get_universe(
    self,
    symbols: list[str],
    start: str,
    end: str,
) -> tuple[pd.DataFrame, str]:
    """批量取多标 OHLCV, 返回 long format [date, Code, close...].
    
    对每个 symbol 串行调 self.get(), 失败时跳过.
    返回: (merged_df, source_name). source_name 是首个成功的源.
    """

def get_index_close(
    self,
    index_code: str,
    start: str,
    end: str,
) -> Optional[pd.Series]:
    """取指数收盘价, 返回 pd.Series (date index → close)."""
```

### Phase 2: 截面因子计算

**2.1 `src/llmwikify/reproduction/factor_backtest.py` 改造**

保留现有 `run_factor_backtest()` (单标 backward compatible)。

新增：

```python
def run_factor_backtest_universe(
    close_wide: pd.DataFrame,         # [date × Code] wide format
    factor_class: str,
    factor_params: dict[str, Any],
    index_close: Optional[pd.Series] = None,  # 基准对冲 (Series)
    adj_mode: str = "D",              # "D" / "M-end"
    n_groups: int = 5,
    factor_direction: int = 1,
    forward_days: int = 1,
) -> FactorBacktestResult:
    """多标截面因子回测主函数.
    
    步骤:
    1. factor_wide = _compute_factor_matrix(close_wide, ...)
    2. return_wide = _compute_return_matrix(close_wide, forward_days)
    3. adj_dates = generate_adj_dates(close_wide.index, adj_mode)
    4. ic_result = _compute_cross_section_ic(factor_wide, return_wide, adj_dates)
    5. group_result = _compute_cross_section_groups(factor_wide, return_wide, adj_dates, n_groups)
    6. ls_result = _compute_long_short(group_result, adj_dates, factor_direction, index_close)
    7. 组装 FactorBacktestResult 并返回
    """
```

辅助函数：
- `_compute_factor_matrix(close_wide, factor_class, factor_params) -> pd.DataFrame`
  - 对每只股票调 `_compute_factor_values` 然后 stack
- `_compute_return_matrix(close_wide, forward_days) -> pd.DataFrame`
  - `close_wide.pct_change(forward_days).shift(-forward_days)`
- `generate_adj_dates(date_index, adj_mode) -> list`
  - "D" → 全部日期
  - "M-end" → 每月最后交易日
- `_compute_cross_section_ic(factor_wide, return_wide, adj_dates) -> dict`
  - 每个 adj_date: `pd.Series.spearmanr(factor_t, return_t)`
  - 计算 `ic_mean, ic_std, rank_ic_mean, rank_ic_std, icir, rank_icir, win_rate, ic_series`
- `_compute_cross_section_groups(factor_wide, return_wide, adj_dates, n_groups) -> dict`
  - 每个 adj_date: `pd.qcut(factor_t.rank(method="first"), n_groups, labels=range(1,n_groups+1))`
  - 计算各组等权平均收益
  - 计算各组日度净值（组内成员当日 mean close → cumprod）
- `_compute_long_short(group_curves, adj_dates, factor_direction, index_close) -> dict`
  - 多头: G_n (factor_direction=1) / G_1 (=-1)
  - 空头: G_1 (=1) / G_n (=-1)
  - 多空净值: `long_net - short_net + 1` (单利)
  - 调 `metrics.evaluation()` 算 sharpe/ann_ret/mdd

**2.2 `src/llmwikify/reproduction/schemas.py` 扩展**

`FactorBacktestResult` 新增 6 字段（默认值保持 backward compatible）：

```python
@dataclass
class FactorBacktestResult:
    # 现有 11 字段
    ic_mean: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0
    t_stat: float = 0.0
    win_rate: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    turnover: float = 0.0
    quantile_returns: dict[str, float] = field(default_factory=dict)
    ic_series: list[dict[str, Any]] = field(default_factory=list)
    quantile_curves: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    
    # 新增 (多标/截面)
    rank_ic_mean: float = 0.0
    rank_ic_std: float = 0.0
    rank_icir: float = 0.0
    longshort_ann_return: float = 0.0
    longshort_sharpe: float = 0.0
    longshort_mdd: float = 0.0
    longshort_curve: list[dict[str, Any]] = field(default_factory=list)
    universe: str = ""
    adj_mode: str = "D"
    n_stocks_per_date: list[int] = field(default_factory=list)
```

### Phase 3: API 端点改造

**3.1 `src/llmwikify/interfaces/server/http/factor.py`**

`FactorBacktestRequest` 新增字段（默认 backward compatible）：

```python
class FactorBacktestRequest(BaseModel):
    # 旧字段保留
    symbol: str = "600660.SH"
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-31"
    benchmark_code: str = "000300.SH"
    
    # 新字段
    universe: str = "HS300"         # 指数/股票池
    adj_mode: str = "D"             # D / M-end
    hedge: str = "equal"            # equal / HS300 / ZZ500 / SZ50
    n_groups: int = 5
    factor_direction: int = 1
```

`backtest_factor` 改造：
- 解析 universe → symbols
- `DataRouter.get_universe(symbols, start, end)` → long format
- pivot to wide close
- `DataRouter.get_index_close(hedge_code, start, end)` → index_close
- `run_factor_backtest_universe(close_wide, ...)` → result
- 写 wiki + 返回 JSON

向后兼容：若 `universe == "single"` 则走旧的单标路径。

**3.2 `src/llmwikify/interfaces/server/http/paper.py` 自动回测**

`_auto_backtest()` 调因子回测时：
- 默认 `universe = "HS300"` 而非 `symbol = "000300.SH"`
- 优先读 `data_requirements.universe` 字段

### Phase 4: 前端 UI 改造

**4.1 `ui/webui/src/components/factor/FactorPanel.tsx`**

替换单标输入：

```tsx
// 股票池选择
<select value={universe} onChange={...}>
  <option value="HS300">沪深 300 (300 只)</option>
  <option value="ZZ500">中证 500 (500 只)</option>
  <option value="SZ50">上证 50 (50 只)</option>
  <option value="ZZ1000">中证 1000 (1000 只)</option>
  <option value="all">全 A 股</option>
  <option value="single">单标的回测（旧）</option>
  <option value="custom">自定义...</option>
</select>

{universe === "custom" && (
  <input placeholder="指数代码 (如 000300)" />
)}
{universe === "single" && (
  <input placeholder="Symbol" />
)}

// 调仓频率
<select value={adjMode}>
  <option value="D">日频</option>
  <option value="M-end">月频 (月末调仓)</option>
</select>

// 对冲基准
<select value={hedge}>
  <option value="equal">等权</option>
  <option value="HS300">HS300 对冲</option>
  <option value="ZZ500">ZZ500 对冲</option>
</select>
```

结果区增强：
- `MetricCards` 增加到 8 列：IC/RankIC/ICIR/胜率/多头年化/多空年化/多头 MDD/多空 MDD
- 新增 `LongShortCurveChart` 组件

**4.2 `ui/webui/src/components/shared/LongShortCurveChart.tsx` (新建)**

D3.js line chart，仿 `ICChart` 模式：
- 单线（多空净值）
- Props: `curve: [{date, value}]`, `height?: number`

### Phase 5: 测试

**5.1 `tests/reproduction/test_universe.py` (新建, ~80 行)**
- `get_index_constituents("HS300")` → 300 只
- `resolve_universe("000300")` → 300 只
- `resolve_universe(["000001", "600519"])` → 自定义列表
- 别名映射 (`"CSI300"`, `"沪深300"`, etc.)

**5.2 `tests/reproduction/test_factor_backtest_cross_section.py` (新建, ~150 行)**
- 模拟 10 只股票 × 100 天 close prices
- 测试 `run_factor_backtest_universe`:
  - `rank_ic_mean != 0`
  - `group_returns` 5 组
  - `longshort_curve` 不为空
- 测试日频 vs 月频
- 测试 `factor_direction=1` vs `-1` 多空方向翻转

**5.3 `tests/reproduction/test_factor_api.py` 扩展**
- `POST /api/factor/{slug}/backtest` 传 `universe: "HS300"`
- 验证返回 `metrics.rank_ic_mean` / `metrics.longshort_ann_return`
- 兼容测试: `universe: "single"` 走旧路径

---

## 4. 修改文件清单

| 文件 | 类型 | 改动 |
|---|---|---|
| `docs/plan/factor-backtest-universe.md` | 新建 | 本文档 |
| `src/llmwikify/reproduction/universe.py` | 新建 | 指数成分股 + universe 解析 |
| `src/llmwikify/reproduction/router.py` | 修改 | + `get_universe()`, `get_index_close()` |
| `src/llmwikify/reproduction/factor_backtest.py` | 重大 | + `_compute_factor_matrix`, `_compute_cross_section_ic`, `_compute_cross_section_groups`, `_compute_long_short`, `run_factor_backtest_universe` |
| `src/llmwikify/reproduction/schemas.py` | 修改 | `FactorBacktestResult` +10 字段 |
| `src/llmwikify/interfaces/server/http/factor.py` | 修改 | API 新字段 + 路由逻辑 |
| `src/llmwikify/interfaces/server/http/paper.py` | 修改 | 自动回测改用 universe |
| `ui/webui/src/components/factor/FactorPanel.tsx` | 修改 | 下拉 + 调仓频率 |
| `ui/webui/src/components/shared/LongShortCurveChart.tsx` | 新建 | D3 多空曲线 |
| `tests/reproduction/test_universe.py` | 新建 | universe 解析 |
| `tests/reproduction/test_factor_backtest_cross_section.py` | 新建 | 截面计算 |
| `tests/reproduction/test_factor_api.py` | 修改 | + universe 测试 |

预估：12 文件修改，~800 行新增代码 + ~200 行修改。

---

## 5. 实施顺序

1. **Phase 1** (universe + router) — 1-2 文件，先跑通多标取数
2. **Phase 2.2** (schemas) — 字段先行
3. **Phase 2.1** (factor_backtest) — 核心逻辑
4. **Phase 3** (API) — 端到端
5. **Phase 4** (前端) — UI
6. **Phase 5** (测试) — 单元 + 集成

每阶段 commit 一次，便于 review 与回滚。

---

## 6. 风险点与缓解

| 风险 | 缓解 |
|---|---|
| AKShare 不可用 | `get_universe` 失败时返回空列表，前端提示"成分股获取失败" |
| 数据量过大 (300×750日) | 串行 fetch 慢但稳定；Phase 2 内不优化性能 |
| QuantNodes `PipelineRunner` 依赖多 | 不调它，复用其算法逻辑（ICAnalyzer/GroupAnalyzer/LongShort）|
| 月频 vs 日频 group 结果差异 | 两种 adj_mode 独立实现，避免耦合 |
| 现有单标 backtest 破坏 | 保留 `run_factor_backtest()` 函数 + `universe=="single"` 兼容路径 |
| 长格式 ↔ 宽格式 转置耗时 | 1000 股票 × 750 天 ≈ 75 万 cells，pandas pivot < 1s |
| `evaluation()` 需要单利 net 曲线 | 在 `_compute_long_short` 内做 `cal_net_simple` 转换 |

---

## 7. 不在范围 (后续迭代)

- 行业中性化 (需要中信一级行业数据)
- 风险因子中性化 (需要 risk_factor 库)
- 市值行业分层打分 (87 组, 来自 `score_by_size_ind`)
- 因子演化 (EvolutionLoop, QualityGate)
- LLM 因子表达式合成 (FactorScoreNode)
- 并行/批量数据获取 (当前串行 fetch)

这些是 QuantNodes 的高级功能，可在后续版本加入。
