# Paper Reproduction 数据流与操作流

> 范围：`/agent/paper`、`/agent/factor`、`/agent/strategy`、`/agent/reproduction`
> 版本：v0.4.0
> 日期：2026-06-10

---

## 1. 总览

Paper Reproduction 当前由两条产品线组成：

1. **三页面架构**
   - `/agent/paper`：论文理解，生成 Wiki 页面
   - `/agent/factor`：读取 Factor 页面并做单因子检验
   - `/agent/strategy`：读取 Strategy 页面并做策略回测

2. **旧 5 阶段流水线**
   - `/agent/reproduction`：一次性执行 extract → data → backtest → wiki → done
   - 使用独立 session DB：`~/.llmwikify/reproduction.db`

整体数据流：

```text
Paper PDF / URL / pasted content
        |
        v
/api/paper/start
        |
        v
extract_paper.py + repro_extract.yaml
        |
        v
Wiki pages: Source / Factor / Strategy
        |
        +--> /agent/factor   -> /api/factor/{slug}/backtest   -> IC / quantile / turnover
        |
        +--> /agent/strategy -> /api/strategy/{slug}/backtest -> metrics / drawdown / heatmap
        |
        +--> /agent/reproduction -> 5-phase pipeline -> BacktestResult / Optimization pages
```

---

## 2. API 与页面映射

| 页面 | API | 用途 | 当前状态 |
|---|---|---|---|
| `/agent/paper` | `POST /api/paper/start` | 论文提取并写 Wiki | LLM 未注入 |
| `/agent/paper` | `GET /api/paper/{id}/artifacts` | 查看论文产物 | 可用 |
| `/agent/factor` | `GET /api/factor/list` | 列出因子页 | 可用 |
| `/agent/factor` | `POST /api/factor/{slug}/backtest` | 单因子回测 | 可用 |
| `/agent/strategy` | `GET /api/strategy/list` | 列出策略页 | 可用 |
| `/agent/strategy` | `POST /api/strategy/{slug}/backtest` | 策略回测 | Equity curve 缺失 |
| `/agent/reproduction` | `POST /api/reproduction/start` | 5 阶段流水线 | Strategy 路径断链 |
| `/agent/reproduction` | `GET /api/reproduction/{sid}` | 获取 session 状态 | 可用 |
| `/agent/reproduction` | `GET /api/reproduction/{sid}/artifacts` | 获取产物 | 可用 |

重要：当前 `src/llmwikify/interfaces/server/http/routes.py` 尚未注册 `paper.py`、`factor.py`、`strategy.py`、`reproduction.py` 这四组 router，生产环境中相关接口会 404。

---

## 3. Paper 页数据流

入口：`ui/webui/src/components/paper/PaperPanel.tsx`

```text
用户输入 paper_id / source_type / source_ref / paper_content
        |
        v
POST /api/paper/start
        |
        v
paper.py:start_paper_extraction
        |
        v
extract_paper_structure(...)
        |
        v
build_paper_pages(...)
        |
        v
wiki.write_page(...)
```

理论产物：

| 页面类型 | Wiki 页面 |
|---|---|
| `Source` | `wiki/sources/paper-{id}-logic.md` |
| `Source` | `wiki/sources/paper-{id}-data.md` |
| `Source` | `wiki/sources/paper-{id}-risks.md` |
| `Factor` | `wiki/factor/factor-{id}.md` |
| `Strategy` | `wiki/strategy/strategy-{id}.md` |

当前问题：`paper.py` 调用 `extract_paper_structure` 时没有传 `llm_client`，而 `extract_paper_structure` 在 `llm_client is None` 时直接返回 `{}`，因此论文内容不会真正被解析。

---

## 4. Factor 页数据流

入口：`ui/webui/src/components/factor/FactorPanel.tsx`

```text
GET /api/factor/list
        |
        v
读取 wiki/factor/*.md frontmatter
        |
        v
用户选择 factor
        |
        v
POST /api/factor/{slug}/backtest
        |
        v
DataRouter.get(symbol, start, end)
        |
        v
run_factor_backtest(data, factor_class, factor_params)
        |
        v
metrics + ic_series + quantile_curves
```

`factor_backtest.py` 支持的 factor class：

- `momentum`
- `volatility`
- `ma_cross`
- `rsi`
- `value`
- `quality`
- `size`
- `growth`
- `signal_composite`

前端展示：

- `MetricCards`
- `ICChart`
- `QuantileCurves`

---

## 5. Strategy 页数据流

入口：`ui/webui/src/components/strategy/StrategyPanel.tsx`

```text
GET /api/strategy/list
        |
        v
读取 wiki/strategy/*.md frontmatter
        |
        v
用户选择 strategy
        |
        v
POST /api/strategy/{slug}/backtest
        |
        v
DataRouter.get(...) + get_benchmark(...)
        |
        v
run_backtest(signal_type, data, config)
        |
        +--> Path A: 预写信号
        |
        +--> Path B: QNSandbox codegen
        |
        v
compute_extended_metrics + compute_monthly_returns
```

Path A 预写信号：

