# llmwikify v0.4.0 — 论文研报策略复现 功能规划

> 创建时间：2026-06-10
> 状态：功能规划（待切分支后实施）
> 版本目标：v0.4.0
> 核心原则：不造新引擎，不造新框架，只做薄适配。

---

## 一、项目概述

**目标**：用户输入 PDF/URL/本地文件，系统自动抽取论文结构化信息、获取数据、运行回测、生成分析报告，全部写回 wiki。

**数据流**：
```
PDF/URL → 理解层（复用） → 抽取层（新） → 数据层（新） → 回测层（已实现） → 分析层（新） → wiki 页
```

---

## 二、模块结构

```
src/llmwikify/reproduction/
├── __init__.py         (5 行)   公共导出
├── schemas.py          (56 行)  BacktestResult 数据类
├── backtest.py         (331 行) 回测引擎（QuantNodes adapter）
├── strategies.py       (307 行) 6 个 StrategyNode 子类
├── metrics.py          (174 行) sharpe/mdd/win_rate 计算
├── datacache.py        (待建)   DataCache（本地 SQLite 缓存）
├── datasource.py       (待建)   ClickHouseDataSource + AKShareDataSource + SynthDataSource
├── router.py           (待建)   DataRouter（链式 fallback）
├── extract.py          (待建)   论文结构化抽取（调 LLM）
├── sessions.py         (待建)   ReproductionDatabase（会话/产物/事件表）
└── run.py              (待建)   run_reproduction 全链路编排

src/llmwikify/foundation/prompts/_defaults/
├── repro_extract.yaml  (待建)   结构化抽取 prompt（双契约）
└── repro_codegen.yaml  (待建)   Path B 代码生成 prompt

src/llmwikify/interfaces/server/http/
└── reproduction.py     (待建)   REST endpoint

tests/reproduction/
├── test_backtest.py    (待建)   4 个 POC 测试迁移
├── test_datacache.py   (待建)   DataCache 单元测试
├── test_datasource.py  (待建)   DataSource 单元测试
├── test_router.py      (待建)   DataRouter 单元测试
├── test_extract.py     (待建)   抽取逻辑单元测试（mock LLM）
└── test_sessions.py    (待建)   Session DB 单元测试
```

---

## 三、分阶段实施

### 阶段 1：数据仓库层

**目标**：实现数据获取链 Cache → ClickHouse → AKShare → Synth。

| 文件 | 行数 | 内容 |
|---|---|---|
| `datacache.py` | ~100 | DataCache 类：本地 SQLite 读写，key=(source, symbol, start, end)，value=序列化 DataFrame |
| `datasource.py` | ~250 | ClickHouseDataSource + AKShareDataSource + SynthDataSource，统一接口 `get(symbol, start, end) → pd.DataFrame` |
| `router.py` | ~100 | DataRouter：链式 fallback，依次尝试各 DataSource，第一个成功即返回 |
| `test_datacache.py` | ~80 | Cache 读写、序列化往返、miss 行为 |
| `test_datasource.py` | ~100 | ClickHouse mock、AKShare 不可达降级、Synth 兜底 |
| `test_router.py` | ~80 | fallback 顺序验证、全失败降级到 Synth |

**命名规范**：
- 缓存类：`DataCache`
- 数据源类：`XxxDataSource`（统一后缀）
- 路由类：`DataRouter`
- 所有 DataSource 接口：`get(symbol, start, end) → pd.DataFrame | None`

**依赖**：`clickhouse-driver`（已安装）、`akshare`（当前不可达）、`sqlite3`（标准库）

---

### 阶段 2：Prompt YAML

**目标**：实现论文结构化抽取的两个核心 prompt。

| 文件 | 行数 | 内容 |
|---|---|---|
| `repro_extract.yaml` | ~120 | 输入 wiki Source Summary，输出 JSON 双契约（Path A: signal_type+params / Path B: unknown+code） |
| `repro_codegen.yaml` | ~70 | Path B 专用，生成 QuantNodes 风格代码 |
| `test_extract.py` | ~80 | mock LLM 测试抽取逻辑（双契约校验、thinking-block 剥离） |

**双契约设计**：

```json
Path A: {"wiki": {...}, "strategy_config": {"signal_type": "ma_cross", "signal_params": {"fast":5,"slow":20}}}
Path B: {"wiki": {...}, "strategy_config": {"signal_type": "unknown", "code": "from llmwikify..."}}
```

**依赖**：`PromptRegistry`（已有）、`LLMClient`（已有）

---

### 阶段 3：抽取层 + 编排

**目标**：实现 extract → backtest → analyze 全链路。

| 文件 | 行数 | 内容 |
|---|---|---|
| `extract.py` | ~150 | extract_paper_structure()：调 LLMClient + PromptRegistry，写入 9 个 wiki 页，返回 strategy_config |
| `sessions.py` | ~120 | ReproductionDatabase：3 张表（sessions/artifacts/events），状态机 pending→extracting→backtesting→done/error |
| `run.py` | ~200 | run_reproduction()：5 个 Phase 编排（理解→抽取→数据→回测→分析） |
| `test_run.py` | ~80 | mock 全链路测试 |

**run_reproduction 流程**：

```
Phase 1: extract_paper_structure() → 写 9 个 wiki 页 + 获取 strategy_config
Phase 2: DataRouter.get() → 获取 DataFrame
Phase 3: run_backtest() → 双路径（Path A: 预写策略 / Path B: LLM 代码）
Phase 4: analyze_results() → 写入 Backtest + Optimization wiki 页
Phase 5: update status → done
```

