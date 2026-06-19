# v0.4 调优与回测验证 — 实施设计

> Status: design (pre-implementation)
> Date: 2026-06-19
> Branch: `refactor/pass2-config-v4`
> Owner: Track B (paper reproduction pipeline)

## 1. 动机

v0.4 paper reproduction pipeline 已基本完成（v3.0 smart mode + v3.1 hybrid mode + v3.2 supplement prompt + CLI + 101 alphas / 广发 / 招商-信贷验证）。但存在以下**已识别**但**未解决**的问题：

### 1.1 已知 v0.4 调优点

| # | 调优点 | 影响 | 现状 |
|---|--------|------|------|
| A | **Hybrid generalization 验证不完整** | hybrid 模式在小 paper 上行为未充分验证 | 5 paper 跑了 2 个，3 个 timeout 截断 |
| B | **L5 validation 未与 v0.4 集成** | factor 质量门缺失，无法决策是否入库 | l5_orchestrator.py 存在但只读 `quant/factors/` 不读 `quant/papers/{id}/factors/` |
| C | **factor → 回测 pipeline 缺失** | 抽取的 factor 不能自动跑回测 | factor_backtest.py 存在但需手动 cp YAML |

### 1.2 后续目标

用户最终目标：**v0.4 抽取 → L5 quality gate → 全 A 股回测 → 决策入库**的完整闭环。

### 1.3 Pass2Config v4.0 重构的处置

为聚焦 v0.4 调优与回测验证，**推迟** Pass2Config 彻底重构（25 常量替换 + 4 测试）：

- 已 commit 的 Step 0 (Bug 1 修复) + Step 1 (config.py) **保留**
- Step 2+ 彻底重构 **推迟到 v0.5+**，避免当前混乱的双重真相源

## 2. 实施阶段

### 阶段 A：Hybrid Generalization A/B 测试（30 min）

**目标**：在 5 个不同 paper 上跑 parallel vs hybrid 对比，验证 hybrid 通用性

**前置**：
- ✅ Step 0 已修 Bug 1（`PASS2_MODE_OVERRIDE=hybrid` 现在真正生效）
- ✅ 已有 `tests/ab_testing/test_hybrid_generalization.py`（仅跑 hybrid，未做 A/B）

**Step A1**：重写 `tests/ab_testing/test_hybrid_ab_generalization.py`
- 每个 paper 跑两次：`PASS2_MODE_OVERRIDE=parallel` 和 `PASS2_MODE_OVERRIDE=hybrid`
- 输出到 `<id>_parallel/` 和 `<id>_hybrid/` 两个目录
- 计算 stats：l3.intuition / l3.theoretical / l4.hypotheses
- 收集 hybrid 的 supplement_targets 数量 + supplement 后提升幅度

**Step A2**：跑 5 paper 串行（~5 min/paper × 5 = ~25 min）

PDFs：
1. `/home/ll/Public/strategy/raw/20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论.pdf`（signal）
2. `/home/ll/Public/strategy/raw/20180816-招商证券-A股投资启示录（一）：布局科技三年上行周期.pdf`（allocation）
3. `/home/ll/Public/strategy/raw/20181125-浙商证券-A股行业比较周报：政策框架的梳理和当前市场的分析.pdf`（summary）
4. `/home/ll/Public/strategy/raw/20180823-招商证券-A股投资启示录（二）：盈利韧性，剩者为王与赢家通吃.pdf`（allocation）
5. `/home/ll/Public/strategy/raw/20180913-招商证券-A股投资启示录（三）：A股投资三段论，兼论市场底部信号与市场风格.pdf`（factor）

**Step A3**：写 `docs/summaries/hybrid_ab_results.md` 报告
- 表格：paper / schema / n_signals / parallel stats / hybrid stats / delta
- 结论：hybrid 在什么 paper 上有效，什么场景退化

**输出**：
- `quant/papers/hybrid_ab_summary.json`（统计汇总）
- `docs/summaries/hybrid_ab_results.md`（人类可读报告）

### 阶段 B：Factor → 回测 Pipeline + 完整 L5 Gate（120 min）

**目标**：v0.4 抽取的 draft YAML 自动跑回测，输出 IC / quantiles / long-short 报告

**前置**：
- ✅ `factor_backtest.py:1207` 完整 backtest engine（IC / quantiles / long-short / turnover）
- ✅ `ifind_data.py:685` 完整数据接入（tradability / IPO / ST / suspend）
- ✅ `l5_orchestrator.py:511` L5 验证入口
- ✅ `l5_validation.py:753` hypothesis 检验

**Step B1**：新建 `src/llmwikify/reproduction/paper_backtest.py`
- 入口：`paper_to_backtest(paper_id, work_dir, ...) -> BacktestResult`
- 流程：读 YAML → L5 gate → 表达式编译 → 跑回测 → 输出报告
- 输入：`quant/papers/{id}/factors/alpha-XXX.yaml`
- 输出：`quant/papers/{id}/backtest_results.json` + `backtest_report.html`

**Step B2**：表达式编译器（核心难点，~60 min）
- L1.formula 是自然语言（"年度5G新建基站数 = 5G宏站新建数 + 5G小站新建数"）
- L2.calculation_steps 已有 step-by-step
- 方案：LLM 辅助编译 + safety check + 沙箱执行
- 失败因子记入 deferred queue（`quant/papers/{id}/deferred_compile.json`）

