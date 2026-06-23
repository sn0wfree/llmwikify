# Prompt 设计原则

## 核心原则

### 原则 1: 负面约束比正面指导更有效

LLM 对 "DO NOT" 的遵守度高于 "USE"。

```
❌ 正面指导: "Use pl.when().then().otherwise() for conditional logic"
✅ 负面约束: "DO NOT use if pl.col(...) — use pl.when().then().otherwise()"
```

**原因**: LLM 在生成代码时，会优先考虑"看起来正确"的模式（如 `if`）。负面约束直接禁止常见错误模式，比正面指导更有效。

### 原则 2: 规则数量与遵守度成反比

| 规则数量 | 遵守度 | 说明 |
|---------|--------|------|
| 1-3 条 | 高 | LLM 能记住并遵守 |
| 4-5 条 | 中 | LLM 可能忽略某条 |
| 6+ 条 | 低 | LLM 容易混淆 |

**建议**: 核心规则控制在 3-5 条，用 "DO NOT" 开头。

### 原则 3: 示例比规则更有效

LLM 对代码示例的理解优于文字描述。

```
❌ 文字描述: "Use pl.when() for conditional logic"
✅ 代码示例:
WRONG:
if rank(pl.col('a')) < rank(pl.col('b')):
    factor = -1
RIGHT:
factor = pl.when(rank(pl.col('a')) < rank(pl.col('b'))).then(-1).otherwise(0)
```

### 原则 4: 开头放最重要的规则

LLM 对 prompt 开头的内容记忆最深。最重要的规则放在最前面。

```
## DO NOT (会导致执行失败)
1. DO NOT use if...  ← 最重要
2. DO NOT use and/or/not...
3. DO NOT call df.sort(...)
4. DO NOT use method form...
```

---

## Prompt 结构模板

```python
SYSTEM_PROMPT = """You are a [角色描述].

## DO NOT (会导致执行失败)
1. DO NOT [最常见的错误模式]
2. DO NOT [第二常见的错误模式]
3. DO NOT [第三常见的错误模式]

## DATA
[数据格式描述]

## N RULES (ALL CRITICAL)
### RULE 1: [规则名]
[规则描述 + 示例]

### RULE 2: [规则名]
[规则描述 + 示例]

### RULE 3: [规则名]
[规则描述 + WRONG/RIGHT 对比]

## OPERATORS
[可用算子列表]

## OUTPUT FORMAT
```python
[代码示例]
```
[输出格式要求]
"""
```

---

## WRONG/RIGHT 示例库

### 示例 1: 条件逻辑

```python
# ❌ WRONG: Python if on polars Expr
if rank(pl.col('a')).over('date') < rank(pl.col('b')).over('date'):
    factor = -1
else:
    factor = 0

# ✅ RIGHT: pl.when().then().otherwise()
factor = pl.when(
    rank(pl.col('a')).over('date') < rank(pl.col('b')).over('date')
).then(-1).otherwise(0)
```

### 示例 2: 布尔运算

```python
# ❌ WRONG: Python and/or/not
condition = (rank(a) > 0.5) and (rank(b) < 0.5)
not_condition = not (rank(a) > 0.5)

# ✅ RIGHT: Polars &/|/~
condition = (rank(a) > 0.5) & (rank(b) < 0.5)
not_condition = ~(rank(a) > 0.5)
```

### 示例 3: 函数形式

```python
# ❌ WRONG: Method form
pl.col('returns').rolling_std(window=20)
pl.col('close').rank().over('date')

# ✅ RIGHT: Function form
rolling_std(pl.col('returns'), window=20)
rank(pl.col('close')).over('date')
```

### 示例 4: Materialization

```python
# ❌ WRONG: Inline expression in select
factor = rank(correlation(a, b, window=200)).over('date')

# ✅ RIGHT: Materialize first
df = df.with_columns(correlation(a, b, window=200).alias('_corr'))
factor = rank(pl.col('_corr')).over('date')
```

### 示例 5: 行业中性化

```python
# ❌ WRONG: indneutralize (不存在)
factor = indneutralize(pl.col('x'), group=pl.col('industry'))

# ✅ RIGHT: neutralize with group
factor = neutralize(pl.col('x'), group=pl.col('industry')).over('date')
```

---

## Prompt 优化检查清单

- [ ] 开头有 "DO NOT" 列表（3-5 条）
- [ ] 核心规则不超过 5 条
- [ ] 每条规则有 WRONG/RIGHT 示例
- [ ] 代码示例覆盖常见错误模式
- [ ] 算子列表精简（只列最常用的）
- [ ] 输出格式明确（返回类型 + 代码块）
