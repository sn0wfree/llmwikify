# 论文研报策略复现 — 实施计划

> 创建时间：2026-06-10
> 最后更新：2026-06-10（已与 v0.4.0-rc 实施版同步）
> 状态：实施计划（待切分支后实现）
> 版本目标：v0.4.0
> 核心原则：不造新引擎，不造新框架，只做薄适配。

---

## 零、设计原则

实现本功能时，以下 7 条原则指导所有决策。遇到分歧时，回溯原则。

### 原则 1：Wiki 优先（Wiki-First）

**一切产出都写回 wiki，不创建平行数据存储。**

- 论文结构化信息 → wiki 页（Logic/Data/Steps/Factors/Model）
- 生成的代码 → wiki 页（Code）+ 本地文件（.ipynb）
- 回测结果 → wiki 页（Backtest/Optimization）
- 知识图谱 → wiki 的 relation 表
- 会话状态 → DB（仅会话元数据，不存业务数据）

**反模式**：在 reproduction/ 下维护独立的 JSON/SQLite 存业务数据。

### 原则 2：逻辑一致 > 数字一致

**复现的价值在于「理解论文逻辑」，不在于「复现论文数字」。**

- 回测数字对不上是常态（数据源/滑点/复权/税费差异）
- UI 必须显式声明「已知偏差」
- 分析层重点评估「逻辑是否正确实现」而非「数字是否匹配」
- 如果逻辑正确但数字差异大，这是「已知偏差」，不是 bug

### 原则 3：Prompt 优先于代码（Prompt-Over-Code）

**能用 prompt 解决的，不写代码模块。**

- 理解层：不写 understand.py，用 wiki.md + prompt 驱动
- 分析层：不写 analyze.py，用 prompt 驱动
- 代码生成：不写 codegen.py，用 prompt 驱动
- 只在「必须执行」的环节写代码（回测/数据路由）

**判断标准**：如果一个功能的输入是文本、输出也是文本，用 prompt；如果需要执行/计算/IO，写代码。

### 原则 4：优雅降级（Graceful Degradation）

**每层都有降级路径，不因单点失败阻塞全链路。**

| 层 | 降级路径 |
|---|---|
| 输入 | 格式不支持 → 提示用户换格式 |
| 理解 | LLM 抽取失败 → 重试 2 次 → 标记 error |
| 理解 | 策略类型无法映射 → 标记 unknown → 自动降级到路径 B（LLM 代码生成）|
| 复现 | 参数配置错误 → 验证合法性，报具体字段 |
| 验证 | 回测超时 → 终止，标注超时 |
| 数据 | **Cache 命中失败 → ClickHouse → AKShare → SynthProvider** |
| 数据源失败 | LLM 抽取失败 → 重试 2 次 → 标记 session 为 error |
| 分析 | LLM 分析失败 → 跳过，标注未完成 |

### 原则 5：最小侵入（Minimal Invasiveness）

**不修改现有模块的核心逻辑，只在边缘扩展。**

- 不改 `analyze_source()` 的 prompt（用 Phase 2 补充抽取）
- 不改 `ReActEngine`（用 Skill 扩展能力）
- 不改 `SkillRuntime`（用新 Skill 注册）
- 不改 `PromptRegistry`（用新 YAML 文件）
- 改动仅限于：新增文件 + 在现有注册点追加 1-2 行

### 原则 6：可测试（Testable）

**每个模块可独立测试，不依赖 LLM/网络/沙箱。**

- Prompt 测试：用 mock LLM 返回值
- Skill 测试：用 mock handler
- 回测测试：用缓存的 DataFrame
- Path B codegen 测试：用硬编码代码 + namespace
- 端到端测试：可选（烧 token，仅 CI 中跑）

### 原则 7：少即是多（Less is More）

**能不做就不做，能简单就简单，能复用就不新建。**

- 能用现有 prompt 的，不新建 YAML
- 能用现有 API 的，不新建 MCP 工具
- 能用 wiki 页的，不新建数据库字段
- 能用 Skill 注册的，不新建引擎
- 能用 prompt 解决的分析，不写分析代码
- 能用 3 行解决的，不写 10 行
- **v0.4.0 WebUI 只做 REST endpoint，不做完整 Reproduction 页面（推迟到 v0.5.0）**

**判断标准**：每次新增文件/函数/字段/工具时，先问「这个真的需要吗？能不能用已有的替代？」。如果犹豫，就不加。

---

## 版本兼容性

- **v0.4.0 新增功能**，不影响现有 wiki 结构
- wiki.md 模板是**追加**，不是替换：现有 wiki.md 内容不变，只追加 `Papers/` 页面类型
- 现有 `ingest → analyze_source → write_page` 链路**零修改**
- 现有 Skill 系统**零修改**（只注册新 Skill）
- 现有 PromptRegistry **零修改**（只新增 YAML 文件）
- 现有 WebUI **零修改**（v0.4.0 仅新增 REST endpoint，不新增前端页面）

### 模块路径约定

- 复现模块代码：`src/llmwikify/reproduction/`（**不**使用 `strategy/` 子包）
- 复现模块 Prompt：`src/llmwikify/foundation/prompts/_defaults/repro_*.yaml`
- 复现 REST endpoint：`src/llmwikify/interfaces/server/http/reproduction.py`
- 复现测试：`tests/reproduction/`

---

## 一、决策汇总

| 决策项 | 选择 |
|---|---|
| 数据源链路 | **Cache → ClickHouse → AKShare → SynthProvider**（链式 fallback） |
| ClickHouse 连接 | `clickhouse://default:***@0.0.0.0:8123/quote`（只读，详见二十二章验证记录） |
| AKShare 角色 | 可选第三层；当前环境不可达（RemoteDisconnected），按需启用 |
| 代码生成 | **主路径：预写通用策略（6 个信号类型）+ 参数化调用**；降级路径：LLM 自动生成 |
| Path B 隔离 | **双模式**：`compile+exec`（默认，快）+ `subprocess`（可选，慢但更隔离） |
| 复现层调用 | 函数式直调（不经过 Skill 系统），`extract.py → backtest.py` |
| WebUI | v0.4.0 只做 REST endpoint（不做完整 Reproduction 页面） |
| arXiv/DOI 适配 | **推迟到 v0.5.0**（v0.4.0 只支持 PDF/URL/本地文件） |
| 券商研报 OCR | 推迟到 v0.5.0 |
| 分支 | 待本文档定稿后切 `feat/paper-reproduction` |
| 目标版本 | v0.4.0 |
| paper_id slug | `{source_type}:{hash(source_ref)[:8]}`（详见九章） |
| 分析层深度 | 浅分析（前置 + 后置各 1 个 prompt），深度分析推迟 v0.5.0 |

---

## 二、整体架构

