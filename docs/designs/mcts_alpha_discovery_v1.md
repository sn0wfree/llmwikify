# MCTS Alpha Discovery — v1.0 重大功能规划

> **下一个重大功能**（论文研报策略复现完成后）：
> 用 Monte Carlo Tree Search + LLM 自动发现新 alpha 因子，
> 突破 101 alphas 的人工天花板。
>
> 前置：Loop v4 LLM 编译框架（commit `225b650` / `fdd68e9`）。

## 1. 背景与动机

### 1.1 现状

v0.4 paper reproduction 框架已具备：

| 能力 | 状态 |
|------|------|
| 论文公式 → factor YAML (L1-L4) | ✅ 完成 |
| LLM 编译 factor YAML → polars.Expr | ✅ Loop v4 (97/97 mock) |
| PipelineRunner 12 阶段回测 | ✅ 集成 |
| L5 5 维质量门 | ✅ IC + Sharpe + 换手率 + 回撤 |
| 真实 HS300 数据 | ✅ ClickHouse 集成 |

**天花板**：当前只能"复现"已发表的 101 alphas，无法"发现"新 alpha。

### 1.2 为什么需要 MCTS

| 传统方法 | 局限 |
|---------|------|
| **人工构造 alpha** | 101 alphas 是 WorldQuant 平台 10 年积累；单研究员一辈子写 100 个 |
| **遗传算法 (GA)** | 探索盲目、易早熟、缺乏方向性 |
| **随机搜索 (Random)** | 因子空间巨大 (157^N 组合)，纯随机效率低 |
| **LLM 直接生成** | 输出随机、不可解释、缺乏质量反馈 |

**MCTS 的优势**：
- **方向性探索** (UCB1) — 平衡 exploitation (高 IC) + exploration (低 visits)
- **可解释路径** — 每个新因子都有 parent + edit history
- **质量闭环** — backtest IC 作为 reward，自我进化
- **LLM 高效利用** — 仅在 Expansion 阶段调用，100 iter × 3 = 300 LLM calls

### 1.3 业界共识（4 个核心证据）

| 论文 / 系统 | 关键贡献 | 与本设计对应 |
|------------|---------|--------------|
| **MCTS Alpha** (Shi 2025, arxiv:2505.11122) | LLM + MCTS + backtest reward 三者结合 | 4 阶段循环 |
| **AlphaAgent** (KDD 2025, arxiv:2502.16789) | 3-agent + AST-similarity 防止 alpha 拥挤 | family diversity constraint |
| **CogAlpha** (2025, arxiv:2511.18850) | LLM-as-mutator + financial feedback | LLM only in Expansion |
| **Hubble** (2026, arxiv:2604.09601) | family-aware selection | 7 family templates as seeds |
| **EFS** (2025, arxiv:2507.17211) | LLM evolutionary search | 对比 baseline |
| **QuantEvolver** (2026, arxiv:2605.15412) | Diversity-Complementarity Reward | 多目标 reward |

**negative result**:
- **Alpha Illusion** (2026, arxiv:2605.16895) — 报告 ≠ 部署，需 **HAC-significant IC** + **out-of-sample 验证**

## 2. 核心架构：4 阶段 MCTS 循环

### 2.1 总览

```
                ┌─────────────────────────────┐
                │  7 Family Templates (Seed)  │
                │  momentum / reversal / ...  │
                └──────────┬──────────────────┘
                           ↓
            ┌── MCTS ROOT (per family) ──┐
            │                            │
            │  visit_count, total_reward │
            │  children: [child_1..N]    │
            └────────────┬───────────────┘
                         ↓
                  ┌──────────────┐
                  │  Selection   │ ← UCB1 选最 promising child
                  └──────┬───────┘
                         ↓
                  ┌──────────────┐
                  │  Expansion   │ ← LLM 提议 K=3 variants
                  └──────┬───────┘
                         ↓
                  ┌──────────────┐
                  │ Simulation   │ ← compile + backtest → IC reward
                  └──────┬───────┘
                         ↓
                  ┌──────────────┐
                  │  Backprop    │ ← 更新 ancestors' visit + reward
                  └──────┬───────┘
                         ↓
                  Loop until budget=100
                         ↓
                ┌────────────────────────┐
                │ Top-K output (K=20)    │
                │ 写 YAML + report       │
                └────────────────────────┘
```

