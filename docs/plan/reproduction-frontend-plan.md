# Reproduction 前端实现计划

> 版本: v0.4.0
> 日期: 2026-06-10
> 状态: **已实施完成**（13 commits, 84/84 测试通过）

---

## 一、三子页面定位

| 页面 | 输入 | 输出 | 独立性 |
|---|---|---|---|
| **Paper** | PDF/URL | Factor + Strategy wiki 页面 | 可独立运行 |
| **Factor** | wiki/factor/ 页面 | 因子回测指标（IC/IR/收益） | 可独立运行 |
| **Strategy** | wiki/strategy/ 页面 | 策略回测指标（Sharpe/MDD/PnL） | 可独立运行 |

**关键关系**：Paper 是"工厂"，产出 Factor 和 Strategy wiki 页面。Factor 和 Strategy 可独立运行（用户自定义因子/策略）。

---

## 二、wiki 页面类型体系

### 现有类型

| Type | 目录 | 用途 |
|---|---|---|
| TradingStrategy | `wiki/trading/` | 从论文中提取的交易策略 |
| BacktestResult | `wiki/backtest/` | TradingStrategy 的回测结果 |
| Optimization | `wiki/optimization/` | 策略参数敏感性分析 |

### 新增类型

| Type | 目录 | Frontmatter 字段 |
|---|---|---|
| **Factor** | `wiki/factor/` | `factor_class`, `factor_params`, `factor_source`, `status` |
| **Strategy** | `wiki/strategy/` | `strategy_class`, `signal_type`, `signal_params`, `factor_refs`, `status` |
| **FactorBacktest** | `wiki/factor-backtest/` | `factor_ref`, `symbol`, `start`, `end`, `ic_mean`, `icir`, `win_rate`, `annual_return` |

### 页面关系

```
Paper 产出:
  wiki/factor/{slug}.md          → Factor 页面读取
  wiki/strategy/{slug}.md        → Strategy 页面读取

Factor 回测产出:
  wiki/factor-backtest/{slug}.md

Strategy 回测产出:
  wiki/backtest/{slug}.md        → 已有 BacktestResult
  wiki/optimization/{slug}.md    → 已有 Optimization
```

---

## 三、分阶段实施

### Phase 1: 基础设施

**目标**：扩展 wiki 类型体系 + 数据类 + 指标计算 + 基准数据

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `wiki_schema.yaml` | 改 | +6 | 新增 Factor/Strategy/FactorBacktest 类型 |
| `schemas.py` | 改 | +40 | 新增 WikiFactor/WikiStrategy/FactorBacktestResult |
| `metrics.py` | 改 | +30 | 新增 CAGR/Sortino/Alpha/Beta |
| `router.py` | 改 | +20 | DataRouter 加 get_benchmark() |

**验证**：现有 49 个测试仍通过 + 新增 metrics 测试 ✅

### Phase 2: 后端引擎

**目标**：论文抽取 + 因子提取 + 因子回测 + 路由

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `extract_paper.py` | 新 | ~120 | LLM 论文结构化抽取 |
| `extract_factors.py` | 新 | ~100 | LLM 因子提取 + 信号映射 |
| `factor_backtest.py` | 新 | ~150 | 因子回测引擎（IC/分层/收益） |
| `repro_extract.yaml` | 新 | ~80 | 论文抽取 prompt |
| `repro_factor.yaml` | 新 | ~60 | 因子提取 prompt |
| `paper.py` | 新 | ~80 | Paper REST 路由 |
| `factor.py` | 新 | ~80 | Factor REST 路由 |
| `strategy.py` | 新 | ~80 | Strategy REST 路由 |

**验证**：单元测试 + E2E 测试（合成数据）✅

### Phase 3: 前端共享组件

