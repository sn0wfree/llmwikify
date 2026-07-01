# 研报复现功能 — 重整规划

> 版本: v0.5.0
> 日期: 2026-06-12
> 范围: `/agent/paper` `/agent/factor` `/agent/strategy` `/agent/reproduction` 四个子系统的端到端重整
> 状态: 调研已完成 (Stage 0 未启动)

---

## 1. 背景

经过多轮迭代，研报复现功能出现系统性混乱：

- 4 个子模块的 REST router 未在生产 `routes.py` 注册 → API 全部 404
- Paper extraction 永远返回空 (`paper.py` 未注入 `llm_client`)
- `wiki/strategy/` 与 `wiki/trading/` 双轨制并存，Reproduction 只读其中一边
- `wiki/factor/` 与 `wiki/factors/` 路径分裂，spec 与代码各执一词
- `n_stocks_per_date` 长度 ≠ 调仓次数、longshort 算 0、`group_metrics.n_stocks=0` 等"数字错位"
- IC/Group/LongShort 算法在 3 个地方重复实现
- 无 invariant test 验证模块间一致性

这些不是独立 bug，是 v0.1 → v0.4 累积的小决策没被整合。

---

## 2. 用户场景

一个量化研究员读到一篇 paper 后的端到端流程：

```
1. 输入 paper (PDF/URL/粘贴内容)
   ↓
2. 系统读懂 paper，识别核心因子 / 策略
   ↓
3. 自动把因子 / 策略定义写进 Wiki
   ↓
4. 在用户股票池上跑回测
   ↓
5. 看到 IC / 分组收益 / 多空曲线 / 净值
   ↓
6. 把回测结果保存为可分享的 Wiki 页面
   ↓
7. 对比多次回测，挑出最好参数
```

期望产物：Paper 理解页 → Factor 定义页 → Strategy 定义页 → BacktestResult 页 → Optimization 页，**全部沉淀在 Wiki**。

---

## 3. 现状断链盘点

| # | 断链 | 证据 |
|---|---|---|
| 1 | 4 个 reproduction router 未在 `routes.py` 注册 | `dataflow.md` §2 表格 |
| 2 | `paper.py` 未注入 LLM client | `dataflow.md` §3 / `paper.py` 调用现场 |
| 3 | `wiki/strategy/` 与 `wiki/trading/` 不一致 | `extract.py:111` |
| 4 | spec 写 `wiki/factor/` 但代码读 `wiki/factors/` | `extract_factors.py:164-185` vs spec §2.1 |
| 5 | `run_factor_backtest_universe` 没用 QuantNodes，自实现 IC 算法对稀疏因子有 bug | `factor_backtest.py` 1141 行 |
| 6 | `daily_net_simp` 全 NaN → longshort 全 1.0 | 上一轮已修，但同源问题在 `metrics.evaluation` 还有 |
| 7 | HS300 池子 23 只缺失 | 上一轮 `n_stocks_per_date=12` 暴露 |
| 8 | tradable 数据已从 iFinD 缓存，但 API 不透传 | `ifind_data.py` 完成；`factor.py` API 缺 query param |
| 9 | Strategy equity curve 缺失 | `dataflow.md` §5 |
| 10 | Reproduction 4-phase 实际只跑 2-phase | `run.py:84-100` analyze 阶段是 scaffold |
| 11 | 4 个 UI 面板后端不可达 | `routes.py` 缺 router 注册 |
| 12 | 无 invariant test | 测试只覆盖 happy path |

### 3.1 核心混乱的根因

**A. 双轨制**：旧 `wiki/trading/` + 新 `wiki/strategy/` 并存；spec 一处，代码另一处。Reproduction 读哪边取决于"哪边有内容"——隐性 race。

**B. 路径硬编码分散**：`wiki/factor/` `wiki/factors/` `wiki/strategy/` `wiki/trading/` `wiki/codegen/` `wiki/backtest/` `wiki/factor-backtest/` `wiki/optimization/` 在 5+ 个文件 hardcoded。

**C. 责任链不明**：
- 谁负责把 `frontmatter.signal_type` 转 `factor_class`？无人
- 谁负责 IC/Group/LongShort 算法？三处实现（自实现 + QuantNodes + 自实现 metrics）
- 谁负责校验 Page 类型？`schemas.py` dataclass 无 validator

**D. 配置与实现不同步**：spec 字段与 API 字段不一致（`factor_direction: -1/1` 在 spec 未列；UI universe 列表与 spec 枚举值大小写不一致 `hs300` vs `HS300` vs `CSI300`）。