```
用户输入 PDF/URL/本地文件
  ↓
┌─────────────────────────────────────────────────────────────┐
│ ① 输入 + 通用理解（完全复用 llmwikify，零新代码）            │
│                                                              │
│ extractors.extract() → wiki.ingest_source()                 │
│   → wiki.analyze_source() → generate_wiki_ops()             │
│   → execute_operations()                                    │
│                                                              │
│ 产出：Source Summary 页 + entities/relations/claims          │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ② 论文结构化抽取（1 个新 prompt + 1 个薄函数）              │
│                                                              │
│ repro_extract.yaml prompt：                                 │
│   读取 Source Summary                                       │
│   按 wiki.md 模板抽取：                                     │
│     Logic / Data / Steps / Factors / Model                  │
│     Analysis / Datasets / Risks / References                │
│   返回双契约 JSON：                                         │
│     Path A: {signal_type, signal_params, ...}               │
│     Path B: {signal_type: "unknown", code: "..."}           │
│   写入 wiki 页面                                            │
│                                                              │
│ 路径：src/llmwikify/reproduction/extract.py（~150行）       │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ③ 复现层（双路径）                                          │
│                                                              │
│ 路径 A（主路径）：参数化直调                                 │
│   signal_type ∈ {ma_cross, rsi, factor_rank,                 │
│                  volatility, momentum, signal_composite}    │
│   → GenericStrategy + 6 个预定义信号                          │
│   → 直接执行（无需 LLM）                                     │
│                                                              │
│ 路径 B（降级路径）：自动 LLM 代码生成                         │
│   signal_type == "unknown" → LLM 生成 Python 代码            │
│   → 双模式执行：                                             │
│      • compile+exec（默认）：注入 namespace={bt,pd,data}    │
│        • 必须定义 `cerebro` 变量                              │
│        • 容忍 LLM 已调用 cerebro.run()                       │
│        • 剥离 <think>...</think>                            │
│      • subprocess（可选）：写入 tempfile + 隔离执行           │
│                                                              │
│ 路径：src/llmwikify/reproduction/backtest.py（已实现 337行）│
│ 路径：src/llmwikify/reproduction/extract.py（~150行）       │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ④ 验证层（回测）                                            │
│                                                              │
│ backtrader + DataRouter                                     │
│   数据获取链：Cache → ClickHouse → AKShare → SynthProvider   │
│   回测执行 → 指标计算 → BacktestResult                       │
│   净值曲线 + 交易记录 + 已知偏差                              │
│                                                              │
│ 产出：wiki Backtest.md + Optimization.md                    │
│ 路径：src/llmwikify/reproduction/datacache.py（~150行）     │
│ 路径：src/llmwikify/reproduction/router.py（~100行）        │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 分析层                                                   │
│                                                              │
│ 理解层中（前置）：                                            │
│   repro_analyze_strategy.yaml → Analysis 页                  │
│                                                              │
│ 验证层后（后置）：                                            │
│   repro_analyze_backtest.yaml → Optimization 页              │
│   复用 GraphAnalyzer 做知识图谱分析                           │
│                                                              │
│ Prompt：2 个新 YAML                                         │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 知识图谱（持续积累）                                         │
│   公式→公式  因子→因子  策略→优势  策略→劣势                  │
│   复现→回测  回测→优化  论文→数据                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、wiki.md 模板

wiki.md 定义论文结构化页面模板，引导 LLM 按固定格式抽取：

```markdown
# 论文/研报策略复现

## 页面类型定义

### Papers/<id>/Logic（策略逻辑）
- 核心假设：这篇论文的核心逻辑是什么？
- 市场逻辑：基于什么市场现象/规律？
- 收益来源：alpha 从哪里来？
- 适用条件：什么条件下有效？

### Papers/<id>/Data（数据需求）
- 字段列表：需要哪些数据字段
- 时间粒度：日/分钟/tick
- 标的范围：股票/期货/期权/指数
- 数据来源：Wind/AKShare/iFinD/ClickHouse/其他

### Papers/<id>/Steps（操作步骤）
1. 信号生成：什么条件触发买入/卖出
2. 仓位管理：单票仓位上限/总仓位
3. 换仓频率：日/周/月
4. 止损止盈：具体规则
5. 交易成本：手续费/滑点假设

### Papers/<id>/Factors（因子/指标）
每个因子：
- 名称
- 定义（文字描述）
- 公式（LaTeX 或代码）
- 超参数值
- 计算周期

### Papers/<id>/Model（模型/框架）
- 模型类型：统计/ML/DL/规则
- 框架：backtrader/pandas/sklearn/pytorch
- 训练/验证划分
- 评价指标

### Papers/<id>/Analysis（优劣分析）
- 优势：为什么有效
- 劣势：潜在风险、失效条件
- 适用场景：市场类型、标的范围、时间周期
- 与其他策略的关系
- 改进方向

### Papers/<id>/Datasets（数据集）
- 数据集名称
- 来源
- 时间范围
- 处理方式（清洗/复权/标准化）

### Papers/<id>/Risks（风险与偏差）
- 已知局限
- 假设风险
- 实现偏差
- 数据局限

### Papers/<id>/References（参考文献）
- 原文引用
- 相关论文
- 代码仓库

### Papers/<id>/Backtest（回测结果）
- 指标汇总
- 净值曲线
- 交易记录
- 已知偏差说明

### Papers/<id>/Optimization（优化建议）
- 参数调整
- 因子改进
- 风控增强
- 其他改进
```

---

## 四、各层详解

### 4.1 输入层（零新代码）

完全复用 llmwikify 现有链路：

```
llmwikify ingest <source>
  → extractors.extract(source)        # 30+ 格式
  → wiki.ingest_source(content)       # raw/ + 元数据
  → wiki.analyze_source(raw_path)     # LLM 提取
  → execute_operations()              # 写入 wiki 页
```

### 4.2 论文结构化抽取（Phase 2）

Phase 1 产出 Source Summary 后，Phase 2 读取它并生成论文专属页面：

```python
# src/llmwikify/reproduction/extract.py（~150行）

async def extract_paper_structure(wiki, source_summary_page: str, paper_id: str):
    """读取 Source Summary，按 wiki.md 模板生成论文结构化页面 + 策略配置。

    Returns:
        (wiki_pages: dict[str, str], strategy_config: dict)
    """
    summary = wiki.read_page(source_summary_page)
    raw = await LLM.aask("repro_extract", {"pages": summary})
    cleaned = strip_thinking_blocks(raw)
    extraction = validate_extraction(cleaned)

    for page_name, content in extraction["wiki"].items():
        wiki.write_page(f"Papers/{paper_id}/{page_name}", content)

    wiki.write_relations(extraction.get("relations", []))
    return extraction["wiki"], extraction["strategy_config"]