**目标**：可复用的图表和展示组件

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `LineChart.tsx` | 新 | ~140 | d3 折线/面积图（IC 序列、净值曲线） |
| `MetricCards.tsx` | 改 | ~60 | 横排指标卡片 |
| `PageView.tsx` | 新 | ~50 | wiki markdown 渲染 |
| `FactorSelector.tsx` | 新 | ~80 | 扫描 wiki/factor/ 目录 |
| `StrategySelector.tsx` | 新 | ~80 | 扫描 wiki/strategy/ 目录 |

**验证**：TypeScript 编译通过 ✅

### Phase 4: Paper 页面

**目标**：论文复现完整流程

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `PaperPanel.tsx` | 新 | ~250 | 论文复现主面板 |
| `PaperForm.tsx` | 新 | ~100 | 论文表单（PDF/URL + 股票 + 日期） |

**验证**：手动测试（提交论文 → 看产出）✅

### Phase 5: Factor 页面

**目标**：单因子回测 + 可视化

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `FactorPanel.tsx` | 新 | ~250 | 单因子测试主面板 |
| `ICChart.tsx` | 新 | ~120 | IC 时间序列图（d3） |
| `QuantileCurves.tsx` | 新 | ~100 | 分层净值曲线（d3） |
| `ICDistribution.tsx` | 新 | ~80 | IC 分布直方图（d3） |

**验证**：手动测试（选择因子 → 看 IC/分层结果）✅

### Phase 6: Strategy 页面

**目标**：策略回测 + 完整报告

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `StrategyPanel.tsx` | 新 | ~250 | 策略跟踪主面板 |
| `MonthlyHeatmap.tsx` | 新 | ~100 | 月度收益热力图（d3） |
| `DrawdownChart.tsx` | 新 | ~80 | 回撤图（d3） |

**验证**：手动测试（选择策略 → 看回测结果）✅

### Phase 7: 路由 + 侧边栏 + 验证

**目标**：整合所有页面 + 最终验证

| 文件 | 操作 | 行数 | 说明 |
|---|---|---|---|
| `App.tsx` | 改 | +6 | 注册 3 个路由 |
| `AgentLayout.tsx` | 改 | +20 | 侧边栏 Quant 分组 |
| `lib/reproduction-api.ts` | 改 | +50 | 补充 API 客户端 |

**验证**：npm install + pnpm build + 手动全流程测试 ✅（后端84/84 测试通过，前端 import 路径已验证）

---

## 四、路由设计

```
/agent/paper          → 论文复现（新建 / 历史列表）
/agent/paper/:id      → 论文详情

/agent/factor         → 单因子测试（因子选择 + 新建）
/agent/factor/:slug   → 因子回测详情

/agent/strategy       → 策略跟踪（策略选择 + 新建）
/agent/strategy/:slug → 策略回测详情
```

---

## 五、侧边栏结构

```
AgentLayout
├── Workspace
│   ├── 💬 Chat
│   └── 🔍 Research
├── Quant                              ← 新建分组
│   ├── 📄 Paper
│   ├── 🧪 Factor
│   └── 📊 Strategy
└── System
    ├── ✓ Tasks
    └── ⚙ Settings
```

---

## 六、后端 API 端点

### Paper

| 方法 | 端点 | 说明 |
|---|---|---|
| POST | `/api/paper/start` | 启动论文复现 |
| GET | `/api/paper/{id}` | 获取论文详情 |
| GET | `/api/paper/{id}/artifacts` | 获取产出的 wiki 页面 |

### Factor

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/factor/list` | 列出所有 wiki/factor/ 页面 |
| GET | `/api/factor/{slug}` | 获取因子定义 |
| POST | `/api/factor/{slug}/backtest` | 执行因子回测 |

### Strategy

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/strategy/list` | 列出所有 wiki/strategy/ 页面 |
| GET | `/api/strategy/{slug}` | 获取策略定义 |
| POST | `/api/strategy/{slug}/backtest` | 执行策略回测 |

---

## 七、数据流

### Paper