### 2.2 关键 invariant

| 不变量 | 保证 |
|--------|------|
| **Deterministic Eval** | Simulation 阶段不调 LLM（仅 compile + backtest） |
| **LLM only in Expansion** | 单次 iter 3 LLM calls（K=3） |
| **Reward ∈ [-1, 1]** | abs(IC) ∈ [0, 1]，便于 UCB1 |
| **Tree depth ≤ 7** | 多数 alpha 不超过 7 ops（实证 99th percentile） |
| **Diversity ≥ 0.3** | AST edit distance 跨代增加，避免重复 |

## 3. 状态空间：AST as Node

### 3.1 节点定义

```python
class MCTSNode:
    ast: ASTNode                          # 完整 AST
    family: str                           # momentum / reversal / ...
    parent_idx: int | None                # 父节点索引
    children_idxs: list[int]              # 子节点索引
    visits: int = 0                       # 被访问次数
    total_reward: float = 0.0             # 累计 IC
    depth: int = 0                        # 距 root 深度
    is_leaf: bool = True                  # 是否可 expand
    # 统计
    best_variant_ic: float = 0.0          # 历史最高 IC
    best_variant_idx: int | None          # 最佳子节点
```

### 3.2 7 个 Family 种子模板

| Family | AST | 预期 IC 范围 | 探索方向 |
|--------|-----|-------------|---------|
| **Momentum** | `rank(pct_change(close, 20))` | [0.01, 0.05] | window / 加 reversal / 加 volume |
| **Mean-reversion** | `-rank(close - rolling_mean(close, 20))` | [0.01, 0.04] | window / 加 abs / 加 vwap |
| **Volume** | `rank(rolling_corr(close, volume, 10))` | [0.01, 0.06] | 换列 (open, high, low) / window |
| **Volatility** | `-rank(rolling_std(returns, 20))` | [0.01, 0.03] | 加 abs / 加 zscore |
| **Cross-corr** | `rank(rolling_corr(open, volume, 10))` | [0.01, 0.05] | 换列对 / window |
| **TS-rank** | `ts_rank(close, 20)` | [0.01, 0.04] | 加 rank / 换 col |
| **Conditional** | `pl.when(returns > 0, rolling_mean(returns, 5), 0)` | [0.02, 0.07] | 换 cond / 换 val |

**Family 检测**（init 阶段）：
- 看 L1.formula 含 `Δ|delta|diff → momentum`
- 看 `-rank(x) → reversal`
- 看 `volume → volume family`
- 看 `std|volatility → volatility family`
- 看 `Corr|correlation → cross_corr family`
- 看 `Ts_Rank|ts_rank → ts_rank family`
- 看 `if|when|pl.when → conditional family`

## 4. 动作空间：5 类 AST Edit Operations

### 4.1 操作清单

| Op | 输入 | 输出 | 实现 |
|----|------|------|------|
| `swap_op(node_path, new_op)` | AST + path + new op | 新 AST | Det |
| `add_layer(node_path, layer_op)` | AST + path + layer (e.g. `neg`, `abs`, `rank`) | 新 AST | Det |
| `change_param(node_path, kwarg, value)` | AST + path + kwarg + value | 新 AST | Det |
| `del_node(node_path)` | AST + path | 新 AST (less 1 node) | Det |
| `combine(node_path_1, node_path_2, bin_op)` | AST + 2 paths + bin op (add/sub/mul/div) | 新 AST | LLM / Det |

**node_path** = 节点在 AST 中的位置（自上而下编号）。

### 4.2 LLM vs Det 操作分配

