# cross-validation summary

## 验证框架

```
外部独立吗?   对比对象                   验证内容              结果
──────────────────────────────────────────────────────────────────────
★★☆☆☆        纯重写 (pandas/numpy)    全链路（IC/Group/LS/ev）  19/19 PASS
★★★★☆        QuantNodes 原始节点       分组一致 0/1113 diff ✅   方向一致 2/2 ✅
★★★★★        Alphalens (行业标准库)     RankIC diff=0.0000 ✅    分组一致 0/1113 ✅
```

## Alphalens 对比结果

Alphalens 是 Quantopian 开源的因子分析库，业界事实标准。

| 检查项 | 结果 |
|--------|------|
| RankIC 对比 | 4 个调仓日 **diff=0.0000** ✅ |
| 分组一致性 | 1113 个股票-日期分配中 **0 差异** ✅ |
| 数据清洗率 | 0.9% 一致 (fill_method='pad') ✅ |

## 已验证的算法逻辑

factor_backtest.py 与 Alphalens 在以下方面完全一致：
- **因子值计算**: per-stock dropna → pct_change(period)
- **Forward return**: prices.pct_change(1).shift(-1) (fill_method='pad')
- **IC 计算**: Spearman rank correlation per date
- **分组**: pd.qcut(..., duplicates='drop')
- **组均收益**: 组内等权 forward return 均值

## 已知差异 (非 bug)

| 差异 | 我们的选择 | QN的选择 | 原因 |
|------|-----------|---------|------|
| Forward horizon | 1-day | inter-period | 设计差异，参数可配 |
| IC 默认输出 | Pearson + Spearman | Spearman only | 设计差异 |
| fill_method | 'pad' (默认) | 'pad' (一致) | pandas 2.1 仍默认 'pad' |
| Adj_dates 生成 | 月末尾+数据过滤 | 月末尾+数据过滤 | 逻辑一致 |