**Step B3**：完整 L5 quality gate（~30 min）
- **IC** > 0.02（核心，统计显著性）
- **Sharpe** > 0.5（年化）
- **多空胜率** > 50%
- **最大回撤** < 20%
- **换手率** < 80%（避免过度交易）
- 决策：pass / needs_revision / reject

**Step B4**：全 A 股通用回测（~30 min）
- Universe：中证全指（CSI All Share）
- 时间窗口：2015-01-01 ~ 2024-12-31
- IC decay：1d / 5d / 10d / 20d
- Quantile returns：5 分组 + 多空对冲
- 报告输出：`quant/papers/{id}/backtest_report.html`

**Step B5**：CLI `llmwikify backtest <paper_id>` 串联
- v0.4 抽取 → L5 gate → 回测 → 报告
- 入口：`src/llmwikify/interfaces/cli/commands/backtest_cmd.py`

**Step B6**：HTML 报告（~5 min）
- 多因子对比 + 回测曲线（nav / drawdown）
- 复用 v0.4 的 HTML 浏览器（self-contained）

### 阶段 C：L5 Validation 独立集成（60 min）

**目标**：让 L5 验证可独立于回测使用（决策报告 + 因子质量评分库）

**Step C1**：扩展 `l5_orchestrator.py`
- 新增 `run_l5_for_paper(paper_id, factor_name=None)`
- 输入：`quant/papers/{id}/factors/alpha-XXX.yaml`
- 输出：score + decision

**Step C2**：CLI `llmwikify validate <paper_id>`
- 对 paper 所有 draft factors 跑 L5
- 输出 `quant/papers/{id}/l5_report.md`

**Step C3**：L5 决策数据库
- 建表 `l5_decisions(factor_name, score, status, date, ...)`
- 累积决策日志 `quant/l5_decisions.jsonl`

## 3. 工作依赖

```
A (parallel vs hybrid A/B)   ← 独立
B (Factor → 回测 pipeline + L5 gate) ← 独立（已含 L5）
C (L5 独立集成 + 决策库)         ← 独立
```

**三阶段可独立并行**。本计划按用户偏好顺序 A → B → C 执行。

## 4. 关键技术风险

| 风险 | 缓解 |
|------|------|
| **B2 表达式编译器**：自然语言 → Python 代码易出错 | LLM 辅助 + 沙箱执行 + 失败进 deferred queue |
| **B3 L5 阈值**：多维度阈值需调优 | 跑已知 factor（如 `momentum_20d`）做 baseline |
| **B4 全 A 股回测耗时**：10 年 × 5000 股 × 100 factors = 巨大 | 中证全指 / 沪深 300 抽样，先 5 signals 跑通 |
| **C3 数据表设计**：L5 decisions 与 factor YAML 关联 | 复用现有 `quant/papers/{id}/l5_report.md` 文件 + 索引文件 |

## 5. 工作量汇总

| 阶段 | 时间 | 关键产出 |
|------|------|----------|
| A | 30 min | hybrid_ab_summary.json + report |
| B | 120 min | backtest pipeline + L5 gate + CLI |
| C | 60 min | L5 standalone + 决策库 |
| **总计** | **~3.5 hours** | v0.4 完整闭环 + 回测验证 |

## 6. Commit 链

1. `docs(reproduction): v0.4 调优 + 回测验证设计` (本文件)
2. `test(ab_testing): hybrid A/B generalization` (Stage A)
3. `docs(summaries): hybrid A/B results` (Stage A 报告)
4. `feat(reproduction): paper → backtest pipeline` (Stage B-1)
5. `feat(reproduction): LLM formula compiler` (Stage B-2)
6. `feat(reproduction): full L5 quality gate` (Stage B-3)
7. `feat(reproduction): 全 A 股通用回测` (Stage B-4)
8. `feat(cli): llmwikify backtest 命令` (Stage B-5)
9. `feat(reproduction): HTML backtest report` (Stage B-6)
10. `feat(l5): run_l5_for_paper API` (Stage C-1)
11. `feat(cli): llmwikify validate 命令` (Stage C-2)
12. `feat(l5): 决策数据库` (Stage C-3)

## 7. 验证策略

1. **Stage A 验证**：hybrid_ab_summary.json 5 paper 数据完整，对比 101 alphas baseline (17x 提升)
2. **Stage B 验证**：
   - 跑 `llmwikify backtest 20180816-招商-...`，验证 5 signals 中至少 3 个过 L5 gate
   - 报告 HTML 可在浏览器打开
3. **Stage C 验证**：
   - 跑 `llmwikify validate 20180816-...`，输出 l5_report.md
   - 累积决策日志可查询

## 8. Pass2Config v4.0 重构的回归

- 当前 Step 0 (Bug 1 修复) + Step 1 (config.py) **保留**为后续 v0.5 重构的起点
- v0.4 调优完成后，**v0.5 阶段**可重新评估是否继续彻底重构
- 若不重构：保留 cfg.py 作为可选用基础设施（CLI/orchestrator 不强制使用）