| Op | LLM? | 原因 |
|----|------|------|
| `swap_op` | ✅ LLM | 需要语义选择（`rolling_mean` vs `rolling_std` vs `ewm_mean`） |
| `add_layer` | ❌ Det | 仅 5-6 种 layer，可枚举 |
| `change_param` | ❌ Det | 数值扰动（20 → 10 / 30 / 60） |
| `del_node` | ❌ Det | 删任一节点（除 root） |
| `combine` | ✅ LLM | 跨 sub-tree 组合，需语义 |

**LLM 调用模板**（Expansion 阶段）：

```
SYSTEM: 你是 alpha 因子编辑器。当前 AST:
{current_ast_json}

任务: 提出 3 个 mutation，应用以下操作之一：
- swap_op: 替换某 op (e.g. rolling_mean → rolling_std)
- combine: 合并两个 sub-expression
- change_param: 改 window/periods (e.g. 20 → 10)

约束:
- 输出 3 个独立 JSON AST (```json fence)
- 每个 AST 必须有 3-30 个节点
- 使用 157 QuantNodes operators (rolling_*, ts_*, rank, etc.)
- 不要重复 parent AST 的 ops
```

### 4.3 编辑预算

| Iter | 节点 visits | Edit ops 倾向 |
|------|------------|---------------|
| 1-30 (warmup) | 各 family root | Det ops (change_param) |
| 31-70 (exploit) | 高 IC 区域 | LLM swap_op + combine |
| 71-100 (explore) | 低 visits 区域 | LLM 跨 family 跳跃 |

## 5. 奖励函数：Multi-Objective

### 5.1 公式

```python
reward = w_ic * |IC| - w_decay * decay_penalty + w_sharpe * sharpe_bonus

default_w = {"w_ic": 0.6, "w_decay": 0.2, "w_sharpe": 0.2}
```

| Component | 来源 | 范围 |
|-----------|------|------|
| `|IC|` | backtest IC mean | [0, 1] |
| `decay_penalty` | IC(t) autocorr (abs) | [0, 1], 越小越好 |
| `sharpe_bonus` | long-short Sharpe / 2 | [0, 1] |

### 5.2 为什么用 |IC|

- **方向不固定** — alpha-007 负 IC 也有效
- **UCB1 需要非负 reward** — `|IC| ∈ [0, 1]` 满足
- **业界标准** — Hubble, MCTS Alpha 都用 abs

### 5.3 备选（v1.1）

```python
# Pareto front 多目标 (可选)
reward_pareto = (ic_rank + sharpe_rank + decay_inv_rank) / 3
```

## 6. 多样性保护

### 6.1 必要性

**Alpha 拥挤** (alpha crowding) — 业界 1 号难题：

> "LLM-generated factors converge to the same crowded volume/momentum motifs"
> — AlphaAgent KDD 2025

### 6.2 三层多样性

| 层 | 机制 | 阈值 |
|----|------|------|
| **AST 距离** | Levenshtein on serialized AST | edit_distance >= 3 |
| **Operator set Jaccard** | `|A ∩ B| / |A ∪ B|` | <= 0.7 |
| **Family diversity** | 跨 family UCB bonus | 1.5x weight for cross-family |

### 6.3 实施

```python
def is_diverse(parent_ast, child_ast) -> bool:
    """Reject children too similar to parent (anti-crowding)."""
    if edit_distance(serialize(parent_ast), serialize(child_ast)) < 3:
        return False
    if jaccard(ops(parent_ast), ops(child_ast)) > 0.7:
        return False
    return True
```

## 7. 集成：复用 Loop v4 + PipelineRunner

### 7.1 模块依赖

```
mcts/
  family_templates.py   (7 templates)
  node.py               (Node + UCB1)
  actions.py            (5 edit ops)
  reward.py             (multi-objective)
  search.py             (4 阶段循环)
  cli.py                (CLI entry)
  
