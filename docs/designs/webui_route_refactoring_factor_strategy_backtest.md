# WebUI 路由重构: 因子库 / 策略库 / 回测平台

> 日期: 2026-06-22
> 作者: sn0wfree
> 状态: 设计稿

## 背景

当前 WebUI 因子/策略页面将 **库浏览** 和 **回测** 混在一起:

| 路由 | 组件 | 实际功能 |
|------|------|---------|
| `/agent/factor` | `FactorPanel` | 单因子回测平台 (选择 → 回测 → 4-tab 结果) |
| `/agent/factor-library` | `FactorDetail` | 因子定义页 (6-layer YAML) |
| `/agent/factor-library/:name` | `FactorDetail` | 同上 |
| `/agent/strategy` | `StrategyPanel` | 策略回测平台 (选择 → 回测 → KPI/PnL) |

问题: 用户想把 **库浏览** 和 **回测** 分离成独立页面。

## 目标架构

```
NAV_QUANT:
  /agent/paper      → Paper
  /agent/factor     → Factor Library (因子库浏览)
  /agent/strategy   → Strategy Library (策略库浏览)
  /agent/backtest   → Backtest Platform (单因子回测 + 策略回测)
```

路由映射:
```
/agent/factor           → FactorDetail (因子库浏览器, 带 FactorSelector)
/agent/factor/:name     → FactorDetail (指定因子)
/agent/strategy         → StrategyDetail (策略库浏览器, 带 StrategySelector) [新建]
/agent/strategy/:name   → StrategyDetail (指定策略)
/agent/backtest         → BacktestPlatform (合并 FactorPanel + StrategyPanel) [新建]
```

## 改动清单

### 1. 新建 `StrategyDetail.tsx` (~200 行)

复制 `FactorDetail.tsx` 结构, 改为策略:
- 路由: `/agent/strategy/:name`
- API: `GET /api/strategy/{slug}` (已有 `strategy.py`)
- 渲染: 策略定义 (L1-L4, 无 L5/L6)
- 左侧无 selector (通过侧栏导航), 或加 StrategySelector

### 2. 新建 `BacktestPlatform.tsx` (~150 行)

合并 FactorPanel + StrategyPanel:
- Tab 切换: 单因子回测 / 策略回测
- 左侧: FactorSelector 或 StrategySelector (随 Tab 切换)
- 右侧: 回测结果 (复用现有 MetricCards, ICChart, GroupReturnBar 等)

### 3. 更新 `App.tsx`

```diff
- <Route path="factor" element={<FactorPanel />} />
- <Route path="factor-library" element={<FactorDetail />} />
- <Route path="factor-library/:name" element={<FactorDetail />} />
- <Route path="strategy" element={<StrategyPanel />} />
+ <Route path="factor" element={<FactorDetail />} />
+ <Route path="factor/:name" element={<FactorDetail />} />
+ <Route path="strategy" element={<StrategyDetail />} />
+ <Route path="strategy/:name" element={<StrategyDetail />} />
+ <Route path="backtest" element={<BacktestPlatform />} />
```

### 4. 更新 `AgentLayout.tsx` 侧栏

```diff
  const NAV_QUANT = [
    { to: '/agent/paper', label: 'Paper', icon: FileText },
    { to: '/agent/factor', label: 'Factor', icon: Beaker },
    { to: '/agent/strategy', label: 'Strategy', icon: TrendingUp },
+   { to: '/agent/backtest', label: 'Backtest', icon: Activity },
  ] as const;
```

### 5. 修复 `StrategySelector.tsx` (同 Phase 0)

- 改调 `/api/strategy/list` (或检查后端返回格式)
- flatten categories → flat array
- 改文案 "wiki/strategy/" → "quant/strategies/"

## 验证

- [ ] `/agent/factor` 显示因子列表 + 点击进入 FactorDetail
- [ ] `/agent/strategy` 显示策略列表 + 点击进入 StrategyDetail
- [ ] `/agent/backtest` 显示 Tab: 单因子回测 / 策略回测
- [ ] 侧栏显示 Factor / Strategy / Backtest 三个入口
- [ ] vite build 成功, 0 个新 TS error