**依赖**：阶段 1 + 阶段 2

---

### 阶段 4：REST endpoint

**目标**：暴露 HTTP API，供 WebUI 和外部调用。

| 文件 | 行数 | 内容 |
|---|---|---|
| `reproduction.py` | ~80 | FastAPI 路由：/start, /get, /stream(SSE), /artifacts |
| `test_repro_endpoint.py` | ~30 | mock HTTP 测试 |

**依赖**：阶段 3

---

## 四、依赖关系

```
阶段 1 (datacache + datasource + router)
    ↓
阶段 2 (prompts)  ← 与阶段 1 无依赖，可并行
    ↓
阶段 3 (extract + sessions + run) ← 阶段 1 + 阶段 2
    ↓
阶段 4 (REST endpoint) ← 阶段 3
```

---

## 五、关键 API

### 已实现（阶段 0）

```python
# backtest.py
run_backtest(strategy: str, data: pd.DataFrame, config: dict) → BacktestResult

# schemas.py
@dataclass class BacktestResult:
    status, error, statistics, trades, final_cash, total_return,
    sharpe_ratio, max_drawdown, win_rate, signal_type, params,
    summary, config, security_status, nodes

# strategies.py
MACrossStrategyNode, RSIStrategyNode, MomentumStrategyNode,
VolatilityStrategyNode, FactorRankStrategyNode, SignalCompositeStrategyNode
```

### 待实现（阶段 1-4）

```python
# datacache.py
class DataCache:
    get(source, symbol, start, end) → pd.DataFrame | None
    set(source, symbol, start, end, df: pd.DataFrame)
    clear()

# datasource.py
class ClickHouseDataSource:
    get(symbol, start, end) → pd.DataFrame | None
class AKShareDataSource:
    get(symbol, start, end) → pd.DataFrame | None
class SynthDataSource:
    get(symbol, start, end) → pd.DataFrame | None

# router.py
class DataRouter:
    get(data_config: dict) → pd.DataFrame

# extract.py
extract_paper_structure(llm, wiki, paper_id) → dict  # strategy_config

# sessions.py
class ReproductionDatabase:
    create_session(wiki_id, paper_id, source_type, source_ref) → session_id
    get_session(session_id) → Session
    update_status(session_id, status, **kwargs)
    create_artifact(session_id, kind, wiki_page, ...)
    get_artifacts(session_id) → list[Artifact]

# run.py
run_reproduction(session_id, deps: ReproductionDeps)
```

---

## 六、测试策略

### 单元测试

| 测试文件 | 覆盖 | Mock 策略 |
|---|---|---|
| test_datacache.py | SQLite 读写、miss | 无（用 tmp_path） |
| test_datasource.py | 各 DataSource | monkeypatch ClickHouse/AKShare |
| test_router.py | fallback 顺序 | monkeypatch 各 provider |
| test_extract.py | 抽取逻辑 | mock LLM 返回值 |
| test_sessions.py | DB CRUD | 无（用 tmp_path） |

### 集成测试

| 测试 | 内容 | Mock 策略 |
|---|---|---|
| test_run.py | 全链路 | mock LLM + mock ClickHouse |
| test_backtest.py | 4 个 POC | 无（真实数据 + 合成数据） |

### 端到端测试（可选）

| 测试 | 内容 | Token 消耗 |
|---|---|---|
| e2e_extract | PDF → wiki 页面 | ~10K tokens |
| e2e_full | PDF → 抽取 → 回测 → 报告 | ~30K tokens |

---

## 七、风险与缓解

| 风险 | 缓解 | 验证 |
|---|---|---|
| ClickHouse 连接失败 | DataRouter fallback 到 AKShare/Synth | test_router_fallback |
| LLM thinking-block 干扰 JSON | strip_thinking_blocks + 强校验 | test_extract_thinking |
| Session DB 与主 agent DB 冲突 | 独立 reproduction.db | test_sessions_independent |
| run_reproduction 异步崩溃 | try/except + update_status("error") | test_run_error_handling |
| 日期类型不一致 | 统一 ISO 字符串（已修复） | test_backtest_dual_path |
| 截面策略多标的数据格式 | _prepare_data 保留 ts_code 列 | test_cross_sectional |

---

## 八、时间线

| 阶段 | 预估行数 | 预估时间 | 依赖 |
|---|---|---|---|
| 阶段 1（数据仓库层） | ~700 行 | 2 小时 | 无 |
| 阶段 2（Prompt YAML） | ~270 行 | 0.5 小时 | 无 |
| 阶段 3（抽取层+编排） | ~550 行 | 3 小时 | 阶段 1+2 |
| 阶段 4（REST endpoint） | ~110 行 | 0.5 小时 | 阶段 3 |
| **合计** | **~1630 行** | **~6 小时** | |

---

## 九、文档更新

| 文档 | 更新内容 |
|---|---|
| `docs/plan/paper-reproduction.md` | 第十六章文件清单更新命名（datasource/datacache/router） |
| `docs/research/paper-reproduction-survey.md` | 无 |
| `AGENTS.md` | 追加 reproduction 模块说明 |

---

## 十、待确认决策

| 问题 | 当前选择 | 备注 |
|---|---|---|
| Session DB 独立还是复用 | **独立 reproduction.db** | 更清晰，避免耦合 |
| run.py 是否本阶段实现 | **实现** | 全链路骨架 |
| 阶段 1 先还是阶段 2 先 | **阶段 1 先** | 数据层独立可测 |
| 测试中 LLM 调用默认 skip | **pytest.mark.llm** | 保护 token |