| signal_type | 实现 |
|---|---|
| `ma_cross` | `MACrossStrategyNode` |
| `rsi` | `RSIStrategyNode` |
| `momentum` | `MomentumStrategyNode` |
| `volatility` | `VolatilityStrategyNode` |
| `factor_rank` | `FactorRankStrategyNode` |
| `signal_composite` | `SignalCompositeStrategyNode` |

前端展示：

- 指标卡片：Sharpe、Sortino、Max DD、Win Rate、CAGR、Trades
- `DrawdownChart`
- `HeatMap`
- Equity Curve 当前只是占位，因为后端没有返回带日期的 equity time series。

---

## 6. Reproduction 5 阶段流水线

入口：`ui/webui/src/components/reproduction/ReproductionPanel.tsx`

```text
POST /api/reproduction/start
        |
        v
create_session in ~/.llmwikify/reproduction.db
        |
        v
run_reproduction(ctx)
        |
        +-- Phase 1: extracting
        |      extract_strategy_config(wiki)
        |
        +-- Phase 2: backtesting
        |      DataRouter.get(...) + run_backtest(...)
        |
        +-- Phase 3: analyzing
        |      写 BacktestResult / Optimization Wiki 页面
        |
        +-- Phase 4: done
```

Session DB 表：

- `reproduction_sessions`
- `reproduction_events`
- `reproduction_artifacts`

主要事件：

- `extract.done`
- `data.fetched`
- `backtest.done`
- `wiki.written`
- `pipeline.error`

当前断链：`extract_strategy_config` 只扫描 `wiki/trading/*.md`，但 Paper 页写出的策略在 `wiki/strategy/*.md`。因此 Paper → Reproduction 不能端到端连通。

---

## 7. Wiki 路径一致性

| 数据 | 写入位置 | 读取位置 | 状态 |
|---|---|---|---|
| Source | `wiki/sources/` | Paper artifacts | 一致 |
| Factor | `wiki/factor/` | Factor API | 一致 |
| Strategy | `wiki/strategy/` | Strategy API | 一致 |
| Strategy | `wiki/strategy/` | Reproduction 读取 `wiki/trading/` | 不一致 |
| BacktestResult | `wiki/backtest/` | 暂无读取 API | 不完整 |
| Optimization | `wiki/optimization/` | 暂无读取 API | 不完整 |
| FactorBacktest | `wiki/factor-backtest/` | 暂未使用 | 未接入 |

---

## 8. 已知问题

### P0：功能断链

| # | 问题 | 影响 |
|---|---|---|
| 1 | 四个 reproduction router 未在 `routes.py` 注册 | API 404 |
| 2 | `paper.py` 未注入 LLM client | Paper extraction 永远为空 |
| 3 | `wiki/strategy/` 与 `wiki/trading/` 不一致 | Reproduction 找不到 Paper 生成的策略 |

### P1：功能受限

| # | 问题 | 影响 |
|---|---|---|
| 4 | 无 `/api/reproduction/list` | 无历史 session 列表 |
| 5 | `CachedClickHouseDataSource` 未真正缓存 | 数据源链名不副实 |
| 6 | 无 equity curve | Strategy 页核心图表缺失 |
| 7 | `compute_monthly_returns` 硬编码 2024 | 月度热力图不准确 |

### P2：一致性问题

| # | 问题 |
|---|---|
| 8 | `_parse_frontmatter` 多处重复 |
| 9 | signal type 枚举在 schema / strategy / factor_backtest 中不一致 |
| 10 | `MetricCards` 有两套实现 |
| 11 | `factor.py` 缺日期格式校验 |

---

## 9. 建议修复顺序

| 优先级 | 修复项 | 目的 |
|---|---|---|
| P0.1 | 在 `routes.py` 注册 paper/factor/strategy/reproduction routers | 先让 API 可访问 |
| P0.2 | 给 `paper.py` 注入 LLM client，或明确提供 offline fallback | 让 Paper 页能产出真实结构 |
| P0.3 | 统一 Strategy 页面读取路径，建议 Reproduction 同时读取 `wiki/strategy/` 和 `wiki/trading/` | 打通 Paper → Reproduction |
| P1.1 | 新增 `/api/reproduction/list` | 支持历史 session |
| P1.2 | 后端返回 `equity_curve[]` | 完善 Strategy 页 |
| P1.3 | `compute_monthly_returns` 使用真实交易日期或行情日期 | 修复热力图 |
| P2.1 | 抽取统一 frontmatter parser | 减少重复 |
| P2.2 | 统一 signal type schema | 降低维护成本 |

---

## 10. 最小可用闭环

要让 v0.4.0 具备最小可用闭环，建议先完成：

1. 注册四个后端 router
2. Paper 页能调用 LLM，写出 Factor / Strategy 页面
3. Reproduction 同时识别 `wiki/strategy/` 和 `wiki/trading/`
4. Factor 页能基于 Paper 生成的 Factor 跑通 IC/分层
5. Strategy 页能基于 Paper 生成的 Strategy 跑通 Path A 回测

目标闭环：

```text
PDF/URL -> Paper extraction -> wiki/factor + wiki/strategy
        -> Factor backtest -> IC/quantile
        -> Strategy backtest -> metrics/drawdown/heatmap
        -> BacktestResult/Optimization Wiki pages
```
