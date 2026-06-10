# 论文 / 研报 策略复现 — 业界调研

> 创建时间：2026-06-10
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
| 数据源授权 | AKShare（主）+ iFinD（补），不用 Tushare | AKShare（主）+ iFinD（补）|
| 券商研报 (中文+图片) | PaddleOCR + 多模态 LLM | Phase 3 评估中 |

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
