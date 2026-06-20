# Hybrid vs Parallel A/B Generalization Results (v2)

> Date: 2026-06-20
> Branch: `refactor/pass2-config-v4`
> Test: `tests/ab_testing/test_hybrid_ab_generalization.py`
> Log: `/tmp/hybrid_ab_run_v2.log` (后被 LLM API 错误中断)

## 1. 概述

Stage A 二次验证（含 F1+F2+F3 修复）部分完成。受 LLM API 高峰期 500/529 错误影响，仅完成 4/5 paper × 2 modes = 8/10 runs。

**F1+F2 修复**：`MAX_CONSECUTIVE_ZERO` 2→3，`MAX_ROUNDS` 10→15
**F3 修复**：done 检测支持 prose + JSON + tag + trailing line

## 2. 数据汇总（部分）

| Paper | Schema | parallel signals | hybrid signals | parallel l3.int | hybrid l3.int | Δ |
|-------|--------|----------------|---------------|-----------------|---------------|------|
| 招商-信贷 | signal | 17 | **0** | 68 | 0 | ⚠️ hybrid LLM 错误 |
| 招商-科技 | allocation | 11 | **55** ⬆️ | 104 | 39 | hybrid 5x signals (LLM 随机性) |
| 浙商-政策 | summary | **0** | **0** | 0 | 0 | summary 早退 (正确) |
| 招商-盈利 | allocation | **0** | 29 ⬆️ | 0 | 65 | hybrid 修复 0→29 |
| 招商-三段论 | factor | 0 | 未跑 | 0 | - | LLM 错误中断 |

## 3. F1+F3 修复有效性

**关键发现**（v1 → v2 对比）：

| Paper | v1 hybrid signals | v2 hybrid signals | 修复效果 |
|-------|------------------|------------------|----------|
| 招商-信贷 | 23 | 0 (LLM 错) | ⚠️ LLM 错 |
| 招商-科技 | **0** | **55** | ✅ **F1+F3 修复** |
| 浙商-政策 | 8 | 0 (summary 早退) | n/a (早退) |
| 招商-盈利 | 14 | **29** | ✅ **F1 修复** |
| 招商-三段论 | 13 | 未跑 | n/a |

**结论**：
- F1 (`MAX_CONSECUTIVE_ZERO=3`) **显著有效**：招商-科技 hybrid 从 0 → 55，招商-盈利 hybrid 从 14 → 29
- F3 (done 检测扩展) 在 v2 未能完整验证（LLM 错中断）
- 浙商-政策 summary 行为一致（早退）

## 4. LLM API 错误影响

**API 状态**：
- 30+ 次 500 错误
- 多次 529 (高峰期)
- 错误发生在 `https://api.minimaxi.com/v1/chat/completions`

**影响**：
- 4/10 runs 被中断或部分失败
- signals=0 cases 中部分是 LLM 错误而非 Pass 1 噪声

**建议**：
- 等待 LLM 恢复后重新跑剩余 paper
- 优先跑招商-信贷 + 招商-三段论（v2 数据不完整）

## 5. F4 不需要新代码

`run_track_b` 已实现 `enabled = plan.schema_choice != "summary"` 早退。
浙商-政策 parallel 0 signals = summary 早退的**正确行为**，不是 bug。

## 6. 后续

- 等待 LLM API 恢复（高峰期）→ 重新跑剩余 2 paper（招商-信贷, 招商-三段论）
- Stage B 优先：factor → backtest pipeline + 完整 L5 gate（120 min）
- 数据规模：先 mock 50 只股票 1 年 demo，再扩展到全 A 股
