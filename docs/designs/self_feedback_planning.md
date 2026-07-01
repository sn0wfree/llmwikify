# 自反馈规划机制设计文档

> 日期：2026-06-18
> 分支：feat/v0.4-paper-reproduction (归档命名)
> 问题：行业轮动/资产配置类论文被误分类为 factor schema，导致因子数量过多

---

## 1. 问题背景

### 1.1 当前问题

广发证券-量化行业轮动论文测试结果：
- **当前行为**：`factor` schema, 300 因子, 200 分钟
- **期望行为**：`allocation` schema, 10-50 因子, 10-30 分钟

### 1.2 根本原因

1. **Prompt 缺乏指导**：没有明确说明行业轮动/资产配置类论文应使用 `allocation` schema
2. **数量约束过死**：Prompt 中包含 "20+"、"1-20" 等明确数量限制
3. **无验证机制**：Planner 只调用一次，无法验证计划质量
4. **无反馈循环**：如果分类错误，无法自我纠正

---

## 2. 解决方案

### 2.1 核心思想

```
Section Detection → Planning (with LLM self-feedback) → Track A → Track B
                         ↓
                    Initial Plan
                         ↓
                    LLM Validate (one-shot)
                         ↓
                    ┌─────┴─────┐
                    ↓           ↓
                 Valid      Invalid
                    ↓           ↓
                 Proceed    LLM Re-plan (with feedback)
                              ↓
                         Max 2 retries
```

### 2.2 关键变化

| 项目 | 原方案 | 新方案 |
|------|--------|--------|
| Prompt | 包含数量约束 | 移除数量约束，基于内容特征 |
| 验证 | 无验证 | LLM 自行评判 |
| 反馈 | 无反馈 | LLM 提供反馈，重新规划 |
| 灵活性 | 固定规则 | LLM 自主决策 |

---

## 3. 实现细节

### 3.1 Prompt 修改

**移除数量约束**：
- 原：`"factor": paper defines 20+ individual factor formulas`
- 新：`"factor": paper defines multiple individual factor formulas with explicit mathematical definitions`

**添加灵活指导**：
```
n_signals_estimate: integer count of distinct signals/factors described
  - Estimate based on the paper's actual content
  - Focus on core, actionable factors that can be extracted
  - You may adjust up or down based on extraction feasibility
```

### 3.2 LLM 验证机制

**新增 `repro_validate_plan.yaml`**：
- 使用 LLM 评判计划质量
- 评估标准：schema 适当性、策略完整性、资源效率、可行性
- 输出：is_valid, issues, suggestions, revised_strategy

### 3.3 自反馈循环

**Orchestrator 实现**：
```python
for attempt in range(max_replan_attempts + 1):
    plan = _run_planner(...)
    is_valid, issues, revised_strategy = _validate_plan_with_llm(...)
    
    if is_valid:
        break
    else:
        replan_feedback = issues
        # 应用修订策略（如果有）
```

---

## 4. 文件变更

| 文件 | 变更内容 |
|------|---------|
| `repro_extract_plan.yaml` | 移除数量约束，添加灵活指导，添加 feedback 支持 |
| `repro_validate_plan.yaml` | **新增**：LLM 验证 prompt |
| `planner.py` | 添加 feedback 参数，新增 validate_plan_with_llm() |
| `orchestrator.py` | 实现 LLM 自反馈循环 |
| `test_success_rate.py` | 添加 plan validation 测试 |

---

## 5. 预期效果

| 论文类型 | 当前行为 | 优化后行为 |
|----------|---------|-----------|
| 101 Alphas | factor, 101 signals | factor, 101 signals (无变化) |
| 广发行业轮动 | factor, 300 signals | allocation, LLM 决定数量 |
| 资产配置策略 | factor, 100+ signals | allocation, LLM 决定数量 |

---

## 6. 测试计划

1. **单元测试**：验证 validate_plan_with_llm() 函数
2. **集成测试**：测试自反馈循环
3. **端到端测试**：测试广发论文提取

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 验证成本增加 | 每次规划增加 1 次 LLM 调用 | 限制最大重试次数（2次） |
| 验证 prompt 设计不当 | 误判计划质量 | 迭代优化 prompt |
| 自反馈循环过长 | 规划时间增加 | 限制最大重试次数 |

---

## 8. 参考

- 设计文档：`docs/designs/paper_extraction_pipeline.md`
- 测试报告：见提交记录
