# 论文 / 研报 策略复现 — 业界调研

> 创建时间：2026-06-10
> 最后更新：2026-06-10（已与 v0.4.0-rc 实施版同步）
> 状态：调研报告
> 目的：梳理业界主流方案、关键工具、典型数据流，给实施计划提供依据。

---

## 一、问题定义

「论文研报策略复现」本质是 **文档 → 知识 → 可执行代码/回测** 的三段式转换：

```
论文 / 研报 PDF  →  结构化知识  →  代码 & 回测报告
 (LaTeX/PDF/HTML)    (公式/方法/数据)    (.ipynb/.py/PNL)
```

三段每一段都有独立的工具生态。复现「完整链路」在业界仍处于早期，多数产品只覆盖其中 1-2 段。

---

## 二、业界项目盘点

### 2.1 论文解析 / 理解类

| 项目 / 产品 | 形态 | 核心能力 |
|---|---|---|
| PyMuPDF4LLM | PyPI 库（1.27.x） | PDF → Markdown/JSON；表格、公式、阅读顺序、Hybrid OCR |
| Microsoft MarkItDown | CLI + Python API（149k⭐） | 万能文件 → Markdown（PDF/Word/PPT/Excel/HTML/Audio/YouTube）|
| LlamaParse | 商业云服务 | Agentic OCR，130+ 格式，高保真但需付费 |
| GROBID | 自托管服务 | 学术论文专用：标题/作者/摘要/章节/参考文献/公式（LaTeX）|
| Nougat | 端到端模型（Meta） | PDF → LaTeX，公式 OCR 强 |

**关键洞察**：

- 纯规则解析（PyMuPDF、pdfplumber）快、稳，但公式转 LaTeX 是死穴。
- Vision-LLM（GPT-4o、Claude with vision）精度最高，但单本研报 30-100 页成本 $1-5。
- **混合方案是行业共识**：本地 PyMuPDF/MarkItDown 提文本 + 图表，按需用 vision-LLM 补关键页/公式。

### 2.2 研究 / 分析类（多 Agent）

| 项目 | 形态 | 核心思路 |
|---|---|---|
| TradingAgents | 多 Agent 框架（84.8k⭐） | 4 类分析师 + 多空辩论 + Trader + 风控；LangGraph 编排；决策日志持久化 |
| OpenAI Deep Research | 商业产品 | 多步研究：拆解 → 搜索 → 综合 → 引文 |
| AutoResearch（本项目） | 内嵌 6 步框架 | 概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单 |
| GPT Researcher | 开源 | Planner + Executor 多 Agent；产出带引文长报告 |

**关键洞察**：

- 多 Agent 框架的核心价值不是「多 agent」本身，而是**结构化反思 + 显式辩论**。
- TradingAgents 仍以**决策信号**为目标（买/卖/不操作），不是「生成回测代码」。repo 里没有任何 backtester。
- 本项目 autoresearch 已有 6 步框架 + 8 个质量门禁，骨架完整，引擎层集成已就位（v5，2026-06-04）。

### 2.3 策略 / 回测类

| 项目 | 形态 | 关键能力 |
|---|---|---|
| backtrader | Python 库（最主流） | 多市场，事件驱动，支持 live trading，丰富 analyzer |
| Zipline-reloaded | Python 库 | 学术派（Quantopian 遗产），pipeline API |
| VectorBT / VectorBT Pro | NumPy 加速 | 1000× 快于 backtrader |
| Qlib（Microsoft） | 平台级 | AI 量化（Alpha 因子 + 风险模型 + 订单执行）|
| WorldQuant Alpha101 | 论文 | 101 个经典 alpha 公式 |

**关键洞察**：

- backtrader 是中文社区最常用，文档/教程/书最多，a 股/期货/期权扩展生态成熟。
- 业内真正复现「论文 PnL」极其少见：滑点、复权、撮合、税费、数据源差异都会让数字差几倍。**复现的价值在于「逻辑一致」而非「数字一致」**。

### 2.4 论文代码 / Notebooks 类

| 平台 / 形态 | 特点 |
|---|---|
| Alpha101 / 150 等公式集 | 公开代码、公开公式 |
| paperswithcode | 论文 → 代码 link 索引（已部分停更）|
| GitHub awesome-quant 系列 | 收录整理 |
| Moxin / AlphaFin / FinAgent | arXiv → GitHub 自动化 |

**关键洞察**：

