# WebUI 路由重构: 因子库 / 策略库 / 回测平台

> 日期: 2026-06-22（实现于 2026-06-23）
> 作者: sn0wfree
> 状态: 已实现

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
/agent/factor           → FactorList (因子库展示页, 卡片按 category 分组)
/agent/factor/:name     → FactorDetail (6 层详情)
/agent/strategy         → StrategyList (策略库展示页)
/agent/strategy/:name   → StrategyDetail (4 层详情)
/agent/backtest         → BacktestPlatform (单因子回测 + 策略回测 Tab)
```

## 改动清单

### 1. 新建 `FactorList.tsx` / `StrategyList.tsx` (展示页)

因子/策略库**展示页**, 独立于回测平台:
- `FactorList`: 调 `GET /api/factor/library/list`, flatten categories → 按 category 分组的卡片网格, 点击导航至 `/agent/factor/:name`
- `StrategyList`: 调 `GET /api/strategy/list`, 卡片网格, 点击导航至 `/agent/strategy/:name`
- 卡片展示 name_cn / definition / status，点击进入对应的 Detail 详情页

### 2. `FactorDetail.tsx` / `StrategyDetail.tsx` (详情页, 已有)

- `FactorDetail`: 渲染 6 层 YAML (L1-L6), API `GET /api/factor/library/{name}`
- `StrategyDetail`: 渲染 4 层定义 (L1-L4), API `GET /api/strategy/{slug}`
- 仅接受 `:name` 路由参数; 无 `name` 时不再渲染 (由 List 页负责选择)

### 3. `BacktestPlatform.tsx` (回测平台, 已有)

合并 FactorPanel + StrategyPanel:
- Tab 切换: 单因子回测 / 策略回测
- `FactorPanel` / `StrategyPanel` 仅在此处使用 (不再绑定 Factor/Strategy 菜单)
- 复用 MetricCards, ICChart, GroupReturnBar 等可视化组件

### 4. `App.tsx` 路由 (最终结果)

```tsx
<Route path="factor" element={<FactorList />} />
<Route path="factor/:name" element={<FactorDetail />} />
<Route path="strategy" element={<StrategyList />} />
<Route path="strategy/:name" element={<StrategyDetail />} />
<Route path="backtest" element={<BacktestPlatform />} />
```

### 5. 更新 `AgentLayout.tsx` 侧栏

```diff
  const NAV_QUANT = [
    { to: '/agent/paper', label: 'Paper', icon: FileText },
    { to: '/agent/factor', label: 'Factor', icon: Beaker },
    { to: '/agent/strategy', label: 'Strategy', icon: TrendingUp },
+   { to: '/agent/backtest', label: 'Backtest', icon: Activity },
  ] as const;
```

## 验证

- [x] `/agent/factor` 显示因子库展示页 (卡片列表) + 点击进入 FactorDetail
- [x] `/agent/strategy` 显示策略库展示页 (卡片列表) + 点击进入 StrategyDetail
- [x] `/agent/backtest` 显示 Tab: 单因子回测 / 策略回测
- [x] 侧栏显示 Factor / Strategy / Backtest 三个入口
- [x] vite build 成功, 0 个新 TS error
