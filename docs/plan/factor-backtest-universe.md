# 因子回测多标支持 + QuantNodes 迁移

> 范围：`/agent/factor`（单因子测试）
> 版本：v0.4.1
> 日期：2026-06-11
> 参考：`~/Public/单因子回测/`、`QuantNodes/research/factor_test/`

---

## 1. 目标

将单因子回测从"单标的时间序列"升级为"股票池截面分析"，并逐步迁移到 QuantNodes 的学术标准实现。

## 2. 分步迁移路径

### Step 1: 用 QuantNodes 纯函数替换自实现的 IC/分组/多空

**改动量**：~150 行适配代码 + ~200 行测试
**数据需求**：无额外需求（使用现有 DataRouter）
**H5 依赖**：无

将自实现的 `_compute_cross_section_ic` / `_compute_cross_section_groups` / `_compute_long_short` 替换为：
- `ICAnalyzerNode._calc_ic(factor_data, price, group_size)`
- `GroupAnalyzerNode._calc_group_return(factor_data, price, index_cp, group, factor_ori, floor_mode, hedge, hedge_path)`
- `LongShortNode._calc_longshort(group_result, factor_ori)`

同时替换 `metrics.cal_net_simple()` / `metrics.evaluation()` 为 QuantNodes 版本。

### Step 2: 加入因子预处理（可选）

加入 `FactorPreprocessNode`（去极值、标准化）和 `FactorNeutralizeNode`（行业中性化）。
需要从 ClickHouse/AKShare 查询行业代码 `id_citic1`。

### Step 3: 接入完整管线（可选）

走 `PipelineRunner.run()` 全流程。需要构造 mock DataLoader + 所有辅助数据。

## 3. 当前状态

### 已完成

- [x] `universe.py` — 指数成分股解析（42 别名、AKShare 查询、缓存）
- [x] `router.py` — `get_universe()` 批量取数 + `get_index_close()` 指数收盘价
- [x] `schemas.py` — `FactorBacktestResult` +11 字段（rank_ic、longshort 等）
- [x] `factor_backtest.py` — 自实现截面 IC/分组/多空（待替换为 QuantNodes）
- [x] `metrics.py` — `cal_net_simple()` / `evaluation()`（待替换为 QuantNodes 版本）
- [x] `factor.py` — API 支持 universe/adj_mode/hedge/n_groups/factor_direction
- [x] `paper.py` — 自动回测改用 universe
- [x] `FactorPanel.tsx` — 前端下拉框 + 调仓频率 + 多空曲线
- [x] `LongShortCurveChart.tsx` — D3 多空净值图
- [x] 测试：`test_universe.py` (15 tests) + `test_factor_backtest_cross_section.py` (20 tests)

### Step 1 待做

- [ ] 新增 `quantnodes_adapter.py`：数据格式转换（DatetimeIndex → int64 yyyymmdd）
- [ ] 改造 `factor_backtest.py`：`run_factor_backtest_universe` 调用 QuantNodes 纯函数
- [ ] 替换 `metrics.py`：改用 QuantNodes `performance_metrics.evaluation()`
- [ ] 测试验证：对比自实现 vs QuantNodes 结果

---

## 4. 文件清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `src/llmwikify/reproduction/universe.py` | ✅ 已完成 | 指数成分股解析 |
| `src/llmwikify/reproduction/router.py` | ✅ 已完成 | get_universe + get_index_close |
| `src/llmwikify/reproduction/schemas.py` | ✅ 已完成 | FactorBacktestResult 扩展 |
| `src/llmwikify/reproduction/factor_backtest.py` | 🔄 Step 1 | 自实现→QuantNodes 调用 |
| `src/llmwikify/reproduction/metrics.py` | 🔄 Step 1 | 自实现→QuantNodes 版本 |
| `src/llmwikify/reproduction/quantnodes_adapter.py` | 📝 Step 1 | 数据格式转换（新建） |
| `src/llmwikify/interfaces/server/http/factor.py` | ✅ 已完成 | API 支持 universe |
| `src/llmwikify/interfaces/server/http/paper.py` | ✅ 已完成 | 自动回测用 universe |
| `ui/webui/src/components/factor/FactorPanel.tsx` | ✅ 已完成 | 前端 UI |
| `ui/webui/src/components/shared/LongShortCurveChart.tsx` | ✅ 已完成 | 多空曲线图 |
| `tests/reproduction/test_universe.py` | ✅ 已完成 | 15 tests |
| `tests/reproduction/test_factor_backtest_cross_section.py` | ✅ 已完成 | 20 tests |

## 5. QuantNodes 节点依赖图

```
LoadData → SamplePoolFilter → TradabilityFilter → AdjustDate → FactorPreprocess → FactorNeutralize
                                                                                      ↓
                                                                              ┌────────┼────────┐
                                                                              ↓        ↓        ↓
                                                                          ICAnalyzer  Group   FactorScore
                                                                                      ↓        ↓
                                                                                    LongShort  (optional)
```

**关键发现**：ICAnalyzerNode / GroupAnalyzerNode / LongShortNode 都有纯函数接口：
- `_calc_ic(factor_data, price, group_size)` — 不依赖 context
- `_calc_group_return(factor_data, price, index_cp, ...)` — 8 个位置参数
- `_calc_longshort(group_result, factor_ori)` — 依赖 GroupAnalyzer 输出 dict

这意味着 Step 1 可以**完全不走 PipelineRunner**，直接调用纯函数。