- 大部分 alpha 论文的官方代码质量堪忧，**复现等于重写**。
- 自动把公式翻译成 pandas/numpy 向量化代码是 LLM 的强项，但回测一致性必须由框架保证。

---

## 三、典型技术栈组合（业界共识）

### 3.1 论文解析层

```
PDF/URL 输入
  → PyMuPDF4LLM  → Markdown（含表格、版式）
  → [可选] Nougat/GROBID  → 公式 LaTeX
  → [按需] vision-LLM  → 图表 OCR/摘要（≤3 页/篇）
```

### 3.2 研究理解层

```
Markdown 全文
  → Chunk + 索引（BM25 + 向量）
  → ReAct / Multi-Agent 循环：
    概念澄清 → 关键提取 → 证据建立 → 综合报告
  → Markdown 报告 + JSON 结构化
```

### 3.3 策略复现层

```
报告 + 公式 + 参数
  → LLM 结构化抽取（非代码生成）
     signal_type + params → 预写 backtrader 策略
  → backtrader 回测
  → 指标（Sharpe / MDD / Calmar / IR）+ 净值曲线
```

---

## 四、关键难点与对策

| 难点 | 业界做法 | 本项目可借鉴 |
|---|---|---|
| PDF 公式识别 | Nougat / Pix2Text / Mathpix | Phase 1 仅做 LaTeX 文本保留，Phase 4 视需求加 Nougat |
| 研报图表 OCR | vision-LLM 描述 + 数据重绘 | Phase 3 引入，按页预算 ≤2 页/篇 |
| 多步推理漂移 | 多 Agent 辩论 + 显式 6 步框架 | autoresearch 框架就位，直接复用 |
| 代码生成正确性 | LLM 多次 + 单元测试 + nbconvert execute | **预写策略优先**，不满足时 LLM 生成 + subprocess 执行 |
| 回测结果复现度 | 固定数据源 + 固定手续费/滑点 + 明确披露 | config 强约束，结果页 + 「已知偏差」声明 |
| LLM 不可重现 | 固定 seed + low temperature + 显式 prompt 版本 | PromptRegistry 已支持 |
| 数据源授权 | AKShare（主）+ iFinD（补），不用 Tushare | v0.4.0 改为 **Cache → ClickHouse → AKShare → SynthProvider**（实测 AKShare 不可达，详见 3.5 节）|
| 券商研报 (中文+图片) | PaddleOCR + 多模态 LLM | Phase 3 评估中 |

---

### 3.5 数据源验证（本项目实际环境实测，2026-06-10）

> v0.4.0 设计调整：放弃"AKShare 主"假设，改为链式 fallback（Cache → ClickHouse → AKShare → SynthProvider）。

| 数据源 | 可达性 | 数据范围 | 推荐度 |
|---|---|---|---|
| **ClickHouse `quote.cn_stock`** | ✅ 可用 | 5535 只 A 股，2008-2024，日 OHLCV | **★★★★★ 首选** |
| **AKShare `stock_zh_a_hist`** | ❌ 不可用（RemoteDisconnected） | A 股日线 | ★★☆☆☆ 备用 |
| **iFinD `ifind-py`** | ❌ 未安装 token | 全市场多频率 | 推迟到 v0.5.0 |
| **Tushare** | — | A 股（积分限制）| ✗ 不使用 |

**ClickHouse 实测连接信息**（仅读，详见测试代码）：
- 协议：`clickhouse://default:***@0.0.0.0:8123/quote`
- 端口：`9000`（native），`8123`（HTTP）
- driver：`clickhouse-driver` 0.2.10（已通过 pipx 安装）
- 表：`cn_stock`（schema 见下）

```sql
cn_stock schema:
  ts_code      LowCardinality(String)  -- e.g. "600660.SH"
  trade_date   DateTime
  open         Float64
  high         Float64
  low          Float64
  close        Float64
  pre_close    Float64
  change       Float64
  pct_chg      Float64
  vol          Float64
  amount       Float64
```

**数据 Cache 设计要点**：
- Cache 表 key：`(source, symbol, start, end)` 哈希
- Cache 表 value：序列化 DataFrame（parquet / pickle）
- 写入时机：ClickHouse / AKShare 成功获取后立即写入
- 读取时机：每次请求先查 Cache，未命中才走 ClickHouse

---

### 4.5 backtrader 兼容性 gotchas（实测发现，2026-06-10）

> 这些 gotchas 在 POC 测试 1-3 中实际遇到，必须在实施时显式处理。