**E. 反馈环缺失**：调仓 12 次、IC 有效 12 次、调仓日 24 个——数字对不上没人发现，因为无 invariant test。

---

## 4. 重整架构

### 4.1 顶层架构：单一闭环

```
用户输入 PDF/URL
      │
      ▼
┌─────────────┐    LLM    ┌──────────────────┐
│ Paper       │ ─────────► │ Wiki Page        │
│ Extraction  │            │ wiki/sources/    │
│ (real LLM)  │            │ wiki/factor/     │  ← 唯一权威源
└─────────────┘            │ wiki/strategy/   │
      │                    └──────────────────┘
      │                           │
      ▼                           │ 读取
┌─────────────┐                   ▼
│ Factor      │  ←──── wiki/factor/{slug}.md
│ Backtest    │  → write wiki/factor-backtest/{slug}.md
│ (截面)      │
└─────────────┘
      │
      ▼
┌─────────────┐  ←──── wiki/strategy/{slug}.md
│ Strategy    │  → write wiki/backtest/{sym}-{signal}.md
│ Backtest    │         + equity_curve + monthly_returns
│ (含 equity) │
└─────────────┘
      │
      ▼
┌─────────────┐
│ Comparison  │  ←──── 同一 slug 的多次 BacktestResult
│ / Optimize  │  → write wiki/optimization/{slug}.md
└─────────────┘
```

### 4.2 路径统一

**单一权威**（删除双轨制别名）：
- 因子定义：`wiki/factor/`
- 策略定义：`wiki/strategy/`
- 论文来源：`wiki/sources/`
- 策略回测：`wiki/backtest/`
- 因子回测：`wiki/factor-backtest/`
- 优化：`wiki/optimization/`
- 代码生成：`wiki/codegen/`

**集中常量**（新建 `reproduction/paths.py`）：

```python
WIKI_DIR_FACTOR = "factor"
WIKI_DIR_STRATEGY = "strategy"
WIKI_DIR_SOURCES = "sources"
WIKI_DIR_BACKTEST = "backtest"
WIKI_DIR_FACTOR_BACKTEST = "factor-backtest"
WIKI_DIR_OPTIMIZATION = "optimization"
WIKI_DIR_CODEGEN = "codegen"

def page_path(wiki, dir: str, slug: str) -> Path:
    return wiki.wiki_dir / dir / f"{slug}.md"
```

所有 module 只通过 paths module 写读 Wiki。**最关键一行修复**。

### 4.3 5 个独立子系统的明确边界

| 子系统 | 输入 | 输出 | 状态机 |
|---|---|---|---|
| **Paper** | paper_id + source_type + source_ref + content | wiki/sources/ + wiki/factor/ + wiki/strategy/ | pending → extracting → done / error |
| **Factor Backtest** | factor_slug + universe + start/end + adj_mode | wiki/factor-backtest/ | pending → running → done / error |
| **Strategy Backtest** | strategy_slug + symbol + start/end | wiki/backtest/ (含 equity) | pending → running → done / error |
| **Reproduction (5-phase)** | paper_id + symbol + dates | 串联 Paper → Factor → Strategy → Backtest | pending → extracting → data.fetching → backtesting → analyzing → done |
| **Optimization** | strategy_slug + parameter_grid | wiki/optimization/ | pending → grid_run → done |

每个子系统都是独立 `Router`，有 `start()` / `get()` / `list()` / `artifacts()` 4 个端点，**完全镜像**。

### 4.4 数据契约 (schema-first)

**新建 `reproduction/contracts.py`** (Pydantic 强制校验)：

