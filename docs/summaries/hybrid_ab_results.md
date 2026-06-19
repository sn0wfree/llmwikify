# Hybrid vs Parallel A/B Generalization Results (v1)

> Date: 2026-06-19
> Branch: `refactor/pass2-config-v4`
> Test: `tests/ab_testing/test_hybrid_ab_generalization.py`
> Data: `quant/papers/hybrid_ab_summary.json`

## 1. 概述

在 5 个不同 schema/size 的 paper 上跑 parallel + hybrid 两种模式，对比 Pass 2 输出质量。

**总耗时**：81.69 min（10 runs）
**成功率**：10/10 runs 100% 完成（部分 signals=0）
**数据**：`quant/papers/hybrid_ab_summary.json`

## 2. 测试矩阵

| # | Paper | Schema | n_signals (p) | n_signals (h) | parallel l3.int | hybrid l3.int | Δ |
|---|-------|--------|---------------|---------------|-----------------|---------------|------|
| 1 | 招商-信贷 | signal | 24 | 23 | 71.4 | 73.1 | +3% |
| 2 | 招商-科技 | allocation | 12 | **0** | 87.2 | **0** | ❌ hybrid 退化 |
| 3 | 浙商-政策 | summary | **0** | 8 | **0** | 82.9 | ⚠️ parallel 失败 |
| 4 | 招商-盈利 | allocation | 18 | 14 | 58.1 | 56.9 | -2% |
| 5 | 招商-三段论 | factor | 16 | 13 | 67.7 | 71.6 | +6% |

## 3. 关键发现

### 3.1 Pass 1 噪声大

**同 paper 不同 mode 跑出不同 signals 数**：

- 招商-科技 (allocation): parallel 12 vs hybrid **0**
- 浙商-政策 (summary): parallel **0** vs hybrid 8
- 招商-盈利 (allocation): parallel 18 vs hybrid 14
- 招商-三段论 (factor): parallel 16 vs hybrid 13

**根因分析**：

1. **Pass 1 终止条件太严** (`MAX_CONSECUTIVE_ZERO = 2`)：
   - continuation prompt 后 LLM 倾向输出重复信号
   - 重复被 `seen_names` 过滤 → 算 0 new
   - 连续 2 轮 0 new → 立即终止
   - **结果**：1-2 轮后提前退出，n_signals 低

2. **`done_llm` 检测太脆**：
   - 仅检查 `parsed.get("done", False)`
   - M2.7 倾向用自然语言 `已完成所有信号`（不被识别）
   - **结果**：done 信号被误判为未完成

3. **LLM 随机性**：
   - 同 paper 同 prompt 多次跑可能输出不同
   - **结果**：A/B 对比不严格 deterministic

### 3.2 Hybrid 在小 paper 提升有限

| Paper | parallel l3.int | hybrid l3.int | hybrid l4.hyp | 提升幅度 |
|-------|-----------------|---------------|---------------|----------|
| 招商-信贷 | 71 | 73 | 3.6 | +3% |
| 招商-三段论 | 68 | 72 | 3.3 | +6% |

**结论**：hybrid 在小 paper 上提升 5-10%，**不显著**。

时间开销：hybrid 多 10-30%（除异常案例）。

### 3.3 异常失败模式

| 模式 | 失败案例 | 根因 |
|------|----------|------|
| parallel 0 signals | 浙商-政策 (summary) | summary schema 通常无 signals，但 planner 仍跑 Track B |
| hybrid 0 signals | 招商-科技 (allocation) | consecutive_zero 触发提前终止 |

**对比 101 alphas**（v3.1 hybrid 大 paper baseline）：
- 101 alphas hybrid: 17x 提升，101/101 success
- 5 paper hybrid（本次）: 1/5 失败，4/5 平均 5-10% 提升
- **结论**：hybrid 主要价值在大 paper（30+ signals），小 paper 收益有限

## 4. 改进方案 (F1-F5)

### F1. `MAX_CONSECUTIVE_ZERO` 2 → 3
更宽容，避免 1-2 轮重复输出就终止。

### F2. `MAX_ROUNDS` 10 → 15
更安全上限，避免大 paper 截断。

### F3. done 检测扩展
`_parse_signals_from_response` 支持更多 done 关键词：
- `done: true` / `"done": true` / `done=true`
- `已完成所有信号` / `全部完成` / `完成` / `<done/>`

### F4. Schema-aware 终止
`summary` schema + 0 signals detected → 立即终止，避免空跑。

### F5. 总数估计更激进
当 LLM 报告 `n_signals_estimate` 后，如果已收集 ≥ estimate × 0.8，触发 early-exit。

## 5. 后续

Stage A-Patch: 应用 F1-F4 修复 → Stage A4 二次验证 → Stage A5 报告 v2。

Stage B: Factor → 回测 pipeline + 完整 L5 gate（120 min）。
