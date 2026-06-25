# Vibe Coding Self-Heal: 删除后处理修补，纯 ReAct 自愈

**Date:** 2026-06-25
**Context:** 101 alpha 重跑发现 12 个 alpha 因 `DangerousCodeError` 失败

---

## 问题

12 个 alpha 新失败（alpha 58,59,69,70,76,80,82,87,89,90,91,97）**100%** 同一错误：

```
DangerousCodeError: Execution error: the truth value of an Expr is ambiguous
```

追踪发现代码中有**两个后处理修补回路**互相冲突，不仅没解决问题，反而干扰了 LLM 自愈。

---

## 分析：两个冲突的回流

### 回路 A（人工修补，要删除）

```
LLM 生成代码 → _sanitize_code (and→&, or→|, not→~ 替换)
             → validate_safety (15 个 if_patterns 正则匹配)
             → 执行
```

**问题：**
1. `_sanitize_code` — 正则替换 `\band\b` 会误伤 Python 内置 `and`；docstring 声称修复 `if expr:` 但实际没实现
2. `validate_safety` — 15 个正则模式永远不全（漏了 IndNeutralize, decay_linear, Ts_Rank 等），新增一个 QuantNodes 操作符就要加一行
3. 回路 A 修改了 LLM 的原始输出，导致回路 B 看到的代码与错误信息不一致

### 回路 B（LLM 自愈，要保留）

```
执行错误 → OBSERVE(原始 polars 错误信息 + 修复建议)
         → REASON(LLM 收到反馈后自行重写)
```

Polars 本身的错误信息已经给出了明确的修复建议：
```
Instead of `pl.col('a') and pl.col('b')`, use `pl.col('a') & pl.col('b')`
```

### 冲突点

回路 A 把 `and` 替换成 `&` 后，执行报错时 OBSERVE 告诉 LLM "不要用 `and`" — 但代码里 `and` 已经被替换成 `&` 了，LLM 看到的代码和错误信息矛盾，**LLM 更困惑**。

---

## 解决方案：删除回路 A，纯靠回路 B

采用 vibe coding agent 的主流做法（Cursor / Claude Code / Aider / Cline 均如此）：

**原则：不修补 LLM 输出，信任 prompt + 错误反馈**

### 具体变更

| 变更 | 文件 | 原因 |
|------|------|------|
| 删除 `_sanitize_code` | `react_engine.py` | 正则修补脆弱，干扰 LLM 自愈 |
| 删除 `if_patterns` 正则列表 | `llm_code.py:validate_safety` | 永远不完备，伪安全 |
| 强化 SYSTEM_PROMPT RULE 3 | `llm_code.py` | 提升到最前 + 多操作符示例 |
| `max_repair_rounds 3→5` | `test_one_factor_llm_code.py` | 给 LLM 更多自愈机会 |

### 删除后的 ReAct 流程

```
LLM 生成代码 → extract_python → validate_syntax → CodeSandbox.validate()
           → 执行
               ├─ 成功 → 返回结果
               └─ 失败 → OBSERVE(polars 原始错误) → REASON(LLM 重写)
                     ↑ 循环 max_repair_rounds 次
```

### 预期效果

1. 代码量 **-55 行**（删 55，加 15）
2. 不再需要维护操作符白名单
3. LLM 看到原始 polars 错误信息，学习更高效
4. 通用：不依赖操作符名称，polars 的任何新操作符也不会漏