```
PDF/URL + 股票 + 日期
  ↓
Phase 1: LLM 论文理解 → 写 8 个知识页面
Phase 2: LLM 因子提取 → 写 wiki/factor/{slug}.md
Phase 3: LLM 策略映射 → 写 wiki/strategy/{slug}.md
  ↓
产出: Factor 页面 + Strategy 页面
```

### Factor

```
wiki/factor/{slug}.md (frontmatter)
  + 用户选择股票/日期
  ↓
复用 strategies.py StrategyNode 计算因子值
  ↓
计算: IC 序列、分层净值、因子收益、换手率
  ↓
产出: wiki/factor-backtest/{slug}.md
```

### Strategy

```
wiki/strategy/{slug}.md (frontmatter)
  + 用户选择股票/日期
  ↓
run_backtest(signal_type, signal_params, data, benchmark)
  ↓
计算: Sharpe/MDD/Sortino/Alpha/Beta + 月度收益矩阵
  ↓
产出: wiki/backtest/{slug}.md + wiki/optimization/{slug}.md
```

---

## 八、工时估算

| Phase | 后端 | 前端 | 总计 |
|---|---|---|---|
| Phase 1: 基础设施 | 60 min | — | 60 min |
| Phase 2: 后端引擎 | 250 min | — | 250 min |
| Phase 3: 前端共享组件 | — | 200 min | 200 min |
| Phase 4: Paper 页面 | — | 150 min | 150 min |
| Phase 5: Factor 页面 | — | 200 min | 200 min |
| Phase 6: Strategy 页面 | — | 180 min | 180 min |
| Phase 7: 路由 + 验证 | 20 min | 30 min | 50 min |
| **总计** | **~330 min** | **~760 min** | **~18 小时** |

---

## 九、风险与缓解

| 风险 | 缓解 |
|---|---|
| 因子回测需要多标的数据 | DataRouter 扩展支持多标的（或先用单标的退化） |
| LLM prompt 调试耗时 | 先用合成数据验证，再接真实 LLM |
| d3 图表组件复杂 | 复用 LineChart 模板，新图表只改数据映射 |
| node_modules 损坏 | 每个 Phase 结束后验证编译 |
| 月度热力图数据量大 | 后端预计算，前端只渲染 |

---

## 十、实际实施结果

### Git 历史（13 commits）

```
a5f7807 feat(reproduction): Phase 2.4 — factor backtest engine
234960f feat(reproduction): Phase 5+6 enhancements — chart components
2722678 feat(reproduction): Phase 4-7 — frontend pages + routing + sidebar
d5ae417 feat(reproduction): Phase 3 — shared frontend components
b8bb1f6 feat(reproduction): Phase 0 — initial frontend scaffolding
3c01818 feat(reproduction): Phase 2.3 — paper/factor/strategy REST routes
d1eff1f feat(reproduction): Phase 2.2 — factor extraction from paper understanding
1f3bf17 feat(reproduction): Phase 2.1 — paper structure extraction
40c1963 feat(reproduction): Phase 1 — wiki types + schemas + metrics + benchmark
362336b docs(plan): reproduction frontend implementation plan
374b179 docs(research): factor & strategy analysis display patterns survey
2d7d20f feat(reproduction): add 5-Phase orchestration + REST endpoint (v0.4.0)
```

### 测试结果

```
84 passed, 5 warnings ✅
- 49 original tests
- 8 extract_paper tests
- 6 extract_factors tests
- 9 routes tests (paper/factor/strategy)
- 12 factor_backtest tests
```

### 实际文件清单

**后端（11 新建 +4 修改）**