依赖 (复用):
  llmwikify.reproduction.ast_nodes         (Pydantic AST)
  llmwikify.reproduction.ast_compiler      (AST → polars)
  llmwikify.reproduction.ast_extractor     (LLM output → AST)
  llmwikify.reproduction.factor_compiler   (LLM emit AST w/ Loop v4)
  llmwikify.reproduction.quantnodes_repro  (PipelineRunner)
  llmwikify.reproduction.clickhouse_data   (H5 cache)
```

### 7.2 不重复造轮子

| MCTS 需要 | 复用 |
|-----------|------|
| LLM emit AST | `FactorCompiler.compile()` (Loop v4) |
| AST → polars | `compile_ast()` |
| Backtest | `run_factor_backtest()` |
| Data | `ClickHouse + H5 cache` |
| Eval (IC/Sharpe) | `PipelineRunner + L5 gate` |

**MCTS 是纯 orchestrator**，不重新实现编译和回测。

## 8. 数据流：端到端

```
            ┌────────────────────────────┐
            │ ClickHouse quote.cn_stock  │
            │  →  ~/.llmwikify/akshare_cache/quantnodes_h5/stk_daily.h5
            └────────────┬───────────────┘
                         ↓
         ┌──────── Family Templates ────────┐
         │ 7 AST seeds (momentum, reversal) │
         └────────────┬─────────────────────┘
                      ↓
       ┌──── MCTS Search (100 iter) ────┐
       │  per iter:                      │
       │    Selection (UCB1)             │
       │    Expansion (LLM K=3)          │
       │    Simulation (compile+backtest)│
       │    Backprop                     │
       └────────────┬────────────────────┘
                    ↓
        ┌──── L5 Gate (5 维) ────┐
        │ IC + Sharpe + winrate  │
        │ + drawdown + turnover  │
        └────────────┬───────────┘
                     ↓
        ┌── Top-K output (K=20) ──┐
        │  quant/papers/mcts_alpha/{family}/alpha_{idx}.yaml
        └─────────────────────────┘
                     ↓
        ┌── Report ──┐
        │ docs/summaries/mcts_v1_results.md
        └─────────────┘
```

## 9. 输出格式

### 9.1 YAML 格式（与现有 101 alphas 一致）

```yaml
factor:
  name: mcts-momentum-001
  family: momentum
  generation: mcts_v1           # 区别于 paper_derived
  parent: rank(pct_change(close, 20))    # parent AST
  edits:
    - op: swap_op
      from: rolling_mean
      to: rolling_std
    - op: change_param
      path: 0.args.0.kwargs.window
      from: 20
      to: 10
  metrics:
    ic_mean: 0.045
    ic_std: 0.012
    icir: 3.75
    sharpe: 0.78
    winrate: 0.54
    drawdown: 0.12
    turnover: 0.45
    decay: 0.03
  reward: 0.048
  visits: 5
  depth: 2
  mcts_iter: 23                # 何时被 expand
  l1:
    definition: MCTS-discovered momentum variant with rolling_std
    formula: \\text{mcts-momentum-001} = rank(rolling_std(pct_change(close, 10), 5))
    input_columns: [close]
    default_params:
      window: 5
  l2:
    calculation_steps:
      - step: 1
        description: 10-day price percentage change
        formula: \\Delta(close, 10) = close_t / close_{t-10} - 1
      - step: 2
        description: 5-day rolling std
        formula: \\sigma_5(\\Delta(close, 10))
      - step: 3
        description: cross-sectional rank
        formula: rank(\\sigma_5(...))
  l3:
    financial_intuition: High volatility momentum — strong moves persist
  l4:
    hypotheses:
      - id: H1
        name: volatility-persistence
        expected_ic_sign: positive
        source: 10-day vol cluster in equity returns
```

### 9.2 Report 格式

```markdown
# MCTS Alpha Discovery v1.0 — Results

## Summary
- Total iterations: 100
- Total LLM calls: 297
- Total backtests: 100
- Wall time: 73 minutes
- Top-K saved: 20
- Best IC: 0.067 (mcts-momentum-007)