| # | Gotcha | 解决方案 | 影响范围 |
|---|---|---|---|
| 1 | `DrawDown` analyzer 的 `.max.drawdown` **属性访问报错** | 改用 `analyzer.get_analysis()["max"]["drawdown"]` | backtest.py:99-100 |
| 2 | `bt.indicators.Constant` **不存在**（本 backtrader 版本未实现） | 用算术运算代替（如 `data.close - data.close`）| backtest.py:265 |
| 3 | `PandasData` feed 要求 **datetime 作 index**（不是 column） | backtest.py 自动 set_index | backtest.py:71-75 |
| 4 | `SharpeRatio` 无交易时返回 None | 显式判 None 转 0.0 | backtest.py:91-96 |
| 5 | `SharpeRatio` 默认年化为年；不传 timeframe 则年化错误 | 显式传 `timeframe=bt.TimeFrame.Days` | backtest.py:82 |
| 6 | `TradeAnalyzer.get()` **不存在** | 用 `.get_analysis()["total"]["closed"]` | backtest.py:97-100 |
| 7 | backtrader `_runonce` 模式下 indicator 预计算时机严格 | 必须在 `__init__` 中预计算（构造 Line 对象）| backtest.py:158 |
| 8 | `array index out of range` 当 indicator 周期未到 | 用 `DivByZero` 保护 | backtest.py:225 |

**经验总结**：
- backtrader API 文档与实现有偏差，必须实测验证
- 所有 analyzer 调用统一走 `get_analysis()` 方法，避免属性访问
- 数据预处理要在框架层兜底（set_index、列名映射）

---

### 5.x LLM 行为观察（MiniMax-M2.7 实测，2026-06-10）

> v0.4.0 默认 LLM 为项目配置的 `MiniMax-M2.7`（`~/.llmwikify/llmwikify.json`）。该模型有几个独特行为需在 prompt 设计和框架层显式处理。

#### 行为 1：大量 thinking-block 输出

- **现象**：M2.7 在生成代码前会输出长达数千 token 的 `<think>...</think>` 推理块
- **数据**：`/tmp/opencode/inspect_llm.py` 实测，一次 prompt 生成 6708 字符，其中 ~50% 是 thinking
- **影响**：容易触发 `max_tokens` 截断，导致有效代码缺失
- **缓解**：
  1. 框架层 `strip_thinking_blocks()` 用正则 `<think>.*?(</think>|$)` 剥离
  2. Prompt 显式禁止：`Output ONLY the Python code (no thinking, no markdown, no commentary)`
  3. `max_tokens` 至少设 4000（覆盖 thinking + code）

#### 行为 2：偏好 `self.p.xxx` 而非 `self.params.xxx`

- **现象**：backtrader 文档推荐 `self.params.xxx`，但 LLM 经常写成 `self.p.xxx`
- **数据**：测试 3 中 2/2 次生成的代码都用 `self.p`
- **影响**：Path B 代码运行时会抛 AttributeError
- **缓解**：
  1. Prompt 显式约束：`禁用 self.p.xxx，统一用 self.params.xxx`
  2. 框架层可在 codegen 后做 AST 改写：`self.p.xxx` → `self.params.xxx`（v0.4.0 未实现，作为 v0.5.0 增强）

#### 行为 3：经常覆盖 `data` 变量

- **现象**：LLM 经常生成 `data = pd.read_csv('data.csv', ...)`，覆盖框架传入的 DataFrame
- **数据**：测试 3a 中第一版输出包含 `data = pd.read_csv(...)`
- **缓解**：exec 后强制恢复 `namespace["data"] = data`（已在 backtest.py:283 实现）

#### 行为 4：经常违反"不调用 cerebro.run()"约束

- **现象**：即使 prompt 明确禁止，LLM 经常自动调用 `cerebro.run()` 并 `print()` 结果
- **缓解**：框架层 catch 异常 + 容忍模式：先尝试 `cerebro.run()`，失败则取 `namespace["results"]`

#### 行为 5：base_url 双 `/v1` 问题

- **现象**：`https://api.minimaxi.com/v1` 已经是完整 base_url，但 LLMClient 默认还会拼 `/v1/chat/completions`，导致 URL 变 `https://api.minimaxi.com/v1/v1/chat/completions`
- **缓解**：调用方在使用 LLMClient 时需 strip `/v1` 后缀：
  ```python
  base_url = llm_cfg.get("base_url", "").rstrip("/")
  if base_url.endswith("/v1"):
      base_url = base_url[:-3]
  ```