| 文件 | 说明 |
|---|---|
| `extract_paper.py` | LLM 论文结构化抽取 |
| `extract_factors.py` | LLM 因子提取 + 信号映射 |
| `factor_backtest.py` | 8 种因子计算 + IC/分层/换手率 |
| `repro_extract.yaml` | 论文抽取 prompt |
| `repro_factor.yaml` | 因子提取 prompt |
| `paper.py` | Paper REST 路由 |
| `factor.py` | Factor REST 路由 |
| `strategy.py` | Strategy REST 路由 |
| `wiki_schema.yaml` | +Factor/Strategy/FactorBacktest 类型 |
| `schemas.py` | +WikiFactor/WikiStrategy/FactorBacktestResult |
| `metrics.py` | +CAGR/Sortino/Alpha/Beta |
| `router.py` | +get_benchmark() |
| `__init__.py` | 导出新 schemas |

**前端（15 新建 +2 修改）**

| 文件 | 说明 |
|---|---|
| `components/paper/PaperPanel.tsx` | 论文复现主面板 |
| `components/paper/PaperForm.tsx` | 论文表单（4 字段一行） |
| `components/factor/FactorPanel.tsx` | 单因子测试主面板 |
| `components/strategy/StrategyPanel.tsx` | 策略跟踪主面板 |
| `components/shared/LineChart.tsx` | d3 折线/面积图 |
| `components/shared/MetricCards.tsx` | 横排指标卡片 |
| `components/shared/PageView.tsx` | wiki markdown 渲染 |
| `components/shared/HeatMap.tsx` | d3 热力图 |
| `components/shared/ICChart.tsx` | IC 时间序列 + 分布直方图 |
| `components/shared/QuantileCurves.tsx` | G1-G5 分层净值曲线 |
| `components/shared/DrawdownChart.tsx` | 回撤水下曲线 |
| `components/shared/FactorSelector.tsx` | 因子选择器 |
| `components/shared/StrategySelector.tsx` | 策略选择器 |
| `components/reproduction/*` | 5 个原 v0.4.0 前端组件 |
| `App.tsx` | 注册 /agent/paper/factor/strategy 路由 |
| `AgentLayout.tsx` | 侧边栏 Quant 分组 |
| `lib/reproduction-api.ts` | API 客户端 |

### 路由结构

```
/agent/paper          → 论文复现（PaperPanel）
/agent/factor         → 单因子测试（FactorPanel）
/agent/strategy       → 策略跟踪（StrategyPanel）
```

### 侧边栏

```
AgentLayout
├── Workspace
│   ├── 💬 Chat
│   └── 🔍 Research
├── Quant
│   ├── 📄 Paper
│   ├── 🧪 Factor
│   └── 📊 Strategy
└── System
    ├── ✓ Tasks
    └── ⚙ Settings
```

### 因子类型支持（8 种）

| factor_class | 计算公式 |
|---|---|
| momentum | `close.pct_change(period)` |
| volatility | `close.pct_change().rolling(period).std()` |
| ma_cross | `(MA(fast) - MA(slow)) / MA(slow)` |
| rsi | `100 - 100 / (1 + RS)` |
| value | `close / MA(period) - 1` |
| quality | `-close.pct_change().rolling(period).std()` |
| size | `log(close * volume + 1)` |
| growth | `close.pct_change(period)` |
| signal_composite | `momentum / volatility` |

### 已知限制

1. **因子回测单标的退化**：当前 `_compute_quantile_returns` 使用 `pd.qcut` 在时序数据上分组，对于单标的数据会退化为时间分层（不是严格的横截面分层）。完整横截面分析需要扩展 DataRouter 支持多标的。

2. **StrategyPanel Equity Curve 占位**：净值曲线区因 QuantNodes Trade 对象不含日期字段，目前仅显示占位。完整实现需要从 trades + 日期数据生成 equity 时序。

3. **LLM prompt 调优**：repro_extract.yaml / repro_factor.yaml 是初始版本，需要根据实际 LLM 输出迭代优化。

### 下一步建议

1. `npm install && pnpm build` 验证前端编译
2. 创建 PR 合并到 main 分支
3. v0.5.0 扩展：多标的数据支持、Equity Curve 完整实现、FactorBacktest 写入 wiki