```python
class FactorPage(BaseModel):
    title: str
    type: Literal["Factor"]
    factor_class: FactorClass  # enum
    factor_params: dict
    signal_type: SignalType
    signal_params: dict
    factor_source: str | None
    status: Literal["draft", "validated", "deprecated"]
    created: date
    updated: date

class StrategyPage(BaseModel):
    title: str
    type: Literal["Strategy"]
    strategy_class: StrategyClass
    signal_type: SignalType
    signal_params: dict
    factor_refs: list[str]
    rebalance_freq: Literal["daily", "weekly", "monthly", "quarterly"]
    status: Literal["draft", "backtested", "validated", "deprecated"]

class BacktestResultPage(BaseModel):
    title: str
    type: Literal["BacktestResult"]
    strategy_ref: str
    symbol: str
    start: date
    end: date
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_return: float
    final_cash: float
    total_trades: int
    equity_curve: list[EquityPoint]      # 之前缺失
    monthly_returns: dict[str, float]   # 之前硬编码 2024
    status: Literal["success", "error"]
    error: str | None = None

class FactorBacktestPage(BaseModel):
    title: str
    type: Literal["FactorBacktest"]
    factor_ref: str
    universe: str
    start: date
    end: date
    ic_mean: float
    icir: float
    win_rate: float
    annual_return: float
    max_drawdown: float
    total_rebalances: int               # 新增
    valid_rebalances: int               # 新增
    n_stocks_per_date: list[dict]       # [{date, n}, ...]
    group_metrics: dict
    status: Literal["success", "error"]
```

**所有后端 → Wiki 写入、前端 ← Wiki 读取** 都通过这些 Pydantic 模型。

### 4.5 Factor Backtest 内部清理

```
run_factor_backtest_universe()
    │
    ├─ DataRouter.get_universe()
    ├─ DataRouter.get_tradable()        ← 新加
    │
    ├─ if tradable:
    │   ├─ TradabilityFilterNode
    │   ├─ FactorPreprocessNode
    │   └─ _compute_cross_section_*    # 我们的纯函数 (IC/Group/LongShort)
    │
    └─ else:
        └─ _compute_cross_section_*
    
    ↓
    n_stocks_per_date  ←  adj_dates 全集统计 (不基于 IC 有效日)
    total_rebalances   ←  adj_dates 长度
    valid_rebalances   ←  IC 成功次数
    group_metrics      ←  每组 sharpe/MDD/win_rate/turnover/n_stocks
```

**关键不变量** (写测试强制)：
- `len(n_stocks_per_date) == total_rebalances`
- `len(ic_series) == valid_rebalances`
- `valid_rebalances <= total_rebalances`
- `sum(group_n_stocks) ≈ universe_size × valid_rebalances_ratio`

### 4.6 tradable 路径接通

```
DataRouter.get_universe() 
    │
    └─ DataRouter.get_tradable(universe, dates)   ← 新建
            │
            ├─ fetch_ipo_dates() from parquet
            ├─ fetch_st_history() from parquet
            ├─ fetch_suspend_history() from parquet
            └─ build_tradable_matrices()
                │
                └─ tradable dict  → run_factor_backtest_universe(tradable=...)
```

API 层加 query param `use_tradable: bool`，自动串联。

### 4.7 Reproduction 5-phase 真正跑通

```
Reproduction Start (paper_id, symbol, dates)
    │
    ├─ Phase 1: extracting
    │   ├─ extract_paper_structure(paper_content, llm_client)  ← 真的传 LLM
    │   └─ build_paper_pages() → wiki/sources/ wiki/factor/ wiki/strategy/
    │
    ├─ Phase 2: data fetching
    │   ├─ DataRouter.get_universe(symbols)
    │   └─ DataRouter.get_tradable()
    │
    ├─ Phase 3: backtesting (并行)
    │   ├─ run_factor_backtest_universe() → wiki/factor-backtest/
    │   └─ run_backtest(strategy_node) → BacktestResult with equity_curve
    │
    ├─ Phase 4: analyzing
    │   └─ 写 ReproductionReport (串联 Paper + Factor + Strategy + Backtest)
    │
    └─ Phase 5: finalize
        └─ emit events / update session status
```

### 4.8 Strategy Backtest equity curve 补齐

新建 `reproduction/equity.py`：

```python
def build_equity_curve(
    data: pd.DataFrame,         # OHLCV long format
    orders: OrdersResult,       # buy/sell signals
    initial_cash: float = 1_000_000,
) -> tuple[list[EquityPoint], dict]:
    """Walk forward through data, apply signals, compute daily mark-to-market."""
```

`MACrossStrategyNode` 等已有策略 → 实盘模拟的桥梁。**缺这个无法谈 strategy backtest 完整**。

### 4.9 前端 4 个面板与后端状态对齐

| 面板 | 现状 | 目标 |
|---|---|---|
| `PaperPanel` | LLM 没注入，提取永远为空 | 注入 LLM，显示论文结构 + 生成的 Factor/Strategy 链接，一键跑 Reproduction |
| `FactorPanel` | 调仓次数显示错误 | total_rebalances / valid_rebalances，group_metrics 表格 |
| `StrategyPanel` | equity curve 占位 | 真实 equity + drawdown + heatmap + 对比历史回测入口 |
| `ReproductionPanel` | 5 阶段跑 2 阶段 | 真正跑 5 阶段，可视化 Paper→Factor→Strategy→Backtest→Report 链路 |