#### 经验总结

| 维度 | 经验 | 设计含义 |
|---|---|---|
| Prompt | 必须显式禁止 thinking-block | repro_codegen.yaml 第一条 system 约束 |
| Prompt | 必须列出"禁止 import"清单 | 否则 LLM 必引入 pandas/numpy |
| 框架 | 必须 strip thinking-block | `strip_thinking_blocks()` 公共函数 |
| 框架 | 必须 force `namespace["data"] = data` | 防止 LLM 覆盖 |
| 框架 | 必须容忍 `cerebro.run()` 已调用 | try/except + fallback to namespace["results"] |
| 框架 | `max_tokens=4000` 是安全下限 | 默认配置建议 |

---

## 五、本项目（llmwikify）的现状盘点

### 5.1 已有可复用能力

| 能力 | 位置 | 复用度 |
|---|---|---|
| PDF/URL/YouTube 摄取 | `foundation/extractors/` | 直接复用 |
| 知识图谱 | `kernel/wiki/engines/relation.py` | 直接复用 |
| Wiki 写回 | `kernel/wiki/wiki.py` | 直接复用 |
| PromptRegistry | `foundation/prompts/prompt_registry.py` | 直接复用 |
| ReAct 循环 | `apps/chat/agent/react_engine.py` | 直接复用 |
| Research 6 步引擎 | `apps/chat/autoresearch/` | 直接复用 |
| Skill 系统 | `apps/chat/skills/` | 直接复用 |
| WebUI + SSE | `web/webui/` + `interfaces/server/` | 直接复用 |
| MCP 工具 | `mcp/` | 直接复用 |
| GraphAnalyzer | `kernel/graph/analyzer.py` | 直接复用 |

### 5.2 缺失 / 需新增

| 缺失项 | 优先级 |
|---|---|---|
| strategy/reproduction 目录和核心模块 | P0 |
| 已改为 `src/llmwikify/reproduction/` 模块路径（v0.4.0 同步）| — |
| arXiv/DOI 输入适配 | P1 |
| 复现专用 Prompt YAML（3 个）| P0 |
| backtrader 集成（预写策略）| P0 |
| 数据源（AKShare + iFinD + DataCache）| P0 |
| Reproduction WebUI 面板 | P1 |
| 分析层（策略分析 + 回测分析）| P0 |

### 5.3 与现有设计文档的关系

| 现有文档 | 关系 |
|---|---|
| `docs/designs/ashare-strategy-building.md`（1224行）| 直接对齐：strategy/ 子目录蓝图已就绪 |
| `docs/designs/autoresearch-structured-reasoning.md`（1175行）| 直接对齐：6 步框架可作为「研究/理解」阶段 |
| `docs/designs/deep-research-implementation-plan.md` | 部分重叠：deep-research 适合「多源综合」，复现适合「单源深挖+生成」|
| `docs/designs/in8-entity-resolution.md` | 可参考：实体/关系抽取的规范化思路 |

---

## 六、参考项目（建议持续追踪）

| 项目 | 关注点 | URL |
|---|---|---|
| TradingAgents | 多 Agent 角色分工 | github.com/TauricResearch/TradingAgents |
| PyMuPDF4LLM | PDF → MD 最稳 | pypi.org/project/pymupdf4llm/ |
| LlamaParse | 高保真 PDF（云）| llamaindex.ai |
| MarkItDown | 万能文件 → MD | github.com/microsoft/markitdown |
| Nougat | 公式 LaTeX（学术）| github.com/facebookresearch/nougat |
| backtrader | 回测框架 | github.com/mementum/backtrader |
| Qlib | 微软 AI 量化平台 | github.com/microsoft/qlib |
| Qlib Alpha158/360 | 因子库 | github.com/microsoft/qlib/tree/main/qlib/contrib/data |
| Qlib Alpha101 复现 | 公式 → 代码范式 | github.com/microsoft/qlib/blob/main/qlib/contrib/strategy/alpha158.py |

---

## 七、总结

1. **完全复用 llmwikify 现有链路**：输入 + 通用理解零新代码。
2. **wiki.md 驱动结构化抽取**：只写 prompt，不写理解层模块。
3. **预写策略优先，LLM 代码生成为降级**：通用模式参数化调用，边缘情况自动生成。
4. **backtrader 回测 + AKShare/iFinD/DataCache**：数据缓存优先，减少网络依赖。
5. **知识图谱 + LLM prompt 驱动分析**：前置 + 后置。