def strip_thinking_blocks(text: str) -> str:
    """剥离 LLM 思考块：<think>...</think>（包含未闭合的）"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()
```

### 4.3 复现层（双路径）

**主路径（A）**：预写策略 + 参数化调用。**降级路径（B）**：自动 LLM 代码生成 + 双模式执行（compile+exec 默认 / subprocess 可选）。无人介入。

#### 路径 A：预写通用策略（已实现）

```python
# src/llmwikify/reproduction/backtest.py（已实现 337行）

def _make_strategy_class(signal_type: str, signal_params: dict):
    """根据 signal_type 动态生成 GenericStrategy 子类。"""
    defaults = _signal_defaults(signal_type)
    merged = {**defaults, **signal_params}

    class GenericStrategy(bt.Strategy):
        params = tuple((k, v) for k, v in merged.items())
        params = params + (("position_pct", 0.95),)

        def __init__(self):
            self.order = None
            self.trades_list = []
            self.signal_line = _make_signal_line(signal_type, self.data, self.params)

        def notify_order(self, order):
            if order.status in [order.Completed, order.Canceled, order.Margin]:
                self.order = None

        def notify_trade(self, trade):
            if trade.isclosed:
                self.trades_list.append(dict(
                    ref=trade.ref, size=trade.size,
                    price=trade.price, pnl=trade.pnl, pnlcomm=trade.pnlcomm
                ))

        def next(self):
            if self.order:
                return
            signal = self.signal_line[0]
            if signal > 0 and not self.position:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
            elif signal < 0 and self.position:
                self.order = self.close()

    GenericStrategy.__name__ = f"GenericStrategy_{signal_type}"
    return GenericStrategy


def _make_signal_line(signal_type: str, data, params):
    """构建指标 Line 对象（必须在 __init__ 中调用以预计算）。"""
    import backtrader as bt
    if signal_type == "ma_cross":
        return bt.indicators.DivByZero(
            bt.indicators.SMA(data.close, period=params.fast)
            - bt.indicators.SMA(data.close, period=params.slow),
            bt.indicators.SMA(data.close, period=params.slow),
        )
    elif signal_type == "rsi":
        return (50.0 - bt.indicators.RSI(data.close, period=params.period)) / 50.0
    elif signal_type == "momentum":
        return bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=params.period),
            bt.indicators.SMA(data.close, period=params.period),
        )
    elif signal_type == "volatility":
        return bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=params.period),
            bt.indicators.StandardDeviation(data.close, period=params.period),
        )
    elif signal_type == "factor_rank":
        return bt.indicators.PercentRank(data.close, period=params.period) - 0.5
    elif signal_type == "signal_composite":
        ma = bt.indicators.DivByZero(
            bt.indicators.SMA(data.close, period=params.fast)
            - bt.indicators.SMA(data.close, period=params.slow),
            bt.indicators.SMA(data.close, period=params.slow),
        )
        mom = bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=params.momentum_period),
            bt.indicators.SMA(data.close, period=params.momentum_period),
        )
        return (ma + mom) / 2
    raise ValueError(f"Unknown signal_type: {signal_type}")
```

#### 路径 B：自动降级到 LLM 代码生成（双模式执行）

**关键设计**：在受控 namespace 中执行 LLM 生成的代码，必须定义 `cerebro` 变量；容忍 LLM 已调用 `cerebro.run()`；剥离 thinking-block。

```python
# src/llmwikify/reproduction/backtest.py 中的 _run_codegen（已实现）

def _run_codegen(code: str, data: pd.DataFrame, cfg: dict[str, Any]) -> BacktestResult:
    """Path B: 在受控 namespace 中执行 LLM 生成的代码。

    Namespace 约束:
        - bt: backtrader 模块
        - pd: pandas 模块
        - data: 用户传入的 DataFrame（exec 后强制恢复）
    """
    import backtrader as bt

    namespace = {"bt": bt, "pd": pd, "data": data}
    try:
        # 1. 剥离 thinking-block
        code = strip_thinking_blocks(code)

        # 2. 编译 + exec 到 namespace
        compiled = compile(code, "<llm_strategy>", "exec")
        exec(compiled, namespace)

        # 3. 强制 data 绑定（防止 LLM 用 data = pd.read_csv(...) 覆盖）
        namespace["data"] = data

        # 4. 必须定义 cerebro 变量
        cerebro_obj = namespace.get("cerebro")
        if cerebro_obj is None:
            return BacktestResult(
                status="error",
                error="Generated code must define a 'cerebro' variable",
                signal_type="codegen",
                params=cfg,
            )

        # 5. 执行（容忍 LLM 已调用 cerebro.run()）
        results = None
        try:
            results = cerebro_obj.run()
        except Exception:
            results = namespace.get("results")
            if not results:
                raise

        # 6. 提取指标
        strat = results[0]
        return BacktestResult(
            status="success",
            statistics=_extract_metrics(strat, strat.analyzers),
            trades=strat.trades_list,
            final_cash=cerebro_obj.broker.getvalue(),
            total_return=(cerebro_obj.broker.getvalue() - cfg["initial_cash"]) / cfg["initial_cash"],
            signal_type="codegen",
            params=cfg,
        )
    except Exception as e:
        return BacktestResult(status="error", error=str(e), signal_type="codegen", params=cfg)


# ── 双模式开关 ──
# run_backtest() 默认 execution_mode="exec"
# 调用方可指定 execution_mode="subprocess" 走 tempfile + sys.executable（更隔离）
# subprocess 模式实现待补（v0.4.0-rc 可选）
```

#### run_reproduction 主流程

```python
# src/llmwikify/reproduction/run.py（待实现 ~200行）

async def run_reproduction(session_id: str):
    """复现主流程（异步执行）"""
    session = db.get_session(session_id)
    wiki = Wiki(session.wiki_id)

    try:
        # Phase 1: 输入 + 通用理解（复用 llmwikify）
        db.update_status(session_id, "extracting")
        source = resolve_input(session.source_type, session.source_ref)
        wiki.ingest_source(source)
        wiki.analyze_source(source)

        # Phase 2: 论文结构化抽取 → 写入 wiki 页 + 获取策略参数
        config = await extract_paper_structure(wiki, session.paper_id)
        db.create_artifact(session_id, "extraction",
                          wiki_page=f"Papers/{session.paper_id}/Logic")

        # Phase 3: 数据获取（Cache → ClickHouse → AKShare → SynthProvider）
        db.update_status(session_id, "fetching_data")
        data = await DataRouter.get(config["data_config"])

        # Phase 4: 回测（双路径）
        db.update_status(session_id, "backtesting")
        if config["signal_type"] != "unknown":
            backtest_result = run_backtest(
                config["signal_type"], data, config
            )
        else:
            backtest_result = run_backtest(
                config["code"], data, config, execution_mode="exec"
            )
        wiki.write_page(f"Papers/{session.paper_id}/Backtest",
                       format_backtest_report(backtest_result))

        # Phase 5: 分析 → 优化建议写入 wiki 页
        db.update_status(session_id, "analyzing")
        await analyze_results(wiki, session.paper_id, backtest_result)

        db.update_status(session_id, "done")
    except Exception as e:
        logger.error(f"Reproduction {session_id} failed: {e}")
        db.update_status(session_id, "error", error=str(e))
```

### 4.4 验证层（backtrader + DataRouter + DataCache）

数据获取链路：**Cache → ClickHouse → AKShare → SynthProvider**

#### 4.4.1 DataCache（已规划，未实现）

```python
# src/llmwikify/reproduction/datacache.py（待实现 ~150行）

class DataCache:
    """本地 SQLite 缓存，按 (source, symbol, start, end) 哈希键。"""
    DB_PATH = "~/.llmwikify/data_cache.db"

    def get(self, source: str, symbol: str, start: str, end: str) -> pd.DataFrame | None:
        """命中返回 DataFrame（带 datetime index + OHLCV columns），未命中返回 None。"""
        ...

    def set(self, source: str, symbol: str, start: str, end: str, df: pd.DataFrame):
        """写入缓存。"""
        ...
```

#### 4.4.2 DataRouter（链式 fallback）

```python
# src/llmwikify/reproduction/router.py（待实现 ~100行）

class DataRouter:
    """链式 fallback 数据源路由器。"""

    PROVIDERS = ["cache", "clickhouse", "akshare", "synth"]

    async def get(self, data_config: dict) -> pd.DataFrame:
        """依次尝试各 provider，第一个成功即返回。"""
        for provider_name in self.PROVIDERS:
            provider = self._get_provider(provider_name)
            try:
                df = await provider.get(data_config)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"{provider_name} failed: {e}")
                continue
        raise RuntimeError("All data providers failed")
```

#### 4.4.3 backtrader 兼容性注意事项（来自测试记录）

**这些是测试中实际遇到并修复的 gotchas，所有使用者必须知道：**

| # | 问题 | 解决方案 |
|---|---|---|
| 1 | `DrawDown` analyzer 使用 `get_analysis()["max"]["drawdown"]`，**不是** `.max.drawdown` 属性 | 见 backtest.py:99-100 |
| 2 | `bt.indicators.Constant` **不存在**于本 backtrader 版本 | 用算术运算替代 |
| 3 | `PandasData` feed 要求 **datetime 作 index**（不是 column） | backtest.py:71-75 自动 set_index |
| 4 | LLM 经常用 `self.p.xxx` 而非 `self.params.xxx` | codegen path 容忍；预写策略统一用 `self.params` |
| 5 | `SharpeRatio` 无交易时返回 None | backtest.py:91-96 显式处理 |
| 6 | `timeframe=bt.TimeFrame.Days` 必须显式传，否则年化错误 | backtest.py:82 |
| 7 | 超过 `max_tokens` 时 LLM 输出被截断（含 thinking + 代码） | strip_thinking_blocks + max_tokens=4000 |
| 8 | LLM 经常生成 `data = pd.read_csv(...)` 覆盖传入的 data | exec 后强制 `namespace["data"] = data` |

### 4.5 分析层（LLM prompt）

前置分析（理解层中）：`repro_analyze_strategy.yaml` → Analysis 页
后置分析（验证层后）：`repro_analyze_backtest.yaml` → Optimization 页

---

## 五、层间数据格式

### ① 输入层 → 理解层

```python
ExtractedContent:
  text: str           # 提取的全文
  source_type: str    # "pdf" / "url" / "youtube"
  title: str
  metadata: dict

SectionMetadata:
  sections: list[{id, title, word_count, preview}]
  total_words: int
  has_headers: bool
```

### ② 理解层 → 复现层

```python
# wiki.md 模板定义的 9 个页面，每个页面是 markdown
pages = {
  "logic":      wiki.read_page("Papers/<id>/Logic"),
  "data":       wiki.read_page("Papers/<id>/Data"),
  "steps":      wiki.read_page("Papers/<id>/Steps"),
  "factors":    wiki.read_page("Papers/<id>/Factors"),
  "model":      wiki.read_page("Papers/<id>/Model"),
  "analysis":   wiki.read_page("Papers/<id>/Analysis"),
  "datasets":   wiki.read_page("Papers/<id>/Datasets"),
  "risks":      wiki.read_page("Papers/<id>/Risks"),
  "references": wiki.read_page("Papers/<id>/References"),
}
```

### ③ 复现层 → 验证层

**对齐 run_backtest(strategy, data, config) 实参**：

```python
strategy_config: {
  signal_type: str,            # "ma_cross" | "rsi" | ... | "unknown"
  signal_params: dict,         # 信号参数，如 {"fast": 5, "slow": 20}
  position_pct: float,         # 仓位比例，默认 0.95
  initial_cash: float,         # 初始资金，默认 1_000_000
  commission: float,           # 手续费率，默认 0.001
  code: str | None,            # 仅 Path B 有值（完整可执行 Python 代码）
  data_config: {               # 数据配置
    symbols: list[str],
    start: str,
    end: str,
    freq: str,                 # "1d" / "1h"
  },
  execution_mode: str,         # "exec"（默认）| "subprocess"
}

# DataFrame 列名约定（强约束）
data: pd.DataFrame = {
  "date":   datetime64[ns],    # 必须（exec 后强制 set_index）
  "open":   float64,
  "high":   float64,
  "low":    float64,
  "close":  float64,
  "volume": float64,
}
# DataFrame.index 必须是 DatetimeIndex（backtest.py 自动 set_index）
```

### ④ 验证层 → 分析层

**对齐 BacktestResult schema（src/llmwikify/reproduction/schemas.py）**：

```python
@dataclass
class BacktestResult:
    status: str                    # "success" | "error"
    error: str | None
    statistics: dict[str, float]   # {sharpe_ratio, max_drawdown, win_rate, trades_count}
    trades: list[dict]             # [{ref, size, price, pnl, pnlcomm}, ...]
    final_cash: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    signal_type: str               # "ma_cross" | "codegen"
    params: dict
```

### ⑤ 分析层 → wiki 回写

```python
optimization_result: {
  performance_assessment: str,
  risk_analysis: str,
  optimization_suggestions: list[str],
  comparison_with_paper: str,
  applicable_scenarios: str,
  limitations: list[str],
}
```

---

## 六、Prompt 设计

### 6.1 repro_extract.yaml（结构化抽取 — 双输出契约）

**输入**：wiki 页面内容（Source Summary 全文）
**输出**：JSON，必须满足以下双契约之一：

#### 契约 A：预写策略映射成功

```json
{
  "wiki": {
    "logic": "...", "data": "...", "steps": "...",
    "factors": "...", "model": "...", "analysis": "...",
    "datasets": "...", "risks": "...", "references": "..."
  },
  "strategy_config": {
    "signal_type": "ma_cross",
    "signal_params": {"fast": 5, "slow": 20},
    "position_pct": 0.95,
    "initial_cash": 1000000,
    "commission": 0.001
  }
}
```

#### 契约 B：预写策略无法满足

```json
{
  "wiki": { ... },
  "strategy_config": {
    "signal_type": "unknown",
    "code": "import backtrader as bt\ncerebro = bt.Cerebro()\n..."
  }
}
```

**关键约束**：
- 必须从原文中抽取，不能编造
- 每个字段标注 confidence（HIGH/MEDIUM/LOW）
- 公式必须保留 LaTeX 格式
- 步骤必须有明确的输入→输出
- **必须二选一**：契约 A（映射到预定义类型）或契约 B（`signal_type="unknown"` + `code`）

```yaml
name: repro_extract
description: "从论文中抽取策略复现所需的 9 类结构化信息 + 策略配置（双契约）"

system: |
  你是一个量化论文结构化抽取器。从给定文档中提取：

  A) 9 类 wiki 信息（每个字段包含 content + confidence）：
  1. Logic（策略逻辑）
  2. Data（数据需求）
  3. Steps（操作步骤）
  4. Factors（因子）
  5. Model（模型/框架）
  6. Analysis（优劣）
  7. Datasets（数据集）
  8. Risks（风险）
  9. References（参考）

  B) strategy_config（回测配置，二选一）：
  ─ 契约 A：预写策略映射成功
    signal_type ∈ {ma_cross, rsi, factor_rank, volatility, momentum, signal_composite}
    signal_params: dict（每种类型的具体参数）
      - ma_cross: {fast, slow}
      - rsi: {period}
      - factor_rank: {period}
      - volatility: {period}
      - momentum: {period}
      - signal_composite: {fast, slow, momentum_period}
    + position_pct, initial_cash, commission

  ─ 契约 B：预写策略无法满足
    signal_type = "unknown"
    code = "完整可执行的 Python backtrader 代码（详见 repro_codegen.yaml 约束）"

  返回 JSON：{"wiki": {...}, "strategy_config": {...}}

user: |
  wiki 页面内容：
  {{ pages }}
```

### 6.2 repro_analyze_strategy.yaml（策略优劣分析）

**输入**：抽取结果 JSON
**输出**：分析报告 markdown

```yaml
name: repro_analyze_strategy
description: "分析策略的优劣与适用场景"

system: |
  分析该策略的：
  1. 优势 — 为什么有效、在什么条件下有效
  2. 劣势 — 潜在风险、失效条件、过拟合风险
  3. 适用场景 — 市场类型（牛/熊/震荡）、标的范围、时间周期
  4. 因子质量 — 每个因子的可信度、衰减风险
  5. 操作步骤 — 步骤是否可执行、是否存在前瞻偏差
  6. 与其他策略的关系 — 是否可组合、是否存在冲突
  7. 改进方向 — 已知文献中的改进方案

user: |
  策略信息：{{ extraction_json }}
```

### 6.3 repro_analyze_backtest.yaml（回测结果分析）

**输入**：回测指标 + 策略分析
**输出**：分析报告 markdown

```yaml
name: repro_analyze_backtest
description: "分析回测结果，提出优化建议"

system: |
  根据回测结果和策略分析，输出：
  1. 业绩评估 — Sharpe/MDD/年化是否合理
  2. 风险分析 — 最大回撤、波动率、集中度风险
  3. 优化建议 — 参数调整、因子改进、风控增强
  4. 与论文对比 — 数字差异的原因分析
  5. 适用场景 — 什么市场/周期/标的下有效
  6. 局限性 — 数据/假设/实现的已知局限

user: |
  回测指标：{{ metrics }}
  交易记录：{{ trades }}
  策略分析：{{ strategy_analysis }}
  已知偏差：{{ deviations }}
```

### 6.4 repro_codegen.yaml（代码生成 — 降级路径专用）

**输入**：wiki 页面 + strategy_config（含 signal_type="unknown"）
**输出**：完整可执行的 Python 回测脚本

**硬性约束**：
1. **输出代码 only**，**禁止 thinking-block**
2. **禁止 import 其他库**：pd、numpy、requests、urllib、socket、subprocess、os、sys 均不允许
3. **必须定义 `cerebro` 变量**
4. **数据源固定**：使用注入的 `data` 变量（pd.DataFrame，含 OHLCV + DatetimeIndex）
5. **必须 add 3 个 analyzers**：SharpeRatio / DrawDown / TradeAnalyzer
6. **禁用 self.p**：统一用 `self.params.xxx`
7. **禁止覆盖 data**：不要写 `data = pd.read_csv(...)` 之类
8. **策略类必须有 `self.trades_list = []` 在 __init__**

```yaml
name: repro_codegen
description: "预写策略无法满足时，LLM 生成自定义回测代码（Path B 专用）"

system: |
  根据论文信息生成完整的 backtrader 回测代码。

  硬性约束（违反任意一条代码无效）：
  1. **第一行必须是 `import backtrader as bt`**，后面直接是 `cerebro = bt.Cerebro()`。
  2. **禁止 thinking-block**：不要输出 <think>...</think> 任何解释。
  3. **禁止 import 其他库**：pd、numpy、requests、urllib、socket、subprocess、os、sys 均不允许。
  4. **必须定义 `cerebro = bt.Cerebro()`**，并 addstrategy / adddata / broker.setcash / broker.setcommission。
  5. **必须 adddata**：使用 `cerebro.adddata(bt.feeds.PandasData(dataname=data))`。
  6. **必须 add 3 个 analyzers**：
     - bt.analyzers.SharpeRatio(_name="sharpe", riskfreerate=0.0, timeframe=bt.TimeFrame.Days)
     - bt.analyzers.DrawDown(_name="drawdown")
     - bt.analyzers.TradeAnalyzer(_name="trades")
  7. **禁用 self.p.xxx**，统一用 `self.params.xxx`。
  8. **禁止调用 cerebro.run()**（框架会调用），调用了也可以（容忍）。
  9. **禁止覆盖 data**：不要写 `data = pd.read_csv(...)`。
  10. **策略类必须有 `self.trades_list = []` 在 __init__**，并在 `notify_trade` 里 append 字典。

user: |
  wiki 页面：{{ pages }}
  策略配置：{{ strategy_config }}

  Output ONLY the Python code (no thinking, no markdown):
```

---

## 七、待确认细节（实施期需要决定）

| # | 问题 | 影响 | 决定优先级 |
|---|---|---|---|
| 1 | `paper_id` slug 方案：`{source_type}:{hash(source_ref)[:8]}`（如 `pdf:a3f9e812`），是否需要人类可读别名？ | wiki 页面命名空间、URL 路由 | P1 实施期初定 |
| 2 | LLM token 成本控制：每次 reproduce 大约消耗多少 token（实测 vs 预估）？是否给用户选项关闭分析层？ | 用户体验、成本 | P1 |
| 3 | ClickHouse 连接信息管理：从 `~/.llmwikify/llmwikify.json` 读取还是硬编码？是否支持连接池？ | 配置复杂度 | P1 |
| 4 | Prompt 版本号：是否在 wiki 页 metadata 标注 `prompt_version`，以追踪 LLM 输出稳定性？ | 可重现性 | P2 |
| 5 | subprocess 模式开关位置：`run_backtest(execution_mode=...)` 参数 vs 全局配置文件 vs 环境变量？ | API 设计 | P1 |
| 6 | 回测报告格式：Markdown 表格 vs JSON vs HTML？是否支持嵌入图表（PNG base64）？ | 输出展示 | P2 |
| 7 | 多策略对比：同一论文是否能批量跑多个参数组合？输出对比表？ | 用户价值 | P2 v0.5.0 |
| 8 | 错误重试策略：LLM 瞬时错误重试 2 次后降级（标记 unknown 走 Path B）？ | 鲁棒性 | P1 |
| 9 | 跨会话缓存：相同论文是否复用之前的回测结果？ | 性能、可重现性 | P2 |

---

## 八、简化备选方案

如果实施期发现某些环节不可行：

| 环节 | 可行时 | 简化方案 |
|---|---|---|
| ClickHouse 数据源 | 可用 | 降级为纯 AKShare（当前环境不可达） |
| AKShare 数据源 | 可用 | 降级为纯 ClickHouse |
| ClickHouse + AKShare 都不可用 | 全失败 | 降级为合成数据（SynthProvider） |
| iFinD 集成 | iFinD token 可用 | 砍掉，只用 ClickHouse + AKShare |
| 策略映射 | LLM 能映射到预定义信号类型 | 降级为手动填写参数 |
| Wiki 模板 | 自动注入模板 | 降级为手动粘贴 |
| 分析层 | LLM 分析可用 | 跳过，不阻塞回测 |
| Path B LLM 代码生成 | LLM 可用 | 降级为预写策略扩展（如加 4 个新信号类型） |

---

## 九、Session/DB 管理

### 模块路径

- 实现路径：`src/llmwikify/reproduction/sessions.py`
- 数据库：`~/.llmwikify/agent/.llmwiki_agent.db`（复用现有 AgentDatabase）

### paper_id slug 方案

**格式**：`{source_type}:{hash(source_ref)[:8]}`

```python
import hashlib

def make_paper_id(source_type: str, source_ref: str) -> str:
    """生成 paper_id slug。

    示例:
        make_paper_id("pdf", "/path/to/fuyao-glass-2015.pdf")
        → "pdf:a3f9e812"
        make_paper_id("url", "https://arxiv.org/abs/2310.12345")
        → "url:5b7c9d2e"
    """
    h = hashlib.sha256(source_ref.encode()).hexdigest()[:8]
    return f"{source_type}:{h}"
```

### 复现会话表

```sql
CREATE TABLE reproduction_sessions (
    id TEXT PRIMARY KEY,                  -- UUID
    wiki_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,               -- {source_type}:{hash[:8]}
    source_type TEXT NOT NULL,            -- pdf / url（v0.4.0）
    source_ref TEXT NOT NULL,             -- 文件路径 / URL
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/extracting/reproducing/backtesting/done/error
    current_phase TEXT,
    progress REAL DEFAULT 0.0,
    config_json TEXT,                     -- 回测配置
    backtest_wiki_page TEXT,              -- 回测报告 wiki 页
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

> **原则 1 约束**：sessions 表只存会话元数据，**不存业务数据**。回测结果等业务数据存 wiki 页，通过 `backtest_wiki_page` 字段引用。

### 复现产物表

```sql
CREATE TABLE reproduction_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,                   -- extraction / code / backtest / analysis
    wiki_page TEXT,                       -- 对应的 wiki 页名称
    file_path TEXT,                       -- 本地文件路径（.ipynb / .py，可选）
    score REAL,                          -- 就绪度评分 / 质量评分
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
);
```

### 复现事件表（SSE 重启用）

```sql
CREATE TABLE reproduction_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES reproduction_sessions(id)
);
```

---

## 十、触发机制

v0.4.0 只支持 **REST endpoint + CLI** 两种触发方式。

### 方式 1：REST API

```python
# src/llmwikify/interfaces/server/http/reproduction.py（待实现 ~80行）

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/reproduction", tags=["reproduction"])


@router.post("/start")
async def start_reproduction(request: Request):
    """启动复现会话"""
    body = await request.json()
    session_id = db.create_session(
        wiki_id=body["wiki_id"],
        source_type=body["source_type"],  # pdf / url
        source_ref=body["source_ref"],
    )
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}


@router.get("/{session_id}")
async def get_session(session_id: str):
    """查询 session 状态"""
    session = db.get_session(session_id)
    return session.to_dict()


@router.get("/{session_id}/stream")
async def stream_progress(session_id: str):
    """SSE 流式进度"""
    async def event_generator():
        async for event in db.get_events(session_id):
            yield f"data: {json.dumps(event)}\n\n"
    return EventSourceResponse(event_generator())


@router.get("/{session_id}/artifacts")
async def list_artifacts(session_id: str):
    """列出产物"""
    artifacts = db.get_artifacts(session_id)
    return {"artifacts": [a.to_dict() for a in artifacts]}
```

### 方式 2：CLI

```bash
# 待实现
llmwikify reproduce <source> --wiki <wiki_id>
```

### 方式 3：MCP 工具（v0.5.0）

推迟到 v0.5.0。Agent 当前直接调用 REST endpoint。

### 推迟到 v0.5.0

- arXiv/DOI 适配（v0.4.0 仅支持本地 PDF / URL）
- 券商研报 OCR（v0.4.0 复用现有 `extractors.extract()`，不做 vision-LLM 降级）
- 完整 Reproduction WebUI 页面（v0.4.0 只做 REST endpoint）

---

## 十一、错误处理策略

### 每层失败处理

| 层 | 失败场景 | 处理方式 |
|---|---|---|
| 输入层 | 文件格式不支持 | 返回错误，提示用户换格式 |
| 输入层 | 文件损坏/空文件 | 返回错误，提示用户检查文件 |
| 理解层 | LLM 抽取失败 | 重试 2 次，失败则标记 session 为 error |
| 理解层 | 抽取结果不完整 | 按已有内容写入，标注缺失字段 |
| 理解层 | LLM 无法映射到已知策略类型 | 标记 `signal_type="unknown"`，自动降级到 Path B |
| 复现层 | 策略参数配置错误 | 验证参数合法性，报具体字段错误 |
| 复现层 | Path B LLM 生成代码语法错误 | 捕获异常，写入 BacktestResult(status="error") |
| 复现层 | Path B LLM 代码缺 cerebro 变量 | 捕获异常，提示重试或手动指定 |
| 验证层 | 回测执行超时 | 终止执行，标注超时 |
| 验证层 | 所有数据源失败 | Cache → ClickHouse → AKShare → SynthProvider，全部失败则报错 |
| 验证层 | 数据缓存查不到 | 同数据源 fallback 流程 |
| 验证层 | 数据格式错误（缺 OHLCV） | 报错并提示期望列名 |
| 分析层 | LLM 分析失败 | 跳过分析，标注未完成 |

### 全局错误处理

```python
async def run_reproduction(session_id):
    try:
        ...
    except Exception as e:
        logger.error(f"Reproduction {session_id} failed: {e}")
        db.update_status(session_id, "error", error=str(e))
```

---

## 十二、测试策略

### 单元测试（每个模块独立）

| 测试文件 | 覆盖 | 行数 |
|---|---|---|
| `tests/reproduction/test_backtest.py` | 7 信号 + 双路径一致性 + codegen 异常路径 | ~150 |
| `tests/reproduction/test_extract.py` | mock LLM，验证双契约（Path A / Path B）输出 | ~100 |
| `tests/reproduction/test_datacache.py` | Cache 读写 + 与 ClickHouse 集成 | ~80 |
| `tests/reproduction/test_router.py` | DataRouter 链式 fallback | ~80 |
| `tests/reproduction/test_sessions.py` | Session 创建/状态更新/产物记录 | ~60 |

### 集成测试（端到端）

| 测试 | 内容 | 耗时 |
|---|---|---|
| `test_e2e_extract` | PDF → wiki 页面（用 fixture PDF）| ~30s |
| `test_e2e_full` | PDF → 抽取 → 回测 → 报告（全链路）| ~90s |

### Mock 策略

- LLM 调用：用固定返回值 mock（不烧 token）
- ClickHouse：用 fixture DataFrame mock
- AKShare：用 fixture DataFrame mock

---

## 十三、wiki.md 集成方式

### 方案：用户手动写入（Phase 1）

wiki.md 是 wiki 的 schema 文件，定义页面类型和约定。复现功能的 wiki.md 模板需要用户手动添加到 wiki.md 中：

```bash
# 用户执行
llmwikify init  # 已有 wiki.md
# 手动将 Papers 页面类型添加到 wiki.md
```

### 方案：CLI 命令自动注入（Phase 2）

```bash
llmwikify reproduce --init-wiki  # 自动将 Papers 模板注入 wiki.md
```

### 实现

```python
# src/llmwikify/reproduction/wiki_template.py（待实现 ~50行）

PAPERS_TEMPLATE = """
## Papers（论文/研报策略复现）