---

## 5. 落地路线图

### Stage 0: Foundation (1-2 天) — 必须先做
- [x] `reproduction/paths.py` 路径常量集中
- [x] `reproduction/contracts.py` Pydantic schemas
- [x] `interfaces/server/http/routes.py` 注册 4 个 router
- [x] `paper.py` 注入 `llm_client`
- [x] 删除 `wiki/trading/` 兼容代码 (一次性) — extract_strategy.py: `for subdir in ("strategy", "trading")` 双轨 fallback 已删 (G+Y Stage 0)
- [x] `wiki/factors/` → `wiki/factor/` 迁移脚本 (`scripts/migrate_wiki_factors_to_factor.py`)
- [x] `BacktestResultPage` Pydantic 补 `equity_curve` + `monthly_returns` 字段
- [x] `tests/reproduction/test_invariants.py` P3 不变量守门 (20 测试)

### Stage 1: Paper 端到端 (2-3 天)
- [ ] `paper.py` 注入 LLM 后产出 paper-{id}-logic / factor-{id}-{slug} / strategy-{id}
- [ ] PaperPanel 显示提取结果 + 生成的 Factor/Strategy 链接
- [ ] 端到端测试：上传 PDF → 看到 wiki page

### Stage 2: Factor Backtest 端到端 (2-3 天)
- [ ] 修 `n_stocks_per_date` / `total_rebalances` / `valid_rebalances`
- [ ] 修 `group_metrics.n_stocks` 取值
- [ ] 改用 QuantNodes IC/Group/LongShort 纯函数 (替代自实现)
- [ ] DataRouter 集成 tradable
- [ ] FactorPanel UI 用真实数字
- [ ] 端到端测试：Momentum 因子 24 次调仓 (2 年月频)

### Stage 3: Strategy Backtest 端到端 (2 天)
- [ ] 实现 `equity.py`
- [ ] `run_backtest` 接入 equity curve
- [ ] StrategyPanel 显示真实 equity
- [ ] monthly_returns 用真实日期

### Stage 4: Reproduction 端到端 (2-3 天)
- [ ] `run.py` 真正 5 阶段
- [ ] analyze 阶段写 ReproductionReport
- [ ] ReproductionPanel 可视化 5 阶段 + 跳转产物

### Stage 5: Polish (1-2 天)
- [ ] invariant test: total_rebalances == len(n_stocks_per_date) 等
- [ ] 错误处理: trading calendar / 数据缺失 / LLM 失败
- [ ] 性能: tradable 缓存、index 缓存

---

## 6. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| LLM 注入后产物质量不稳定 | Paper 提取失败率高 | retry + schema validation + offline 兜底 |
| QuantNodes 替换自实现有边界 case | IC/Group 算法不匹配 | 保留自实现为 fallback，QuantNodes opt-in，invariant test 强制比较 |
| 路径统一破坏现有 wiki | 用户已存数据 | 一次性迁移脚本：trading → strategy，factors → factor |
| equity curve 实现有状态机错误 | 回测指标算错 | 用已知例子 (金叉死叉) 人工核对 |
| 全栈改动大，难一次验完 | 阶段卡住 | 每 stage 端到端测试 + 截图 |

---

## 7. 待定原则 (需要你拍板)

重整文档完成后，需要在 `docs/principles/` 写明几条开发原则作为后续决策依据。**这些是元规则，不是实现细节**。

候选清单 (待讨论定夺)：

| 编号 | 候选原则 | 性质 |
|---|---|---|
| P1 | 路径唯一权威：所有 Wiki 读写只走 `reproduction/paths.py` | 架构 |
| P2 | Schema 优先：所有 Wiki 页面必须能用 Pydantic 模型 round-trip 解析 | 契约 |
| P3 | 不变量强制：跨模块的数据关系 (rebalances vs n_stocks vs ic_series) 必须有 test 守门 | 反馈环 |
| P4 | 端到端提交：一个 PR 必须走完一个子系统的"用户点击 → 后端处理 → Wiki 写入 → UI 显示" | 工作流 |
| P5 | 算法单一实现：IC/Group/LongShort 只允许一处实现，QuantNodes 优先 | 责任 |
| P6 | 路径兼容窗口 = 0：要么立刻迁移、要么读时拒绝，不留隐性 race | 迁移 |
| P7 | 兜底可降级：LLM 失败时给 minimal offline 提取；QuantNodes 失败时回退自实现 | 鲁棒 |
| P8 | Wiki 即文档：所有产物落 Wiki 而非额外文件，可被 grep | 可见性 |
| P9 | spec 与代码同源：枚举值在 `contracts.py` 定义，spec 文档自动生成 | 防脱节 |
| P10 | 测试即 invariant：bug 暴露后第一件事是写 regression test | 反馈 |

