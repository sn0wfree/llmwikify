# LLM 代码生成五大失败模式

## 概览

| # | 失败模式 | 频率 | 严重度 | 修复方案 |
|---|---------|------|--------|---------|
| 1 | Polars `.over()` 惰性求值陷阱 | 高 | NaN IC | RULE 2: with_columns 物化 |
| 2 | Python `if` on Polars Expr | 高 | DangerousCodeError | RULE 3 + 正则拦截 |
| 3 | 函数形式 vs 方法形式混淆 | 高 | 执行失败 | RULE 1: 函数形式 |
| 4 | 二值/常数因子导致 IC NaN | 低 | NaN IC | 自动检测 + noise |
| 5 | 复杂公式超时 | 低 | TimeoutError | timeout 120s |

---

## 失败模式 1: Polars `.over()` 惰性求值陷阱

### 问题描述

Polars 的 `.over('date')` 在 `select()` 上下文中会**在每个分组内重新计算整个表达式**。当表达式含 rolling/correlation 操作时，分组内行数（50 行/日期）不足以满足窗口需求，导致 NaN 或跨 code 污染。

### 表现

- 因子值 100% NaN
- 或因子值全零（ranking 相同导致比较永远 False）
- IC 计算返回 NaN

### 根因

```python
# ❌ 错误：select() 内联表达式，.over('date') 会在分组内重算
factor = rank(correlation(expr1, expr2, window=200)).over('date')
# correlation(window=200) 需要 200 行，但每个 date 分组只有 50 行 → NaN
```

### 修复方案

```python
# ✅ 正确：先用 with_columns 物化，再在物化列上做 .over('date')
df = df.with_columns(correlation(expr1, expr2, window=200).alias('_corr'))
factor = rank(pl.col('_corr')).over('date')
```

### 规则

**RULE 2: MATERIALIZE BEFORE .over('date')**

当 rank/scale 依赖 rolling/correlation 结果时，必须先用 `with_columns().alias()` 物化。

### 验证

- Alpha-037: 修复前 NaN IC → 修复后 IC=+0.0359, ICIR=+0.2732
- Alpha-061: 修复前全零 → 修复后 IC=-0.0000 (valid)

---

## 失败模式 2: Python `if` on Polars Expr

### 问题描述

LLM 看到公式中的比较运算符（`<`, `>`, `? :`）会生成 Python `if` 语句，但 Polars 表达式不能用在 Python 布尔上下文中。

### 表现

- `DangerousCodeError: the truth value of an Expr is ambiguous`
- LLM 4 轮重试都犯同样错误

### 根因

```python
# ❌ 错误：LLM 生成的代码
if rank(pl.col('a')).over('date') < rank(pl.col('b')).over('date'):
    factor = -1
else:
    factor = 0
```

### 修复方案

```python
# ✅ 正确：使用 pl.when().then().otherwise()
factor = pl.when(
    rank(pl.col('a')).over('date') < rank(pl.col('b')).over('date')
).then(-1).otherwise(0)
```

### 防御层

| 层级 | 机制 | 效果 |
|------|------|------|
| Prompt | RULE 3: NO PYTHON BOOLEAN ON POLARS EXPR | 教 LLM 正确模式 |
| Safety | `_validate_safety()` 正则拦截 | 执行前拦截 |
| OBSERVE | 反馈模板给具体修复示例 | 重试时修复 |
| Auto-fix | `_sanitize_code()` and→&, or→\|, not→~ | 自动修正 |

### 规则

**RULE 3: NO PYTHON BOOLEAN ON POLARS EXPR**

- `if/elif/else` → `pl.when().then().otherwise()`
- `and` → `&`
- `or` → `|`
- `not` → `~`

### 局限

LLM (minimax-M3) 对此规则遵守度不高。即使 prompt 明确禁止，LLM 仍可能生成 `if` 代码。需要多层防御。

---

## 失败模式 3: 函数形式 vs 方法形式混淆

### 问题描述

QuantNodes 算子是函数（如 `rolling_std(pl.col('x'), window=20)`），但 LLM 有时用 Polars 方法形式（如 `pl.col('x').rolling_std(window=20)`）。

### 表现

- 参数错误（Polars 方法参数与 QuantNodes 不同）
- 或调用不存在的方法

### 修复方案

```python
# ❌ 错误：方法形式
pl.col('returns').rolling_std(window=20)

# ✅ 正确：函数形式
rolling_std(pl.col('returns'), window=20)
```

### 规则

**RULE 1: USE FUNCTION FORM**

QuantNodes 算子是 FUNCTIONS，不是 Expr 方法。

---

## 失败模式 4: 二值/常数因子导致 IC NaN

### 问题描述

当因子只有 0/-1 或全零时，Pearson IC 的方差为零，导致 NaN。

### 表现

- 因子值只有 2 个或 1 个 unique values
- IC 计算返回 NaN
- PipelineRunner 报 `ic_series_pts=0`

### 修复方案

```python
# 自动检测 + 加 noise
unique_vals = factor_series.drop_nulls().unique()
if len(unique_vals) <= 2:
    noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(factor_series)))
    factor_series = factor_series.cast(pl.Float64) + noise
```

### 验证

- Alpha-068: 修复前 NaN IC → 修复后 IC=+0.0091
- Alpha-086: 修复前 NaN IC → 修复后 IC=+0.0104

---

## 失败模式 5: 复杂公式超时

### 问题描述

多层嵌套 rolling/correlation 导致执行时间超过 timeout。

### 表现

- `TimeoutError: compute_factor() exceeded 120.0s timeout`
- LLM 生成的代码有无限循环或过慢计算

### 修复方案

1. 提升 timeout 到 120s
2. Prompt 中提示 materialization 优化
3. 对于极度复杂的公式，标记为"计算复杂度过高"

### 验证

- Alpha-057: `decay_linear(rank(ts_argmax(close, 30)), 2)` — 仍可能超时
- Alpha-100: 双重 `indneutralize` — 仍可能超时

---

## 修复优先级

| 优先级 | 失败模式 | 影响范围 | 修复难度 |
|--------|---------|---------|---------|
| P0 | Python if on Polars Expr | 4+ alpha | 中 |
| P1 | .over() 惰性求值 | 15+ alpha | 低 |
| P2 | 函数形式混淆 | 全部 alpha | 低 |
| P3 | 二值因子 NaN | 3 alpha | 低 |
| P4 | 复杂公式超时 | 2 alpha | 高 |