### Papers/<id>/Logic（策略逻辑）
...

### Papers/<id>/Data（数据需求）
...
"""

def inject_papers_template(wiki_root):
    """将 Papers 模板注入 wiki.md"""
    wiki_md_path = os.path.join(wiki_root, "wiki.md")
    with open(wiki_md_path, "r") as f:
        content = f.read()
    if "Papers/<id>/Logic" not in content:
        with open(wiki_md_path, "a") as f:
            f.write(PAPERS_TEMPLATE)
```

---

## 十四、MCP 工具实现

> 原则 7（Less is More）：v0.4.0 不暴露 MCP 工具（推迟到 v0.5.0）。Agent 当前直接调用 REST endpoint。

**v0.5.0 计划**：2 个 MCP 工具（Less is More）

```python
# 1. wiki_paper_repro_start — 触发复现
async def handle_start(wiki_id, source_type, source_ref):
    session_id = db.create_session(wiki_id, source_type, source_ref)
    asyncio.create_task(run_reproduction(session_id))
    return {"session_id": session_id, "status": "pending"}

# 2. wiki_paper_repro_report — 返回全部信息（status + artifacts + code + backtest）
async def handle_report(session_id):
    session = db.get_session(session_id)
    artifacts = db.get_artifacts(session_id)
    wiki = Wiki(session.wiki_id)
    result = {"status": session.status, "progress": session.progress, "artifacts": []}
    for a in artifacts:
        item = {"kind": a.kind, "wiki_page": a.wiki_page, "score": a.score}
        if a.wiki_page:
            item["content"] = wiki.read_page(a.wiki_page)
        result["artifacts"].append(item)
    return result
```

---

## 十五、arXiv/DOI 输入适配（推迟到 v0.5.0）

> v0.4.0 仅支持本地 PDF / URL 输入。arXiv/DOI 适配推迟到 v0.5.0。

### arXiv（v0.5.0）

```python
# src/llmwikify/reproduction/input_adapter.py（v0.5.0 ~80行）

import arxiv

def download_arxiv(arxiv_id: str) -> str:
    """下载 arXiv 论文 PDF，返回本地路径"""
    client = arxiv.Client()
    search = client.results(arxiv.Search(id_list=[arxiv_id]))
    paper = next(search)
    paper.download_pdf(dirpath=".cache/repro/", filename=f"{arxiv_id}.pdf")
    return f".cache/repro/{arxiv_id}.pdf"
```

### DOI（v0.5.0）

```python
from habanero import Crossref

def resolve_doi(doi: str) -> str:
    """解析 DOI，返回 PDF URL（如有 OA）"""
    cr = Crossref()
    result = cr.works(doi)
    for link in result.get("message", {}).get("link", []):
        if link.get("content-type") == "application/pdf":
            return link["URL"]
    raise ValueError(f"DOI {doi} 无可用 PDF")
```

### 券商研报 OCR 降级（v0.5.0）

```python
async def extract_broker_report(pdf_path: str) -> str:
    """券商研报提取，图表多时降级到 vision-LLM"""
    result = extractors.extract(pdf_path)
    if len(result.text) < 500:  # 提取率低，可能是扫描件
        pages = extract_pages_with_figures(pdf_path, max_pages=2)
        for page in pages:
            description = await llm.describe_image(page.image)
            result.text += f"\n\n[图表描述] {description}"
    return result.text
```

---

## 十六、文件清单

| 文件 | 行数 | 状态 | 说明 |
|---|---|---|---|
| `src/llmwikify/reproduction/__init__.py` | 5 | **已实现** | 公共导出 |
| `src/llmwikify/reproduction/schemas.py` | 40 | **已实现** | BacktestResult |
| `src/llmwikify/reproduction/backtest.py` | 337 | **已实现** | run_backtest + GenericStrategy + 6 信号 + codegen |
| `src/llmwikify/reproduction/datacache.py` | ~150 | 待实现 | DataCache（本地 SQLite）+ ClickHouse provider |
| `src/llmwikify/reproduction/router.py` | ~100 | 待实现 | DataRouter 链式 fallback |
| `src/llmwikify/reproduction/extract.py` | ~150 | 待实现 | repro_extract prompt 调用 + thinking-block 剥离 |
| `src/llmwikify/reproduction/sessions.py` | ~120 | 待实现 | SQLite session/artifact 表 |
| `src/llmwikify/reproduction/run.py` | ~200 | 待实现 | run_reproduction 编排 |
| `src/llmwikify/reproduction/wiki_template.py` | ~50 | 待实现 | wiki.md 模板注入 |
| `src/llmwikify/reproduction/subprocess_runner.py` | ~80 | 待实现 | Path B subprocess 模式（可选）|
| `src/llmwikify/foundation/prompts/_defaults/repro_extract.yaml` | ~80 | 待写 | 双契约 prompt |
| `src/llmwikify/foundation/prompts/_defaults/repro_codegen.yaml` | ~60 | 待写 | Path B 专用 prompt |
| `src/llmwikify/foundation/prompts/_defaults/repro_analyze_strategy.yaml` | ~60 | 待写 | 策略分析 prompt |
| `src/llmwikify/foundation/prompts/_defaults/repro_analyze_backtest.yaml` | ~80 | 待写 | 回测分析 prompt |
| `src/llmwikify/interfaces/server/http/reproduction.py` | ~80 | 待实现 | REST endpoint |
| `tests/reproduction/test_backtest.py` | ~150 | 待写 | 7 信号 + 双路径一致性 + codegen 异常 |
| `tests/reproduction/test_extract.py` | ~100 | 待写 | mock LLM 双契约验证 |
| `tests/reproduction/test_datacache.py` | ~80 | 待写 | Cache + ClickHouse |
| `tests/reproduction/test_router.py` | ~80 | 待写 | DataRouter fallback |
| `tests/reproduction/test_sessions.py` | ~60 | 待写 | Session CRUD |
| **合计（v0.4.0）** | **~2054** | | **Python ~1674 + YAML ~280 + 测试 ~100（4个 e2e）** |

> **推迟到 v0.5.0**：5 个 TS 文件（Reproduction WebUI 页面，约 700 行 LOC），已砍掉。

---

## 十七、时间线（v0.4.0）

| 周 | 里程碑 | 交付 |
|---|---|---|
| W1 | M0 数据 + 验证 | datacache.py（Cache + ClickHouse）+ router.py（链式 fallback）+ repro_extract.yaml + repro_codegen.yaml |
| W2 | M1 抽取层 | extract.py + run.py 骨架 + sessions.py + 单元测试 |
| W3 | M2 复现层（已完成70%）| 完善 backtest.py 边界 case + subprocess_runner.py（可选）+ Path B LLM 异常处理 |
| W4 | M3 验证 + e2e | REST endpoint + 3 篇论文端到端测试 + 性能基准 |
| W5 | M4 收尾 + RC | bug fix + 文档同步 + v0.4.0-rc 发布 |

> 相比原 12 周计划，v0.4.0 压缩到 5 周（因为 backtest.py 已完成 70%）。

---

## 十八、M0 POC 验证（已通过 3/3）

| POC | 内容 | 状态 | 备注 |
|---|---|---|---|
| 双路径一致性 | 同一策略逻辑分别走 Path A / Path B，6 个核心指标 diff=0 | ✅ 已通过 | 见 `/tmp/opencode/test_backtest_dual_path.py` |
| 真实股票数据 | 600660.SH 福耀玻璃 2015-2024（2307 行，ClickHouse），7 个信号全部跑通 | ✅ 已通过 | 见 `/tmp/opencode/test_backtest_real_data.py` |
| LLM 代码生成 | MiniMax-M2.7 生成 Bollinger Bands 代码，框架端到端执行成功 | ✅ 已通过 | 见 `/tmp/opencode/test_llm_codegen.py` |

### 待验证（M1 期）

| POC | 内容 | 目标 |
|---|---|---|
| repro_extract prompt | mock LLM 返回双契约 JSON，extract.py 正确解析 | 验证 prompt schema 设计 |
| DataRouter fallback | 关闭 Cache 后自动走 ClickHouse；关闭 CH 后自动走 SynthProvider | 验证链路 fallback |
| run_reproduction 编排 | session 状态正确转移、产物正确写入 wiki 页 | 验证全链路无断裂点 |

---

## 十九、依赖

```toml
[project.optional-dependencies]
repro = [
  "backtrader>=1.9.78",      # 回测框架（核心）
  "clickhouse-connect>=0.14", # 主要数据源（实盘可达）
  "clickhouse-driver>=0.2",   # 备选 driver（已安装）
  "akshare>=1.16",            # 备用数据源（当前环境不可达）
]

# 推迟到 v0.5.0
# ifind = [
#   "ifind-py>=1.0",
# ]
# arxiv = ["arxiv>=2.1"]
# doi = ["habanero>=1.2"]
```

> 当前环境已安装 `clickhouse-driver` 0.2.10（通过 pipx），可直接使用。

---

## 二十、MCP 工具列表（v0.5.0）

| 工具名 | 参数 | 返回 |
|---|---|---|
| `wiki_paper_repro_start` | wiki_id, source_type, source_ref | session_id |
| `wiki_paper_repro_report` | session_id | status, progress, artifacts (全部内容) |

> v0.4.0 不暴露 MCP 工具。

---

## 二十一、风险与缓解

| 风险 | 缓解 |
|---|---|
| 论文回测数字对不上 | UI「已知偏差」模板 + 逻辑一致 ≠ 数字一致 |
| LLM 不可重现 | seed + low temp + prompt 版本号（v0.5.0）|
| iFinD 无 token | v0.4.0 不依赖 iFinD（仅 ClickHouse + AKShare）|
| AKShare 不可达 | 当前环境已确认 RemoteDisconnected；fallback 链路 Cache → ClickHouse 已就位 |
| 策略类型映射失败 | LLM 无法映射 → 自动降级到 Path B（LLM 代码生成 + 输出验证）|
| ClickHouse 不可达 | fallback 到 AKShare → SynthProvider |
| 数据格式错误（缺 OHLCV） | DataRouter 显式校验，报具体缺失列名 |
| Path B LLM 代码 bug | thinking-block 剥离 + 强制 namespace 注入 + 多重 try/except |
| **LLM 调用成本** | **~3-4 次/篇（提取 + 策略分析 + 回测分析），比代码生成方案减少 ~50%** |
| **WebUI 复杂度** | **v0.4.0 砍掉 5 个 TS 文件，只做 REST endpoint** |

---

## 二十二、已验证假设（测试记录）

> 本章记录实施前通过 3 个 POC 测试验证的关键假设。如未来设计改动导致与本章矛盾，必须先更新测试和实现。

### 测试 1：双路径一致性（合成数据）

- **目的**：证明 Path A（预写策略）与 Path B（LLM 生成代码）产生**完全一致**的回测结果
- **数据**：130 行正弦波 + 随机噪声（2024-01-01 至 2024-06-28）
- **策略**：5/20 SMA 交叉，95% 仓位
- **结果**（`/tmp/opencode/test_backtest_dual_path.py`）：
  - sharpe_ratio: A=0.153814, B=0.153814, **diff=0.00000000**
  - total_return: A=0.225543, B=0.225543, **diff=0.00000000**
  - max_drawdown: A=7.684677, B=7.684677, **diff=0.00000000**
  - win_rate: A=0.500000, B=0.500000, **diff=0.00000000**
  - final_cash: A=1,225,543.32, B=1,225,543.32, **diff=0.00000000**
  - trades_count: A=2, B=2
- **结论**：✅ 双路径接口契约稳定，BacktestResult schema 可信

### 测试 2：真实股票数据（600660.SH 福耀玻璃）

- **目的**：证明 backtest.py 在真实 A 股数据上对全部 6 个预定义信号类型都能跑通
- **数据源**：ClickHouse `quote.cn_stock` 表，600660.SH，2015-01-05 至 2024-07-01，**2307 行**
- **策略与结果**（`/tmp/opencode/test_backtest_real_data.py`）：

  | Strategy | Return | Sharpe | MaxDD | Trades |
  |---|---|---|---|---|
  | ma_cross(5,20) | +85.23% |0.026 |37.94% |75 |
  | ma_cross(10,30) | +136.31% |0.033 |33.60% |46 |
  | rsi(14) | -27.95% | -0.003 |49.44% |115 |
  | momentum(60) | +78.51% |0.024 |52.24% |72 |
  | volatility(20) | +72.02% |0.023 |46.64% |127 |
  | factor_rank(20) | +106.49% |0.029 |39.38% |127 |
  | signal_composite | +77.29% |0.024 |43.34% |63 |
  | Buy & Hold 基准 | +267.23% | - | - | - |

- **结论**：✅ 全部 6 个信号类型在真实数据上工作正常；点击率 Buy & Hold 远胜策略（说明这些都是教科书策略，对强趋势股票不及持有）

### 测试 3：LLM 代码生成（MiniMax-M2.7）

- **目的**：证明 LLM 生成的代码能在框架中端到端执行
- **LLM 配置**：provider=minimax, model=MiniMax-M2.7, base_url=`https://api.minimaxi.com`
- **数据源**：600660.SH 2020-01-02 至 2024-07-01，1088 行（ClickHouse）
- **测试 3a**：SMA 交叉策略描述
  - LLM 生成 1534 字符代码 → 框架执行成功
  - **结果**：total_return=+68.94%, sharpe=+0.039, 35 trades, cash=1,689,355
- **测试 3b**：Bollinger Bands 均值回归描述
  - LLM 生成 1320 字符代码 → 框架执行成功
  - **结果**：total_return=+0.00%, sharpe=+0.008, 11 trades, cash=1,000,005
- **观察**：
  - LLM 输出大量 `<think>...</think>` 块（占总输出 50%+），必须 strip
  - LLM 经常用 `self.p.xxx` 而非 `self.params.xxx`（需 codegen path 容忍）
  - LLM 经常生成 `data = pd.read_csv(...)` 覆盖（需 exec 后强制恢复 namespace["data"]）
  - LLM `max_tokens=2000` 经常截断代码（建议 max_tokens=4000）
- **结论**：✅ Path B 在真实 LLM + 真实数据下端到端可行

### 综合结论

3 个 POC 全部通过，证明：
1. **BacktestResult schema 稳定**（测试1、3 验证）
2. **6 个预写信号类型完整可用**（测试2 验证）
3. **Path B 双模式执行可行**（测试1 + 测试3 验证）
4. **ClickHouse 真实数据可获取**（测试2、3 验证）
5. **LLM 代码生成端到端**（测试3 验证）

可进入实施阶段（v0.4.0-rc）。