## Family Performance
| Family    | Avg IC | Best IC | Top-K count |
|-----------|--------|---------|-------------|
| momentum  | 0.038  | 0.067   | 4           |
| reversal  | 0.029  | 0.052   | 3           |
| volume    | 0.041  | 0.071   | 5           |
| ...       |        |         |             |

## Diversity Stats
- Avg AST edit distance: 4.2
- Avg operator Jaccard: 0.58
- Cross-family count: 7/20

## Out-of-Sample Validation
- Train: 2020-01-01 ~ 2022-12-31
- Val:   2023-01-01 ~ 2024-12-31
- HAC-IC p-value < 0.05: 14/20 (70%)

## Key Discoveries
1. mcts-momentum-007 (IC=0.067, vol-weighted momentum)
2. mcts-volume-003 (IC=0.071, open-volume cross-corr)
...
```

## 10. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|-------|------|
| **LLM API 限流** | 高 | retry 3 + K=2 fallback |
| **100 iter 不够探索** | 中 | max_visits=10 强制广度 |
| **IC overfit (in-sample)** | **高** | train/val split 强制 + HAC-IC 检验 |
| **Diversity 不足** | 中 | AST distance + Jaccard 双重约束 |
| **Compute 超时** | 中 | budget 50 iter fallback |
| **Backtest noise** | 中 | 多 seed 求 reward 均值 |
| **LLM 输出格式错** | 低 | Loop v4 已有 Stage 2.5 complexity check |

### 10.1 Out-of-Sample 验证（关键）

```python
# Train period: 2020-01-01 ~ 2022-12-31 (2.5 years)
# Val period:   2023-01-01 ~ 2024-12-31 (1.5 years)

# In MCTS:
train_data = setup_cache("HS300", "2020-01-01", "2022-12-31")
reward = backtest(factor, train_data) → IC

# Post-MCTS validation:
val_data = setup_cache("HS300", "2023-01-01", "2024-12-31")
oos_ic = backtest(factor, val_data)
oos_hac_p = newey_west_p(oos_ic)  # HAC-significant

