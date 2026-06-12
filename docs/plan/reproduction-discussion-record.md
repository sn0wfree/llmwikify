# 研报复现功能 — 项目逻辑流 + 数据流讨论记录

> 版本: v1.0
> 日期: 2026-06-12
> 状态: 已定稿，待实施
> 关联: `docs/plan/reproduction-realignment.md` v0.5.1, `docs/principles/reproduction-principles.md` v1.1

---

## A. 讨论背景

本次讨论基于 v0.5.1 重整规划，重新审视项目整体逻辑流和数据流，解决以下问题：

1. 项目的"用户主路径"是什么？
2. "数据流"到底是哪一种？
3. "5 个独立子系统"是真需求还是过度抽象？
4. 数据流里"Wiki 是数据库"还是"Wiki 是文档"？

---

## B. 拍板决策

| 维度 | 决策 | 理由 |
|---|---|---|
| **产品路径** | D（Paper-Repro + Backtest 工作台 + Wiki-Quant），分阶段 | 三条路径都做，按成熟度排序 |
| **数据源** | Wiki-as-Doc（DB 是真值，Wiki 是镜像） | DB 存指标，Wiki 退化为文档镜像 |
| **子系统** | 5 个都做，分阶段 | 先 Backtest → Wiki-Quant → Paper-Repro |
| **数据流** | ii（DB + Wiki mirror） | 算法 → DB（真值）+ 同步写 Wiki md（镜像） |
| **Stage 排期** | 先 Backtest → Wiki-Quant → Paper-Repro | 基于成熟度排序 |
| **Wiki 目录** | 4 个顶层目录（factor/strategy/sources/reproduction） | 简化结构 |
| **DB** | SQLite（session + result 同文件） | 简单部署 |
| **Wiki 写入时机** | 同步（算法写完立即渲染 md） | 保留 P8 Wiki 即文档原则 |
| **配置系统** | 所有参数可配置，不 hardcode | 配置文件 + 环境变量 + 默认值 |

---