---

## 7.1 实施决策定稿

经过讨论，4 个决策全部定稿：

| # | 决策 | 选择 | 强度 | 关联原则 |
|---|---|---|---|---|
| 1 | 路径统一 | **A. 一次性删 trading/factors 别名 + 写迁移脚本** | 🔒 | P1 / P6 |
| 2 | QuantNodes 替换 | **A. 全替换 run_factor_backtest_universe** | ⚠️ | P5 |
| 3 | LLM 兜底 | **A. 启动时强校验，没 LLM 就 503** | 🔒 | P7 |
| 4 | 提交节奏 | **A. 严格按 Stage 0→5 拆 5 个端到端 PR** | 🔒 | P4 |

### 决策 1（A）落地细节

- Stage 0 写一次性 idempotent 迁移脚本 `scripts/migrate_wiki_paths.py`：
  - `wiki/trading/*.md` → `wiki/strategy/{stem}.md`（保留 stem）
  - `wiki/factors/*.md` → `wiki/factor/{stem}.md`
  - 重复运行安全：检测目标存在则跳过
- 删 `extract.py:111` 的 `for subdir in ("strategy", "trading")` 双轨循环
- 删 `extract_factors.py` 的 `("factors", "factor")` 别名
- 写完跑 `git status wiki/` 确认无残留

### 决策 2（A）落地细节

- Stage 2 一次性全替换：
  - 删 `factor_backtest.py` 的 `_compute_cross_section_ic / _compute_cross_section_groups / _compute_long_short` 自实现
  - 删 `metrics.py` 的 `cal_net_simple / evaluation` 自实现
  - 改用 QuantNodes `ICAnalyzerNode / GroupAnalyzerNode / LongShortNode / performance_metrics.evaluation`
- 替换前先在测试里记录当前自实现输出（baseline），替换后断言 QuantNodes 输出在数值范围内
- 删除前用 git grep 确认无外部引用

### 决策 3（A）落地细节

- 在 `app = create_app()` 启动时调用 `llm_client.healthcheck()`：
  - 成功 → 启动继续
  - 失败 → logger.error + 启动 `PaperService.set_enabled(False)`
- Paper Router 在 `start_paper_extraction` 入口：
  - `if not service.enabled: raise HTTPException(503, "LLM unavailable")`
  - 测试用 `MONKEYPATCH llm_client` 不影响其它路由
- 非 Paper 路由不受影响（factor / strategy / reproduction 各自独立）

### 决策 4（A）落地细节

5 个 PR 的边界已经写在 §5 路线图。每个 PR 必须满足 P4 端到端提交的全部 5 项 checklist。

---

## 8. 不在本期范围

- 真实接入 QuantNodes PipelineRunner 全流程 (Step 2-3 from `factor-backtest-universe.md`)
- 行业中性化 (FactorNeutralizeNode)
- LLM 评测 (如何衡量 paper 提取质量)
- 跨语言 (i18n)
- 性能优化 (除明显瓶颈外)

---

## 9. 参考文档

- `docs/plan/reproduction-spec.md` — 命名、frontmatter schema、枚举值定义
- `docs/plan/reproduction-dataflow.md` — API 现状、已知 P0/P1/P2 问题
- `docs/plan/factor-backtest-universe.md` — QuantNodes 迁移路径
- `docs/plan/reproduction-frontend-plan.md` — UI 面板规划
- `docs/principles/reproduction-principles.md` — 开发原则 v1.1（P1-P10 + 5 附录）
- `src/llmwikify/reproduction/` — 所有后端模块

---

## 10. 文档变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.5.1 | 2026-06-12 | 定稿 4 个实施决策（路径统一 A / QN 替换 A / LLM 兜底 A / 提交节奏 A）；新建 §7.1 落地细节 |
| v0.5.0 | 2026-06-12 | 初版重整规划，建立 5 Stage 路线图 |