# Accept if HAC p-value < 0.05
```

## 11. 实施阶段（4 phases / 6 weeks）

### Phase 1: Foundation (Week 1, ~3 hr)

| # | 内容 | 文件 | 时间 |
|---|------|------|------|
| 1.1 | Family templates | `mcts/family_templates.py` | 30 min |
| 1.2 | Node + UCB1 | `mcts/node.py` | 45 min |
| 1.3 | Actions (Det only) | `mcts/actions.py` | 60 min |
| 1.4 | Unit tests | `tests/reproduction/test_mcts.py` | 45 min |

**Deliverable**: 跑 30 iter 纯 Det (no LLM)，验证 UCB1 收敛。

### Phase 2: LLM Integration (Week 2, ~4 hr)

| # | 内容 | 时间 |
|---|------|------|
| 2.1 | LLM in Expansion (K=3) | 60 min |
| 2.2 | Structured error from Loop v4 | 30 min |
| 2.3 | Reward calculator (IC) | 45 min |
| 2.4 | 4-stage loop | 90 min |
| 2.5 | CLI entry | 30 min |
| 2.6 | Integration test | 45 min |

**Deliverable**: 跑 50 iter with LLM, top-10 输出。

### Phase 3: Diversity + Validation (Week 3-4, ~5 hr)

| # | 内容 | 时间 |
|---|------|------|
| 3.1 | AST edit distance | 30 min |
| 3.2 | Jaccard op diversity | 30 min |
| 3.3 | Train/val split | 45 min |
| 3.4 | HAC-IC 检验 | 60 min |
| 3.5 | 100 iter full benchmark | 90 min |
| 3.6 | Report generator | 45 min |

**Deliverable**: 100 iter 全量 + top-20 + report。

### Phase 4: Polish (Week 5-6, ~3 hr)

| # | 内容 | 时间 |
|---|------|------|
| 4.1 | HTML report | 60 min |
| 4.2 | Visualization (tree plot) | 60 min |
| 4.3 | 文档 (mcts_alpha_design.md) | 30 min |
| 4.4 | Tests + lint | 30 min |

**Deliverable**: 完整 production-ready MCTS alpha discovery。

### 总计

| 维度 | 数值 |
|------|------|
| 总时间 | ~15 hr (~6 weeks part-time) |
| 新增代码 | ~1500 lines |
| 新增模块 | 6 (mcts/*) |
| LLM 调用 | 300 (100 iter × K=3) |
| Wall time | 60-90 min / 100 iter |
| Top-K 输出 | 20 |
| Acceptance | OOS HAC-IC p < 0.05 |

## 12. 验收标准（KPIs）

### 12.1 必须达成

- [ ] MCTS 跑 100 iter 完成, wall time < 90 min
- [ ] 输出 top-20 新因子存为 YAML
- [ ] Out-of-sample HAC-IC p < 0.05: 至少 10/20
- [ ] Diversity: AST edit distance >= 3
- [ ] pytest pass, ruff clean
- [ ] Report 生成 (markdown)

### 12.2 期望达成

- [ ] Best OOS IC > 0.05 (5%)
- [ ] 跨 family 因子 >= 7/20
- [ ] HTML 报告 + tree 可视化

### 12.3 长期目标 (v1.1+)

- [ ] 1000+ iter 跑 batch
- [ ] Multi-objective Pareto
- [ ] Online learning (incremental)
- [ ] Cross-market (CSI500, S&P500)

## 13. 未来扩展 (v1.1+)

### 13.1 v1.1: Multi-Objective Pareto
```python
# 同时优化 IC + Sharpe + turnover
reward = (ic_rank + sharpe_rank + turnover_inv_rank) / 3
# 输出 Pareto front 而非单点
```

### 13.2 v1.2: AST-level RL Fine-tuning
```python
# 借鉴 QuantEvolver (arxiv:2605.15412)
# 把 MCTS reward 转为 policy gradient
# LoRA fine-tune LLM for 更快 expansion
```

### 13.3 v1.3: Online Learning
```python
# 增量模式: 每月新增 1 批新因子
# 用最近 N 月数据 re-evaluate 旧因子
# 自动淘汰 IC decay 大的
```

### 13.4 v1.4: 跨市场
```python
# 用同一套 AST seeds 探索 CSI500 / S&P500 / HS300
# 跨市场 alpha portability 研究
```

## 14. 关键参考

1. **MCTS Alpha** (Shi 2025) - arxiv:2505.11122
2. **AlphaAgent** (KDD 2025) - arxiv:2502.16789
3. **CogAlpha** (2025) - arxiv:2511.18850
4. **Hubble** (2026) - arxiv:2604.09601
5. **EFS** (2025) - arxiv:2507.17211
6. **QuantEvolver** (2026) - arxiv:2605.15412
7. **Alpha Illusion** (2026) - arxiv:2605.16895
8. **Loop v4 design** - docs/designs/llm_compile_loop_v4.md
9. **Pass2Config v4** - docs/designs/pass2_config_v4.md

## 15. 决策记录

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-20 | 7 family templates as seed | 业界共识 + 覆盖度足够 |
| 2026-06-20 | UCB1 默认 C=sqrt(2) | MCTS 经典参数 |
| 2026-06-20 | K=3 expansion | cost/quality 平衡 |
| 2026-06-20 | 100 iter budget | 用户指定"低预算" |
| 2026-06-20 | IC 主 reward | 用户指定 + 业界标准 |
| 2026-06-20 | Train/val split 强制 | 防 overfit (Alpha Illusion) |
| 2026-06-20 | 复用 Loop v4 (不重写) | AGENTS.md 简洁优先 |
| 2026-06-20 | Mock 不动 | 用户指定"仅 MCTS" |

---

**Status**: 设计 v1.0 (planning)  
**Next**: Phase 1 Foundation (3 hr)  
**Owner**: 下一阶段开发  
**Blocked by**: 无 (Loop v4 已完成)