## C. 项目逻辑流 — 4 层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: UI                                                │
│  - FactorPanel (group_metrics / n_rebalances / equity)      │
│  - StrategyPanel (equity_curve / monthly_returns)           │
│  - PaperPanel (paper extraction + links)                    │
│  - ReproductionPanel (5-phase + artifacts)                  │
│  - WikiExplorer (浏览定义页 + 跳转结果)                      │
└─────────────────────────────────────────────────────────────┘
                          ↕ HTTP/JSON
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: API (FastAPI routes)                              │
│  - /api/factor/list → extract_factors.py → Wiki glob        │
│  - /api/factor/{slug}/backtest → factor_backtest.py         │
│  - /api/factor/{slug}/results → results DB read             │
│  - /api/strategy/list → extract.py → Wiki glob              │
│  - /api/strategy/{slug}/backtest → backtest.py              │
│  - /api/paper/extract → llm_client.extract()                │
│  - /api/reproduction/start → run.py (5-phase)               │
│  - /api/reproduction/{session_id} → session DB read         │
│  - /api/wiki/page/{path} → Wiki md read                     │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: 服务层 (reproduction/*.py)                         │
│  - factor_backtest.py: IC/Group/LongShort 算法               │
│  - equity.py: walk forward 模拟 equity curve                 │
│  - metrics.py: sharpe/MDD/win_rate 计算                      │
│  - ifind_data.py: tradable 矩阵构建                          │
│  - quantnodes_adapter.py: QuantNodes 对接                    │
│  - run.py: Reproduction 5-phase 编排                         │
│  - extract.py / extract_factors.py: Wiki 读取                │
│  - extract_paper.py: LLM 提取                               │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: 存储层                                             │
│  - session DB (执行状态 + 状态机)                            │
│  - result DB (计算结果: ic/equity/group)                     │
│  - Wiki md (文档镜像 + 检索)                                 │
│  - iFinD parquet cache (全市场数据)                          │
│  - ClickHouse (OHLCV)                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## D. 数据流详解（以 Factor Backtest 为例）

### 写路径（触发回测）

```
1. UI POST /api/factor/momentum/backtest
     {universe: "HS300", start_date: "2023-01-01", end_date: "2024-12-31", adj_mode: "M-end"}

2. factor.py 路由
     → 读 Wiki 定义页: wiki/factor/momentum.md (确认 factor 存在)

3. factor_backtest.py run_factor_backtest_universe()
     → ifind_data.py: 读 parquet 构建 tradable 矩阵
     → clickhouse: 拉 OHLCV 数据
     → quantnodes_adapter: 计算 IC/Group/LongShort
     → 返回 FactorBacktestResult dataclass

4. 写 results 表 (run_id, factor_ref, ic_mean, sharpe, ic_series, group_metrics, ...)

5. 渲染 Wiki md: wiki/factor/momentum/results/{run_id}.md
     内容: 简略结果 (ic_mean, sharpe, max_drawdown) + 引用 JSON

6. 返回 JSON {run_id, ic_mean, sharpe, ...} → UI 渲染
```

### 读路径（查看结果）

```
1. UI GET /api/factor/momentum/results
     → 读 results 表 WHERE factor_ref = 'momentum' ORDER BY created_at DESC
     → 返回 [{run_id, ic_mean, sharpe, created_at}, ...]

2. UI GET /api/factor/momentum/results/{run_id}
     → 读 results 表 WHERE run_id = '{run_id}'
     → 返回 {run_id, ic_mean, ic_series, group_metrics, ...}

3. UI GET /api/wiki/page/factor/momentum/results/{run_id}.md
     → 读 Wiki md 文件
     → 返回 markdown 内容 (文档视图)
```

---

## E. Wiki 目录结构

```
wiki/
├── factor/
│   ├── momentum.md                    # 定义页 (LLM提取 或 人写)
│   ├── value.md                       # 定义页
│   └── momentum/
│       ├── results/
│       │   ├── 20240101-20241231.md   # 结果镜像 (简略结果)
│       │   └── 20230101-20231231.md   # 历史结果
│       └── index.md                   # 结果索引 (可选)
├── strategy/
│   ├── ma_cross.md                    # 定义页
│   └── ma_cross/
│       └── backtests/
│           └── 20240101-20241231.md   # 结果镜像
├── sources/
│   └── momentum-paper-2024.md         # 论文来源页
├── reproduction/
│   └── momentum-repro-2024.md         # 复现报告页
└── index.md
```

---

## F. DB Schema（SQLite）

### sessions 表（执行状态）

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    paper_id TEXT,
    stage TEXT CHECK(stage IN ('pending','extracting','data.fetching','backtesting','analyzing','done','error')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    artifacts JSONB,  -- {factor: {ref, run_id}, backtest: {ref, run_id}, ...}
    error TEXT
);
```

### results 表（计算结果）

```sql
CREATE TABLE results (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    type TEXT CHECK(type IN ('factor_backtest','strategy_backtest','reproduction')),
    factor_ref TEXT,
    strategy_ref TEXT,
    universe TEXT,
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT CHECK(status IN ('success','error')),
    error TEXT,
    
    -- factor_backtest 特有字段
    ic_mean FLOAT,
    rank_ic_mean FLOAT,
    icir FLOAT,
    rank_icir FLOAT,
    win_rate FLOAT,
    annual_return FLOAT,
    longshort_ann_return FLOAT,
    longshort_sharpe FLOAT,
    longshort_max_dd FLOAT,
    n_stocks_per_date JSONB,
    ic_series JSONB,
    group_metrics JSONB,
    
    -- strategy_backtest 特有字段
    equity_curve JSONB,
    monthly_returns JSONB,
    total_return FLOAT,
    final_cash FLOAT,
    total_trades INT,
    
    -- 通用字段
    wiki_path TEXT,
    adj_mode TEXT,
    hedge TEXT,
    data_source TEXT,
    
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
```

---

## G. 配置系统设计

### 配置文件结构

```json
{
  "reproduction": {
    "db": {
      "path": "~/.llmwikify/agent/reproduction.db"
    },
    "ifind": {
      "config_path": "~/.llmwikify/ifind_http.yaml",
      "date_sequence_url": "https://quantapi.51ifind.com/api/v1/date_sequence",
      "mcp_dir": "~/Public/ifind-finance-data-1.1.0"
    },
    "clickhouse": {
      "host": "0.0.0.0",
      "port": 8123,
      "user": "default",
      "password": "",
      "database": "quote",
      "table": "cn_stock"
    },
    "backtest": {
      "initial_cash": 1000000,
      "commission": 0.001,
      "default_benchmark": "000300.SH",
      "trading_days": 252,
      "risk_free_rate": 0.03
    },
    "synth": {
      "n_days": 60,
      "base_price": 10.0
    },
    "akshare": {
      "timeout_s": 5.0
    },
    "universe": {
      "aliases": {
        "HS300": "000300",
        "CSI300": "000300",
        "沪深300": "000300"
      },
      "hedge_aliases": {
        "HS300": "000300.SH",
        "ZZ500": "000905.SH",
        "SZ50": "000016.SH"
      }
    },
    "wiki": {
      "factor_dir": "factor",
      "strategy_dir": "strategy",
      "sources_dir": "sources",
      "reproduction_dir": "reproduction"
    }
  }
}
```

### 环境变量覆盖

```bash
# 敏感值用环境变量
CLICKHOUSE_PASSWORD=xxx
IFIND_ACCESS_TOKEN=xxx
```

### 配置加载优先级

```
1. 环境变量 (最高优先级)
2. 配置文件 (~/.llmwikify/llmwikify.json)
3. 代码默认值 (最低优先级)
```

---

## H. Stage 0-5 任务表（基于复用）

### 复用率评估

| 模块 | 现有能力 | 复用率 |
|---|---|---|
| **ReproductionDatabase** | SQLite 连接池 + CRUD | **70%** |
| **schemas.py** | 完整字段定义 | **50%** |
| **extract_factors.py** | 双目录处理 | **60%** |
| **factor_backtest.py** | 完整算法实现 | **85%** |
| **factor.py / strategy.py** | 完整路由 | **70%** |
| **UI 组件** | FactorPanel / StrategyPanel | **60%** |
| **数据源** | ifind_data / clickhouse | **100%** |

### Stage 0: Foundation (2-3 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 0.0 | 新建 `reproduction/config.py` | `src/llmwikify/reproduction/config.py` |
| 0.1 | 扩展 `sessions.py` 加 `results` 表 | `src/llmwikify/reproduction/sessions.py` |
| 0.2 | 新建 `reproduction/paths.py` | `src/llmwikify/reproduction/paths.py` |
| 0.3 | 新建 `reproduction/contracts.py` | `src/llmwikify/reproduction/contracts.py` |
| 0.4 | 改造 `schemas.py` 转 Pydantic | `src/llmwikify/reproduction/schemas.py` |
| 0.5 | 新建迁移脚本 | `scripts/migrate_wiki_paths.py` |
| 0.6 | 改造所有 hardcode 模块 | 各 module |

### Stage 1: Factor Backtest (2-3 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 1.1 | 修 `factor_backtest.py` | `src/llmwikify/reproduction/factor_backtest.py` |
| 1.2 | 改 `factor.py` 路由 | `src/llmwikify/interfaces/server/http/factor.py` |
| 1.3 | UI FactorPanel v3 | `ui/webui/src/components/factor/FactorPanel.tsx` |

### Stage 2: Strategy Backtest (2 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 2.1 | 新建 `reproduction/equity.py` | `src/llmwikify/reproduction/equity.py` |
| 2.2 | 改 `strategy.py` 路由 | `src/llmwikify/interfaces/server/http/strategy.py` |
| 2.3 | UI StrategyPanel | `ui/webui/src/components/strategy/StrategyPanel.tsx` |

### Stage 3: Wiki-Quant 知识库 (1-2 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 3.1 | 改 `extract_factors.py` | `src/llmwikify/reproduction/extract_factors.py` |
| 3.2 | 改 `extract.py` | `src/llmwikify/reproduction/extract.py` |
| 3.3 | UI WikiExplorer | `ui/webui/src/components/wiki/WikiExplorer.tsx` |

### Stage 4: Paper-Reproduction (3-4 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 4.1 | 修 `paper.py` | `src/llmwikify/interfaces/server/http/paper.py` |
| 4.2 | 修 `run.py` | `src/llmwikify/reproduction/run.py` |
| 4.3 | UI ReproductionPanel | `ui/webui/src/components/reproduction/ReproductionPanel.tsx` |

### Stage 5: Polish (2-3 天)

| # | 任务 | 产出文件 |
|---|---|---|
| 5.1 | 新建 `tests/reproduction/test_invariants.py` | `tests/reproduction/test_invariants.py` |
| 5.2 | 错误处理 | 各 module |
| 5.3 | 性能优化 | `ifind_data.py`, `factor_backtest.py` |

---

## I. 实际断链清单

| # | 断链 | 影响 Stage | 优先级 |
|---|---|---|---|
| 1 | `wiki/factor/` 目录不存在（实际是 `wiki/factors/`） | Stage 0 | P0 |
| 2 | `wiki/factorbacktest/` 目录存在但命名不对 | Stage 0 | P0 |
| 3 | `schemas.py` 是 dataclass 不是 Pydantic | Stage 0 | P0 |
| 4 | `sessions.py` 缺 result 字段 | Stage 0 | P0 |
| 5 | `factor_backtest.py` 自实现 + QuantNodes 双路径 | Stage 1 | P1 |
| 6 | `n_stocks_per_date=12`（已修？需验证） | Stage 1 | P1 |
| 7 | `group_metrics.n_stocks=0` | Stage 1 | P1 |
| 8 | `wiki/strategy/` 目录不存在 | Stage 0 | P0 |
| 9 | `wiki/sources/` 目录不存在 | Stage 4 | P2 |
| 10 | `wiki/reproduction/` 目录不存在 | Stage 4 | P2 |
| 11 | `extract_paper.py` 未注入 LLM | Stage 4 | P2 |
| 12 | Reproduction 5-phase 实际只跑 2-phase | Stage 4 | P2 |
| 13 | `wiki/factorbacktest/factor-momentum.md` 是旧契约 | Stage 1 | P1 |
| 14 | P7 vs 决策 3A 矛盾 | Stage 4 | P2 |
| 15 | 所有参数 hardcode | Stage 0 | P0 |

---

## J. 文档变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-06-12 | 项目逻辑流+数据流讨论记录，拍板 D+Wiki-as-Doc+ii+SQLite+同步写入 |

---
